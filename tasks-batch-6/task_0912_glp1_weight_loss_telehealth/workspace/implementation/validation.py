"""Body-shape and query-parameter validation (PRD 2.7 rung 5, PRD 2.3).

Every failure in this module is ERR_VALIDATION (400).  In particular PRD 2.7
rung 5 and the PRD section 5 catalogue route *every* enum-membership failure
here -- "every enum value is a declared member ... otherwise ERR_VALIDATION" --
so no enum field anywhere in the service is routed to a different identifier.
"""

from flask import request

import errors
from errors import ApiError
from store import parse_iso

MISSING = object()


def _fail(message):
    raise ApiError(errors.ERR_VALIDATION, message)


def body():
    """The JSON body as a dict; a missing or malformed body reads as empty."""
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _fail("Request body must be a JSON object.")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def require_present(data, name):
    if not _present(data, name):
        _fail("Field '%s' is required." % name)


# --- scalars ---------------------------------------------------------------
def string_field(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % name)
    return value


def bool_field(data, name, required=False, default=None):
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        _fail("Field '%s' must be a boolean." % name)
    return value


def int_field(data, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _fail("Field '%s' must be at most %s." % (name, maximum))
    return value


def number_field(data, name, required=True, default=None, minimum=None,
                 exclusive_minimum=None):
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _fail("Field '%s' must be greater than %s." % (name, exclusive_minimum))
    return float(value) if isinstance(value, float) else value


def enum_field(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        _fail("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def datetime_field(data, name, required=True, default=None):
    """Returns the caller's exact string; it is echoed back verbatim."""
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or parse_iso(value) is None:
        _fail("Field '%s' must be an ISO 8601 instant." % name)
    return value


def state_code_field(data, name, required=True, default=None):
    value = string_field(data, name, required=required, default=default)
    if value is default and not _present(data, name):
        return default
    if len(value) != 2 or not value.isalpha() or not value.isupper():
        _fail("Field '%s' must be exactly two upper-case letters." % name)
    return value


def state_code_list(data, name, required=False, default=None):
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return list(default) if default is not None else []
    value = data[name]
    if not isinstance(value, list):
        _fail("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or len(item) != 2 or not item.isalpha() \
                or not item.isupper():
            _fail("Field '%s' entries must be two upper-case letters." % name)
    return list(value)


def enum_list(data, name, allowed, required=False, default=None, unique=True):
    if not _present(data, name):
        if required:
            _fail("Field '%s' is required." % name)
        return list(default) if default is not None else []
    value = data[name]
    if not isinstance(value, list):
        _fail("Field '%s' must be an array." % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _fail("Field '%s' entries must be one of %s." % (name, ", ".join(allowed)))
        if unique and item in seen:
            _fail("Field '%s' may not repeat a value." % name)
        seen.add(item)
    return list(value)


def interval(start_raw, end_raw, start_name="scheduled_start_at",
             end_name="scheduled_end_at"):
    """PRD 2.7 rung 5: every interval's end is strictly after its start."""
    start = parse_iso(start_raw)
    end = parse_iso(end_raw)
    if start is None or end is None:
        _fail("Both %s and %s must be ISO 8601 instants." % (start_name, end_name))
    if not end > start:
        _fail("%s must be strictly after %s." % (end_name, start_name))
    return start, end


# --- query parameters ------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _fail("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            _fail("Query parameter 'limit' must be between 1 and 100.")

    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _fail("Query parameter 'offset' must be an integer.")
        if offset < 0:
            _fail("Query parameter 'offset' may not be negative.")

    return limit, offset


def query_filters(*names):
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            out[name] = value
    return out


def apply_filters(records, filters, field_map=None):
    field_map = field_map or {}
    out = records
    for name, value in filters.items():
        field = field_map.get(name, name)
        out = [r for r in out if str(r.get(field)) == value]
    return out


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
