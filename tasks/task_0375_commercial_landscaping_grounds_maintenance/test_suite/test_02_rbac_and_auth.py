"""Role-based access control and the user-context header guard.

Translates queue B (Corner) instances under section `rbac`.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    create_account_payload, create_site_payload, create_contract_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS, UNKNOWN_ROLE_HEADERS

AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]
QI = TEST_USERS["quality_inspector_headers"]


def test_crewlead_cannot_create_contract(api):
    """PRD §2.1: "When an operation is invoked by a role that the access-control
    matrix does not authorize for it, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "POST | `/v1/contracts` | Create a service contract | AccountManager".

    Design: Corner/rbac/crewlead_cannot_create_contract
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    resp = api.create_contract(create_contract_payload(acct["id"], site["id"]), CL)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_accountmanager_cannot_grade_inspection(api):
    """PRD §2.1: "When an operation is invoked by a role that the access-control
    matrix does not authorize for it, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "POST | `/v1/inspections/{inspectionId}/grade` | Grade a pending
    inspection | QualityInspector".

    Design: Corner/rbac/accountmanager_cannot_grade_inspection
    """
    scenario = fixtures.setup_pending_inspection(actual_labor_minutes=90)
    resp = api.grade_inspection(scenario["inspection"]["id"], {"score": 90}, AM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_unknown_role_header_returns_401(api):
    """PRD §2.1: "If either header is absent, or if the value of `X-User-Role` is
    not one of the recognized roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    resp = api.get_account(acct["id"], UNKNOWN_ROLE_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, expected_status=401)
