"""Request-shape validation (validation priority 3 -> ERR_VALIDATION)."""
from flask import request

from errors import fail
from util import parse_iso

TOOL_TYPES = ("LITHO", "ETCH", "DEPOSITION", "IMPLANT", "CMP")
PRODUCT_FAMILIES = ("LOGIC_N5", "LOGIC_N7", "MEMORY_D1")
PRIORITY_CLASSES = ("STANDARD", "HOT", "SUPER_HOT")


def _bad(message):
    fail("ERR_VALIDATION", message)


def body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True)
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object")
    return parsed


def _present(data, key):
    return key in data and data[key] is not None


def v_str(data, key, required=True, min_len=1, max_len=None, default=None):
    if not _present(data, key):
        if required:
            _bad("Field '%s' is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string" % key)
    if min_len is not None and len(value) < min_len:
        _bad("Field '%s' must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' must be at most %d characters" % (key, max_len))
    return value


def v_int(data, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        if required:
            _bad("Field '%s' is required" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %s" % (key, maximum))
    return value


def v_num(data, key, required=True, gt=None, ge=None, le=None, default=None):
    if not _present(data, key):
        if required:
            _bad("Field '%s' is required" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number" % key)
    value = float(value)
    if gt is not None and not value > gt:
        _bad("Field '%s' must be greater than %s" % (key, gt))
    if ge is not None and value < ge:
        _bad("Field '%s' must be >= %s" % (key, ge))
    if le is not None and value > le:
        _bad("Field '%s' must be <= %s" % (key, le))
    return value


def v_bool(data, key, required=False, default=None):
    if not _present(data, key):
        if required:
            _bad("Field '%s' is required" % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean" % key)
    return value


def v_enum(data, key, allowed, required=True, default=None):
    if not _present(data, key):
        if required:
            _bad("Field '%s' is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        _bad("Field '%s' must be one of %s" % (key, ", ".join(allowed)))
    return value


def v_list(data, key, required=True, min_len=None, default=None):
    if not _present(data, key):
        if required:
            _bad("Field '%s' is required" % key)
        return default
    value = data[key]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array" % key)
    if min_len is not None and len(value) < min_len:
        _bad("Field '%s' must contain at least %d element(s)" % (key, min_len))
    return value


def v_datetime(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            _bad("Field '%s' is required" % key)
        return default
    value = data[key]
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 UTC timestamp" % key)
    return parsed


def v_tool_type_list(data, key):
    value = v_list(data, key, required=True)
    if len(value) < 1:
        _bad("Field '%s' must be a non-empty array" % key)
    for element in value:
        if not isinstance(element, str) or element not in TOOL_TYPES:
            _bad("Field '%s' elements must each be one of %s" % (key, ", ".join(TOOL_TYPES)))
    return list(value)


# --------------------------------------------------------------- query params

def pagination():
    """limit defaults to 10 (1..100), offset defaults to 0 (min 0) - PRD 2.3."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            _bad("Query parameter 'limit' must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            _bad("Query parameter 'offset' must be >= 0")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed):
    value = q_str(name)
    if value is None:
        return None
    if value not in allowed:
        _bad("Query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value
