"""Authentication / authorization / enrollment-ownership (PRD §2.1, §2.10).

Headers: X-User-ID + X-User-Role. Bank roles are opaque operator identities;
Customer* roles are entity-backed by EnrollmentUser records whose user_role
must match the claimed role.
"""
from flask import request

import store
from errors import (
    ERR_CROSS_ENROLLMENT_ACCESS,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_err,
)

ROLES = [
    "BankTreasuryManager",
    "BankOps",
    "CustomerAdmin",
    "CustomerManager",
    "CustomerDecisionMaker",
    "CustomerViewer",
]

ALL_ROLES = list(ROLES)
BANK_ROLES = ["BankTreasuryManager", "BankOps"]

# claimed role -> required EnrollmentUser.user_role
CUSTOMER_ROLE_MAP = {
    "CustomerAdmin": "ADMIN",
    "CustomerManager": "MANAGER",
    "CustomerDecisionMaker": "DECISION_MAKER",
    "CustomerViewer": "VIEWER",
}


def authenticate():
    """Priority 1: headers present and role name recognized.

    Returns (user_id, role, enrollment_user_or_None). The EnrollmentUser
    record may be None for a customer-role caller; that failure surfaces at
    priority 2 as ERR_FORBIDDEN_FOR_ROLE.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if role in CUSTOMER_ROLE_MAP:
        return uid, role, store.users.get(uid)
    return uid, role, None


def authorize(role, user, allowed):
    """Priority 2: role listed for the endpoint; customer claimed role must
    match the persisted EnrollmentUser.user_role."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_FOR_ROLE, "Role %s is not authorized for this endpoint" % role)
    if role in CUSTOMER_ROLE_MAP:
        if user is None or user.get("user_role") != CUSTOMER_ROLE_MAP[role]:
            raise_err(
                ERR_FORBIDDEN_FOR_ROLE,
                "EnrollmentUser.user_role does not match the claimed role",
            )


def check_ownership(user, enrollment_id):
    """Priority 3: customer-role callers may only touch resources whose
    enrollment chain equals their own enrollment_id."""
    if user is not None and user.get("enrollment_id") != enrollment_id:
        raise_err(
            ERR_CROSS_ENROLLMENT_ACCESS,
            "Resource belongs to a different enrollment",
        )


def scope_list(records, user, enrollment_of):
    """Restrict a list result set to the caller's enrollment (customer roles)."""
    if user is None:
        return list(records)
    return [r for r in records if enrollment_of(r) == user["enrollment_id"]]


def check_list_enrollment_param(user):
    """An explicit enrollment_id list filter naming a foreign enrollment is a
    cross-enrollment access for customer-role callers."""
    if user is None:
        return request.args.get("enrollment_id")
    enr = request.args.get("enrollment_id")
    if enr is not None and enr != user["enrollment_id"]:
        raise_err(
            ERR_CROSS_ENROLLMENT_ACCESS,
            "enrollment_id filter names a different enrollment",
        )
    return enr if enr is not None else user["enrollment_id"]
