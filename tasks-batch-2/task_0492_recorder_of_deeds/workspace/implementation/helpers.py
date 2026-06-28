"""Request parsing, pagination, validation, and existence helpers.
All money is integer cents; percentage math uses Decimal + ROUND_HALF_UP
(PRD §2.6, §2.7)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import serialize


def body():
    """Parse the JSON body, tolerating an empty body (-> {})."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def round_half_up(value):
    """Round a Decimal/number to a whole integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paginate(items):
    """Apply limit/offset pagination (PRD §2.3). Defaults limit=10 (1..100),
    offset=0. Returns (window, limit, offset, total_count)."""
    limit = _int_param("limit", 10, minimum=1, maximum=100)
    offset = _int_param("offset", 0, minimum=0, maximum=None)
    total = len(items)
    window = items[offset:offset + limit]
    return window, limit, offset, total


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid %s" % name)
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s below minimum" % name)
    if maximum is not None and val > maximum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s above maximum" % name)
    return val


def sort_created(items):
    """Default list sort: created_at ascending. Tie-break on a monotonic
    creation sequence for stability when timestamps coincide (logical clock)."""
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


def out(entity):
    return serialize(entity)


def out_list(entities):
    return [serialize(e) for e in entities]


# --- Existence helper (ERR_NOT_FOUND, priority 3) ---

def get_or_404(collection, _id):
    ent = collection.get(_id)
    if ent is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return ent


# --- Request-body validation helpers (ERR_INVALID_REQUEST, priority 4) ---

def require_fields(data, names):
    for n in names:
        if n not in data or data[n] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing field: %s" % n)


def as_int(data, name, minimum=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s below minimum" % name)
    return v


def as_number(data, name, minimum=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a number" % name)
    if minimum is not None and v < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s below minimum" % name)
    return v


def as_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return v


def as_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a non-empty string" % name)
    return v


def as_enum(data, name, choices):
    v = data.get(name)
    if not isinstance(v, str) or v not in choices:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be one of %s" % (name, sorted(choices)))
    return v
