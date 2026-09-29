"""Payload-shape validation (PRD S2.11 rung 7) and pagination (PRD S2.3)."""

from flask import request

from errors import fail
from store import parse_iso

_MISSING = object()


def body():
    """The JSON body as a dict.  A missing body is treated as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        if request.data.strip() == b"":
            return {}
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def peek_body():
    """A non-raising body read, used only where a rung above payload shape must
    consult a body field (the WAIVED seniority peek in PRD S2.11 rung 3)."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    return data if isinstance(data, dict) else {}


def _present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, required=True, default=None, allow_empty=True):
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if not allow_empty and value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % key)
    return value


def req_id(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an identifier string." % key)
    return value


def req_int(payload, key, required=True, default=None, minimum=None, maximum=None):
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    return value


def req_num(payload, key, required=True, default=None, minimum=None):
    """A non-monetary numeric field (fte_count).  Integers are accepted."""
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    return value


def req_bool(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def req_enum(payload, key, allowed, required=True, default=None):
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (key, ", ".join(allowed)),
        )
    return value


def req_dt(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = payload[key]
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def req_int_array_ascending(payload, key, required=True):
    if not _present(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return None
    value = payload[key]
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % key)
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain integers." % key)
    for i in range(1, len(value)):
        if value[i] <= value[i - 1]:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be strictly ascending." % key,
            )
    return list(value)


def require_interval(start, end, label="interval"):
    """Every interval must end strictly after it starts (PRD S2.11 rung 7)."""
    if start is not None and end is not None and end <= start:
        fail("ERR_INVALID_REQUEST", "%s must end strictly after it starts." % label)


# ---------------------------------------------------------------------------
# pagination and filters
# ---------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _parse_int_param(raw):
    text = raw.strip()
    if text == "":
        return None
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        parsed = _parse_int_param(raw_limit)
        if parsed is None or parsed < LIMIT_MIN or parsed > LIMIT_MAX:
            fail("ERR_PAGINATION_INVALID")
        limit = parsed
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        parsed = _parse_int_param(raw_offset)
        if parsed is None or parsed < OFFSET_MIN:
            fail("ERR_PAGINATION_INVALID")
        offset = parsed
    return limit, offset


_UNMATCHABLE = object()


def q_str(name):
    return request.args.get(name)


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return _UNMATCHABLE


def q_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    parsed = _parse_int_param(raw)
    if parsed is None:
        return _UNMATCHABLE
    return parsed


def matches(row, field, wanted):
    if wanted is None:
        return True
    if wanted is _UNMATCHABLE:
        return False
    return row.get(field) == wanted
