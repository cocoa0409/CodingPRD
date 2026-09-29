"""Rung 1-2 authentication / authorization and rung 5 request-validity helpers.

The rejection ladder of PRD section 2.8 is enforced by the routes calling these
helpers in the documented order.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_iso

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_FIELD_TECHNICIAN = "FieldTechnician"
ROLE_QA_VERIFIER = "QAVerifier"
ROLE_UTILITY_INSPECTOR = "UtilityInspector"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_FIELD_TECHNICIAN,
    ROLE_QA_VERIFIER,
    ROLE_UTILITY_INSPECTOR,
)

_SENTINEL = object()


# --------------------------------------------------------------------------
# rungs 1-2
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Rung 1 (401) then rung 2 (403).  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------
# rung 5 - body access
# --------------------------------------------------------------------------
def body():
    """The JSON body as a dict.  A malformed or non-object body is an empty dict,
    which then surfaces as ERR_INVALID_REQUEST through the required-field checks."""
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {}


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def _present(data, name, required, default):
    if name not in data or data.get(name) is None:
        if required:
            _bad(name, "is required")
        return False, default
    return True, data.get(name)


def vstr(data, name, required=True, default=None, allow_empty=False):
    ok, value = _present(data, name, required, default)
    if not ok:
        return value
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


def vbool(data, name, required=True, default=None):
    ok, value = _present(data, name, required, default)
    if not ok:
        return value
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def vint(data, name, required=True, default=None, minimum=None, maximum=None):
    ok, value = _present(data, name, required, default)
    if not ok:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % maximum)
    return value


def vnum(data, name, required=True, default=None, minimum=None, maximum=None,
         exclusive_minimum=None):
    """A JSON number (int or float).  Returns a Decimal built from its literal text."""
    ok, value = _present(data, name, required, default)
    if not ok:
        return value if not isinstance(value, (int, float)) else to_decimal(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    dec = to_decimal(value)
    if dec is None or not dec.is_finite():
        _bad(name, "must be a finite number")
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(name, "must be >= %s" % minimum)
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad(name, "must be <= %s" % maximum)
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        _bad(name, "must be > %s" % exclusive_minimum)
    return dec


def venum(data, name, allowed, required=True, default=None):
    ok, value = _present(data, name, required, default)
    if not ok:
        return value
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def vdt(data, name, required=True, default=None, nullable=False):
    """An ISO 8601 UTC instant.  Returns an aware datetime."""
    if nullable and name in data and data.get(name) is None:
        return None
    ok, value = _present(data, name, required, default)
    if not ok:
        return value
    parsed = parse_iso(value)
    if parsed is None:
        _bad(name, "must be a well-formed ISO 8601 UTC instant")
    return parsed


def vlist_str(data, name, required=True):
    ok, value = _present(data, name, required, [])
    if not ok:
        return list(value or [])
    if not isinstance(value, list):
        _bad(name, "must be an array of strings")
    out = []
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            _bad(name, "must be an array of non-empty strings")
        out.append(item)
    return out


def vid(data, name, required=True):
    """A foreign-key style identifier: rung 4 resolves it, so only the scalar
    shape is policed here."""
    ok, value = _present(data, name, required, None)
    if not ok:
        return None
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be a non-empty string identifier")
    return value


def fk_candidate(data, name):
    """The raw payload value for a foreign key, for rung-4 existence checks.

    Returns the string when the key carries a usable identifier, otherwise None
    (absent, null or of the wrong scalar type - all of which are rung-5 faults)."""
    if name not in data:
        return None
    value = data.get(name)
    if isinstance(value, str) and value.strip() != "":
        return value
    return None


def to_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# --------------------------------------------------------------------------
# rung 5 - query string
# --------------------------------------------------------------------------
def pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            _bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            _bad("offset", "must be an integer >= 0")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def qenum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def qstr(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
