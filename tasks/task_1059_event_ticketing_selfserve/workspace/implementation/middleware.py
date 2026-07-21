"""Authentication, role authorisation and request-shape validation.

Header scheme (PRD §2.1): X-User-Role names the acting role, X-User-ID names
the acting principal. Anonymous alone requires no X-User-ID.
"""
from flask import request

import db
from errors import ApiError

ROLES = ("Organizer", "Buyer", "GateStaff", "FinanceOfficer", "PlatformAdmin", "Anonymous")

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"

_MISSING = object()


class Actor(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_organizer(self):
        return self.role == "Organizer"

    @property
    def is_buyer(self):
        return self.role == "Buyer"


def authenticate(allowed_roles):
    """Step 1 (authentication) and step 2 (role authorisation) of PRD §2.8."""
    role = request.headers.get(ROLE_HEADER)
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or not a recognised role.")
    user_id = request.headers.get(ID_HEADER)
    if role != "Anonymous" and (user_id is None or user_id == ""):
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required for role %s." % role)
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not access this endpoint." % role)
    return Actor(role, user_id)


# --------------------------------------------------------------------------
# request-shape helpers (step 3 of PRD §2.8 -> ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def req_string(payload, field, allow_empty=False):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % field)
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if not allow_empty and value.strip() == "":
        bad("%s must be a non-empty string." % field)
    return value


def opt_string(payload, field, default=None, allow_null=True):
    value = payload.get(field, _MISSING)
    if value is _MISSING:
        return default
    if value is None:
        if allow_null:
            return None
        bad("%s must be a string." % field)
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    return value


def req_int(payload, field, minimum=None, maximum=None):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % field)
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %d." % (field, maximum))
    return value


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %d." % (field, maximum))
    return value


def req_enum(payload, field, members):
    value = req_string(payload, field)
    if value not in members:
        bad("%s must be one of %s." % (field, ", ".join(sorted(members))))
    return value


def opt_enum(payload, field, members, default=None):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in members:
        bad("%s must be one of %s." % (field, ", ".join(sorted(members))))
    return value


def req_datetime(payload, field):
    raw = req_string(payload, field)
    parsed = db.parse_iso(raw)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC instant." % field)
    return parsed


def query_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        bad("%s must be one of %s." % (name, ", ".join(sorted(members))))
    return value
