"""Shared utilities: datetime parsing/rendering, ids, response envelope, errors."""
import calendar
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 instant (accepts trailing 'Z'). Returns aware UTC datetime.
    Raises ValueError on failure."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_domain_dt(dt):
    """Render a domain/input datetime, round-tripping input format.
    Second precision -> plain 'Z'; sub-second -> milliseconds + 'Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def render_system_ts(dt):
    """Render a system timestamp (created_at/updated_at/meta) with 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def add_months(dt, months):
    """Add whole calendar months, preserving day-of-month clamped to month end."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------
def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# IDs
# --------------------------------------------------------------------------
def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
