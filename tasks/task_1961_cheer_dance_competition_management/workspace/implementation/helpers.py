"""Auth middleware, request-body parsing, and field validators."""
import functools

from flask import g, request

import errors
from store import parse_date, parse_datetime

ALL_ROLES = (
    "EventDirector", "TeamCoach", "Judge", "HeadJudge", "SafetyJudge",
    "MusicCompliance", "EligibilityOfficer", "Spectator",
)


def require_roles(*roles):
    """Priority 1 (authentication) then priority 2 (role membership)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ALL_ROLES:
                raise errors.unauthenticated()
            if role not in roles:
                raise errors.forbidden(
                    f"Role {role} is not authorized for this operation")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def body():
    """Parse the JSON request body into a dict ({} when absent)."""
    if request.data in (None, b""):
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_input("Request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_input("Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Field validators (all raise ERR_INVALID_INPUT / 400 on shape violations)
# ---------------------------------------------------------------------------

def _missing(b, field):
    return field not in b or b[field] is None


def req_str(b, field):
    if _missing(b, field) or not isinstance(b[field], str) or b[field] == "":
        raise errors.invalid_input(f"Field '{field}' is required and must be a string")
    return b[field]


def opt_str(b, field, default=None):
    if _missing(b, field):
        return default
    if not isinstance(b[field], str):
        raise errors.invalid_input(f"Field '{field}' must be a string")
    return b[field]


def req_int(b, field, lo=None, hi=None):
    v = b.get(field)
    if _missing(b, field) or isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_input(f"Field '{field}' is required and must be an integer")
    if lo is not None and v < lo:
        raise errors.invalid_input(f"Field '{field}' must be >= {lo}")
    if hi is not None and v > hi:
        raise errors.invalid_input(f"Field '{field}' must be <= {hi}")
    return v


def opt_int(b, field, default=None, lo=None, hi=None):
    if _missing(b, field):
        return default
    return req_int(b, field, lo=lo, hi=hi)


def req_num(b, field, lo=None, hi=None):
    v = b.get(field)
    if _missing(b, field) or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_input(f"Field '{field}' is required and must be a number")
    if lo is not None and v < lo:
        raise errors.invalid_input(f"Field '{field}' must be >= {lo}")
    if hi is not None and v > hi:
        raise errors.invalid_input(f"Field '{field}' must be <= {hi}")
    return v


def opt_num(b, field, default=None, lo=None, hi=None):
    if _missing(b, field):
        return default
    return req_num(b, field, lo=lo, hi=hi)


def req_enum(b, field, allowed):
    v = b.get(field)
    if _missing(b, field) or not isinstance(v, str) or v not in allowed:
        raise errors.invalid_input(
            f"Field '{field}' is required and must be one of {sorted(allowed)}")
    return v


def req_list(b, field):
    v = b.get(field)
    if _missing(b, field) or not isinstance(v, list):
        raise errors.invalid_input(f"Field '{field}' is required and must be an array")
    return v


def req_date_field(b, field):
    return parse_date(b.get(field), field)


def req_datetime_field(b, field):
    if _missing(b, field):
        raise errors.invalid_input(f"Field '{field}' is required")
    return parse_datetime(b[field], field)


# ---------------------------------------------------------------------------
# Existence / ownership
# ---------------------------------------------------------------------------

def get_or_404(collection, rid, what="Resource"):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found(f"{what} {rid} not found")
    return rec


def own_team(team):
    if g.user_id != team["coach_user_id"]:
        raise errors.forbidden("Acting coach does not own this team")
