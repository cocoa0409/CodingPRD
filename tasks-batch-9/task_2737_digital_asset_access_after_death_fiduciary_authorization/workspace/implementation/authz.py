"""Authentication, RBAC and tenancy scoping (PRD section 2.1)."""
from db import DB
from errors import ApiError

FIDUCIARY = "Fiduciary"
PLATFORM_COMPLIANCE = "PlatformCompliance"
COURT_REGISTRAR = "CourtRegistrar"
ESTATE_ADMIN = "EstateAdmin"

ROLES = (FIDUCIARY, PLATFORM_COMPLIANCE, COURT_REGISTRAR, ESTATE_ADMIN)
ALL_ROLES = ROLES
READ_ROLES_NO_PLATFORM = (FIDUCIARY, COURT_REGISTRAR, ESTATE_ADMIN)


def authenticate(request):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip() or not role or not str(role).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def require_action_role(role, action, owners):
    if owners.get(action) != role:
        raise ApiError("ERR_ACTION_ROLE_MISMATCH")


def acting_fiduciary(user_id):
    return DB.fiduciaries.get(user_id)


def require_fiduciary_estate(user_id, role, estate_id):
    """A Fiduciary caller may only touch resources under its own estate."""
    if role != FIDUCIARY:
        return None
    fid = DB.fiduciaries.get(user_id)
    if fid is None or fid.get("estate_id") != estate_id:
        raise ApiError("ERR_FIDUCIARY_ESTATE_MISMATCH")
    return fid


def require_named_fiduciary_estate(fiduciary, estate_id):
    if fiduciary is None or fiduciary.get("estate_id") != estate_id:
        raise ApiError("ERR_FIDUCIARY_ESTATE_MISMATCH")
    return fiduciary


def require_platform_scope(user_id, role, platform_id):
    """A PlatformCompliance caller's X-User-ID is the Platform id it speaks for."""
    if role != PLATFORM_COMPLIANCE:
        return
    if user_id != platform_id:
        raise ApiError("ERR_PLATFORM_SCOPE_MISMATCH")
