"""Permits, HOA approval, and the permit_clearance derivation that gates the
project from MEASURED to APPROVED.

Translates Difficulty/non_linear_state_machine (permit revision cycle),
Difficulty/cross_entity_state_dependency (project APPROVED requires clearance),
and Corner/state_machines + Corner/validations permit/HOA instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_accepted_estimate, setup_measured_project,
    FENCE_100_PLAIN,
)

PM = TEST_USERS["project_manager_headers"]
PC = TEST_USERS["permit_clerk_headers"]


# ===========================================================================
# non_linear_state_machine instance 1: permit SUBMITTED->RETURNED->SUBMITTED
# ===========================================================================
def test_permit_resubmit_after_return_clears_reason(api):
    """PRD §3.4: "A decision of RETURN moves the permit from `SUBMITTED` to `RETURNED` and records a `return_reason`, sending the permit back into a revision loop; resubmitting a `RETURNED` permit moves it to `SUBMITTED` again and clears `return_reason` back to null."

    Design: Difficulty/non_linear_state_machine/permit_submitted_returned_resubmitted_cycle
    """
    ctx = setup_measured_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    permit = get_success_data(api.create_permit(
        pid, {"permit_type": "FENCE_PERMIT", "jurisdiction": "City of Elm"}, PC))
    get_success_data(api.submit_permit(pid, permit["id"], PC))
    get_success_data(api.decide_permit(
        pid, permit["id"], {"decision": "RETURN", "return_reason": "Missing site plan"}, PC))
    resp = api.submit_permit(pid, permit["id"], PC)
    permit_after = validate_success(resp, expected_status=200)
    assert permit_after["status"] == "SUBMITTED"
    assert permit_after["return_reason"] is None


def test_permit_return_records_reason_then_loops(api):
    """PRD §3.4: "A decision of RETURN moves the permit from `SUBMITTED` to `RETURNED` and records a `return_reason`, sending the permit back into a revision loop; resubmitting a `RETURNED` permit moves it to `SUBMITTED` again and clears `return_reason` back to null."

    Design: Difficulty/non_linear_state_machine/permit_submitted_returned_resubmitted_cycle
    """
    ctx = setup_measured_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    permit = get_success_data(api.create_permit(
        pid, {"permit_type": "FENCE_PERMIT", "jurisdiction": "City of Elm"}, PC))
    get_success_data(api.submit_permit(pid, permit["id"], PC))
    resp = api.decide_permit(
        pid, permit["id"], {"decision": "RETURN", "return_reason": "Missing site plan"}, PC)
    returned = validate_success(resp, expected_status=200)
    assert returned["status"] == "RETURNED"
    # The revision loop then accepts a resubmit back to SUBMITTED.
    resp2 = api.submit_permit(pid, permit["id"], PC)
    resub = validate_success(resp2, expected_status=200)
    assert resub["status"] == "SUBMITTED"


# ===========================================================================
# cross_entity_state_dependency instance 2: project APPROVED on clearance
# ===========================================================================
def test_issuing_last_permit_clears_and_advances_project_to_approved(api):
    """PRD §3.4: "clearance is `CLEARED` when at least one permit is `ISSUED` and additionally either the customer is not HOA-governed (`hoa_governed` is false) or at least one HOA approval is `APPROVED`."
    PRD §3.4: "The moment clearance becomes `CLEARED` while the project is in `MEASURED`, the system auto-transitions the project from `MEASURED` to `APPROVED`, opening the gate for crew scheduling and material ordering."

    Design: Difficulty/cross_entity_state_dependency/project_approved_requires_permit_clearance_cleared
    """
    ctx = setup_measured_project(line_specs=[FENCE_100_PLAIN], hoa_governed=False, job_type="FENCE")
    pid = ctx["project"]["id"]
    permit = get_success_data(api.create_permit(
        pid, {"permit_type": "FENCE_PERMIT", "jurisdiction": "City of Elm"}, PC))
    get_success_data(api.submit_permit(pid, permit["id"], PC))
    resp = api.decide_permit(pid, permit["id"], {"decision": "ISSUE"}, PC)
    permit_after = validate_success(resp, expected_status=200)
    assert permit_after["status"] == "ISSUED"
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["permit_clearance"] == "CLEARED"
    assert proj["status"] == "APPROVED"


def test_project_stays_measured_with_clearance_pending_before_issue(api):
    """PRD §3.4: "In every other case clearance remains `PENDING`." With a permit
    only SUBMITTED (not yet ISSUED) on a non-HOA project, clearance is PENDING
    and the project has not advanced to APPROVED.
    PRD §3.4: "The moment clearance becomes `CLEARED` while the project is in `MEASURED`, the system auto-transitions the project from `MEASURED` to `APPROVED`, opening the gate for crew scheduling and material ordering."

    Design: Difficulty/cross_entity_state_dependency/project_approved_requires_permit_clearance_cleared
    """
    ctx = setup_measured_project(line_specs=[FENCE_100_PLAIN], hoa_governed=False, job_type="FENCE")
    pid = ctx["project"]["id"]
    permit = get_success_data(api.create_permit(
        pid, {"permit_type": "FENCE_PERMIT", "jurisdiction": "City of Elm"}, PC))
    get_success_data(api.submit_permit(pid, permit["id"], PC))
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["permit_clearance"] == "PENDING"
    assert proj["status"] == "MEASURED"


# ===========================================================================
# Corner/state_machines: permit submit too early
# ===========================================================================
def test_permit_submit_before_measured_returns_permit_too_early(api):
    """PRD §3.4: "Submitting a permit moves it from `DRAFT` to `SUBMITTED`, but only while the project is in `MEASURED` or `APPROVED`; submitting earlier is rejected with `ERR_PERMIT_TOO_EARLY`."

    Design: Corner/state_machines/permit_submit_before_measured_returns_permit_too_early
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]  # project is ESTIMATED, not yet MEASURED
    permit = get_success_data(api.create_permit(
        pid, {"permit_type": "FENCE_PERMIT", "jurisdiction": "City of Elm"}, PC))
    resp = api.submit_permit(pid, permit["id"], PC)
    validate_error(resp, ApiErrorId.ERR_PERMIT_TOO_EARLY.value)


# ===========================================================================
# Corner/state_machines: permit denied blocks clearance
# ===========================================================================
def test_permit_denied_blocks_clearance(api):
    """PRD §3.4: "if any permit is `DENIED` or any HOA approval is `REJECTED`, clearance is `BLOCKED`."
    The project does not advance to APPROVED because clearance is not CLEARED.

    Design: Corner/state_machines/permit_denied_blocks_clearance
    """
    ctx = setup_measured_project(line_specs=[FENCE_100_PLAIN], hoa_governed=False, job_type="FENCE")
    pid = ctx["project"]["id"]
    permit = get_success_data(api.create_permit(
        pid, {"permit_type": "FENCE_PERMIT", "jurisdiction": "City of Elm"}, PC))
    get_success_data(api.submit_permit(pid, permit["id"], PC))
    resp = api.decide_permit(pid, permit["id"], {"decision": "DENY"}, PC)
    permit_after = validate_success(resp, expected_status=200)
    assert permit_after["status"] == "DENIED"
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["permit_clearance"] == "BLOCKED"
    assert proj["status"] == "MEASURED"


# ===========================================================================
# Corner/validations: HOA-required project not cleared until HOA approved
# ===========================================================================
def test_hoa_required_project_cleared_only_after_hoa_approved(api):
    """PRD §3.4: "clearance is `CLEARED` when at least one permit is `ISSUED` and additionally either the customer is not HOA-governed (`hoa_governed` is false) or at least one HOA approval is `APPROVED`."
    For an HOA-governed customer, an ISSUED permit alone is insufficient; only
    once the HOA approval is APPROVED does clearance become CLEARED and the
    project advance to APPROVED.

    Design: Corner/validations/hoa_required_project_not_cleared_until_hoa_approved
    """
    ctx = setup_measured_project(line_specs=[FENCE_100_PLAIN], hoa_governed=True, job_type="FENCE")
    pid = ctx["project"]["id"]
    permit = get_success_data(api.create_permit(
        pid, {"permit_type": "FENCE_PERMIT", "jurisdiction": "City of Elm"}, PC))
    get_success_data(api.submit_permit(pid, permit["id"], PC))
    get_success_data(api.decide_permit(pid, permit["id"], {"decision": "ISSUE"}, PC))
    # Permit issued but HOA still pending -> clearance not yet CLEARED.
    proj_mid = get_success_data(api.get_project(pid, PM))
    assert proj_mid["permit_clearance"] == "PENDING"
    assert proj_mid["status"] == "MEASURED"
    hoa = get_success_data(api.create_hoa_approval(pid, {"architectural_packet_ref": "PKT-1"}, PC))
    get_success_data(api.decide_hoa_approval(pid, hoa["id"], {"decision": "APPROVE"}, PC))
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["permit_clearance"] == "CLEARED"
    assert proj["status"] == "APPROVED"
