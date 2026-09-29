"""Request screening helpers: identity, role, body shape, pagination.

Rung 1 and rung 2 of the PRD section 2.7 ladder live in `auth`; every typed
getter here raises ERR_INVALID_REQUEST (422), which is rung 6.
"""
from decimal import Decimal, InvalidOperation

from flask import request

import store
from constants import ROLES
from errors import (
    ERR_INVALID_REQUEST,
    ERR_ROLE_NOT_PERMITTED,
    ERR_UNAUTHENTICATED,
    fail,
)


def auth(*roles):
    """Rung 1 then rung 2. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        fail(ERR_UNAUTHENTICATED, "X-User-ID header is required.")
    if not role or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, "X-User-Role header must name one of the six roles.")
    if roles and role not in roles:
        fail(ERR_ROLE_NOT_PERMITTED, "Role %s may not call this endpoint." % role)
    return user_id, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def _missing(data, name, required, default):
    if name not in data or data[name] is None:
        if required:
            fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return True, default
    return False, None


def get_str(data, name, min_len=1, max_len=None, required=True, default=None,
            blank_ok=False):
    absent, dflt = _missing(data, name, required, default)
    if absent:
        return dflt
    value = data[name]
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
    if not blank_ok and not value.strip():
        fail(ERR_INVALID_REQUEST, "Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        fail(ERR_INVALID_REQUEST, "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail(ERR_INVALID_REQUEST, "Field '%s' is too long." % name)
    return value


def get_enum(data, name, members, required=True, default=None):
    absent, dflt = _missing(data, name, required, default)
    if absent:
        return dflt
    value = data[name]
    if not isinstance(value, str) or value not in members:
        fail(ERR_INVALID_REQUEST,
             "Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def get_bool(data, name, required=True, default=None):
    absent, dflt = _missing(data, name, required, default)
    if absent:
        return dflt
    value = data[name]
    if not isinstance(value, bool):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % name)
    return value


def _as_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)


def get_num(data, name, minv=None, maxv=None, places=None, required=True,
            default=None, exclusive_min=False):
    absent, dflt = _missing(data, name, required, default)
    if absent:
        return dflt
    dec = _as_decimal(name, data[name])
    if not dec.is_finite():
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a finite number." % name)
    if places is not None:
        exp = dec.as_tuple().exponent
        if exp < -places:
            fail(ERR_INVALID_REQUEST,
                 "Field '%s' allows at most %d decimal places." % (name, places))
    if minv is not None:
        limit = Decimal(str(minv))
        if exclusive_min:
            if dec <= limit:
                fail(ERR_INVALID_REQUEST, "Field '%s' must be greater than %s." % (name, limit))
        elif dec < limit:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be at least %s." % (name, limit))
    if maxv is not None and dec > Decimal(str(maxv)):
        fail(ERR_INVALID_REQUEST, "Field '%s' must not exceed %s." % (name, maxv))
    return dec


def get_int(data, name, minv=None, maxv=None, required=True, default=None):
    absent, dflt = _missing(data, name, required, default)
    if absent:
        return dflt
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    dec = _as_decimal(name, value)
    if dec != dec.to_integral_value():
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    ival = int(dec)
    if minv is not None and ival < minv:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be at least %s." % (name, minv))
    if maxv is not None and ival > maxv:
        fail(ERR_INVALID_REQUEST, "Field '%s' must not exceed %s." % (name, maxv))
    return ival


def get_dt(data, name, required=True, default=None):
    absent, dflt = _missing(data, name, required, default)
    if absent:
        return dflt
    value = data[name]
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO-8601 timestamp." % name)
    parsed = store.parse_iso(value)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO-8601 timestamp." % name)
    return parsed


def get_enum_array(data, name, members, required=True, default=None):
    absent, dflt = _missing(data, name, required, default)
    if absent:
        return dflt
    value = data[name]
    if not isinstance(value, list) or not value:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a non-empty array." % name)
    for member in value:
        if not isinstance(member, str) or member not in members:
            fail(ERR_INVALID_REQUEST,
                 "Field '%s' members must be one of %s." % (name, ", ".join(members)))
    return list(value)


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        text = args.get("limit")
        try:
            limit = int(str(text).strip())
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        text = args.get("offset")
        try:
            offset = int(str(text).strip())
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must not be negative.")
    return limit, offset


def arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def arg_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be a boolean." % name)
