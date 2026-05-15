"""Authentication and RBAC middleware.

Per PRD §2.1: every request must carry X-User-ID and X-User-Role.
Per §1.4 validations table the priority order is auth (1) → role (2) → existence (3) → state (4) → ...
"""

from flask import request, g

from config import HEADER_USER_ID, HEADER_USER_ROLE, VALID_ROLES
from errors import (
    AppError,
    ERR_AUTH_REQUIRED,
    ERR_FORBIDDEN,
)


def authenticate():
    """Validate auth headers and stash identity in flask.g.

    Missing/empty headers → ERR_AUTH_REQUIRED (401).
    Unknown role → ERR_AUTH_REQUIRED (treated as missing; auth precedes role check).
    """
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role:
        raise AppError(ERR_AUTH_REQUIRED, "Missing authentication headers.", 401)
    if role not in VALID_ROLES:
        # An unrecognized role value: treat as forbidden (auth headers were present
        # but the role doesn't map to any endpoint's permitted list).
        raise AppError(ERR_FORBIDDEN, f"Role '{role}' is not recognized.", 403)
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    """Raise ERR_FORBIDDEN unless g.role is in allowed."""
    if g.role not in allowed:
        raise AppError(
            ERR_FORBIDDEN,
            f"Role '{g.role}' is not authorized for this endpoint.",
            403,
        )


def require_exhibitor_ownership(resource, exhibitor_field="exhibitor_id"):
    """Exhibitor-role caller must own the resource (X-User-ID == resource.exhibitor_id)."""
    if g.role == "Exhibitor":
        if resource.get(exhibitor_field) != g.user_id:
            raise AppError(
                ERR_FORBIDDEN,
                "Exhibitor does not own this resource.",
                403,
            )
