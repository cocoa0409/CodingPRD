"""Lifetime warranty: claim filing gate and the approve/reject decision branches.

Queue A (difficulty): non_linear_state_machine / warranty_claim_branching_approve.
Queue B (corner): state_machines + validations warranty instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    create_warranty_claim_payload,
    setup_installed_with_claim, setup_install_ready_project, refresh_customer,
)

IC = TEST_USERS["install_coordinator_headers"]


def _decide(api, claim_id, **body):
    return api.decide_warranty_claim(claim_id, body, IC)


def test_warranty_claim_approve_sets_status(api):
    """PRD §3.6: "An approve decision requires a resolution of either REPAIR or
    REPLACE (ERR_VALIDATION), records that resolution together with any
    review_notes, and moves the claim SUBMITTED → APPROVED."

    Design: Difficulty/non_linear_state_machine/warranty_claim_branching_approve
    """
    ctx = setup_installed_with_claim(api, defect_type="CRACK")
    claim = validate_success(
        _decide(api, ctx["claim"]["id"], decision="APPROVE", resolution="REPAIR",
                review_notes="warranted repair"), 200)
    assert claim["status"] == "APPROVED"


def test_warranty_claim_approve_records_resolution(api):
    """PRD §3.6: "An approve decision requires a resolution of either REPAIR or
    REPLACE (ERR_VALIDATION), records that resolution together with any
    review_notes, and moves the claim SUBMITTED → APPROVED."

    Design: Difficulty/non_linear_state_machine/warranty_claim_branching_approve
    """
    ctx = setup_installed_with_claim(api, defect_type="CRACK")
    claim = validate_success(
        _decide(api, ctx["claim"]["id"], decision="APPROVE", resolution="REPAIR",
                review_notes="warranted repair"), 200)
    assert claim["resolution"] == "REPAIR", (
        f"an approve decision must record the supplied resolution, got {claim['resolution']}"
    )


def test_warranty_claim_reject_sets_denied(api):
    """PRD §3.6: "A reject decision moves the claim SUBMITTED → REJECTED, sets its
    resolution to DENIED, and records any review_notes."

    Design: Corner/state_machines/warranty_claim_reject_branch_sets_denied
    """
    ctx = setup_installed_with_claim(api, defect_type="LEAK", description="seam leak")
    claim = validate_success(
        _decide(api, ctx["claim"]["id"], decision="REJECT",
                review_notes="wear and tear, not covered"), 200)
    assert claim["status"] == "REJECTED"
    assert claim["resolution"] == "DENIED"


def test_decide_already_decided_claim_rejected(api):
    """PRD §3.6: "An InstallCoordinator then decides it, which is allowed only from
    SUBMITTED (ERR_CLAIM_INVALID_STATE) and carries a decision."

    Design: Corner/state_machines/decide_claim_twice_returns_invalid_state
    """
    ctx = setup_installed_with_claim(api, defect_type="HARDWARE_FAILURE",
                                     description="faucet handle")
    validate_success(_decide(api, ctx["claim"]["id"], decision="APPROVE", resolution="REPLACE"), 200)
    resp = _decide(api, ctx["claim"]["id"], decision="REJECT")
    validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE.value)


def test_warranty_claim_on_non_installed_project_rejected(api):
    """PRD §3.6: "A claim can be filed only when the project's warranty_status is
    ACTIVE; otherwise it is refused with ERR_WARRANTY_NOT_ACTIVE."

    Design: Corner/validations/warranty_claim_on_non_installed_project_rejected
    """
    ctx = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(ctx["project"]["id"], description="premature claim"),
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_WARRANTY_NOT_ACTIVE.value)
