"""In-memory data store, logical clock, and common-field helpers.

Storage is in-memory only: plain dicts keyed by id. No disk persistence, no
seeding — every entity is created through the declared API surface.
"""

import uuid
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        # Logical clock: starts at exactly 2026-05-01T00:00:00Z and never
        # falls back to wall-clock time.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.policyholders = {}
        self.state_regulations = {}
        self.state_reg_by_code = {}
        self.policies = {}
        self.shops = {}
        self.parts = {}
        self.claims = {}
        self.disclosures = {}
        self.work_orders = {}
        self.calibrations = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.fraud_alerts = {}
        self.warranty_claims = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def now_dt():
    return store.clock


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(store.clock)


def set_clock(dt):
    store.clock = dt.astimezone(timezone.utc)


def base_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "_created_dt": store.clock,
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError for malformed input (caller maps to ERR_INVALID_REQUEST).
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date string. Raises ValueError if invalid."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def public(entity):
    """Strip internal keys (leading underscore) before serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sorted_created(items):
    """Default list ordering: created_at ascending, stable on clock ties."""
    return sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))
