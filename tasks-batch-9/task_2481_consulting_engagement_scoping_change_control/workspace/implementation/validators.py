"""Request body / query-string validation helpers."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

_MISSING = object()
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_RE = re.compile(r"^[+-]?\d+$")


def json_body():
    """Parsed JSON object, or {} when no body was sent at all."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def reject_unknown(data, allowed):
    # Unknown members are ignored rather than rejected; kept for symmetry.
    return data


def present(data, key):
    return key in data and data[key] is not None


# ---------------------------------------------------------------- strings


def get_str(data, key, required=True, min_len=1, max_len=None, default=None):
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    val = data[key]
    if not isinstance(val, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if min_len is not None and len(val) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(val) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    return val


def get_enum(data, key, allowed, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    val = data[key]
    if not isinstance(val, str) or val not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return val


def get_id(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    val = data[key]
    if not isinstance(val, str) or not val.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string identifier." % key)
    return val


# ---------------------------------------------------------------- numbers


def get_int(data, key, required=True, minimum=None, maximum=None, default=None):
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and val < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % key)
    if maximum is not None and val > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % key)
    return val


def get_decimal(
    data,
    key,
    required=True,
    places=2,
    gt=None,
    ge=None,
    le=None,
    default=None,
    range_error="ERR_INVALID_REQUEST",
):
    """A 2-decimal number.  Out-of-range values may surface a domain error id."""
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(val))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if not dec.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % key)
    if places is not None:
        exp = dec.as_tuple().exponent
        if isinstance(exp, int) and -exp > places:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' carries more than %d decimal places." % (key, places),
            )
    if gt is not None and not dec > Decimal(str(gt)):
        fail(range_error, "Field '%s' must be greater than %s." % (key, gt))
    if ge is not None and not dec >= Decimal(str(ge)):
        fail(range_error, "Field '%s' must be at least %s." % (key, ge))
    if le is not None and not dec <= Decimal(str(le)):
        fail(range_error, "Field '%s' must be at most %s." % (key, le))
    return dec


def get_bool(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    val = data[key]
    if not isinstance(val, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return val


# ---------------------------------------------------------------- lists


def get_str_list(data, key, required=True, max_items=None, default=None, upper=False):
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return list(default) if default is not None else None
    val = data[key]
    if not isinstance(val, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    out = []
    for item in val:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain only strings." % key)
        if upper and not re.match(r"^[A-Z0-9]+$", item):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain uppercase codes." % key)
        out.append(item)
    if max_items is not None and len(out) > max_items:
        fail("ERR_INVALID_REQUEST", "Field '%s' holds too many entries." % key)
    return out


# ---------------------------------------------------------------- dates


def get_date(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    val = data[key]
    if not isinstance(val, str) or not DATE_RE.match(val):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % key)
    try:
        y, m, d = val.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a valid calendar date." % key)


def parse_date(text):
    y, m, d = text.split("-")
    return date(int(y), int(m), int(d))


def iso_date(value):
    return value.isoformat()


def get_datetime(data, key, required=True):
    """ISO 8601 UTC instant used by the logical clock endpoint."""
    from datetime import datetime, timezone

    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return None
    val = data[key]
    if not isinstance(val, str) or not val.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC timestamp." % key)
    text = val.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC timestamp." % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- pagination


def pagination():
    """limit default 10 (1..100), offset default 0 (>= 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not INT_RE.match(raw.strip()):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not INT_RE.match(raw.strip()):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer of 0 or greater.")
        offset = int(raw.strip())
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be 0 or greater.")
    return limit, offset


def filter_arg(name):
    val = request.args.get(name)
    if val is None:
        return None
    return val


def bool_arg(name):
    val = request.args.get(name)
    if val is None:
        return None
    low = val.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None
