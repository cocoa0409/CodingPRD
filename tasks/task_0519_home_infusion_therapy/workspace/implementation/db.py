"""In-memory data store. Starts EMPTY on every boot — no seeding, no preload.
Every entity is created by tests via the declared API surface."""
import uuid

from clock import clock


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.drug_catalog = {}
        self.payer_plans = {}
        self.nurses = {}
        self.patients = {}
        self.referrals = {}
        self.infusion_orders = {}
        self.prior_authorizations = {}
        self.compounds = {}
        self.pumps = {}
        self.supply_kits = {}
        self.nursing_visits = {}
        self.lab_results = {}
        self.adverse_events = {}
        self.claims = {}
        # monotonically increasing sequence to break created_at ties deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(entity):
    """Set the common system fields on create (PRD §2.4)."""
    now = clock.iso()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and bump version by exactly 1 on every mutation (PRD §2.4)."""
    entity["updated_at"] = clock.iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity
