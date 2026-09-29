"""Authentication headers, role gating and ClientUser ownership scoping."""
from functools import wraps

from flask import g, request

from errors import ApiError

PANEL_OPERATIONS_MANAGER = "PanelOperationsManager"
FIELD_TECHNICIAN = "FieldTechnician"
METHODOLOGY_STATISTICIAN = "MethodologyStatistician"
CLIENT_SERVICE_REP = "ClientServiceRep"
CLIENT_USER = "ClientUser"
ACCREDITATION_AUDITOR = "AccreditationAuditor"
GOVERNANCE_DIRECTOR = "GovernanceDirector"

ALL_ROLES = (
    PANEL_OPERATIONS_MANAGER,
    FIELD_TECHNICIAN,
    METHODOLOGY_STATISTICIAN,
    CLIENT_SERVICE_REP,
    CLIENT_USER,
    ACCREDITATION_AUDITOR,
    GOVERNANCE_DIRECTOR,
)

# Respondent-level reads are confidential.
CONFIDENTIAL_READ_ROLES = (
    PANEL_OPERATIONS_MANAGER,
    METHODOLOGY_STATISTICIAN,
    ACCREDITATION_AUDITOR,
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is invalid")
    g.user_id = user_id
    g.role = role
    return user_id, role


def roles(*allowed):
    """Authenticate, then gate on the endpoint's declared role list."""
    allowed_set = tuple(allowed) or ALL_ROLES

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed_set:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "role %s may not perform this operation" % g.role,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.user_id


def actor_role():
    return g.role


def require_client_scope(client_id):
    """A ClientUser may only act on rows belonging to its own client."""
    if g.role == CLIENT_USER and g.user_id != client_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "caller does not own this client resource")
