"""In-memory data store. Starts empty on every boot; NO seeding."""
from util import new_uuid, now_iso


class Store:
    def __init__(self):
        # entity collections keyed by id
        self.projects = {}
        self.workers = {}
        self.assessments = {}
        self.samples = {}
        self.zones = {}
        self.pressure_logs = {}
        self.orders = {}
        self.manifests = {}
        self.clearances = {}
        self.permits = {}
        self.claims = {}
        self.assignments = {}
        # monotonic insertion sequence for stable created_at ordering / tie-breaks
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def base_fields(versioned=True):
    """Common system fields. created_at/updated_at/version per PRD §2.4."""
    ts = now_iso()
    rec = {
        "id": new_uuid(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutate a versioned record: refresh updated_at, bump version."""
    if "version" in rec:
        rec["updated_at"] = now_iso()
        rec["version"] = rec["version"] + 1
