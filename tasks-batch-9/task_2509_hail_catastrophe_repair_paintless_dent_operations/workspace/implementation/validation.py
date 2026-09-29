"""Request-shape validation (PRD §2.11 ordinal 3) and pagination parsing (§2.3)."""

from flask import request

from clock import parse_date, parse_instant
from errors import bad_request

_MISSING = object()


def json_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise bad_request("Request body must be a JSON object.")
    return payload


def _present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, min_length=1):
    if not _present(body, name):
        raise bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str) or len(value) < min_length:
        raise bad_request("Field '%s' must be a non-empty string." % name)
    return value


def opt_string(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise bad_request("Field '%s' must be a non-empty string." % name)
    return value


def req_state_code(body, name):
    value = req_string(body, name)
    if len(value) != 2 or not value.isalpha() or not value.isupper():
        raise bad_request("Field '%s' must be exactly 2 uppercase letters." % name)
    return value


def req_exact_length_string(body, name, length):
    value = req_string(body, name)
    if len(value) != length:
        raise bad_request("Field '%s' must be exactly %d characters." % (name, length))
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        raise bad_request("Field '%s' is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_number(body, name, minimum=None, maximum=None,
               exclusive_minimum=None):
    if not _present(body, name):
        raise bad_request("Field '%s' is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise bad_request("Field '%s' must be > %s." % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_number(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_number(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name):
    if not _present(body, name):
        raise bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % name)
    return value


def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        raise bad_request(
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_date_string(body, name):
    value = req_string(body, name)
    if parse_date(value) is None:
        raise bad_request("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    return value


def opt_date_string(body, name, default=None):
    if not _present(body, name):
        return default
    return req_date_string(body, name)


def req_instant_string(body, name):
    value = req_string(body, name)
    if parse_instant(value) is None:
        raise bad_request("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return value


def req_enum_array(body, name, allowed, default=None):
    if not _present(body, name):
        return list(default) if default is not None else []
    value = body[name]
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad_request("Field '%s' contains an unknown value." % name)
    return list(value)


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise bad_request("Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum:
        raise bad_request("Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def pagination():
    """limit default 10 (min 1, max 100); offset default 0 (min 0).

    A value outside those bounds is a malformed request rather than a clamped one.
    """
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
