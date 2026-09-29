"""Auth header extraction, role checking and request-body schema validation.

Header names and role spellings come from PRD §2.1 / SCAFFOLD validations[1..4].
"""

from decimal import Decimal, InvalidOperation

from flask import g, request

from db import parse_ts
from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "CatalogAdmin",
    "RightsManager",
    "LicensingAgent",
    "RoyaltyAccountant",
    "Composer",
    "Licensee",
)

ALL_STAFF = ("CatalogAdmin", "RightsManager", "LicensingAgent", "RoyaltyAccountant")


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------
def user_id():
    return request.headers.get(USER_ID_HEADER)


def user_role():
    return request.headers.get(USER_ROLE_HEADER)


def require_role(*allowed):
    """Validation ladder step 4 — ERR_UNAUTHORIZED (403)."""
    role = user_role()
    if role is None or role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role %r may not call this endpoint." % (role,))
    return role


def is_role(name):
    return user_role() == name


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------
def body():
    """The JSON request body as a dict; a missing body counts as empty."""
    if "_body" in g:
        return g._body
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        parsed = {}
    else:
        try:
            parsed = request.get_json(force=True, silent=False)
        except Exception:
            fail("ERR_VALIDATION", "Request body is not valid JSON.")
        if parsed is None:
            parsed = {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    g._body = parsed
    return parsed


def present(data, name):
    return name in data and data[name] is not None


# ---------------------------------------------------------------------------
# field validators — every failure is ERR_VALIDATION (422), ladder step 1
# ---------------------------------------------------------------------------
def _bad(name, why):
    fail("ERR_VALIDATION", "Field %r %s." % (name, why))


def req(data, name):
    if name not in data or data[name] is None:
        _bad(name, "is required")
    return data[name]


def opt_string(data, name, default=None, allow_empty=True):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "may not be empty")
    return value


def req_string(data, name, allow_empty=True):
    value = req(data, name)
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "may not be empty")
    return value


def req_enum(data, name, choices):
    value = req(data, name)
    if not isinstance(value, str) or value not in choices:
        _bad(name, "must be one of %s" % (", ".join(choices),))
    return value


def opt_enum(data, name, choices, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in choices:
        _bad(name, "must be one of %s" % (", ".join(choices),))
    return value


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % (minimum,))
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % (maximum,))
    return value


def req_int(data, name, minimum=None, maximum=None):
    return _check_int(name, req(data, name), minimum, maximum)


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    return _check_int(name, data[name], minimum, maximum)


def _check_number(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number")
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(name, "must be >= %s" % (minimum,))
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad(name, "must be <= %s" % (maximum,))
    return dec


def req_number(data, name, minimum=None, maximum=None):
    return _check_number(name, req(data, name), minimum, maximum)


def opt_number(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return None if default is None else Decimal(str(default))
    return _check_number(name, data[name], minimum, maximum)


def req_bool(data, name):
    value = req(data, name)
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_datetime(data, name):
    value = req(data, name)
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 timestamp string")
    parsed = parse_ts(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 timestamp string")
    return value, parsed


def opt_datetime(data, name):
    if not present(data, name):
        return None, None
    return req_datetime(data, name)


def req_enum_array(data, name, choices, min_len, max_len, distinct=True):
    value = req(data, name)
    return _check_enum_array(name, value, choices, min_len, max_len, distinct)


def opt_enum_array(data, name, choices, min_len, max_len, default=None, distinct=True):
    if not present(data, name):
        return default
    return _check_enum_array(name, data[name], choices, min_len, max_len, distinct)


def _check_enum_array(name, value, choices, min_len, max_len, distinct):
    if not isinstance(value, list):
        _bad(name, "must be an array")
    if len(value) < min_len or len(value) > max_len:
        _bad(name, "must hold between %d and %d members" % (min_len, max_len))
    for member in value:
        if not isinstance(member, str) or member not in choices:
            _bad(name, "members must be drawn from %s" % (", ".join(choices),))
    if distinct and len(set(value)) != len(value):
        _bad(name, "members must be distinct")
    return list(value)


def opt_int_array(data, name, minimum, maximum, min_len, max_len, default=None):
    if not present(data, name):
        return [] if default is None else list(default)
    value = data[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    if len(value) < min_len or len(value) > max_len:
        _bad(name, "must hold between %d and %d members" % (min_len, max_len))
    for member in value:
        _check_int(name, member, minimum, maximum)
    return list(value)
