"""Shared helpers: record mutation, balance bucket math, body validation."""
from decimal import Decimal

from db import db, next_seq
from errors import err
from numeric import D, to_number


def touch(rec):
    """Refresh updated_at and bump version on a mutable record (§2.4)."""
    rec["updated_at"] = db.clock.now()
    rec["version"] = rec.get("version", 1) + 1


# --- balance bucket mutation -------------------------------------------------
# Buckets are stored as Decimal-string-derived floats but always manipulated via
# Decimal to avoid drift. We keep them as Decimal in the *_raw fields by storing
# Decimal objects directly.

def _bd(b, key):
    return D(b[key])


def credit_available(b, amount):
    b["available_raw"] = _bd(b, "available_raw") + D(amount)
    touch(b)


def debit_available(b, amount):
    b["available_raw"] = _bd(b, "available_raw") - D(amount)
    touch(b)


def credit_held(b, amount):
    b["held_raw"] = _bd(b, "held_raw") + D(amount)
    touch(b)


def debit_held(b, amount):
    b["held_raw"] = _bd(b, "held_raw") - D(amount)
    touch(b)


def credit_reserved(b, amount):
    b["reserved_raw"] = _bd(b, "reserved_raw") + D(amount)
    touch(b)


def debit_reserved(b, amount):
    b["reserved_raw"] = _bd(b, "reserved_raw") - D(amount)
    touch(b)


def available(b):
    return D(b["available_raw"])


# --- body validation ---------------------------------------------------------

def require_body(body):
    if body is None or not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def required_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Missing or invalid field: %s" % field)
    return v


def required_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def required_number(body, field, allow_zero=True, allow_negative=False):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    dv = D(v)
    if not allow_negative and dv < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must not be negative" % field)
    if not allow_zero and dv == 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must not be zero" % field)
    return dv


def optional_number(body, field, allow_negative=False):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    dv = D(v)
    if not allow_negative and dv < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must not be negative" % field)
    return dv


def required_int(body, field, allow_negative=False):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if not allow_negative and v < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must not be negative" % field)
    return v


def required_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v
