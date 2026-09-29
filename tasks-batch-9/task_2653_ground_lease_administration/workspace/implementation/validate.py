"""Request-body validators, pagination parsing and money arithmetic.

All monetary and basis-point arithmetic goes through :func:`rhu` -- integer
division rounded half up on Decimal, never float (PRD 2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import store
from errors import ApiError

ONE = Decimal("1")


def rhu(numerator, denominator):
    """Divide two integers and round the result half up to a whole unit."""
    if denominator == 0:
        return 0
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(q.quantize(ONE, rounding=ROUND_HALF_UP))


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# Body access.
# ---------------------------------------------------------------------------
def body():
    """The parsed JSON object, or {} when the request carried no body."""
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise bad("Request body must be a JSON object.")
    return payload


def reject_unknown(payload, allowed):
    for key in payload:
        if key not in allowed:
            raise bad("Unrecognised field '%s'." % key)


# ---------------------------------------------------------------------------
# Scalar field helpers.  Every one raises ERR_INVALID_REQUEST on shape faults.
# ---------------------------------------------------------------------------
def req_str(payload, field, max_len=512):
    if field not in payload or payload[field] is None:
        raise bad("Field '%s' is required." % field)
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be a non-empty string." % field)
    if len(value) > max_len:
        raise bad("Field '%s' is too long." % field)
    return value.strip()


def opt_str(payload, field, default=None, max_len=512):
    if field not in payload or payload[field] is None:
        return default
    return req_str(payload, field, max_len=max_len)


def req_enum(payload, field, allowed):
    value = req_str(payload, field)
    if value not in allowed:
        raise bad("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def opt_enum(payload, field, allowed, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_enum(payload, field, allowed)


def _as_int(field, value):
    if isinstance(value, bool):
        raise bad("Field '%s' must be an integer." % field)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise bad("Field '%s' must be a whole number." % field)
        return int(value)
    raise bad("Field '%s' must be an integer." % field)


def req_int(payload, field, minimum=None, maximum=None):
    if field not in payload or payload[field] is None:
        raise bad("Field '%s' is required." % field)
    value = _as_int(field, payload[field])
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be at most %d." % (field, maximum))
    return value


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    if field not in payload or payload[field] is None:
        return default
    return req_int(payload, field, minimum=minimum, maximum=maximum)


def req_money(payload, field):
    """Non-negative integer cents."""
    return req_int(payload, field, minimum=0)


def opt_money(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_money(payload, field)


def req_bps(payload, field):
    return req_int(payload, field, minimum=0, maximum=10000)


def opt_bps(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_bps(payload, field)


def req_area(payload, field):
    return req_int(payload, field, minimum=0)


def opt_area(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_area(payload, field)


def req_score(payload, field):
    return req_int(payload, field, minimum=0, maximum=100)


def req_bool(payload, field):
    if field not in payload or payload[field] is None:
        raise bad("Field '%s' is required." % field)
    if not isinstance(payload[field], bool):
        raise bad("Field '%s' must be a boolean." % field)
    return payload[field]


def opt_bool(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_bool(payload, field)


def req_dt(payload, field):
    text = req_str(payload, field)
    parsed = store.parse_dt(text)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 timestamp." % field)
    return parsed


def opt_dt(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_dt(payload, field)


def fk_present(payload, field):
    """True when a foreign-key field carries a usable (non-null) value.

    A present-but-wrong reference is resolved as a not-found; an absent one is
    a body-shape fault handled at the lower priority band.
    """
    return field in payload and payload[field] is not None


def fk_value(payload, field):
    value = payload[field]
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return "\x00unresolvable"
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3).
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must be zero or greater.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
