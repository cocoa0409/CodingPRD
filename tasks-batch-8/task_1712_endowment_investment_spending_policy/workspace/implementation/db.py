# In-memory data store. Module-level dicts keyed by id; the store starts
# completely empty on every process boot (no seeding of any kind).
from util import now_iso


class Store:
    def __init__(self):
        self.pools = {}
        self.policies = {}
        self.valuations = {}
        self.donors = {}
        self.funds = {}
        self.gifts = {}
        self.distributions = {}
        self.exceptions = {}
        self.payouts = {}
        self.allocations = {}
        self.managers = {}
        self.manager_reports = {}
        self.reports = {}
        self.ledger = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def stamp_new(rec):
    """Assign created_at/updated_at and a stable insertion sequence."""
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["_seq"] = store.next_seq()
    return rec


def bump(rec):
    """Increment the optimistic version and refresh updated_at on mutation."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()


def pub(rec):
    """Public view of a record: strip private (underscore-prefixed) fields."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
