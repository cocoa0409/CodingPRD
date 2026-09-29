"""Request-shape validation, pagination and collection filters.

Shape problems (unknown enum value, wrong JSON type, missing required field)
are step 6 of the global ladder and therefore precede *every* 404 and every
state check. Pagination is step 7.
"""

from flask import request

from errors import fail
from util import D, parse_dt
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)


def body_dict():
    """Return the JSON body as a dict (an absent body counts as ``{}``)."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def present(body, name):
    return name in body and body[name] is not None


def _missing(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def _bad(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' has an invalid value." % name)


def str_field(body, name, required=False, min_len=None, max_len=None):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if not isinstance(value, str):
        _bad(name)
    if min_len is not None and len(value) < min_len:
        _bad(name)
    if max_len is not None and len(value) > max_len:
        _bad(name)
    return value


def int_field(body, name, required=False):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if isinstance(value, bool):
        _bad(name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    _bad(name)


def num_field(body, name, required=False):
    """Numeric field -- returned as ``Decimal`` so downstream math stays exact."""
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name)
    return D(value)


def bool_field(body, name, required=False, default=None):
    if not present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name)
    return value


def enum_field(body, name, allowed, required=False):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name)
    return value


def dt_field(body, name, required=False):
    """Returns ``(raw_string, datetime)``; the raw string is echoed verbatim."""
    if not present(body, name):
        if required:
            _missing(name)
        return None, None
    value = body[name]
    if not isinstance(value, str):
        _bad(name)
    parsed = parse_dt(value)
    if parsed is None:
        _bad(name)
    return value, parsed


def list_field(body, name, required=False):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if not isinstance(value, list):
        _bad(name)
    return value


def id_field(body, name, required=False):
    return str_field(body, name, required=required, min_len=1)


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be zero or greater.")
    return limit, offset


def apply_pagination(rows, limit, offset):
    return rows[offset:offset + limit]


# --------------------------------------------------------------------------
# collection filters
# --------------------------------------------------------------------------

def query_filters(spec):
    """Parse and validate the declared query filters for a collection.

    ``spec`` maps a query parameter name to either ``"str"``, ``"int"``,
    ``"bool"``, ``"dt"`` or a tuple/list of permitted enum values. Unknown enum
    values and wrong types are shape errors (ERR_INVALID_REQUEST).
    """
    out = {}
    args = request.args
    for name, kind in spec.items():
        if name not in args:
            continue
        raw = args.get(name)
        if kind == "str":
            out[name] = raw
        elif kind == "int":
            try:
                out[name] = int(str(raw).strip())
            except (TypeError, ValueError):
                fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
        elif kind == "bool":
            lowered = str(raw).strip().lower()
            if lowered in ("true", "1"):
                out[name] = True
            elif lowered in ("false", "0"):
                out[name] = False
            else:
                fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)
        elif kind == "dt":
            parsed = parse_dt(raw)
            if parsed is None:
                fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an ISO 8601 timestamp." % name)
            out[name] = parsed
        else:
            if raw not in kind:
                fail("ERR_INVALID_REQUEST", "Query parameter '%s' has an unknown value." % name)
            out[name] = raw
    return out


def check_range(name, value, minimum=None, maximum=None,
                min_exclusive=False, max_exclusive=False):
    """Step 36 of the ladder -- numeric bounds (ERR_VALUE_OUT_OF_RANGE, 422)."""
    if value is None:
        return
    v = D(value)
    if minimum is not None:
        low = D(minimum)
        if (v <= low) if min_exclusive else (v < low):
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is below its permitted range." % name)
    if maximum is not None:
        high = D(maximum)
        if (v >= high) if max_exclusive else (v > high):
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is above its permitted range." % name)


def match_filters(rows, filters, fields=None):
    """Exact-match every supplied filter against the identically named field."""
    fields = fields or list(filters.keys())
    result = rows
    for name in fields:
        if name not in filters:
            continue
        expected = filters[name]
        result = [r for r in result if r.get(name) == expected]
    return result
