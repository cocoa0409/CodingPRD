"""Auth header extraction, role checking and request payload validation.

Ladder tiers implemented here: tier 1 (authentication), tier 2 (authorization)
and the tier 5 schema/enum/range machinery used by the route modules.
"""

from flask import request

from db import parse_date, parse_instant, store
from errors import ApiError

# PRD 2.1 - exactly these six role values are recognised.
ROLES = (
    "PerformanceDirector",
    "Coach",
    "MedicalProvider",
    "FrontDesk",
    "Athlete",
    "Guardian",
)

ATHLETE_ROLES = ("Athlete", "Guardian")


class Ctx(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id
        self.staff = None

    @property
    def is_athlete_role(self):
        return self.role in ATHLETE_ROLES


def guard(*allowed_roles):
    """Tier 1 then tier 2.  Returns the acting context."""
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "A recognised X-User-Role header is required")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    return Ctx(role, request.headers.get("X-User-ID"))


def guard_optional(*allowed_roles):
    """Used by the logical-clock facility, which requires no role header."""
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        return Ctx(None, request.headers.get("X-User-ID"))
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "A recognised X-User-Role header is required")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    return Ctx(role, request.headers.get("X-User-ID"))


def resolve_acting_staff(ctx):
    """A Coach's X-User-ID must resolve to a StaffMember (PRD 2.1 / 2.9)."""
    if ctx.role != "Coach":
        return None
    staff = store.staff_members.get(ctx.user_id) if ctx.user_id else None
    if staff is None:
        raise ApiError("ERR_STAFF_MEMBER_NOT_FOUND", "Acting X-User-ID does not resolve to a staff member")
    ctx.staff = staff
    return staff


# --------------------------------------------------------------- payload ----
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _invalid(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def present(body, name):
    return name in body and body[name] is not None


def v_string(body, name, required=True, min_len=1, max_len=None, default=None, nullable=False):
    if name not in body or body[name] is None:
        if required and not nullable:
            _invalid(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        _invalid(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _invalid(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _invalid(name, "must be at most %d characters" % max_len)
    return value


def v_enum(body, name, allowed, required=True, default=None, nullable=False):
    if name not in body or body[name] is None:
        if required and not nullable:
            _invalid(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _invalid(name, "must be one of %s" % ", ".join(allowed))
    return value


def v_int(body, name, required=True, minimum=None, maximum=None, default=None, nullable=False):
    if name not in body or body[name] is None:
        if required and not nullable:
            _invalid(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(name, "must be an integer")
    if minimum is not None and value < minimum:
        _invalid(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _invalid(name, "must be at most %s" % maximum)
    return value


def v_number(body, name, required=True, minimum=None, maximum=None, default=None,
             exclusive_minimum=None, nullable=False):
    if name not in body or body[name] is None:
        if required and not nullable:
            _invalid(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(name, "must be a number")
    if minimum is not None and value < minimum:
        _invalid(name, "must be at least %s" % minimum)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _invalid(name, "must be greater than %s" % exclusive_minimum)
    if maximum is not None and value > maximum:
        _invalid(name, "must be at most %s" % maximum)
    return value


def v_bool(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            _invalid(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, bool):
        _invalid(name, "must be a boolean")
    return value


def v_date(body, name, required=True, default=None, nullable=False):
    if name not in body or body[name] is None:
        if required and not nullable:
            _invalid(name, "is required")
        return default
    value = body[name]
    parsed = parse_date(value)
    if parsed is None:
        _invalid(name, "must be a calendar date formatted YYYY-MM-DD")
    return parsed


def v_instant(body, name, required=True, default=None, nullable=False):
    if name not in body or body[name] is None:
        if required and not nullable:
            _invalid(name, "is required")
        return default
    parsed = parse_instant(body[name])
    if parsed is None:
        _invalid(name, "must be an ISO 8601 UTC instant")
    return parsed


def v_id(body, name, required=True, default=None, nullable=False):
    if name not in body or body[name] is None:
        if required and not nullable:
            _invalid(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        _invalid(name, "must be a non-empty identifier string")
    return value


# ------------------------------------------------------------ pagination ----
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            raise ApiError("ERR_INVALID_REQUEST", "limit may not be smaller than 1")
        if limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit may not be larger than 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_instant(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    parsed = parse_instant(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % name)
    return parsed


def slice_page(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
