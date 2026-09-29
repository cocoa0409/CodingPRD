"""Auth / RBAC (PRD 2.1) plus body & query-parameter validation (rule 3)."""

from flask import request

from errors import ApiError
from util import parse_dt

ROLES = [
    "Patron",
    "BoxOfficeAgent",
    "TicketingApprover",
    "GateOperator",
    "SecurityInvestigator",
    "VenueAdmin",
]

ANY_ROLE = tuple(ROLES)


def auth(allowed_roles):
    """Rule 1 then rule 2 of the global ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


# --------------------------------------------------------------------------
# Request body helpers -- every failure is ERR_INVALID_REQUEST (400), rule 3.
# --------------------------------------------------------------------------

def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


_MISSING = object()


def f_str(body, key, required=True, default=None, allow_empty=True):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            invalid("'%s' is required." % key)
        return default
    if not isinstance(value, str):
        invalid("'%s' must be a string." % key)
    if not allow_empty and not value.strip():
        invalid("'%s' must be a non-empty string." % key)
    return value


def f_int(body, key, required=True, default=None, minimum=None, maximum=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            invalid("'%s' is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("'%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        invalid("'%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("'%s' must be <= %s." % (key, maximum))
    return value


def f_number(body, key, required=True, default=None, minimum=None, maximum=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            invalid("'%s' is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("'%s' must be a number." % key)
    if minimum is not None and value < minimum:
        invalid("'%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("'%s' must be <= %s." % (key, maximum))
    return value


def f_bool(body, key, required=True, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            invalid("'%s' is required." % key)
        return default
    if not isinstance(value, bool):
        invalid("'%s' must be a boolean." % key)
    return value


def f_enum(body, key, allowed, required=True, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            invalid("'%s' is required." % key)
        return default
    if not isinstance(value, str) or value not in allowed:
        invalid("'%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def f_dt(body, key, required=True):
    """Returns (raw_string, datetime). Input instants are echoed verbatim."""
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            invalid("'%s' is required." % key)
        return None, None
    if not isinstance(value, str):
        invalid("'%s' must be an ISO-8601 timestamp string." % key)
    parsed = parse_dt(value)
    if parsed is None:
        invalid("'%s' must be a parseable ISO-8601 timestamp." % key)
    return value, parsed


# --------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# --------------------------------------------------------------------------

def paging():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("'limit' must be an integer.")
        if limit < 1 or limit > 100:
            invalid("'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("'offset' must be an integer.")
        if offset < 0:
            invalid("'offset' must be >= 0.")
    return limit, offset


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_bool(name):
    value = q(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None
