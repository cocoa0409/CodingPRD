"""Authentication and role-based authorization gates."""
from test_helpers import (
    validate_error, NON_EXISTENT_UUID,
    create_vehicle_payload, create_department, create_issued_invoice,
    make_department_user_headers, anonymous_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
CLERK = TEST_USERS["motor_pool_clerk_headers"]
FIN = TEST_USERS["finance_officer_headers"]


def test_motorpoolclerk_cannot_create_vehicle_returns_unauthorized(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with ERR_UNAUTHORIZED." PRD §3.1:
    "A FleetAdmin registers a vehicle" (POST /vehicles is FleetAdmin-only per §4).

    Design: Corner/rbac/motorpoolclerk_cannot_create_vehicle_returns_unauthorized
    """
    res = api.create_vehicle(create_vehicle_payload(vin="VIN-RB-1"), CLERK)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of these
    five known roles, the request is rejected with ERR_UNAUTHENTICATED. This
    authentication check is the very first gate applied to every endpoint".

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.get_vehicle(NON_EXISTENT_UUID, anonymous_headers())
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_department_user_cannot_dispute_other_department_invoice(api):
    """PRD §2.1: "any attempt to read or act on another department's reservation,
    invoice, or department record — that is, a resource whose department reference
    does not equal the caller's X-User-ID — is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/department_user_cannot_dispute_other_department_invoice
    """
    d1 = create_department(cost_center_code="CC-XA")
    d2 = create_department(cost_center_code="CC-XB")
    invoice = create_issued_invoice(d2["id"])
    res = api.dispute_invoice(invoice["id"], {"disputed_reason": "not ours"},
                              make_department_user_headers(d1["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")
