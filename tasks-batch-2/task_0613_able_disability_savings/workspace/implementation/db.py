"""In-memory data store. All state lives in process memory and is wiped on
every process boot. NO seeding, NO preload, NO disk persistence."""
import uuid

from clock import clock


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.programs = {}
        self.investment_options = {}
        self.beneficiaries = {}
        self.certifications = {}
        self.accounts = {}
        self.authorized_representatives = {}
        self.contributions = {}
        self.distributions = {}
        self.qde_records = {}
        self.medicaid_claims = {}
        self._seq = 0  # monotonic counter for stable created_at ordering

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    """Populate common system fields on a brand-new entity."""
    now = clock.iso()
    obj["id"] = new_id()
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1
    obj["_seq"] = db.next_seq()
    return obj


def touch(obj):
    """Record a mutation: bump updated_at and version."""
    obj["updated_at"] = clock.iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
