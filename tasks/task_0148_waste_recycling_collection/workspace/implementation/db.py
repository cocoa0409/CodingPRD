"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # Per-entity dicts keyed by id.
        self.accounts = {}
        self.carts = {}
        self.service_plans = {}
        self.routes = {}
        self.stops = {}
        self.pickups = {}
        self.contamination_tags = {}
        self.weight_tickets = {}
        self.invoices = {}
        self.special_pickups = {}
        self.credits = {}
        self.diversion_periods = {}
        # Monotonic counter to provide a stable creation sequence (tie-break for
        # records minted within the same millisecond).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def base_record(common_fields=True):
    """Returns a fresh record with system fields populated.

    common_fields=False -> WeightTicket: only id + created_at (PRD §2.4).
    """
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at and bump version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
