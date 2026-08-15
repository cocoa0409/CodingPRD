"""Auth header extraction, role checking, and BrandCustomerRep scoping."""
from flask import request

from db import STORES
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN_CUSTOMER_SCOPE,
)
from util import ROLES


def require_roles(*roles):
    """Cascade stages 1-2: authentication then role authorization.
    Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-Role header missing or not a declared role")
    if role not in roles:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                       f"Role {role} is not authorized for this endpoint")
    uid = request.headers.get("X-User-ID", "")
    return uid, role


def scope_fail():
    raise ApiError(ERR_FORBIDDEN_CUSTOMER_SCOPE, 403,
                   "BrandCustomerRep may only address its own customer's resources")


def rep_list_scope(uid, role):
    """For in-scope list endpoints: BrandCustomerRep must pass customer_id
    equal to its own id. Returns the customer_id to filter by, or None."""
    if role != "BrandCustomerRep":
        return None
    cid = request.args.get("customer_id")
    if cid != uid:
        scope_fail()
    return cid


def rep_owns_customer(uid, role, customer_id):
    """Stage-3 ownership check for a resolved resource."""
    if role == "BrandCustomerRep" and customer_id != uid:
        scope_fail()


def revision_customer_id(revision):
    formula = STORES["formulas"].get(revision["formula_id"])
    return formula["customer_id"] if formula else None


def run_customer_id(run):
    agreement = STORES["agreements"].get(run["agreement_id"])
    return agreement["customer_id"] if agreement else None
