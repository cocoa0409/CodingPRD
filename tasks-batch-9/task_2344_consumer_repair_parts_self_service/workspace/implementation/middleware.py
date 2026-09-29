"""Identity extraction, RBAC and caller-scope enforcement (PRD 2.1)."""
import functools

from flask import g, request

import db
from errors import ApiError

PROGRAM_ADMIN = "ProgramAdmin"
SAFETY_REVIEWER = "SafetyReviewer"
DOCUMENTATION_ENGINEER = "DocumentationEngineer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
SELF_REPAIR_CUSTOMER = "SelfRepairCustomer"
REPAIR_PROVIDER_TECH = "RepairProviderTech"
FAILURE_ANALYSIS_ENGINEER = "FailureAnalysisEngineer"

ALL_ROLES = [
    PROGRAM_ADMIN,
    SAFETY_REVIEWER,
    DOCUMENTATION_ENGINEER,
    COMPLIANCE_OFFICER,
    SELF_REPAIR_CUSTOMER,
    REPAIR_PROVIDER_TECH,
    FAILURE_ANALYSIS_ENGINEER,
]

BUYER_ROLES = [SELF_REPAIR_CUSTOMER, REPAIR_PROVIDER_TECH]


def read_role():
    value = request.headers.get("X-User-Role")
    if value is None:
        value = request.headers.get("X-Role")
    return value


def read_user_id():
    return request.headers.get("X-User-ID")


def endpoint(roles, require_user_id=True):
    """Guard a view with the band-1 ladder: role known, user id present, role allowed."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role = read_role()
            if not role or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHORIZED")
            g.role = role
            user_id = read_user_id()
            if require_user_id and request.method == "POST":
                if user_id is None or str(user_id).strip() == "":
                    raise ApiError("ERR_MISSING_USER_ID")
            g.user_id = user_id
            if roles is not None and role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# caller scope
# --------------------------------------------------------------------------

def resolve_provider_for_caller():
    """Resolve the acting technician to a provider via TrainingCertification rows."""
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return None
    for cert in db.ordered(db.db.certs.all()):
        if cert.get("technician_user_id") == user_id:
            return cert.get("provider_id")
    return None


def check_order_ownership(order):
    """A SelfRepairCustomer may only act on an order they own."""
    if getattr(g, "role", None) != SELF_REPAIR_CUSTOMER:
        return
    if order.get("customer_user_id") != getattr(g, "user_id", None):
        raise ApiError("ERR_ORDER_NOT_OWNED")


def check_assessment_ownership(assessment):
    if getattr(g, "role", None) != SELF_REPAIR_CUSTOMER:
        return
    if assessment.get("requester_user_id") != getattr(g, "user_id", None):
        raise ApiError("ERR_ORDER_NOT_OWNED")


def check_provider_scope(provider_id):
    """A RepairProviderTech must resolve to a provider, and to *this* provider."""
    if getattr(g, "role", None) != REPAIR_PROVIDER_TECH:
        return
    resolved = resolve_provider_for_caller()
    if resolved is None:
        raise ApiError("ERR_PROVIDER_SCOPE_VIOLATION")
    if provider_id is not None and resolved != provider_id:
        raise ApiError("ERR_PROVIDER_SCOPE_VIOLATION")
