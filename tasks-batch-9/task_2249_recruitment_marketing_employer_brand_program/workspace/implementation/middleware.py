"""RBAC admission (PRD 2.9 steps 1-3)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "BrandProgramLead",
    "PersonaResearcher",
    "ComplianceReviewer",
    "MediaBuyer",
    "CommunityManager",
    "RecruitingOps",
    "Candidate",
    "Anonymous",
)


def require(*allowed):
    """Guard a route with its authorized-role list."""
    anonymous_ok = "Anonymous" in allowed

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            user_id = user_id.strip() if isinstance(user_id, str) else None
            role = role.strip() if isinstance(role, str) else None

            if anonymous_ok:
                if not role:
                    role = "Anonymous"
                elif role not in ROLES:
                    raise ApiError("ERR_UNAUTHENTICATED", "Unknown X-User-Role.")
            else:
                if not user_id or not role:
                    raise ApiError(
                        "ERR_UNAUTHENTICATED",
                        "X-User-ID and X-User-Role headers are required.",
                    )
                if role not in ROLES:
                    raise ApiError("ERR_UNAUTHENTICATED", "Unknown X-User-Role.")

            if role not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s may not call this endpoint." % role,
                )

            g.role = role
            g.user_id = user_id or None
            return view(*args, **kwargs)

        return wrapper

    return decorator
