"""Authentication, RBAC, ownership and pagination gates (PRD 2.1, 2.3, 2.9)."""

from flask import request

import response
from errors import ApiError

PLATFORM_ADMIN = "PlatformAdmin"
COMPLIANCE_OFFICER = "ComplianceOfficer"
STORE_MANAGER = "StoreManager"
SALES_ASSOCIATE = "SalesAssociate"
COLLECTIONS_AGENT = "CollectionsAgent"
SERVICE_TECHNICIAN = "ServiceTechnician"
CUSTOMER = "Customer"

ALL_ROLES = (
    PLATFORM_ADMIN,
    COMPLIANCE_OFFICER,
    STORE_MANAGER,
    SALES_ASSOCIATE,
    COLLECTIONS_AGENT,
    SERVICE_TECHNICIAN,
    CUSTOMER,
)

STAFF_ROLES = (
    PLATFORM_ADMIN,
    COMPLIANCE_OFFICER,
    STORE_MANAGER,
    SALES_ASSOCIATE,
    COLLECTIONS_AGENT,
    SERVICE_TECHNICIAN,
)


def authenticate(allowed_roles):
    """Checks 1, 2 and 3 of the ordered validation sequence."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_FORBIDDEN")
    return user_id, role


def require_owner(role, user_id, customer_id):
    """Check 5: a Customer caller may only address its own records."""
    if role == CUSTOMER and user_id != customer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    return value


def parse_paging():
    """Check 6 for collection reads: limit in 1..100 and a non-negative offset."""
    limit = _int_arg("limit", response.PAGINATION_DEFAULT_LIMIT)
    offset = _int_arg("offset", response.PAGINATION_DEFAULT_OFFSET)
    if limit < response.PAGINATION_MIN_LIMIT or limit > response.PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
