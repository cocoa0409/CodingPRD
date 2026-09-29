"""Request-shape validation (PRD 2.6 tier 3 -> ERR_INVALID_REQUEST)."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import invalid

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)


def body_json():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise invalid("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object")
    return parsed


def _present(body, field):
    return field in body and body[field] is not None


# --------------------------------------------------------------- strings
def req_str(body, field):
    if not _present(body, field):
        raise invalid("Field '%s' is required" % field)
    value = body[field]
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("Field '%s' must be a non-empty string" % field)
    return value


def opt_str(body, field, default=None):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string" % field)
    return value


# ----------------------------------------------------------------- enums
def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        raise invalid("Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if not _present(body, field):
        return default
    return req_enum(body, field, allowed)


# -------------------------------------------------------------- integers
def _check_int(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be <= %s" % (field, maximum))
    return value


def req_int(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        raise invalid("Field '%s' is required" % field)
    return _check_int(field, body[field], minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if not _present(body, field):
        return default
    return _check_int(field, body[field], minimum, maximum)


# -------------------------------------------------------------- booleans
def opt_bool(body, field, default=False):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean" % field)
    return value


# -------------------------------------------------------------- decimals
def _to_decimal(field, value, places):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise invalid("Field '%s' must be a number" % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise invalid("Field '%s' must be a number" % field)
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        raise invalid("Field '%s' must carry at most %d decimal place(s)" % (field, places))
    return dec


def req_decimal(body, field, places, gt=None):
    if not _present(body, field):
        raise invalid("Field '%s' is required" % field)
    dec = _to_decimal(field, body[field], places)
    if gt is not None and dec <= gt:
        raise invalid("Field '%s' must be > %s" % (field, gt))
    return dec


def opt_decimal(body, field, places, gt=None, default=None):
    if not _present(body, field):
        return default
    return req_decimal(body, field, places, gt)


# ----------------------------------------------------------------- dates
def parse_date_str(field, value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise invalid("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % field)
    try:
        parts = [int(p) for p in value.split("-")]
        return date(parts[0], parts[1], parts[2])
    except ValueError:
        raise invalid("Field '%s' must be a valid calendar date" % field)


def req_date(body, field):
    if not _present(body, field):
        raise invalid("Field '%s' is required" % field)
    return body[field], parse_date_str(field, body[field])


def parse_instant(field, value):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an RFC 3339 UTC datetime" % field)
    match = _DT_RE.match(value)
    if not match:
        raise invalid("Field '%s' must be an RFC 3339 UTC datetime" % field)
    offset = match.group(8)
    if offset not in ("Z", "z", "+00:00", "-00:00"):
        raise invalid("Field '%s' must be expressed in UTC" % field)
    frac = match.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4)), int(match.group(5)), int(match.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        raise invalid("Field '%s' must be a valid datetime" % field)


def req_instant(body, field):
    if not _present(body, field):
        raise invalid("Field '%s' is required" % field)
    return parse_instant(field, body[field])


# ---------------------------------------------------------------- arrays
def opt_str_array(body, field, default=None):
    if not _present(body, field):
        return list(default or [])
    value = body[field]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array" % field)
    for item in value:
        if not isinstance(item, str) or item == "":
            raise invalid("Field '%s' must be an array of non-empty strings" % field)
    return list(value)


def opt_enum_array(body, field, allowed, default=None, non_empty=False):
    if not _present(body, field):
        if non_empty:
            raise invalid("Field '%s' is required" % field)
        return list(default or [])
    value = body[field]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array" % field)
    if non_empty and len(value) == 0:
        raise invalid("Field '%s' must be a non-empty array" % field)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid("Field '%s' entries must be one of %s" % (field, ", ".join(allowed)))
    return list(value)


def req_enum_array(body, field, allowed):
    if not _present(body, field):
        raise invalid("Field '%s' is required" % field)
    return opt_enum_array(body, field, allowed, non_empty=True)


def opt_object(body, field, default=None):
    if not _present(body, field):
        return default if default is not None else {}
    value = body[field]
    if not isinstance(value, dict):
        raise invalid("Field '%s' must be an object" % field)
    return value


# ------------------------------------------------------------ query args
def q_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise invalid("Query parameter 'limit' must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise invalid("Query parameter 'offset' must be >= 0")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("Query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer" % name)


def q_date(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value, parse_date_str(name, value)


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("Query parameter '%s' must be a boolean" % name)


def q_required_date(name):
    value = request.args.get(name)
    if value is None or value == "":
        raise invalid("Query parameter '%s' is required" % name)
    return value, parse_date_str(name, value)


def q_required_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        raise invalid("Query parameter '%s' is required" % name)
    if value not in allowed:
        raise invalid("Query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def paginate(rows):
    limit, offset = q_pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
