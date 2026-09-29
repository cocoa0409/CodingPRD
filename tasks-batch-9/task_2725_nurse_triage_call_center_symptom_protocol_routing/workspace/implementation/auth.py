"""Authentication and role authorisation — validation priorities 1 and 2."""
import functools

from flask import g, request

from errors import ApiError

PLATFORM_ADMIN = "PlatformAdmin"
INTAKE_AGENT = "IntakeAgent"
TRIAGE_NURSE = "TriageNurse"
CHARGE_NURSE = "ChargeNurse"
COMPLIANCE_AUDITOR = "ComplianceAuditor"
PRACTICE_LIAISON = "PracticeLiaison"

ALL_ROLES = (PLATFORM_ADMIN, INTAKE_AGENT, TRIAGE_NURSE, CHARGE_NURSE,
             COMPLIANCE_AUDITOR, PRACTICE_LIAISON)


def authorize(roles):
    """Decorator enforcing priority 1 (headers) then priority 2 (role list)."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or str(user_id).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            if role is None or str(role).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)
        return wrapper
    return decorator


def acting_user():
    return getattr(g, "user_id", None)


def acting_role():
    return getattr(g, "role", None)


def practice_scope_guard(practice_id):
    """Priority 15: a PracticeLiaison may only touch its own practice."""
    if acting_role() == PRACTICE_LIAISON and acting_user() != practice_id:
        raise ApiError("ERR_PRACTICE_SCOPE_VIOLATION")
