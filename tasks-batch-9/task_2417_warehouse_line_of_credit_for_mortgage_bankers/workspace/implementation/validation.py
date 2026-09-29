"""Request-schema validation (ladder priority 7) and pagination (PRD 2.3)."""

from datetime import date

from flask import request

from errors import ApiError
from money import frac

MISSING = object()

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def body():
    """The parsed JSON object, or {} when no body was supplied."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def v_string(data, name, required=True, min_len=1, max_len=None, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must not be empty." % name)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def v_digits(data, name, length=4, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string of %d digits." % (name, length))
    if len(value) != length or not value.isdigit():
        bad("Field '%s' must be exactly %d digits." % (name, length))
    return value


def v_int(data, name, required=True, minimum=None, maximum=None,
          exclusive_min=None, exclusive_max=None, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % name)
    if isinstance(value, float):
        if not value.is_integer():
            bad("Field '%s' must be an integer number of cents." % name)
        value = int(value)
    if not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (name, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        bad("Field '%s' must be strictly greater than %d." % (name, exclusive_min))
    if exclusive_max is not None and value >= exclusive_max:
        bad("Field '%s' must be strictly less than %d." % (name, exclusive_max))
    return value


def v_rate(data, name, required=True, minimum=None, maximum=None,
           exclusive_min=None, exclusive_max=None, default=None):
    """A rate carried to four decimal places (PRD 2.5)."""
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    f = frac(value)
    if minimum is not None and f < frac(minimum):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and f > frac(maximum):
        bad("Field '%s' must be at most %s." % (name, maximum))
    if exclusive_min is not None and f <= frac(exclusive_min):
        bad("Field '%s' must be strictly greater than %s." % (name, exclusive_min))
    if exclusive_max is not None and f >= frac(exclusive_max):
        bad("Field '%s' must be strictly less than %s." % (name, exclusive_max))
    return value


def v_bool(data, name, required=False, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def v_enum(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def v_enum_array(data, name, allowed, required=True, non_empty=True, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return list(default) if default is not None else None
    value = data[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if non_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % name)
    for member in value:
        if not isinstance(member, str) or member not in allowed:
            bad("Field '%s' members must be drawn from %s."
                % (name, ", ".join(sorted(allowed))))
    return list(value)


def v_id(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be an identifier string." % name)
    return value


def v_date(data, name, required=True, default=None):
    """A calendar date in year-month-day form."""
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a calendar date in YYYY-MM-DD form." % name)
    parts = value.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        bad("Field '%s' must be a calendar date in YYYY-MM-DD form." % name)
    try:
        parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        bad("Field '%s' must be a calendar date in YYYY-MM-DD form." % name)
    return value, parsed


def reject_system_fields(data, expected):
    """Priority 7: an attempt to set a computed or system-owned field from the
    body is rejected — although such a field is ignored rather than rejected
    when the supplied value merely echoes what is already stored."""
    for name, stored in expected.items():
        if name not in data:
            continue
        supplied = data[name]
        if stored is MISSING:
            bad("Field '%s' is server-owned and may not be supplied." % name)
        if isinstance(stored, bool) or isinstance(supplied, bool):
            same = supplied is stored
        elif isinstance(stored, (int, float)) and isinstance(supplied, (int, float)):
            same = frac(supplied) == frac(stored)
        else:
            same = supplied == stored
        if not same:
            bad("Field '%s' is server-owned and may not be supplied." % name)


COMMON_SYSTEM_FIELDS = {
    "id": MISSING,
    "created_at": MISSING,
    "updated_at": MISSING,
}


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit_value < PAGINATION_MIN_LIMIT or limit_value > PAGINATION_MAX_LIMIT:
            bad("Query parameter 'limit' must lie in the inclusive range 1 to 100.")
    if offset is None or offset == "":
        offset_value = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_value = int(offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset_value < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit_value, offset_value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def q_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be true or false." % name)
