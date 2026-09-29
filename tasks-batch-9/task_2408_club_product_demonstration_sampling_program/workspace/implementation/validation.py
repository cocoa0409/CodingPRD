"""Rungs 1-5 of the rejection ladder: auth, endpoint role, body schema, pagination."""

import re

from flask import request

import calc
from errors import ApiError

ROLE_NAMES = (
    "ProgramAdmin",
    "ClubOperations",
    "Manufacturer",
    "StaffingCoordinator",
    "Demonstrator",
)

CLUB_NUMBER_RE = re.compile(r"^C\d{4}$")


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


# --- rung 1 -----------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_NAMES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid identity headers.")
    return Caller(user_id, role)


# --- rung 2 -----------------------------------------------------------------
def require_role(caller, allowed):
    if caller.role not in allowed:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorised for this endpoint." % caller.role,
        )


def guard(allowed):
    """rung 1 + rung 2 in one call."""
    caller = authenticate()
    require_role(caller, allowed)
    return caller


# --- rung 8 -----------------------------------------------------------------
def check_ownership(caller, manufacturer_id=None, club_id=None, demonstrator_id=None):
    """Entity-backed roles may only touch rows they own (write endpoints only)."""
    if caller.role == "Manufacturer" and manufacturer_id is not None:
        if caller.user_id != manufacturer_id:
            raise ApiError(
                "ERR_RESOURCE_OWNERSHIP", "Caller does not own this manufacturer's resource."
            )
    elif caller.role == "ClubOperations" and club_id is not None:
        if caller.user_id != club_id:
            raise ApiError(
                "ERR_RESOURCE_OWNERSHIP", "Caller does not own this club's resource."
            )
    elif caller.role == "Demonstrator" and demonstrator_id is not None:
        if caller.user_id != demonstrator_id:
            raise ApiError(
                "ERR_RESOURCE_OWNERSHIP", "Caller does not own this assignment."
            )


# --- rung 4 helpers ---------------------------------------------------------
def json_body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    raise ApiError("ERR_VALIDATION", "%s %s" % (field, why))


def present(body, field):
    return field in body and body[field] is not None


def req_present(body, field):
    if field not in body or body[field] is None:
        _bad(field, "is required.")
    return body[field]


def as_string(field, value, max_len=None, allow_empty=False):
    if not isinstance(value, str):
        _bad(field, "must be a string.")
    if not allow_empty and value.strip() == "":
        _bad(field, "must be non-empty.")
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters." % max_len)
    return value


def req_string(body, field, max_len=None, allow_empty=False):
    return as_string(field, req_present(body, field), max_len, allow_empty)


def opt_string(body, field, default=None, max_len=None, allow_empty=False):
    if not present(body, field):
        return default
    return as_string(field, body[field], max_len, allow_empty)


def as_int(field, value, minimum=None, maximum=None, choices=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %d." % maximum)
    if choices is not None and value not in choices:
        _bad(field, "must be one of %s." % (list(choices),))
    return value


def req_int(body, field, minimum=None, maximum=None, choices=None):
    return as_int(field, req_present(body, field), minimum, maximum, choices)


def opt_int(body, field, default=None, minimum=None, maximum=None, choices=None):
    if not present(body, field):
        return default
    return as_int(field, body[field], minimum, maximum, choices)


def as_bool(field, value):
    if not isinstance(value, bool):
        _bad(field, "must be a boolean.")
    return value


def req_bool(body, field):
    return as_bool(field, req_present(body, field))


def opt_bool(body, field, default=None):
    if not present(body, field):
        return default
    return as_bool(field, body[field])


def as_enum(field, value, allowed):
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s." % (list(allowed),))
    return value


def req_enum(body, field, allowed):
    return as_enum(field, req_present(body, field), allowed)


def opt_enum(body, field, allowed, default=None):
    if not present(body, field):
        return default
    return as_enum(field, body[field], allowed)


def req_date(body, field):
    value = req_present(body, field)
    parsed = calc.parse_date(value)
    if parsed is None:
        _bad(field, "must be a YYYY-MM-DD date.")
    return parsed


def opt_date(body, field, default=None):
    if not present(body, field):
        return default
    parsed = calc.parse_date(body[field])
    if parsed is None:
        _bad(field, "must be a YYYY-MM-DD date.")
    return parsed


def req_instant(body, field):
    value = req_present(body, field)
    parsed = calc.parse_instant(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant.")
    return parsed


def opt_instant(body, field, default=None):
    if not present(body, field):
        return default
    parsed = calc.parse_instant(body[field])
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant.")
    return parsed


def req_email(body, field):
    value = req_string(body, field)
    if "@" not in value:
        _bad(field, "must contain '@'.")
    return value


def opt_email(body, field, default=None):
    if not present(body, field):
        return default
    return req_email(body, field)


def opt_addon_services(body, field, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, list):
        _bad(field, "must be an array.")
    if len(value) > calc.MAX_ADDON_SERVICES:
        _bad(field, "may hold at most %d members." % calc.MAX_ADDON_SERVICES)
    seen = set()
    for member in value:
        if not isinstance(member, str) or member not in calc.ADDON_SERVICES:
            _bad(field, "members must be drawn from %s." % (calc.ADDON_SERVICES,))
        if member in seen:
            _bad(field, "members must be free of duplicates.")
        seen.add(member)
    return list(value)


def req_club_number(body, field):
    value = req_string(body, field)
    if not CLUB_NUMBER_RE.match(value):
        _bad(field, "must read as the letter C followed by exactly four digits.")
    return value


# --- rung 5 -----------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer from 1 through 100.")
        if str(limit_raw).strip() != str(limit):
            raise ApiError("ERR_VALIDATION", "limit must be an integer from 1 through 100.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be an integer from 1 through 100.")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer of at least 0.")
        if str(offset_raw).strip() != str(offset):
            raise ApiError("ERR_VALIDATION", "offset must be an integer of at least 0.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be an integer of at least 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", "%s must be one of %s." % (name, list(allowed)))
    return value
