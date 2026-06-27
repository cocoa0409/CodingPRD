"""Request-body validation primitives and existence lookups.

Validation ordering (PRD §2.10): auth -> RBAC -> existence (path then body
left-to-right) -> OCC -> state -> field shape/range (422) -> uniqueness (409)
-> cross-herd referential (409) -> temporal/safety.
"""
import db
import errors
from errors import err
from util import parse_datetime

# Lookup table: entity dict -> not-found error pair
_NOT_FOUND = {
    "herd": (db.herds, errors.ERR_HERD_NOT_FOUND),
    "parlor": (db.parlors, errors.ERR_PARLOR_NOT_FOUND),
    "ration": (db.rations, errors.ERR_RATION_NOT_FOUND),
    "price_sheet": (db.coop_price_sheets, errors.ERR_PRICE_SHEET_NOT_FOUND),
    "animal": (db.animals, errors.ERR_ANIMAL_NOT_FOUND),
    "lactation": (db.lactations, errors.ERR_LACTATION_NOT_FOUND),
    "shift": (db.milking_shifts, errors.ERR_SHIFT_NOT_FOUND),
    "breeding": (db.breeding_events, errors.ERR_BREEDING_NOT_FOUND),
    "treatment": (db.health_treatments, errors.ERR_TREATMENT_NOT_FOUND),
    "milk_check": (db.milk_checks, errors.ERR_MILK_CHECK_NOT_FOUND),
}


def get_or_404(kind, rid):
    store, error_pair = _NOT_FOUND[kind]
    if rid is None or rid not in store:
        raise err(error_pair, "%s not found" % kind)
    return store[rid]


def require_json_object():
    from flask import request
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def invalid(message="Invalid request"):
    return err(errors.ERR_INVALID_REQUEST, message)


def require_str(body, key, allow_empty=False):
    if key not in body:
        raise invalid("Missing field: %s" % key)
    val = body[key]
    if not isinstance(val, str):
        raise invalid("Field %s must be a string" % key)
    if not allow_empty and not val.strip():
        raise invalid("Field %s must not be empty" % key)
    return val


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise invalid("Field %s must be a string" % key)
    return val


def require_number(body, key, minimum=None, maximum=None):
    if key not in body:
        raise invalid("Missing field: %s" % key)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise invalid("Field %s must be a number" % key)
    if minimum is not None and val < minimum:
        raise invalid("Field %s must be >= %s" % (key, minimum))
    if maximum is not None and val > maximum:
        raise invalid("Field %s must be <= %s" % (key, maximum))
    return val


def opt_number(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise invalid("Field %s must be a number" % key)
    if minimum is not None and val < minimum:
        raise invalid("Field %s must be >= %s" % (key, minimum))
    if maximum is not None and val > maximum:
        raise invalid("Field %s must be <= %s" % (key, maximum))
    return val


def require_int(body, key, minimum=None, maximum=None):
    if key not in body:
        raise invalid("Missing field: %s" % key)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid("Field %s must be an integer" % key)
    if minimum is not None and val < minimum:
        raise invalid("Field %s must be >= %s" % (key, minimum))
    if maximum is not None and val > maximum:
        raise invalid("Field %s must be <= %s" % (key, maximum))
    return val


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid("Field %s must be an integer" % key)
    if minimum is not None and val < minimum:
        raise invalid("Field %s must be >= %s" % (key, minimum))
    if maximum is not None and val > maximum:
        raise invalid("Field %s must be <= %s" % (key, maximum))
    return val


def require_datetime(body, key):
    if key not in body:
        raise invalid("Missing field: %s" % key)
    dt = parse_datetime(body[key])
    if dt is None:
        raise invalid("Field %s must be an ISO 8601 datetime" % key)
    return dt


def require_enum(body, key, allowed):
    val = require_str(body, key)
    if val not in allowed:
        raise invalid("Field %s must be one of %s" % (key, sorted(allowed)))
    return val


def require_fk(body, key):
    """A foreign-key string field must be present and a non-empty string."""
    return require_str(body, key)
