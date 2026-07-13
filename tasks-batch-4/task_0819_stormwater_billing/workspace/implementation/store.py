"""In-memory data store, logical clock, and id/timestamp/constants helpers.

Everything here is process-local. A fresh process (start.sh re-invocation)
starts with completely empty stores and the default logical clock.
NO entity is ever seeded at import time.
"""
import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Domain constants (from SCAFFOLD.yaml calculations)
# ---------------------------------------------------------------------------
ERU_BASE_SQFT = 3000

RATE_T1 = 4000
RATE_T2 = 3500
RATE_T3 = 3000
FIXED_CHARGE_CENTS = 500

MAX_CREDIT_PCT = 0.50
CREDIT_SCALE = 0.60
INSPECTION_INTERVAL_DAYS = 365

CAPITAL_TARGET_PCT = 0.30

GRACE_DAYS = 30
DELINQUENCY_PENALTY_PCT = 0.10

KNOWN_ROLES = {
    "PropertyOwner",
    "Assessor",
    "BillingClerk",
    "CreditInspector",
    "StormwaterAdmin",
}

DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"


# ---------------------------------------------------------------------------
# In-memory collections (keyed by id)
# ---------------------------------------------------------------------------
accounts = {}
parcels = {}
measurements = {}
exemptions = {}
bmp_credits = {}
inspections = {}
bills = {}
appeals = {}
payments = {}
fund_ledger = {}


# ---------------------------------------------------------------------------
# Ordering sequence + logical clock
# ---------------------------------------------------------------------------
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


# Logical clock (server-controlled). Never wall clock for time-dependent logic.
_clock = {"now": None}


def get_clock():
    if _clock["now"] is None:
        _clock["now"] = parse_dt(DEFAULT_CLOCK_ISO)
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Id / timestamp helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real wall-clock UTC, ISO 8601 with exactly three fractional digits."""
    return fmt_dt(datetime.now(timezone.utc))


def fmt_dt(dt):
    """Format an aware/naive datetime as ISO 8601 UTC with 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def base_entity(common_fields=True):
    """Create the system-managed base fields for a new entity."""
    ent = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    if common_fields:
        ent["updated_at"] = ent["created_at"]
        ent["version"] = 1
    return ent


def touch(ent):
    """Refresh updated_at and bump version by one (common-field entities)."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 0) + 1


def public(ent):
    """Strip internal (underscore-prefixed) keys for the response body."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
