import ipaddress as ipaddr
from typing import Dict, Generator, List, TypeVar
from typing_extensions import Self


def find(obj_list, obj):
    for candidate in obj_list:
        if candidate == obj:
            return candidate
    return None


class ProcessID():
    def __init__(self, ident: str) -> None:
        self.id = ident
        self.unique_id = ident
        self.index = current_fingerprint
        self.matching: List[Self] = []
        
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.id == other.id \
                and self.index == other.index
        else:
            return False
    
    def extend(self, other: Self):
        self.matching.append(other)
        try:
            while True:
                ProcessID.all_ids.remove(other)
        except ValueError:
            pass
    
    all_ids: List[Self] = []

    @staticmethod
    def unique_all_ids():
        used = set()
        for proc_id in ProcessID.all_ids:
            while proc_id.unique_id in used:
                try:
                    last_num = int(proc_id.unique_id[-1])
                    proc_id.unique_id = proc_id.unique_id[:-1] + str(last_num + 1)
                except ValueError:
                    proc_id.unique_id += f"_{proc_id.index}"

    @staticmethod
    def unified_id(ident: str) -> str:
        proc_id = ProcessID(ident)
        for other_id in ProcessID.all_ids:
            if proc_id in other_id.matching or proc_id == other_id:
                return other_id.unique_id
        import pdb; pdb.set_trace()
        raise ValueError(f"ID {ident} did not match any processes")


class ProcessNode():
    def __init__(self, node: Dict) -> None:
        self.node = node
        self.id = ProcessID(node['id'])
        self.children = []
        if 'children' in node:
            self.children = [ProcessNode(child) for child in node['children']]
        ProcessID.all_ids.append(self.id)
    
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            compare_keys = ['name', 'exe', 'euser']
            for key in compare_keys:
                if self.node.get(key) != other.node.get(key):
                    return False
            return True
        else:
            return False
    
    def extend(self, other: Self):
        if other != self:
            raise ValueError("Other process did not match")
        self.id.extend(other.id)
        for child in other.children:
            match = find(self.children, child)
            if match is not None:
                match.extend(child)
            else:
                self.children.append(child)
        self.update_node()
    
    def update_node(self):
        self.node['id'] = self.id.unique_id
        if len(self.children) == 0:
            if 'children' in self.node:
                del self.node['children']
            return
        self.node['children'] = []
        for child in self.children:
            child.update_node()
            self.node['children'].append(child.node)


class ConnectionNode():
    def __init__(self, node: Dict) -> None:
        self.has_from = 'from' in node
        self.has_to = 'to' in node
        self.node = node
        self.collapse_ips()
        self.unify_ids()
    
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.has_from == other.has_from \
                and self.has_to == other.has_to \
                and self.procs == other.procs \
                and self.ports == other.ports
        else:
            return False
    
    @property
    def procs(self):
        return self.node['processes']
    
    @property
    def ports(self):
        return self.node['ports']
    
    def extend(self, other: Self):
        if other != self:
            raise ValueError("Other connection not did not match")
        if self.has_from:
            self.node['from'] += other.node['from']
        if self.has_to:
            self.node['to'] += other.node['to']
        self.collapse_ips()
        
    def collapsed_cidrs(self, key):
        to_collapse = []
        ret = []
        for block in self.node[key]:
            if not 'ipBlock' in block:
                ret.append(block)
                continue
            cidr = block['ipBlock']['cidr']
            try:
                to_collapse.append(ipaddr.IPv4Network(cidr))
            except ValueError:
                ret.append(block)
                continue
        ret += [{ 'ipBlock': { 'cidr': str(add) } }
            for add in ipaddr.collapse_addresses(to_collapse)
        ]
        return ret
    
    def collapse_ips(self):
        if self.has_from:
            self.node['from'] = self.collapsed_cidrs('from')
        if self.has_to:
            self.node['to'] = self.collapsed_cidrs('to')
    
    def unify_ids(self):
        new_proc = []
        for proc in self.procs:
            new_proc.append(ProcessID.unified_id(proc))
        self.node['processes'] = new_proc


current_fingerprint = 0

T = TypeVar('T')
def iter_prints(objs: List[T]) -> Generator[T, None, None]:
    global current_fingerprint
    for i, obj in enumerate(objs):
        current_fingerprint = i
        yield obj


def merge_subs(objs, key, ret):
    sub_list = [obj[key] for obj in objs]
    ret[key] = globals()[f"merge_{key}"](sub_list)


def merge_fingerprints(fingerprints):
    if len(fingerprints) == 0:
        raise ValueError("Cannot merge 0 fingerprints")
    new_obj = dict()
    merge_subs(fingerprints, "spec", new_obj)
    return new_obj


def merge_spec(fingerprints):
    new_obj = dict()
    merge_subs(fingerprints, "serviceSelector", new_obj)
    merge_subs(fingerprints, "machineSelector", new_obj)
    merge_subs(fingerprints, "proc_profile", new_obj)
    merge_subs(fingerprints, "conn_profile", new_obj)
    # metadata probably removed
    return new_obj


def merge_serviceSelector(selectors):
    if selectors[:-1] != selectors[1:]:
        # todo: handle better
        raise ValueError("Services to be merged did not match")
    return selectors[0]


def merge_machineSelector(selectors):
    new_obj = dict()
    merge_subs(selectors, 'hostname', new_obj)
    return new_obj


def merge_hostname(hostnames: List[str]):
    if len(hostnames) == 1:
        return hostnames[0]['hostname']
    ret = ""
    for chars in zip(*hostnames):
        if chars[:-1] != chars[1:]:
            return ret + '*'
        ret += chars[0]
    comp = len(hostnames[0])
    for name in hostnames:
        if len(name) != comp:
            return ret + '*'
    return ret


def merge_proc_profile(profiles):
    ret: List[ProcessNode] = []
    ProcessID.all_ids = []
    for proc_list in iter_prints(profiles):
        for proc in proc_list:
            obj = ProcessNode(proc)
            match = find(ret, obj)
            if match is not None:
                match.extend(obj)
            else:
                ret.append(obj)
    return [node.node for node in ret]


def merge_conn_profile(profiles):
    new_obj = dict()
    merge_subs(profiles, "ingress", new_obj)
    merge_subs(profiles, "egress", new_obj)
    return new_obj


def merge_ingress(conns: List[List[Dict]]):
    ret: List[ConnectionNode] = []
    # uses ConnectionNode.__eq__ to find matches
    # and ConnectionNode.extend to merge matching nodes
    for conn_list in iter_prints(conns):
        for conn in conn_list:
            obj = ConnectionNode(conn)
            match = find(ret, obj)
            if match is not None:
                match.extend(obj)
            else:
                ret.append(obj)
    return [node.node for node in ret]


def merge_egress(conns: List[List[Dict]]):
    ret: List[ConnectionNode] = []
    # uses ConnectionNode.__eq__ to find matches
    # and ConnectionNode.extend to merge matching nodes
    for conn_list in iter_prints(conns):
        for conn in conn_list:
            obj = ConnectionNode(conn)
            if obj in ret:
                ret[ret.index(obj)].extend(obj)
            else:
                ret.append(obj)
    return [node.node for node in ret]
