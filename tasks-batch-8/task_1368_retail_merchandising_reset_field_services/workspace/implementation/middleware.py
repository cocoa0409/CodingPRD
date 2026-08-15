"""Auth header extraction, role checks, and typed body-field validators.

Validation cascade (PRD §2.6 / SCAFFOLD validations):
  1 auth (401) -> 2 RBAC (403) -> 3 existence (404) -> 4 state (409) ->
  5 cross-entity (422) -> 6 temporal (422) -> 7-12 business constraints ->
  13 input sanitization (400) -> 14/15 OCC (412) -> 16 rework authorization.
"""
from datetime import date, datetime, timezone

from flask import request

import errors

DECLARED_ROLES = {"ProjectManager", "FieldRep", "Client", "PayrollAdmin", "BillingClerk"}


def auth():
    """Priority 1: X-User-Role and X-User-ID present; role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not str(uid).strip() or not str(role).strip():
        raise errors.unauthenticated()
    role = str(role).strip()
    if role not in DECLARED_ROLES:
        raise errors.unauthenticated("Unrecognized role")
    return str(uid).strip(), role


def require_role(role, allowed):
    """Priority 2: acting role permitted for this endpoint."""
    if role not in allowed:
        raise errors.unauthorized()


def get_body():
    """JSON body as a dict; missing/malformed/non-object bodies yield {}."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


# ---------- typed field validators (priority 13: ERR_INVALID_REQUEST) ----------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str):
        raise errors.invalid_request(f"{key} is required and must be a string")
    return v


def opt_str(body, key):
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.invalid_request(f"{key} must be a string")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(f"{key} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, key, allowed):
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(f"{key} must be one of {sorted(allowed)}")
    return v


def req_int(body, key, min_val=None):
    v = body.get(key)
    if not is_int(v):
        raise errors.invalid_request(f"{key} is required and must be an integer")
    if min_val is not None and v < min_val:
        raise errors.invalid_request(f"{key} must be >= {min_val}")
    return v


def opt_int(body, key, min_val=None):
    v = body.get(key)
    if v is None:
        return None
    if not is_int(v):
        raise errors.invalid_request(f"{key} must be an integer")
    if min_val is not None and v < min_val:
        raise errors.invalid_request(f"{key} must be >= {min_val}")
    return v


# ---------- datetime / date parsing ----------

def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD); None if invalid."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def req_datetime(body, key):
    v = body.get(key)
    dt = parse_dt(v)
    if dt is None:
        raise errors.invalid_request(f"{key} is required and must be an ISO 8601 datetime")
    return dt


def req_date(body, key):
    v = body.get(key)
    d = parse_date(v)
    if d is None:
        raise errors.invalid_request(f"{key} is required and must be an ISO date")
    return d
