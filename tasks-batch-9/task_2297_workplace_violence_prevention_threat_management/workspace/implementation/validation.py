"""Request-shape validation (precedence step 4) and pagination parsing.

Every failure in this module is ERR_INVALID_REQUEST (400).  Unknown body fields
are ignored.
"""

from flask import request

from db import parse_dt
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON body as a dict.  A missing body is treated as {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad("Request body is not valid JSON.")
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def req_present(data, name):
    if not _present(data, name):
        bad("Field '%s' is required." % name)


def str_field(data, name, required, min_len=None, max_len=None, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def id_field(data, name, required, default=None):
    """A foreign-key reference: must be a non-empty string when supplied."""
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value == "":
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def int_field(data, name, required, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %d." % (name, maximum))
    return value


def bool_field(data, name, required, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    bad("Field '%s' must be a boolean." % name)


def enum_field(data, name, values, required, default=None):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in values:
        bad("Field '%s' must be one of %s." % (name, ", ".join(values)))
    return value


def enum_list_field(data, name, values, required, min_items=1):
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if len(value) < min_items:
        bad("Field '%s' must contain at least %d item(s)." % (name, min_items))
    for item in value:
        if not isinstance(item, str) or item not in values:
            bad("Field '%s' entries must be one of %s." % (name, ", ".join(values)))
    return list(value)


def dt_field(data, name, required, default=None):
    """Returns (raw_string, datetime) so the client's own rendering is preserved."""
    if not _present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return (default, None)
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 timestamp string." % name)
    try:
        parsed = parse_dt(value)
    except Exception:
        bad("Field '%s' must be an ISO 8601 timestamp string." % name)
        return (None, None)
    return (value, parsed)


def nullable_enum_field(data, name, values):
    """Optional field that explicitly accepts null."""
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str) or value not in values:
        bad("Field '%s' must be one of %s." % (name, ", ".join(values)))
    return value


# ---------------------------------------------------------------- pagination


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except Exception:
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except Exception:
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def qs_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qs_enum(name, values):
    value = qs_str(name)
    if value is None:
        return None
    if value not in values:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(values)))
    return value


def qs_bool(name):
    value = qs_str(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered not in ("true", "false"):
        bad("Query parameter '%s' must be true or false." % name)
    return lowered == "true"


def qs_int(name):
    value = qs_str(name)
    if value is None:
        return None
    try:
        return int(value.strip())
    except Exception:
        bad("Query parameter '%s' must be an integer." % name)
