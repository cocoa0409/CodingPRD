"""Access control: authentication, role authorization, ownership, and pagination
input validation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_corporate_account, create_unit_payload, create_employee_payload,
    make_corporate_admin_headers, make_employee_headers, TEST_USERS,
)

PM = TEST_USERS["property_manager_headers"]


def test_create_unit_without_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two authentication headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming their operational
    capacity. If either header is absent, or if `X-User-Role` is not one of the
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/error_unauthenticated_missing_headers_on_create_unit
    """
    resp = api.create_unit(create_unit_payload(), headers={})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_employee_cannot_create_unit_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/error_employee_cannot_create_unit_returns_unauthorized
    """
    employee_headers = make_employee_headers("11111111-1111-4111-8111-111111111111")
    resp = api.create_unit(create_unit_payload(), employee_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_corporate_admin_cannot_add_employee_to_foreign_account_forbidden(api):
    """PRD §3.1: "Because this is an ownership-scoped write, the
    `corporate_account_id` in the body must match the admin's own `X-User-ID`, or the
    request is refused with `ERR_FORBIDDEN`."

    Design: Corner/rbac/error_corporate_admin_cannot_add_employee_to_foreign_account_forbidden
    """
    account_a = create_corporate_account(api, company_name="Acme", billing_email="ap@acme.test")
    account_b = create_corporate_account(api, company_name="Globex", billing_email="ap@globex.test")
    admin_a = make_corporate_admin_headers(account_a["id"])
    resp = api.create_employee(
        create_employee_payload(account_b["id"], full_name="Mallory", email="m@globex.test"),
        admin_a)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_list_stays_with_zero_limit_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or an `offset`
    below 0, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/error_pagination_invalid_limit_on_list
    """
    resp = api.list_stays(PM, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)
