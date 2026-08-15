"""Auth header extraction, role checks, physician ownership (PRD 2.1, validation
ladder priorities 1-3)."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_NOT_OWN_RESOURCE,
)

ALL_ROLES = {"SystemAdmin", "CompAnalyst", "ComplianceOfficer", "CompCommittee", "Physician"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: headers present, role declared, Physician identity resolves."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers must both be present")
    if role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED, f"undeclared role: {role}")
    if role == "Physician" and user_id not in db["physicians"]:
        raise_error(ERR_UNAUTHENTICATED,
                    "Physician role X-User-ID must be the id of an existing Physician")
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: authentication, then role authorization."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_UNAUTHORIZED_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")
    return caller


def require_own(caller: Caller, owner_physician_id):
    """Priority 3: a Physician-role caller may only touch its own resources."""
    if caller.role == "Physician" and caller.user_id != owner_physician_id:
        raise_error(ERR_NOT_OWN_RESOURCE,
                    "resource belongs to a different physician")
