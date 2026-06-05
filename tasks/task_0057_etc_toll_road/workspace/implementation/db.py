import uuid
from datetime import datetime, timezone


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.accounts = {}
        self.vehicles = {}
        self.transponders = {}
        self.transponder_bindings = {}
        self.hov_windows = {}
        self.plazas = {}
        self.toll_transactions = {}
        self.violations = {}
        self.interop_agencies = {}
        self.ledger_entries = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def init_common(obj):
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = db.next_seq()
    return obj


def init_ledger(obj):
    obj["id"] = new_id()
    obj["created_at"] = now_iso()
    obj["_seq"] = db.next_seq()
    return obj


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] += 1
    return obj
