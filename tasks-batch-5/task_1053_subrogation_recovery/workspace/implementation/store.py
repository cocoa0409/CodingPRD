"""In-memory data store (§1.0 storage). Fresh & empty on every process boot.

NOTHING is seeded here. Every entity is created via the declared API surface.
The single exception is the logical-clock default (CLOCK_DEFAULT_UTC).
"""
import uuid
from timeutil import parse_iso, now_wall

# Declared constants (SCAFFOLD §constants).
DEMAND_RESPONSE_DAYS = 30
ARBITRATION_FILING_DAYS = 60
HEARING_BUFFER_DAYS = 7
MANAGER_AUTHORITY_CENTS = 5000000
CLOCK_DEFAULT_UTC = "2026-07-01T00:00:00Z"


class Store:
    def __init__(self):
        self.carriers = {}
        self.adverse_parties = {}
        self.claims = {}
        self.demands = {}
        self.arbitrations = {}
        self.settlements = {}
        self.recovery_payments = {}
        self.deductible_reimbursements = {}
        self.commission_statements = {}
        self.claim_documents = {}
        self._seq = 0
        self.clock = parse_iso(CLOCK_DEFAULT_UTC)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp(obj, versioned=True):
    """Populate common fields (id, created_at, [updated_at, version], _seq)."""
    now = now_wall()
    obj["id"] = new_id()
    obj["created_at"] = now
    obj["_seq"] = db.next_seq()
    if versioned:
        obj["updated_at"] = now
        obj["version"] = 1
    return obj


def touch(obj):
    """A mutation: refresh updated_at and increment version by one (§2.4/§2.8)."""
    obj["updated_at"] = now_wall()
    obj["version"] = obj.get("version", 1) + 1


def clock_now():
    return db.clock
