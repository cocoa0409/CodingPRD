"""Request body helpers, lookup helpers and rounding discipline (PRD 2.6, 2.7)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors
from errors import fail, invalid

MISSING = object()


# --------------------------------------------------------------------------
# rounding discipline (PRD 2.6)
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half-up to ``places`` decimals; returns Decimal."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half-up to whole cents; returns int."""
    return int(rhu(value, 0))


def hours2(value):
    """Hours carried to two decimals, round half-up; returns float."""
    return float(rhu(value, 2))


def amps1(value):
    """Amperage carried to one decimal, round half-up; returns float."""
    return float(rhu(value, 1))


def pct2(value):
    return float(rhu(value, 2))


def ceil_int(value):
    d = dec(value)
    whole = int(d)
    if d > whole:
        whole += 1
    return whole


def floor_int(value):
    d = dec(value)
    whole = int(d)
    if d < whole:
        whole -= 1
    return whole


def decimals_at_most(value, places):
    d = dec(value).normalize()
    exponent = d.as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    return -exponent <= places


# --------------------------------------------------------------------------
# body access
# --------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        invalid("Request body must be a JSON object.")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, allow_empty=False):
    if not _present(body, name):
        invalid("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str) or (not allow_empty and value.strip() == ""):
        invalid("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        invalid("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def _as_int(name, value):
    if isinstance(value, bool):
        invalid("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    invalid("Field '%s' must be an integer." % name)


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        invalid("Field '%s' is required." % name)
    value = _as_int(name, body[name])
    _range_check(name, value, minimum, maximum)
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    value = _as_int(name, body[name])
    _range_check(name, value, minimum, maximum)
    return value


def _range_check(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be <= %s." % (name, maximum))


def req_num(body, name, minimum=None, maximum=None, max_decimals=None):
    if not _present(body, name):
        invalid("Field '%s' is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % name)
    if minimum is not None and dec(value) < dec(minimum):
        invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec(value) > dec(maximum):
        invalid("Field '%s' must be <= %s." % (name, maximum))
    if max_decimals is not None and not decimals_at_most(value, max_decimals):
        invalid("Field '%s' may carry at most %d decimals." % (name, max_decimals))
    return value


def opt_num(body, name, default=None, minimum=None, maximum=None, max_decimals=None):
    if not _present(body, name):
        return default
    return req_num(body, name, minimum=minimum, maximum=maximum,
                   max_decimals=max_decimals)


def req_bool(body, name):
    if not _present(body, name):
        invalid("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=False):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def req_dt(body, name):
    """Returns (raw_string, datetime).  Input instants are echoed verbatim."""
    value = req_str(body, name)
    try:
        parsed = db.parse_iso(value)
    except (ValueError, TypeError):
        invalid("Field '%s' must be an ISO 8601 UTC instant." % name)
        return None
    return value, parsed


def opt_dt(body, name):
    if not _present(body, name):
        return None, None
    return req_dt(body, name)


def opt_str_list(body, name, allowed=None, default=None):
    if not _present(body, name):
        return list(default or [])
    value = body[name]
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % name)
    out = []
    for item in value:
        if not isinstance(item, str):
            invalid("Field '%s' must be an array of strings." % name)
        if allowed is not None and item not in allowed:
            invalid("Field '%s' contains an unknown value." % name)
        out.append(item)
    return out


# --------------------------------------------------------------------------
# existence lookups
# --------------------------------------------------------------------------
_TABLE_ERRORS = {
    "routes": errors.ERR_ROUTE_NOT_FOUND,
    "route_stops": errors.ERR_ROUTE_STOP_NOT_FOUND,
    "contracts": errors.ERR_CONTRACT_NOT_FOUND,
    "ride_allocations": errors.ERR_ALLOCATION_NOT_FOUND,
    "permit_applications": errors.ERR_PERMIT_NOT_FOUND,
    "inspection_orders": errors.ERR_INSPECTION_NOT_FOUND,
    "crew_assignments": errors.ERR_ASSIGNMENT_NOT_FOUND,
    "settlements": errors.ERR_SETTLEMENT_NOT_FOUND,
    "weather_closures": errors.ERR_CLOSURE_NOT_FOUND,
    "make_goods": errors.ERR_MAKEGOOD_NOT_FOUND,
    "workers": errors.ERR_WORKER_NOT_FOUND,
}


def path_row(table_name, row_id):
    """Path existence (global order step 4) with the table's own 404 id."""
    table = getattr(db.store, table_name)
    row = table.get(row_id)
    if row is None:
        fail(_TABLE_ERRORS[table_name], "%s not found." % table_name)
    return row


def path_jurisdiction(row_id):
    row = db.store.jurisdictions.get(row_id)
    if row is None:
        fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Jurisdiction not found.")
    return row


def path_venue(row_id):
    row = db.store.venues.get(row_id)
    if row is None:
        fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Venue not found.")
    return row


def path_ride(row_id):
    row = db.store.rides.get(row_id)
    if row is None:
        fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Ride not found.")
    return row


def body_ref(body, name, table_name, required=True):
    """Body reference existence (global order step 5)."""
    if not _present(body, name):
        if required:
            return None  # absence is reported later at step 6
        return None
    value = body[name]
    table = getattr(db.store, table_name)
    row = table.get(value) if isinstance(value, str) else None
    if row is None:
        fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND,
             "Referenced %s does not exist." % name)
    return row
