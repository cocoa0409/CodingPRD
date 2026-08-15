"""Shared helpers: field validation, calendar arithmetic, pagination."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err_invalid_request
from db import parse_iso


def require_fields(payload, fields):
    if not isinstance(payload, dict):
        raise err_invalid_request("Request body must be a JSON object")
    for f in fields:
        if f not in payload or payload[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def require_enum(payload, field, allowed):
    v = payload.get(field)
    if v not in allowed:
        raise err_invalid_request(f"Invalid value for {field}: {v!r}")
    return v


def require_positive_int(payload, field):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise err_invalid_request(f"{field} must be a positive integer")
    return v


def optional_positive_int(payload, field):
    v = payload.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise err_invalid_request(f"{field} must be a positive integer")
    return v


def require_int(payload, field):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    return v


def require_string(payload, field):
    v = payload.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{field} must be a non-empty string")
    return v


def require_number(payload, field):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    return v


def require_bool(payload, field):
    v = payload.get(field)
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return v


def parse_datetime_field(payload, field, required=True):
    v = payload.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    try:
        return parse_iso(v)
    except Exception:
        raise err_invalid_request(f"{field} must be a valid ISO 8601 timestamp")


def get_pagination(args):
    """Read limit/offset per scaffold pagination_defaults {limit:10,min:1,max:100,offset:0}."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def whole_months_between(start, end):
    """Whole calendar months between start and end per PRD §2.8:
    12*(dy) + dm, minus 1 when end.day < start.day; clamped >= 0.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def add_months(dt, months):
    """Add N calendar months to a datetime, clamping day-of-month."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    # clamp day
    if m == 12:
        next_month_start = datetime(y + 1, 1, 1, tzinfo=dt.tzinfo or timezone.utc)
    else:
        next_month_start = datetime(y, m + 1, 1, tzinfo=dt.tzinfo or timezone.utc)
    month_start = datetime(y, m, 1, tzinfo=dt.tzinfo or timezone.utc)
    days_in_month = (next_month_start - month_start).days
    d = min(dt.day, days_in_month)
    return dt.replace(year=y, month=m, day=d)


def round_half_up_cents(value):
    """Round a Decimal to whole cents using ROUND_HALF_UP, return int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_two(value):
    """Round a Decimal to two decimal places using ROUND_HALF_UP, return float."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)
