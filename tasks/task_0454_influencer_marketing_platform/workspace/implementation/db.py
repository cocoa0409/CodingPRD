"""In-memory data store. Starts EMPTY on every boot (no seeding)."""
import itertools
import uuid

from clock import clock, format_iso


class DB:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.brands = {}
        self.creators = {}
        self.audience_snapshots = {}
        self.campaigns = {}
        self.deliverables = {}
        self.offers = {}
        self.contracts = {}
        self.content_submissions = {}
        self.attribution_assets = {}
        self.conversion_events = {}
        self.payouts = {}
        self.tax_forms = {}
        self.brand_safety_flags = {}
        # Monotonic counter to break created_at ties for deterministic ordering.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return format_iso(clock.now())


def base_fields(versioned=True):
    """Common system fields. `created_at`/`updated_at`/`version` (PRD 2.4)."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def bump(rec):
    """Increment version by exactly 1 and refresh updated_at (PRD 2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()
