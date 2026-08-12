"""Authentication, authorization (RBAC), and contractor ownership checks.

Pipeline stages 1-3:
  1. X-User-ID and X-User-Role present; role is one of the declared roles
     -> ERR_AUTH_REQUIRED (401)
  2. Role permitted for the endpoint -> ERR_FORBIDDEN_ROLE (403)
  3. Contractor callers: X-User-ID is the ContractorAccount.id that owns the
     addressed resource (directly or via the contractor_account_id chain
     through JobAccount / Order / RebateStatement / ColorMatchRequest)
     -> ERR_NOT_RESOURCE_OWNER (403)
"""
from flask import request

import db
from errors import raise_err, ERR_AUTH_REQUIRED, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER

ROLES = {"CorporateAdmin", "StoreManager", "StoreAssociate", "SpecWriter", "Contractor"}

# Roles that are opaque (X-User-ID is an operator id, never compared to resources).
CONTRACTOR = "Contractor"


def require_roles(allowed):
    """Authenticate and authorize. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_AUTH_REQUIRED,
                  "X-User-ID and X-User-Role headers are required and the role must be known")
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, "role %s is not permitted for this endpoint" % role)
    return uid, role


def owner_or_forbid(uid, role, account_id):
    """For a Contractor caller, X-User-ID must equal the owning account id."""
    if role == CONTRACTOR and uid != account_id:
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "contractor caller does not own the addressed resource")


def owner_of_order(uid, role, order):
    owner_or_forbid(uid, role, order["contractor_account_id"])


def owner_of_job(uid, role, job):
    owner_or_forbid(uid, role, job["contractor_account_id"])


def owner_of_order_line(uid, role, line):
    order = db.orders.get(line["order_id"])
    if order is not None:
        owner_or_forbid(uid, role, order["contractor_account_id"])


def owner_of_return_record(uid, role, rr):
    line = db.order_lines.get(rr["order_line_id"])
    if line is not None:
        owner_of_order_line(uid, role, line)


def owner_of_delivery(uid, role, delivery):
    order = db.orders.get(delivery["order_id"])
    if order is not None:
        owner_or_forbid(uid, role, order["contractor_account_id"])


def owner_of_match(uid, role, match):
    owner_or_forbid(uid, role, match["contractor_account_id"])


def owner_of_statement(uid, role, stmt):
    owner_or_forbid(uid, role, stmt["contractor_account_id"])


def scoped_account_filter(uid, role, requested):
    """For list endpoints carrying a contractor_account_id filter.

    Contractor callers are scoped to their own account; an explicit filter
    naming a different account is rejected with ERR_NOT_RESOURCE_OWNER.
    Returns the account id to filter by, or None for no scoping."""
    if role != CONTRACTOR:
        return requested
    if requested is not None and requested != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "contractor caller may only list its own resources")
    return uid
