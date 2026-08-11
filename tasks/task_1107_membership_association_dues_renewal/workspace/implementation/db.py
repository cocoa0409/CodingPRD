"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock (test-driving). Startup default per PRD §2.9.
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_now = _CLOCK_DEFAULT
_clock_set = False


def now_utc():
    return _clock_now


def set_clock(to_dt):
    global _clock_now, _clock_set
    _clock_now = to_dt
    _clock_set = True


def iso(dt):
    """Format datetime as ISO 8601 UTC with three fractional digits (e.g. 2025-05-24T10:30:00.123Z)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_dt(value):
    """Parse an ISO8601 timestamp (accepts trailing Z or offset, date-only, fractional seconds)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # try date-only
        dt = datetime.strptime(str(value)[:10], "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# Entity stores — plain dicts keyed by id. Empty at boot.
# ---------------------------------------------------------------------------
membership_categories = {}
dues_schedules = {}
chapters = {}
renewal_cycle_policies = {}
members = {}
membership_terms = {}
dues_invoices = {}
payment_attempts = {}
auto_renew_authorizations = {}
benefit_entitlements = {}
directory_listings = {}
dues_increase_notices = {}
revenue_attributions = {}
reinstatement_requests = {}

# Non-entity ledgers kept in-memory too.
chapter_share_ledger = {}  # chapter_id -> net cents accrued
member_lapse_ts = {}       # member_id -> datetime of LAPSED transition
benefit_usage_events = {}  # member_id -> list of datetime (trailing usage, for risk score)

MAX_RETRY = 5
RENEWAL_LOOKAHEAD_DAYS = 30


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = iso(now_utc())
    entity["version"] = entity.get("version", 1) + 1
