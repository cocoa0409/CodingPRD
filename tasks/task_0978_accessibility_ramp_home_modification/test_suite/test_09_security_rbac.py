"""User-context validation, path-existence ordering, and role exclusivity."""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_case, add_funding_source, setup_draft_invoice,
    create_case_payload, create_quote_payload, case_version, get_case,
    set_clock,
)

IC = TEST_USERS["intake_coordinator_headers"]
PM = TEST_USERS["project_manager_headers"]
FC = TEST_USERS["funding_coordinator_headers"]
CL = TEST_USERS["crew_lead_headers"]
CLIENT = TEST_USERS["client_headers"]


def test_request_missing_auth_headers_returns_400(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, naming the role under
    which the operator acts. A request in which either header is missing or
    carries an unrecognized value is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

    Design: Corner/validations/request_missing_auth_headers_returns_400
    """
    res = api.create_case(
        {"client_name": "No Auth", "client_address": "1 Authless Way",
         "client_phone": "555-0401"}, {})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT, expected_status=400)


def test_existence_check_case_before_nested_quote(api):
    """PRD §2.7: "Path parameters are validated strictly left to right: the
    `{caseId}` segment is checked first, then the next nested identifier, then the
    next. The first segment that does not resolve produces the 404 for that
    resource type and evaluation stops."

    Design: Corner/validations/existence_check_case_before_nested_quote
    """
    res = api.get_quote(NON_EXISTENT_UUID, "11111111-1111-1111-1111-111111111111", IC)
    validate_error(res, ApiErrorId.ERR_CASE_NOT_FOUND, expected_status=404)


def test_pm_cannot_approve_funding_source_returns_403(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to perform
    the requested operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)." PRD §4: funding-source approval is authorized for FundingCoordinator
    only, and "Write operations are exclusive to the roles named in §4".

    Design: Corner/rbac/pm_cannot_approve_funding_source_returns_403
    """
    case = create_case(client_name="Role Pm", client_address="67 Role Rd",
                       client_phone="555-0701")
    src = add_funding_source(case["id"], 4000, source_type="CHARITY", program_name="C2")
    res = api.approve_funding_source(
        case["id"], src["id"],
        {"approved_cents": 4000, "expected_case_version": case_version(case["id"])},
        PM)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert after["status"] == "PENDING"


def test_funding_coordinator_cannot_create_quote_returns_403(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to perform
    the requested operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)." PRD §4: quote creation is authorized for ProjectManager only.
    PRD §2.6: "2. **Role permission.** The presented role must be permitted to
    perform the operation on every endpoint; failure is
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/funding_coordinator_cannot_create_quote_returns_403
    """
    case = create_case(client_name="Role Fc", client_address="68 Role Rd",
                       client_phone="555-0702")
    res = api.create_quote(case["id"], create_quote_payload(case["version"]), FC)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    assert get_case(case["id"])["status"] == "INTAKE", "no quote may be created"


def test_crew_lead_cannot_send_invoice_returns_403(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to perform
    the requested operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)." PRD §4: invoice send is authorized for BillingCoordinator only.

    Design: Corner/rbac/crew_lead_cannot_send_invoice_returns_403
    """
    set_clock()
    case, inv = setup_draft_invoice(unit_price_cents=2000)
    res = api.send_invoice(case["id"], inv["id"],
                           {"expected_case_version": case_version(case["id"])}, CL)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    after = validate_success(api.get_invoice(case["id"], inv["id"], IC), 200)
    assert after["status"] == "DRAFT"


def test_client_cannot_create_case_returns_403(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to perform
    the requested operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)." PRD §4: case creation is authorized for IntakeCoordinator only.

    Design: Corner/rbac/client_cannot_create_case_returns_403
    """
    res = api.create_case(
        {"client_name": "Role Client", "client_address": "70 Role Rd",
         "client_phone": "555-0704"}, CLIENT)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
