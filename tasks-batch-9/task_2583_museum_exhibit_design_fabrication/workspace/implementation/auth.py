"""Authentication, authorisation and segregation of duties (PRD §2.1, §2.11 steps 1-3)."""

import functools

from flask import g, request

from errors import ApiError

ROLE_PROJECT_MANAGER = "ProjectManager"
ROLE_CURATOR = "Curator"
ROLE_CONSERVATOR = "Conservator"
ROLE_ACCESSIBILITY = "AccessibilitySpecialist"
ROLE_FABRICATION_LEAD = "FabricationLead"
ROLE_MUSEUM_OPERATIONS = "MuseumOperations"

ALL_ROLES = (
    ROLE_PROJECT_MANAGER,
    ROLE_CURATOR,
    ROLE_CONSERVATOR,
    ROLE_ACCESSIBILITY,
    ROLE_FABRICATION_LEAD,
    ROLE_MUSEUM_OPERATIONS,
)

PANEL_ELIGIBLE_ROLES = (
    ROLE_CURATOR,
    ROLE_CONSERVATOR,
    ROLE_PROJECT_MANAGER,
    ROLE_ACCESSIBILITY,
    ROLE_FABRICATION_LEAD,
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def authenticate():
    """Step 1 of the ladder: the two headers."""
    role = request.headers.get(ROLE_HEADER, None)
    user_id = request.headers.get(USER_HEADER, None)
    if role is None or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role must name one of the six declared roles.")
    if request.method in MUTATING_METHODS:
        if user_id is None or user_id.strip() == "":
            raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required on a mutating request.")
    g.role = role
    g.user_id = user_id
    return role, user_id


def authorize(roles):
    """Step 2: role authorisation, before any path segment is resolved."""
    if roles is None:
        return
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % g.role)


def endpoint(roles=None, authenticated=True):
    """Decorator wiring ladder steps 1 and 2 ahead of the handler body."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            g.touched = set()
            if authenticated:
                authenticate()
                authorize(roles)
            else:
                g.role = request.headers.get(ROLE_HEADER, None)
                g.user_id = request.headers.get(USER_HEADER, None)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def caller_role():
    return g.get("role", None)


def caller_id():
    return g.get("user_id", None)


def check_segregation(other_user_id):
    """Step 3: raw string comparison, no trimming, no normalisation, no case folding."""
    if other_user_id is None:
        return
    if g.get("user_id", None) == other_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
