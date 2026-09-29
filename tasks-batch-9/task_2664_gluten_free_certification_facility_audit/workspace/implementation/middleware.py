"""Auth header extraction, role checking, request-shape helpers."""

from decimal import Decimal

from flask import g, request

import clock
from constants import ALL_ROLES
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    """Validation 1 then 2: identity headers, then role authorisation."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def actor():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "user_role", None)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, allow_blank=False):
    if not _present(data, name):
        bad(name, "is required")
    value = data[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if not allow_blank and value.strip() == "":
        bad(name, "must not be blank")
    return value


def opt_str(data, name, default=None, allow_blank=True):
    if not _present(data, name):
        return default
    return req_str(data, name, allow_blank=allow_blank)


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_bool(data, name):
    if not _present(data, name):
        bad(name, "is required")
    value = data[name]
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    return req_bool(data, name)


def _number(data, name):
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    return value


def req_num(data, name, minimum=None, maximum=None,
            exclusive_min=None, exclusive_max=None):
    if not _present(data, name):
        bad(name, "is required")
    value = _number(data, name)
    _range(name, value, minimum, maximum, exclusive_min, exclusive_max)
    return value


def opt_num(data, name, default=None, minimum=None, maximum=None,
            exclusive_min=None, exclusive_max=None):
    if not _present(data, name):
        return default
    return req_num(data, name, minimum, maximum, exclusive_min, exclusive_max)


def _range(name, value, minimum, maximum, exclusive_min, exclusive_max):
    dv = Decimal(str(value))
    if minimum is not None and dv < Decimal(str(minimum)):
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and dv > Decimal(str(maximum)):
        bad(name, "must be <= %s" % maximum)
    if exclusive_min is not None and dv <= Decimal(str(exclusive_min)):
        bad(name, "must be > %s" % exclusive_min)
    if exclusive_max is not None and dv >= Decimal(str(exclusive_max)):
        bad(name, "must be < %s" % exclusive_max)


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        bad(name, "is required")
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def req_dt(data, name):
    value = req_str(data, name)
    parsed = clock.parse_iso_z(value)
    if parsed is None:
        bad(name, "must be an ISO 8601 instant with a Z offset")
    return parsed


def opt_dt(data, name, default=None):
    if not _present(data, name):
        return default
    return req_dt(data, name)


def req_country(data, name):
    value = req_str(data, name)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad(name, "must be exactly two uppercase letters")
    return value


def opt_id(data, name):
    if not _present(data, name):
        return None
    return req_str(data, name)
