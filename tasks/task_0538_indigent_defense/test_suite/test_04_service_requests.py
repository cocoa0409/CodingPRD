"""Investigator/expert service requests: authorization ceiling, completion gate,
and the office-budget-restricted approval block."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["assignment_coordinator_headers"]
SUPER = TEST_USERS["supervising_attorney_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


# ===========================================================================
# Corner: service authorized amount capped at the per-type service cap
# ===========================================================================

def test_service_authorized_amount_capped_by_service_cap(api):
    """PRD 3.6: "On approval the server sets the authorized ceiling: it
    multiplies `estimated_hours` by `estimated_rate_cents`, rounds that product
    half up to whole cents, and caps it at the per-type service cap — $2,500
    (250,000 cents) for `INVESTIGATOR`, $5,000 (500,000 cents) for
    `EXPERT_PSYCH`, and $7,500 (750,000 cents) for `EXPERT_FORENSIC` — storing
    the lesser of the two into `authorized_amount_cents`."

    Design: Corner/calculations/service_authorized_amount_capped_by_service_cap
    """
    ctx = fx.setup_assigned_case(case_overrides={"charge_class": "FELONY_A"},
                                 screening_overrides={"household_income_cents": 500_000})
    sr = validate_success(api.create_service_request(
        {"case_id": ctx["case"]["id"], "service_type": "INVESTIGATOR",
         "estimated_hours": 40, "estimated_rate_cents": 8_000}, COORD), 201)
    # gross = 40 * 8000 = 320000; capped at SERVICE_CAP[INVESTIGATOR] = 250000.
    approved = validate_success(api.approve_service_request(sr["id"], SUPER), 200)
    assert approved["authorized_amount_cents"] == 250_000
    assert approved["status"] == "APPROVED"


# ===========================================================================
# Corner: completing a REQUESTED (not APPROVED) service request is invalid
# ===========================================================================

def test_complete_service_request_without_approval_invalid(api):
    """PRD 3.6: "An `AssignmentCoordinator` later marks the request `COMPLETED`,
    which requires it to be `APPROVED` (else `ERR_SERVICE_REQUEST_NOT_APPROVED`);
    completion is what unlocks a service voucher for the work."

    Design: Corner/state_machines/complete_service_request_without_approval_invalid
    """
    ctx = fx.setup_assigned_case(screening_overrides={"household_income_cents": 800_000})
    sr = validate_success(api.create_service_request(
        {"case_id": ctx["case"]["id"], "service_type": "INVESTIGATOR",
         "estimated_hours": 10, "estimated_rate_cents": 8_000}, COORD), 201)
    resp = api.complete_service_request(sr["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_SERVICE_REQUEST_NOT_APPROVED.value)
    still = validate_success(api.get_service_request(sr["id"], CLERK), 200)
    assert still["status"] == "REQUESTED"


# ===========================================================================
# Corner: office RESTRICTED blocks service-request approval
# ===========================================================================

def test_budget_restricted_blocks_service_request_approval(api):
    """PRD 3.6: "Approval is permitted only from `REQUESTED` (a wrong-state
    approval is rejected with `ERR_SERVICE_REQUEST_NOT_APPROVED`), requires the
    parent case to be `ASSIGNED` (else `ERR_CASE_NOT_ASSIGNED`), and is blocked
    while the office is `RESTRICTED` (else `ERR_BUDGET_RESTRICTED`)."
    PRD 2.10: "While an office is `RESTRICTED`, new service-request approvals are
    blocked with `ERR_BUDGET_RESTRICTED`."

    Design: Corner/validations/budget_restricted_blocks_service_request_approval
    """
    ctx = fx.setup_restricted_office_with_assigned_case()
    # The office is RESTRICTED after the 187500 panel voucher approval.
    office = validate_success(api.get_defender_office(ctx["office"]["id"], CLERK), 200)
    assert office["budget_status"] == "RESTRICTED"
    resp = api.approve_service_request(ctx["service_request"]["id"], SUPER)
    validate_error(resp, ApiErrorId.ERR_BUDGET_RESTRICTED.value)
