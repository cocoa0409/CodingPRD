"""Authentication header extraction and role checking (PRD 2.1, ranks 1-3)."""

from flask import g, request

from errors import ApiError

ROLE_ENGAGEMENT_MANAGER = "EngagementManager"
ROLE_STAFFING_COORDINATOR = "StaffingCoordinator"
ROLE_QC_LEAD = "QCLead"
ROLE_REVIEWER = "Reviewer"
ROLE_CLIENT_COUNSEL = "ClientCounsel"

ALL_ROLES = (
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_STAFFING_COORDINATOR,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_CLIENT_COUNSEL,
)

OPERATOR_ROLES = (
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_STAFFING_COORDINATOR,
    ROLE_QC_LEAD,
)

# The logical-clock control operation requires no headers and performs no role
# check (PRD 2.1 / rank 1-3 carve-out).
UNAUTHENTICATED_PATHS = ("/_clock/set_current_utc",)


def authenticate():
    g.user_id = None
    g.role = None
    if request.path.rstrip("/") in [p.rstrip("/") for p in UNAUTHENTICATED_PATHS]:
        return
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None:
        # Tolerated alias; PRD 2.1 names X-User-Role as the authoritative header.
        role = request.headers.get("X-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS",
                       "Both X-User-ID and X-User-Role headers are required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS",
                       "Both X-User-ID and X-User-Role headers are required.")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "'%s' is not a recognised role." % role)
    g.user_id = str(user_id).strip()
    g.role = role


def require_roles(*roles):
    """Rank 3 - the caller's role must appear in the operation's role list."""
    if g.get("role") not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Role '%s' may not perform this operation." % g.get("role"))


def role():
    return g.get("role")


def user_id():
    return g.get("user_id")


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload
