"""In-memory store. Empty on every boot; nothing is ever seeded."""
import itertools
import uuid
from datetime import datetime, timezone

# The logical clock starts at exactly this instant and only ever moves because
# an operator moved it. Wall-clock time is never consulted.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "customers",
    "mattress_models",
    "promotion_bundles",
    "retail_partners",
    "disposition_partners",
    "trial_orders",
    "return_cases",
    "pickup_routes",
    "pickup_appointments",
    "disposition_assignments",
    "refund_authorizations",
    "comfort_exchanges",
    "quality_claims",
    "attribution_claims",
    "abuse_signals",
)


class Store(object):
    def __init__(self):
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """Current logical clock instant."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """Common system fields. TrialAbuseSignal is the one resource that carries
    only id and created_at, so it asks for versioned=False."""
    rec = {"id": new_id(), "created_at": db.clock, "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = db.clock
        rec["version"] = 1
    return rec


def touch(rec):
    """A mutation: bump version by exactly one and refresh updated_at."""
    rec["version"] = rec["version"] + 1
    rec["updated_at"] = db.clock
    return rec


def ordered(records):
    """Declared list ordering: created_at ascending, insertion order breaking
    ties (the logical clock stands still, so ties are the norm)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records, limit, offset):
    """Returns (page, total_count) where total_count counts every match before
    the window is applied."""
    total = len(records)
    return records[offset:offset + limit], total
