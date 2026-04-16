import uuid
from datetime import datetime, timezone


def gen_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now():
    return datetime.now(timezone.utc)


def parse_iso(value):
    """Parse an ISO 8601 datetime string to a timezone-aware datetime in UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    # Flask/JSON payloads may pass Z suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# In-memory stores
shelters = {}
animals = {}
vaccination_records = {}
adopters = {}
adoption_applications = {}
home_visits = {}
boarding_reservations = {}
boarding_matches = {}
fee_invoices = {}
compliance_holds = {}
fee_schedules = {}
settlement_batches = {}
