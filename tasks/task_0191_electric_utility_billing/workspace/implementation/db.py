"""In-memory data store. Starts empty on every boot; no seeding.

Per-entity dicts keyed by id. A monotonic _seq counter provides a stable
creation ordering used for created_at tie-breaks (PRD §2.3, §2.8, §3.5).

The SystemClock is a singleton control surface (PRD §2.8). Its current_utc
starts as None until a BillingOperator sets it via /_clock/set_current_utc.
"""
import itertools
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # Per-entity dicts keyed by id.
        self.tariffs = {}
        self.accounts = {}
        self.meters = {}
        self.meter_reads = {}
        self.bills = {}
        self.payments = {}
        self.service_orders = {}
        self.budget_plans = {}
        self.assistance_grants = {}

        # SystemClock singleton: a single record with id + created_at + current_utc.
        self.clock = {
            "id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "_seq": 0,
            "current_utc": None,
        }

        # Monotonic creation sequence (tie-break for records minted within the
        # same millisecond). Used as the secondary key for created_at sorting.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# db must be constructed after now_iso is defined (clock uses it).
db = DB()


def base_record(common_fields=True):
    """Returns a fresh record with system fields populated (PRD §2.4).

    common_fields=False -> MeterRead/SystemClock carry only id + created_at.
    common_fields=True  -> also carry updated_at and version (starts at 1).
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
    """Mark a record mutated: refresh updated_at and bump version by 1."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
