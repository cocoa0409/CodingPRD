"""In-memory data store. Starts empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone, timedelta

# Entity stores: dict keyed by id
account_standards = {}
partner_institutions = {}
certification_reviews = {}
participants = {}
referrals = {}
account_opening_events = {}
account_applications = {}
barrier_cases = {}
education_pairings = {}
retention_checkpoints = {}
funding_grants = {}
partner_reports = {}
outreach_campaigns = {}

# Logical clock state
_DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
_clock = {"current": _DEFAULT_CLOCK}


def get_clock():
    return _clock["current"]


def set_clock(value):
    _clock["current"] = value


def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware datetime."""
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (or datetime) into a date."""
    if value is None:
        return None
    s = str(value).strip()
    if "T" in s:
        return parse_dt(s).date()
    return datetime.strptime(s, "%Y-%m-%d").date()


def now_iso():
    """Current logical clock reading in canonical form (3 fractional digits, Z)."""
    return parse_dt(get_clock()).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ts_now():
    """Timestamp used for created_at/updated_at — logical clock based, 3 frac digits."""
    return now_iso()


def new_id():
    return str(uuid.uuid4())


def add_months(dt, months):
    """Add months to an aware datetime (clamping day as needed)."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    # days per month
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1)
    else:
        next_month_start = datetime(year, month + 1, 1)
    month_start = datetime(year, month, 1)
    days_in_month = (next_month_start - month_start).days
    day = min(dt.day, days_in_month)
    return dt.replace(year=year, month=month, day=day)


def is_valid_iso_datetime(value):
    try:
        parse_dt(value)
        return True
    except Exception:
        return False


def is_valid_iso_date(value):
    try:
        parse_date(value)
        return True
    except Exception:
        return False
