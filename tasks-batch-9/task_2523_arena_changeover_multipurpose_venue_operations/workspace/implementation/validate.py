"""Authentication, role authorisation, request-shape and pagination validation.

Ladder ranks 1, 2, 5 and 6 of PRD 2.10 live here.
"""

from flask import request

from errors import ApiError
from store import parse_dt

ROLES = (
    "VenueOperationsDirector",
    "BookingManager",
    "ChangeoverSupervisor",
    "LaborCoordinator",
    "AnchorTenantRep",
)

ALL_ROLES = ROLES


def auth(allowed_roles):
    """Ladder 1 then 2. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def body():
    """The JSON request body as a dict; a malformed or absent body reads as {}."""
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def _present(payload, field):
    return field in payload and payload[field] is not None


def req_str(payload, field, min_len=1, max_len=None):
    if not _present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if len(value) < min_len:
        bad("%s must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (field, max_len))
    return value


def opt_str(payload, field, default=None, min_len=1, max_len=None):
    if not _present(payload, field):
        return default
    return req_str(payload, field, min_len=min_len, max_len=max_len)


def req_id(payload, field):
    if not _present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not isinstance(value, str) or not value:
        bad("%s must be a non-empty string identifier." % field)
    return value


def opt_id(payload, field):
    if not _present(payload, field):
        return None
    value = payload[field]
    if not isinstance(value, str) or not value:
        bad("%s must be a non-empty string identifier." % field)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_int(payload, field, minimum=None, maximum=None):
    if not _present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not _is_int(value):
        bad("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (field, maximum))
    return value


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    if not _present(payload, field):
        return default
    return req_int(payload, field, minimum=minimum, maximum=maximum)


def plain_int(payload, field):
    """An integer with no range constraint (e.g. expected_venue_version)."""
    if not _present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not _is_int(value):
        bad("%s must be an integer." % field)
    return value


def req_num(payload, field, minimum=None, maximum=None):
    if not _present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not _is_num(value):
        bad("%s must be a number." % field)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (field, maximum))
    return value


def opt_num(payload, field, default=None, minimum=None, maximum=None):
    if not _present(payload, field):
        return default
    return req_num(payload, field, minimum=minimum, maximum=maximum)


def req_bool(payload, field):
    if not _present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % field)
    return value


def req_enum(payload, field, members):
    if not _present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        bad("%s must be one of %s." % (field, ", ".join(members)))
    return value


def req_dt(payload, field):
    if not _present(payload, field):
        bad("%s is required." % field)
    parsed = parse_dt(payload[field])
    if parsed is None:
        bad("%s must be an ISO 8601 instant." % field)
    return parsed


def opt_dt(payload, field, default=None):
    if not _present(payload, field):
        return default
    return req_dt(payload, field)


def pagination():
    """PRD 2.3: limit default 10 (1..100), offset default 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer between 1 and 100.")
        if str(raw_limit).strip() != str(limit):
            bad("limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            bad("limit must be an integer between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer >= 0.")
        if str(raw_offset).strip() != str(offset):
            bad("offset must be an integer >= 0.")
        if offset < 0:
            bad("offset must be an integer >= 0.")
    return limit, offset


def filter_arg(name, members=None):
    """A query filter value; an unknown enum member simply matches nothing."""
    value = request.args.get(name)
    if value is None:
        return None
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
