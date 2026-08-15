import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from errors import ERR_INVALID_REQUEST, ApiError


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_uuid():
    return str(uuid.uuid4())


def iso_z(dt):
    """Normalize a tz-aware datetime to ...Z form (seconds, or fractional when present)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value, field):
    """Strict YYYY-MM-DD date. Raises ERR_INVALID_REQUEST otherwise."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO date string", 400)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO date (YYYY-MM-DD)", 400)


def parse_datetime(value, field):
    """ISO 8601 datetime; naive values are assumed UTC. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime string", 400)
    text = value.strip()
    try:
        if text.endswith("Z") or text.endswith("z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_time_loose(value):
    """Parse a stored datetime/date string without raising (internal use)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = value
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_loose(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def add_months(d, months):
    """Anniversary arithmetic: same day-of-month, clamped to the target month's last day."""
    total = (d.year * 12 + (d.month - 1)) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)  # 10^-places
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def round2_float(value):
    return float(round_half_up(value, 2))


def minutes_between(start_dt, end_dt):
    """Whole minutes of a [start, end) interval."""
    return int((end_dt - start_dt).total_seconds() // 60)


def hours_display(minutes):
    return float(round_half_up(Decimal(minutes) / Decimal(60), 2))
