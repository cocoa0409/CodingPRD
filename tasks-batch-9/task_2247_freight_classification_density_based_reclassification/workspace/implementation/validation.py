"""Request-shape helpers.

Step 6 of PRD 2.5 (presence / type / enum / range -> ERR_INVALID_REQUEST) is separated
from step 7 (domain-typed shape -> ERR_INVALID_CLASS_CODE, ERR_INVALID_DIMENSIONS,
ERR_INVALID_DENSITY_BREAKS, ERR_INVALID_INTERVAL) so that callers can run the two
passes in the normative order.
"""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import db
from constants import CLASS_CODE_SET
from errors import fail
from util import D, decimal_places, is_number

_MISSING = object()


def body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


# ---------------------------------------------------------------------------
# step 4 - foreign keys supplied in the body
# ---------------------------------------------------------------------------
def fk(payload, field, tablename, error_id, required=True):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None or not isinstance(raw, str) or not raw.strip():
        return None
    row = db.get(tablename, raw)
    if row is None:
        fail(error_id, "%s %s does not exist." % (field, raw))
    return row


def path_row(tablename, row_id, error_id):
    row = db.get(tablename, row_id)
    if row is None:
        fail(error_id, "Resource %s does not exist." % row_id)
    return row


# ---------------------------------------------------------------------------
# step 6 - request shape
# ---------------------------------------------------------------------------
def req_str(payload, field, min_len=1, max_len=None):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % field)
    value = raw
    if len(value.strip()) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % field)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters." % (field, max_len))
    if min_len > 1 and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters." % (field, min_len))
    return value


def opt_str(payload, field, default=None):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        return default
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % field)
    return raw


def req_int(payload, field, minimum=None, maximum=None):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return _as_int(field, raw, minimum, maximum)


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        return default
    return _as_int(field, raw, minimum, maximum)


def _as_int(field, raw, minimum, maximum):
    if isinstance(raw, bool) or not isinstance(raw, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    if minimum is not None and raw < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (field, minimum))
    if maximum is not None and raw > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (field, maximum))
    return raw


def req_number(payload, field, minimum=None, maximum=None):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return _as_number(field, raw, minimum, maximum)


def opt_number(payload, field, default=None, minimum=None, maximum=None):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        return default
    return _as_number(field, raw, minimum, maximum)


def _as_number(field, raw, minimum, maximum):
    if not is_number(raw):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % field)
    value = D(raw)
    if minimum is not None and value < D(minimum):
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (field, minimum))
    if maximum is not None and value > D(maximum):
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (field, maximum))
    return value


def req_enum(payload, field, allowed):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    if not isinstance(raw, str) or raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, ", ".join(allowed)))
    return raw


def opt_enum(payload, field, allowed, default=None):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        return default
    if not isinstance(raw, str) or raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, ", ".join(allowed)))
    return raw


def req_datetime(payload, field):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 string." % field)
    parsed = clock.parse(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a valid ISO-8601 instant." % field)
    return parsed


def req_bool(payload, field):
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    if not isinstance(raw, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % field)
    return raw


def must_be_absent(payload, field, reason=None):
    raw = payload.get(field, _MISSING)
    if raw is not _MISSING and raw is not None:
        fail("ERR_INVALID_REQUEST", reason or "%s must be null here." % field)


# ---------------------------------------------------------------------------
# step 7 - domain typed shape
# ---------------------------------------------------------------------------
def as_class_code(value, field="class code"):
    code = D(value)
    if code not in CLASS_CODE_SET:
        fail("ERR_INVALID_CLASS_CODE", "%s %s is not a recognized classification code." % (field, value))
    return code


def as_dimension(value, field="dimension"):
    dim = D(value)
    if dim <= 0:
        fail("ERR_INVALID_DIMENSIONS", "%s must be strictly greater than zero." % field)
    if decimal_places(dim) > 1:
        fail("ERR_INVALID_DIMENSIONS", "%s carries more than one decimal place." % field)
    return dim


def as_density_breaks(raw):
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_DENSITY_BREAKS", "density_breaks must be a non-empty array.")
    table = []
    previous = None
    for element in raw:
        if not isinstance(element, dict):
            fail("ERR_INVALID_DENSITY_BREAKS", "each density break must be an object.")
        min_density = element.get("min_density_pcf")
        class_code = element.get("class_code")
        if not is_number(min_density) or not is_number(class_code):
            fail("ERR_INVALID_DENSITY_BREAKS", "each density break needs numeric min_density_pcf and class_code.")
        try:
            min_density = D(min_density)
            class_code = D(class_code)
        except (InvalidOperation, ValueError):
            fail("ERR_INVALID_DENSITY_BREAKS", "malformed density break element.")
        if min_density < 0:
            fail("ERR_INVALID_DENSITY_BREAKS", "min_density_pcf may not be negative.")
        if class_code not in CLASS_CODE_SET:
            fail("ERR_INVALID_DENSITY_BREAKS", "density break names an unrecognized class code.")
        if previous is not None and not min_density < previous:
            fail("ERR_INVALID_DENSITY_BREAKS", "density_breaks must be strictly descending by min_density_pcf.")
        previous = min_density
        table.append({"min_density_pcf": min_density, "class_code": class_code})
    if table[-1]["min_density_pcf"] != Decimal(0):
        fail("ERR_INVALID_DENSITY_BREAKS", "density_breaks must terminate at min_density_pcf 0.")
    return table


def check_interval(start, end, message="interval end must be strictly after its start"):
    if not end > start:
        fail("ERR_INVALID_INTERVAL", message + ".")
    return start, end


# ---------------------------------------------------------------------------
# pagination and list filters (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def query_filter(name, allowed=None):
    raw = request.args.get(name)
    if raw is None:
        return None
    if allowed is not None and raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return raw
