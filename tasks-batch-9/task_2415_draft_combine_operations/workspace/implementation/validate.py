"""Rule 3 (request shape) plus pagination helpers from PRD 2.3 / 2.4."""

from decimal import Decimal

from flask import request

from errors import ApiError
from timeutil import parse_iso

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body. A body that is present but not a JSON object,
    or malformed JSON, is a rule-3 failure."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def peek(field):
    """Lenient body read used for per-action role narrowing at rule 2."""
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get(field)
    if isinstance(value, str):
        return value
    return None


def present(data, name):
    return name in data and data[name] is not None


def _get(data, name, required):
    if name not in data or data[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return MISSING
    return data[name]


def string(data, name, required=True, allow_empty=False):
    raw = _get(data, name, required)
    if raw is MISSING:
        return None
    if not isinstance(raw, str):
        bad("Field '%s' must be a string." % name)
    if not allow_empty and raw.strip() == "":
        bad("Field '%s' may not be empty." % name)
    return raw


def integer(data, name, required=True, minimum=None, maximum=None):
    raw = _get(data, name, required)
    if raw is MISSING:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and raw < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and raw > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return raw


def number(data, name, required=True, minimum=None, maximum=None):
    """Returns a Decimal so downstream arithmetic stays exact."""
    raw = _get(data, name, required)
    if raw is MISSING:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        bad("Field '%s' must be a number." % name)
    value = Decimal(str(raw))
    if minimum is not None and value < Decimal(str(minimum)):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        bad("Field '%s' must be at most %s." % (name, maximum))
    return value


def boolean(data, name, required=True, default=None):
    raw = _get(data, name, required)
    if raw is MISSING:
        return default
    if not isinstance(raw, bool):
        bad("Field '%s' must be a boolean." % name)
    return raw


def enum(data, name, allowed, required=True, default=None):
    raw = _get(data, name, required)
    if raw is MISSING:
        return default
    if not isinstance(raw, str) or raw not in allowed:
        bad("Field '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return raw


def instant(data, name, required=True):
    raw = _get(data, name, required)
    if raw is MISSING:
        return None
    try:
        return parse_iso(raw)
    except Exception:
        bad("Field '%s' must be an ISO 8601 instant." % name)


def id_list(data, name, required=True):
    raw = _get(data, name, required)
    if raw is MISSING:
        return None
    if not isinstance(raw, list):
        bad("Field '%s' must be an array." % name)
    for item in raw:
        if not isinstance(item, str) or item.strip() == "":
            bad("Field '%s' must be an array of identifiers." % name)
    return list(raw)


def int_list(data, name, required=True):
    raw = _get(data, name, required)
    if raw is MISSING:
        return None
    if not isinstance(raw, list):
        bad("Field '%s' must be an array." % name)
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            bad("Field '%s' must be an array of integers." % name)
    return list(raw)


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def pagination():
    limit = _query_int("limit", 10)
    offset = _query_int("offset", 0)
    if limit < 1 or limit > 100:
        bad("Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        bad("Query parameter 'offset' must be zero or greater.")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_int(name, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be at most %s." % (name, maximum))
    return value


def page(items, limit, offset):
    return items[offset : offset + limit], len(items)
