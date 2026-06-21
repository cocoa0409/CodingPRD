"""Auth header extraction, role checking, common request helpers."""
from datetime import datetime, timezone

from flask import request

from errors import err

VALID_ROLES = {"ProgramManager", "HiringManager", "Supplier", "Finance"}


def get_user_context():
    """Validate and return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE",
                  "Role %s is not permitted for this operation" % role)


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


# --- datetime parsing -------------------------------------------------------

def parse_iso(value, field_name):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field_name)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 datetime" % field_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def date_of(dt):
    """Return the UTC calendar date of a datetime."""
    return dt.date()


def inclusive_days(start_dt, end_dt):
    """Inclusive calendar-day count between two datetimes (both endpoints counted)."""
    return (end_dt.date() - start_dt.date()).days + 1
