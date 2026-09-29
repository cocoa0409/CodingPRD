"""Authentication, RBAC and scope checks (PRD 2.1, rules 1/2/6/7)."""

from db import db
from errors import ApiError
from flask import request

ROLES = (
    "Servicer",
    "BranchCounterRep",
    "CreditManager",
    "WarrantyAdmin",
    "PricingAdmin",
    "PlatformAdmin",
)


def authenticate(allowed_roles):
    """Rule 1 then rule 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and a recognized X-User-Role are required")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not perform this operation" % role)
    return user_id, role


def check_account_scope(user_id, role, account_id):
    """Rule 6: a Servicer only ever reaches its own account."""
    if role == "Servicer" and user_id != account_id:
        raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION",
                       "Servicer may only act on its own servicer account")


def check_branch_scope(user_id, role, branch_id):
    """Rule 7: a BranchCounterRep only ever reaches its own branch."""
    if role == "BranchCounterRep" and user_id != branch_id:
        raise ApiError("ERR_BRANCH_SCOPE_VIOLATION",
                       "Branch counter rep may only act on its own branch")


def acting_branch(user_id, role):
    """The Branch a BranchCounterRep's X-User-ID resolves to (or None)."""
    if role != "BranchCounterRep":
        return None
    return db.branches.get(user_id)


def require_acting_branch(user_id, role):
    if role != "BranchCounterRep":
        return None
    branch = db.branches.get(user_id)
    if branch is None:
        raise ApiError("ERR_BRANCH_SCOPE_VIOLATION",
                       "X-User-ID does not resolve to a branch")
    return branch


def check_branch_open(branch):
    """Rule 9."""
    if branch is not None and branch["branch_status"] != "OPEN":
        raise ApiError("ERR_BRANCH_NOT_OPEN",
                       "Branch %s is not OPEN" % branch["id"])
