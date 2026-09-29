"""Auth header extraction, role authorisation, peer-ownership scope, segregation
of duties, and path/body existence lookups.

Header names and role strings come from PRD section 2.1:
    X-User-ID, X-User-Role
    PlatformAdmin, Customer, PartnerManager, Courier, ComplianceOfficer,
    SecretShopperAuditor
"""
from flask import g, request

from db import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
CUSTOMER = "Customer"
PARTNER_MANAGER = "PartnerManager"
COURIER = "Courier"
COMPLIANCE_OFFICER = "ComplianceOfficer"
SECRET_SHOPPER_AUDITOR = "SecretShopperAuditor"

ALL_ROLES = (
    PLATFORM_ADMIN,
    CUSTOMER,
    PARTNER_MANAGER,
    COURIER,
    COMPLIANCE_OFFICER,
    SECRET_SHOPPER_AUDITOR,
)


def auth(*allowed_roles):
    """Tier 1 then tier 2 of the precedence ladder (PRD 2.7).

    Role authorisation is decided before any resource is loaded.
    """
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def scope_check(expected_owner_id):
    """Tier 3: peer-ownership. `expected_owner_id` is the id the caller must equal."""
    if g.user_id != expected_owner_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE")


def scope_if(role, expected_owner_id):
    if g.user_role == role:
        scope_check(expected_owner_id)


def segregation_of_duties(case):
    """Tier 4: the officer who substantiated a case may not review or verify its plan."""
    substantiated_by = case.get("substantiated_by_user_id")
    if substantiated_by is not None and g.user_id == substantiated_by:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


# ---------------------------------------------------------------------------
# Existence lookups -- one error identifier per entity (PRD 2.6)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "jurisdictions": "ERR_JURISDICTION_NOT_FOUND",
    "policies": "ERR_POLICY_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "order_lines": "ERR_ORDER_LINE_NOT_FOUND",
    "partners": "ERR_PARTNER_NOT_FOUND",
    "couriers": "ERR_COURIER_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "attempts": "ERR_ATTEMPT_NOT_FOUND",
    "shopper_tests": "ERR_SHOPPER_TEST_NOT_FOUND",
    "cases": "ERR_CASE_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
}


def fetch(collection, row_id):
    table = getattr(db, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection])
    return row


def lookup(collection, row_id):
    table = getattr(db, collection)
    return table.get(row_id) if isinstance(row_id, str) else None
