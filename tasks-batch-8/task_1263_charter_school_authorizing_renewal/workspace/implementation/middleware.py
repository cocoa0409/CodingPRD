"""Auth header extraction, role checking, ownership helpers (PRD §2.1, §2.9).

Validation layer order (§2.9):
  1. identity headers present + role declared   -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2. caller role in endpoint roles list         -> ERR_INSUFFICIENT_PERMISSIONS (403)
  3. path resource existence, left-to-right     -> ERR_NOT_FOUND (404)
  3.5 SchoolOperator ownership                  -> ERR_RESOURCE_OWNERSHIP_MISMATCH (403)
  3.6 OCC version checks                        -> 412s
  4. state preconditions                        -> 409s
  5. SOD / panel integrity                      -> 403s
  6. temporal windows                           -> 422s
  7. constraint / aggregate                     -> 409s
  8. fiscal guards                              -> 409s
"""
from flask import request

import errors
from errors import raise_error


ROLES = {
    "Applicant",
    "AuthorizerStaff",
    "ApplicationReviewer",
    "BoardMember",
    "AppealsOfficer",
    "SchoolOperator",
    "AuthorizerAdmin",
}

ALL_ROLES = sorted(ROLES)


def caller():
    """Validate identity headers (layer 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and role must be a declared role",
        )
    return user_id, role


def require_roles(allowed):
    """Validate identity (layer 1) then role authorization (layer 2)."""
    user_id, role = caller()
    if role not in allowed:
        raise_error(
            errors.ERR_INSUFFICIENT_PERMISSIONS,
            f"Role {role} is not authorized for this endpoint",
        )
    return user_id, role


def check_operator_owns(user_id: str, role: str, owning_school_id):
    """Layer 3.5 — SchoolOperator ownership check (§2.1)."""
    if role == "SchoolOperator" and user_id != owning_school_id:
        raise_error(
            errors.ERR_RESOURCE_OWNERSHIP_MISMATCH,
            "SchoolOperator does not own the target resource's school",
        )


def body():
    """JSON request body as a dict (empty dict when absent/invalid JSON is
    left to field validation which raises ERR_INVALID_REQUEST)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_field(data: dict, name: str):
    value = data.get(name)
    if value is None:
        raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return value


def require_non_empty_string(data: dict, name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or value == "":
        raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def require_int(data: dict, name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


def require_number(data: dict, name: str):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return value
