"""Authentication and role/ownership authorization (PRD §2.1)."""
from flask import request

from db import store
from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Anonymous", "Customer", "Coordinator", "Veterinarian", "ComplianceOfficer", "Operator"}


def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role / X-User-ID headers")
    return role, uid


def require(allowed_roles):
    """Layer 1-2 of the validation pipeline: authentication + role permission."""
    role, uid = authenticate()
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN, "Role %s is not permitted for this endpoint" % role)
    if role == "Customer" and uid not in store.customers:
        # Entity-backed identity: a Customer caller must be a registered customer.
        raise_err(ERR_FORBIDDEN, "Customer identity does not match a registered customer")
    return role, uid


def check_customer_ownership(role, uid, owner_customer_id):
    if role == "Customer" and owner_customer_id != uid:
        raise_err(ERR_FORBIDDEN, "Customer may only access its own resources")
