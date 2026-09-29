"""Body / query validation helpers.

Precedence rule 3 (ERR_INVALID_REQUEST, 400) covers presence, declared type and
the declared numeric bounds.  Rule 4 (ERR_INVALID_ENUM, 400) covers enum
membership and is therefore always evaluated *after* every rule-3 check on the
same request.
"""

from decimal import InvalidOperation

from flask import request

from errors import ApiError
from money import dec
from timeutil import fmt_iso, parse_iso

_MISSING = object()


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(name, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_int(payload, name, gt=None, ge=None, le=None, lt=None):
    if not _present(payload, name):
        _bad(name, "is required")
    return _as_int(payload[name], name, gt, ge, le, lt)


def opt_int(payload, name, default=None, gt=None, ge=None, le=None, lt=None):
    if not _present(payload, name):
        return default
    return _as_int(payload[name], name, gt, ge, le, lt)


def _as_int(value, name, gt=None, ge=None, le=None, lt=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if gt is not None and not value > gt:
        _bad(name, "must be greater than %s" % gt)
    if ge is not None and not value >= ge:
        _bad(name, "must be at least %s" % ge)
    if le is not None and not value <= le:
        _bad(name, "must be at most %s" % le)
    if lt is not None and not value < lt:
        _bad(name, "must be below %s" % lt)
    return value


def req_number(payload, name, gt=None, ge=None, le=None, max_dp=None):
    if not _present(payload, name):
        _bad(name, "is required")
    return _as_number(payload[name], name, gt, ge, le, max_dp)


def opt_number(payload, name, default=None, gt=None, ge=None, le=None, max_dp=None):
    if not _present(payload, name):
        return default
    return _as_number(payload[name], name, gt, ge, le, max_dp)


def _as_number(value, name, gt=None, ge=None, le=None, max_dp=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    try:
        as_dec = dec(value)
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number")
    if not as_dec.is_finite():
        _bad(name, "must be a finite number")
    if gt is not None and not as_dec > dec(gt):
        _bad(name, "must be greater than %s" % gt)
    if ge is not None and not as_dec >= dec(ge):
        _bad(name, "must be at least %s" % ge)
    if le is not None and not as_dec <= dec(le):
        _bad(name, "must be at most %s" % le)
    if max_dp is not None:
        exponent = as_dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and -exponent > max_dp:
            _bad(name, "must carry at most %d decimal places" % max_dp)
    return value


def req_str(payload, name):
    if not _present(payload, name):
        _bad(name, "is required")
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    return value


def opt_str(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    return value


def opt_bool(payload, name, default=False):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_datetime(payload, name):
    """Return the instant normalised to the canonical three-fraction-digit form."""
    text = req_str(payload, name)
    parsed = parse_iso(text)
    if parsed is None:
        _bad(name, "must be an ISO 8601 instant")
    return fmt_iso(parsed)


def check_enum(value, allowed, name):
    if value is None:
        return None
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "Field '%s' must be one of %s." % (name, ", ".join(allowed)),
        )
    return value


# --------------------------------------------------------------------------
# Pagination (PRD §2.3, precedence rule 5)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def pagination(strict=False):
    """Return (limit, offset).

    ``strict`` is set only for GET /hotel-management/budgets, the one list
    operation whose pagination arguments precedence rule 5 validates.  Every
    other list clamps into range instead of failing.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET

    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            if strict:
                raise ApiError("ERR_INVALID_PAGINATION")
            limit = DEFAULT_LIMIT
        else:
            if limit < MIN_LIMIT or limit > MAX_LIMIT:
                if strict:
                    raise ApiError("ERR_INVALID_PAGINATION")
                limit = min(max(limit, MIN_LIMIT), MAX_LIMIT)

    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            if strict:
                raise ApiError("ERR_INVALID_PAGINATION")
            offset = DEFAULT_OFFSET
        else:
            if offset < 0:
                if strict:
                    raise ApiError("ERR_INVALID_PAGINATION")
                offset = DEFAULT_OFFSET

    return limit, offset


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None
