"""Authentication context, role authorization, and identifier existence: the
first three steps of the validation pipeline (PRD §2.1, §2.10, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_draft_assignment,
    create_employee,
    create_engagement,
    create_policy,
    create_program,
    create_program_payload,
    create_record_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
MOBILITY_APPROVER = TEST_USERS["mobility_approver_headers"]
VENDOR = TEST_USERS["tax_vendor_headers"]


def test_request_missing_auth_headers_returns_400(api, admin_headers):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which they act. A
    request missing either header, or carrying an empty value for either, is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/request_missing_auth_headers_returns_400
    """
    program = create_program()

    # The resource exists and reads are open to every authenticated role, yet the
    # missing auth context fails first.
    res = api.get_program(program["id"], headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    # Only one of the two headers present is equally a failure.
    res = api.get_program(program["id"], headers={"X-User-ID": "adm-1"})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_wrong_role_denied_on_exclusive_endpoints(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for the
    endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §2.10: "2. **Authorization.** The role must be listed for the endpoint; for
    `Assignee`-only operations the caller must additionally own the target assignment,
    else `ERR_FORBIDDEN_FOR_ROLE` (403)."

    Design: Corner/validations/wrong_role_denied_on_exclusive_endpoints
    """
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    assignment = create_draft_assignment(program["id"], employee["id"], policy["id"])
    engagement = create_engagement(assignment["id"], tax_year=2026)

    # PayrollSpecialist may not perform the business-unit approval step.
    res = api.approve_bu(assignment["id"], PAYROLL)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    # MobilityApprover may not create programs (MobilityAdmin only).
    res = api.create_program(
        create_program_payload(name="Sneaky", home_country_code="US"),
        MOBILITY_APPROVER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    # TaxVendor may not send the data package (VendorCoordinator only).
    res = api.send_data(engagement["id"], VENDOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_record_create_with_unknown_assignment_fk_returns_not_found(api, payroll_headers):
    """PRD §2.10: "3. **Existence.** Every path identifier must resolve to an existing
    resource, validated left to right; body foreign-key fields (`program_id`,
    `employee_id`, `policy_id`, `assignment_id`) must reference existing rows, else
    `ERR_NOT_FOUND` (404)."

    Design: Corner/validations/record_create_with_unknown_assignment_fk_returns_not_found
    """
    create_program()
    res = api.create_record(
        create_record_payload(
            "11111111-2222-3333-4444-555555555555", tax_year=2026, period_month=9,
            total_gross_cents=900000, per_diem_days=0, housing_receipts_cents=0),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)
