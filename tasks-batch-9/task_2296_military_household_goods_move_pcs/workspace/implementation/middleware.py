"""Acting identity and role-based access control (PRD §2.1)."""

import functools

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_SERVICE_MEMBER = "ServiceMember"
ROLE_MOVE_COUNSELOR = "MoveCounselor"
ROLE_TSP_COORDINATOR = "TspCoordinator"
ROLE_CLAIMS_EXAMINER = "ClaimsExaminer"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    ROLE_SERVICE_MEMBER,
    ROLE_MOVE_COUNSELOR,
    ROLE_TSP_COORDINATOR,
    ROLE_CLAIMS_EXAMINER,
    ROLE_PROGRAM_ADMIN,
)


def endpoint(roles):
    """Decorator enforcing ladder steps 1 and 2 of PRD §2.5."""
    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(USER_ID_HEADER)
            role = request.headers.get(USER_ROLE_HEADER)
            if not user_id or not role or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED", "Acting role may not call this endpoint.")
            g.user_id = user_id
            g.role = role
            g.touched = set()
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return getattr(g, "user_id", None)


def acting_role():
    return getattr(g, "role", None)


def require_ownership(service_member_id):
    """Ladder step 6 — member ownership (PRD §2.1)."""
    if acting_role() != ROLE_SERVICE_MEMBER:
        return
    if service_member_id is None or service_member_id != acting_user_id():
        raise ApiError("ERR_OWNERSHIP_REQUIRED", "Resource does not belong to the acting member.")
