"""In-memory data store, logical clock, and (de)serialization helpers.

The store starts completely empty on every boot. No entity data is ever seeded,
preloaded, or hardcoded — every entity is created by the declared endpoints.
"""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt


clock = _Clock()


def now():
    return clock.get()


# ---------------------------------------------------------------------------
# Entity tables (all empty at startup)
# ---------------------------------------------------------------------------
class _DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.defendants = {}
        self.cases = {}
        self.charges = {}
        self.courtrooms = {}
        self.arraignments = {}
        self.diversion_agreements = {}
        self.service_sites = {}
        self.service_assignments = {}
        self.ledger_accounts = {}
        self.installment_plans = {}
        self.payments = {}
        self.warrants = {}
        self.amnesty_programs = {}
        self.expungement_referrals = {}
        self.clock = clock
        clock.now = DEFAULT_CLOCK


db = _DB()

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------
def base_fields(with_common=True):
    """Return the id + common lifecycle fields for a fresh record."""
    ts = now()
    rec = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if with_common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec, bump_version=True):
    rec["updated_at"] = now()
    if bump_version and "version" in rec:
        rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Time formatting / parsing
# ---------------------------------------------------------------------------
def format_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_datetime(value):
    """Parse an ISO-8601 instant into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Parse a YYYY-MM-DD date (no time). Raises ValueError on bad input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def clean(obj):
    """Recursively convert Decimal->float, datetime->iso string for JSON."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    if isinstance(obj, Decimal):
        f = float(obj)
        return f
    if isinstance(obj, datetime):
        return format_dt(obj)
    return obj


def serialize(rec):
    """Public representation: drop private (underscore-prefixed) keys, clean types."""
    return {k: clean(v) for k, v in rec.items() if not k.startswith("_")}
