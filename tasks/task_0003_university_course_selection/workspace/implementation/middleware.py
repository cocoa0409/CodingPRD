"""Auth header extraction and role checking."""
from flask import request
from errors import APIError, raise_error, ENROLLMENT_AUTH_MISSING, ENROLLMENT_ROLE_DENIED

VALID_ROLES = {"Student", "Professor", "Registrar"}


def get_caller():
    """Extract and validate caller identity and role from headers.
    Returns (caller_id, caller_role).

    Accepts both naming conventions:
      - X-User-Role / X-User-ID  (generic test harness convention)
      - X-Caller-Role / X-Student-Number|X-Instructor-Id|X-Registrar-Id
    """
    role = (
        request.headers.get("X-User-Role")
        or request.headers.get("X-Caller-Role")
    )
    if not role or role not in VALID_ROLES:
        raise_error(ENROLLMENT_AUTH_MISSING, "Missing or invalid role header")

    # Accept generic X-User-ID or the role-specific identity headers
    caller_id = (
        request.headers.get("X-User-ID")
        or request.headers.get("X-Student-Number")
        or request.headers.get("X-Instructor-Id")
        or request.headers.get("X-Registrar-Id")
    )
    if not caller_id:
        raise_error(ENROLLMENT_AUTH_MISSING, "Missing identity header")

    return caller_id, role


def require_roles(*allowed_roles):
    """Get caller and check role is in allowed_roles. 'Any' means any authenticated caller."""
    caller_id, role = get_caller()
    if "Any" not in allowed_roles and role not in allowed_roles:
        raise_error(ENROLLMENT_ROLE_DENIED, f"Role '{role}' is not authorized for this operation")
    return caller_id, role
