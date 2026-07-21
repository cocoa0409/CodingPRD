"""Auth header extraction and RBAC (§1.4 p1/p2, §1.7 / PRD §2.1)."""
import errors

VALID_ROLES = {
    "RecoverySpecialist",
    "RecoveryManager",
    "CarrierUser",
    "FinanceOfficer",
    "System",
    "Any",
}


def authenticate(request):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or uid.strip() == "":
        raise errors.missing_headers()
    if not role or role not in VALID_ROLES:
        raise errors.missing_headers()
    return uid, role


def authorize(request, allowed_roles):
    """Authenticate, then enforce endpoint role permission.

    allowed_roles=None means any authenticated principal may proceed (GET/Any).
    """
    uid, role = authenticate(request)
    if allowed_roles is not None and role not in allowed_roles:
        raise errors.forbidden_role()
    return uid, role
