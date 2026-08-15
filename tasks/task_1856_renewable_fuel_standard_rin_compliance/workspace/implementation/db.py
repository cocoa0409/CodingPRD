"""In-memory data store. All dicts are keyed by entity id (UUID string).

The store starts completely empty on every boot. No seeding, no preloading.
"""
import uuid
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Entity collections
# ---------------------------------------------------------------------------
compliance_accounts = {}
obligation_years = {}
vendors = {}
rin_lots = {}
blending_records = {}
rin_trades = {}
retirement_batches = {}
compliance_reports = {}
attest_engagements = {}
state_programs = {}
state_credit_reports = {}
price_quotes = {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_utc = _STARTUP_UTC


def now_utc():
    """Current logical clock time."""
    return _current_utc


def set_clock(dt):
    """Advance the logical clock (test-driving endpoint)."""
    global _current_utc
    _current_utc = dt
    return _current_utc


def new_id():
    """Mint a new opaque resource id (UUID, no type prefix)."""
    return str(uuid.uuid4())


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits, trailing Z."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string (accepts trailing Z)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def retention_until_from(created_at):
    """created_at + 1825 days (fixed 5-year retention)."""
    return created_at + timedelta(days=1825)


def march31_deadline(year):
    """23:59:59 UTC on March 31 of the given year."""
    return datetime(year, 3, 31, 23, 59, 59, tzinfo=timezone.utc)
