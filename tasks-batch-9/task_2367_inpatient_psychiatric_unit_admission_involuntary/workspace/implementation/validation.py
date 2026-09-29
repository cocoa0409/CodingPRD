"""Request body / query-string schema validation (ERR_INVALID_REQUEST, PRD §2.9 rule 3)."""

from flask import request

from errors import fail
from timeutil import parse_dt

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def body():
    """Parsed JSON object body; an absent body is treated as {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def _absent(data, name):
    return name not in data or data[name] is None


def vstr(data, name, required=True, allow_empty=False, default=None):
    if _absent(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", f"missing required field: {name}")
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", f"{name} must be a string")
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", f"{name} must not be empty")
    return value


def vbool(data, name, required=True, default=None):
    if _absent(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", f"missing required field: {name}")
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", f"{name} must be a boolean")
    return value


def vint(data, name, required=True, minimum=None, maximum=None, default=None):
    if _absent(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", f"missing required field: {name}")
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", f"{name} must be an integer")
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", f"{name} must be <= {maximum}")
    return value


def venum(data, name, allowed, required=True, default=None):
    if _absent(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", f"missing required field: {name}")
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(allowed)}")
    return value


def vdt(data, name, required=True, default=None):
    if _absent(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", f"missing required field: {name}")
        return default
    value = data[name]
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", f"{name} must be an ISO 8601 datetime")
    return parsed


def vchoice_in_set(data, name, allowed, required=True, default=None):
    return venum(data, name, allowed, required=required, default=default)


def pagination():
    """Read and validate limit/offset (PRD §2.3)."""
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail(
                "ERR_INVALID_REQUEST",
                f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}",
            )
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def filters(*names):
    """Equality filters from the query string."""
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            out[name] = value
    return out


def apply_filters(rows, spec):
    result = rows
    for field, value in spec.items():
        result = [r for r in result if str(r.get(field)) == value]
    return result
