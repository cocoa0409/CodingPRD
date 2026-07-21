"""In-memory data store + logical clock (PRD 2.4, 2.10).

Everything is process-local and starts empty on every boot; start.sh re-invocation
wipes all state.  No seeding.
"""
import uuid
from datetime import datetime, timezone, timedelta
import calendar

from constants import CLOCK_DEFAULT

# --- Entity stores: id -> entity dict ---
portfolios = {}
applicants = {}
landlords = {}
guarantees = {}
agreements = {}
claims = {}
recovery_plans = {}
recovery_installments = {}
compliance_reviews = {}
ledger_entries = {}

# --- Monotonic insertion sequence for stable ordering ---
_seq_counter = 0

# --- Logical clock ---
_clock = None  # datetime (tz-aware UTC)


def reset_all():
    global _seq_counter, _clock
    for store in (portfolios, applicants, landlords, guarantees, agreements,
                  claims, recovery_plans, recovery_installments,
                  compliance_reviews, ledger_entries):
        store.clear()
    _seq_counter = 0
    _clock = parse_iso(CLOCK_DEFAULT)


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO-8601 string into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format a tz-aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def get_clock():
    global _clock
    if _clock is None:
        _clock = parse_iso(CLOCK_DEFAULT)
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt.astimezone(timezone.utc)


def now_iso():
    return format_iso(get_clock())


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    mo = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, mo)[1])
    return dt.replace(year=y, month=mo, day=d)


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def stamp_common(entity):
    """Add id + common system fields (PRD 2.4)."""
    now = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Record a mutation: bump updated_at + version (PRD 2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# Initialize on import
reset_all()
