"""Auth middleware (PRD 2.1, pipeline steps 1-3).

Every request carries X-User-ID and X-User-Role. Eight declared roles.
"Any" in an endpoint's role list means any declared role may call it.
"""

from flask import request

from errors import ApiError, ERR_AUTH_HEADER, ERR_FORBIDDEN

DECLARED_ROLES = (
    "PlatformAdmin",
    "ProductionManager",
    "CastingDirector",
    "ContractsOfficer",
    "TechnicalDirector",
    "BoxOfficeManager",
    "PartnerRepresentative",
    "Any",
)


def auth():
    """Pipeline step 1: headers present and role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in DECLARED_ROLES:
        raise ApiError(ERR_AUTH_HEADER, 400,
                       "X-User-ID and X-User-Role headers are required and "
                       "X-User-Role must be a declared role")
    return uid, role


def require_roles(*allowed):
    """Pipeline steps 1-2: auth, then role permission for the endpoint."""
    uid, role = auth()
    if "Any" in allowed:
        return uid, role
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403,
                       f"Role {role} is not permitted for this endpoint")
    return uid, role
