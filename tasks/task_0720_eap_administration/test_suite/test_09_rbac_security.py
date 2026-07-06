"""RBAC: authentication, authorization, confidentiality firewall."""
import pytest
from test_helpers import (
    TEST_USERS, build_user_headers,
    validate_success, validate_error, ApiErrorId,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]
EMPLOYER = TEST_USERS["employer_headers"]


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or names a role the
    system does not recognize, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    contract = fx.create_contract(employer_name="AuthCo")
    # No X-User-Role header.
    no_role_headers = {"X-User-ID": "someone"}
    validate_error(api.get_contract(contract["id"], no_role_headers),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_care_coordinator_cannot_create_contract_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/care_coordinator_cannot_create_contract_unauthorized
    """
    payload = {"employer_name": "X", "sessions_per_issue": 2, "annual_session_cap": 10,
               "session_rate_cents": 12000, "annual_reimbursement_budget_cents": 100000}
    validate_error(api.create_contract(payload, COORD), ApiErrorId.ERR_UNAUTHORIZED.value)


def test_employer_cannot_read_case_pii_confidentiality_blocked(api):
    """PRD §2.7: "Specifically, an `Employer` attempting to read an employee, a
    dependent, a case, or a counseling session is rejected with
    `ERR_CONFIDENTIALITY_BLOCKED`. This block is distinct from a generic
    authorization failure: it expresses that the data exists but is confidential,
    not that the role is unknown or the route is forbidden in general."

    Design: Corner/rbac/employer_cannot_read_case_pii_confidentiality_blocked
    """
    contract, plan, employee = fx.setup_contract_plan_employee(
        employee_overrides={"full_name": "Empl Cf", "external_ref": "ECF1"})
    case = fx.create_case(contract["id"], employee["id"])
    resp = api.get_case(case["id"], EMPLOYER)
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}"
