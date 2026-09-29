"""Request-shape validation (PRD 2.12 step 4) and date/decimal helpers."""
import calendar
import numbers
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import request

from errors import invalid

SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")


def body():
    """Parses the JSON body.  Missing bodies are treated as empty objects so that
    action endpoints declaring no input work with or without a payload."""
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise invalid("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object.")
    return payload


def present(payload, field):
    return field in payload and payload[field] is not None


def req_str(payload, field, required=True, default=None, allow_empty=False):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        raise invalid("Field '%s' must not be empty." % field)
    return value


def req_enum(payload, field, allowed, required=True, default=None):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def req_bool(payload, field, required=True, default=None):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % field)
    return value


def req_int(payload, field, required=True, default=None, minimum=None, maximum=None):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise invalid("Field '%s' must be an integer." % field)
    value = int(value)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' is out of range." % field)
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' is out of range." % field)
    return value


def req_num(payload, field, required=True, default=None, minimum=None, maximum=None,
            exclusive_min=None):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise invalid("Field '%s' must be a number." % field)
    # A whole number stays whole, so the echo matches what the client sent.
    value = int(value) if isinstance(value, numbers.Integral) else float(value)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' is out of range." % field)
    if exclusive_min is not None and value <= exclusive_min:
        raise invalid("Field '%s' is out of range." % field)
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' is out of range." % field)
    return value


def req_str_list(payload, field, allowed, required=True, default=None):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return list(default or [])
    value = payload[field]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % field)
    out = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid("Field '%s' contains an unknown value." % field)
        out.append(item)
    return out


# ---------------------------------------------------------------- date helpers

def parse_date(value, field):
    """Accepts a whole UTC calendar date, either 'YYYY-MM-DD' or a full ISO
    instant whose date part is taken."""
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 date." % field)
    text = value.strip()
    try:
        if len(text) == 10:
            return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        return parse_instant(text, field).date()
    except invalid_types:
        raise invalid("Field '%s' must be an ISO 8601 date." % field)


def parse_instant(value, field):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 timestamp." % field)
    text = value.strip()
    try:
        if len(text) == 10:
            dt = datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        else:
            if text.endswith("Z") or text.endswith("z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
    except invalid_types:
        raise invalid("Field '%s' must be an ISO 8601 timestamp." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


invalid_types = (ValueError, TypeError, IndexError)


def req_date(payload, field, required=True, default=None):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return default
    return parse_date(payload[field], field)


def req_instant(payload, field, required=True, default=None):
    if not present(payload, field):
        if required:
            raise invalid("Field '%s' is required." % field)
        return default
    return parse_instant(payload[field], field)


def fmt_date(value):
    if value is None:
        return None
    return value.isoformat()


def add_months(base, months):
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    # A projection may run past the representable calendar; clamp rather than
    # raise, so that an absurdly long forecast still yields a comparable date.
    if year > date.max.year:
        return date.max
    if year < date.min.year:
        return date.min
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_days(base, days):
    try:
        return base + timedelta(days=days)
    except (OverflowError, ValueError, OSError):
        return date.max if days > 0 else date.min


def add_years(base, years):
    """Anniversary arithmetic: 29 Feb + n years clamps to 28 Feb (PRD 2.10)."""
    return add_months(base, 12 * years)


# ------------------------------------------------------------- money rounding

def round_half_up(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_up(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)
