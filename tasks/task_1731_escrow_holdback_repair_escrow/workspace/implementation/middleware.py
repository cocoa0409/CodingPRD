"""Authentication and role authorization (PRD section 2.1)."""

from flask import request

from errors import ApiError

ROLES = {"EscrowOfficer", "Buyer", "Seller", "Lender", "Insurer", "Contractor", "Inspector"}
ALL_ROLES = ["EscrowOfficer", "Buyer", "Seller", "Lender", "Insurer", "Contractor", "Inspector"]


def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role or X-User-ID header missing or invalid")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role %s is not permitted on this endpoint" % role)
