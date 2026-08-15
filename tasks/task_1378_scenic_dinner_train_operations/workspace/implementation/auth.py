"""Auth context extraction and role checks (PRD section 2.1).

Every request carries X-User-ID (opaque operator identifier, never compared to
any resource id) and X-User-Role (one of six declared roles). Missing/invalid
headers -> ERR_UNAUTHENTICATED (401); role not permitted -> ERR_FORBIDDEN (403)."""
from flask import request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

ROLES = (
    "Scheduler",
    "Mechanic",
    "StationAgent",
    "CrewManager",
    "CateringManager",
    "OperationsManager",
)
ALL_ROLES = ROLES


def get_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip():
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID header missing or empty", 401)
    if role is None or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED, "X-User-Role header missing or not recognized", 401
        )
    return uid, role


def require_roles(*roles):
    """Priority 1-2 of the validation pipeline: authentication then authorization."""
    uid, role = get_context()
    if role not in roles:
        raise ApiError(
            ERR_FORBIDDEN, "Role %s is not permitted for this endpoint" % role, 403
        )
    return uid, role


def require_event_role(data, event_role_map, endpoint_roles):
    """Event endpoints split authorization further by event_type (priority 2).
    A recognized event_type enforces that event's roles; an unrecognized one
    falls back to the endpoint's role union (the unknown-event error fires later)."""
    uid, role = get_context()
    event_type = data.get("event_type") if isinstance(data, dict) else None
    allowed = endpoint_roles
    if isinstance(event_type, str) and event_type in event_role_map:
        allowed = event_role_map[event_type]
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN,
            "Role %s is not permitted for this event" % role,
            403,
        )
    return uid, role
