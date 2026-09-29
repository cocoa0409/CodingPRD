"""Authentication, role authorization, unit scope and request-schema helpers.

Implements bands 1, 2, 4 and 5 of the rejection precedence (PRD 2.10).
"""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError

ROLES = (
    "NetworkAdmin",
    "UnitDirector",
    "IntakeNeonatologist",
    "ReferringClinician",
    "TransportCoordinator",
    "BedsideNurse",
    "FollowUpCoordinator",
)

UNIT_SCOPED_ROLES = ("UnitDirector", "IntakeNeonatologist", "ReferringClinician")

ALL_ROLES = list(ROLES)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def unit(self):
        """The unit portion of a unit-scoped X-User-ID (text before the colon)."""
        if ":" in self.user_id:
            return self.user_id.split(":", 1)[0]
        return self.user_id

    @property
    def is_unit_scoped(self):
        return self.role in UNIT_SCOPED_ROLES


def authenticate(allowed_roles):
    """Bands 1 and 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", 403)
    return Caller(user_id, role)


def require_scope(caller, unit_id):
    """Band 4. Only mutating operations are unit-scope gated; reads are shared."""
    if request.method == "GET":
        return
    if not caller.is_unit_scoped:
        return
    if unit_id is None:
        return
    if caller.unit != unit_id:
        raise ApiError("ERR_UNIT_SCOPE_VIOLATION", 403)


# --------------------------------------------------------------------------
# Body / query helpers (band 5)
# --------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", 400, "%s %s." % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def req_string(data, field, allow_empty=False):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and not value.strip():
        _bad(field, "must be a non-empty string")
    return value


def opt_string(data, field, default=None, allow_empty=True):
    if not present(data, field):
        return default
    return req_string(data, field, allow_empty=allow_empty)


def req_enum(data, field, allowed):
    value = req_string(data, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_number(data, field, minimum=None, maximum=None, exclusive_min=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        _bad(field, "must be a number")
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad(field, "must be <= %s" % maximum)
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        _bad(field, "must be > %s" % exclusive_min)
    return dec


def opt_number(data, field, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not present(data, field):
        return default
    return req_number(data, field, minimum=minimum, maximum=maximum,
                      exclusive_min=exclusive_min)


def req_bool(data, field):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    return req_bool(data, field)


def req_dt(data, field):
    value = req_string(data, field)
    parsed = clock.parse_dt(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 instant")
    return parsed


def opt_dt(data, field, default=None):
    if not present(data, field):
        return default
    return req_dt(data, field)


def req_str_array(data, field, allowed=None):
    if not present(data, field):
        _bad(field, "is required")
    return _check_str_array(data[field], field, allowed)


def opt_str_array(data, field, default=None, allowed=None):
    if not present(data, field):
        return default
    return _check_str_array(data[field], field, allowed)


def _check_str_array(value, field, allowed):
    if not isinstance(value, list):
        _bad(field, "must be an array")
    for item in value:
        if not isinstance(item, str):
            _bad(field, "must be an array of strings")
        if allowed is not None and item not in allowed:
            _bad(field, "may only contain %s" % ", ".join(allowed))
    return list(value)


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be a non-negative integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def filters(*names):
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            out[name] = value
    return out


def page(rows, limit, offset):
    return rows[offset:offset + limit]
