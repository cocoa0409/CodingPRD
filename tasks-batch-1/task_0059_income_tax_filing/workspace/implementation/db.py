import uuid
from datetime import datetime, timezone


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.taxpayers = {}
        self.tax_returns = {}
        self.income_documents = {}
        self.schedules = {}
        self.dependents = {}
        self.credit_claims = {}
        self.estimated_tax_payments = {}
        self.efilings = {}
        self.amended_returns = {}
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


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] += 1
    return obj
