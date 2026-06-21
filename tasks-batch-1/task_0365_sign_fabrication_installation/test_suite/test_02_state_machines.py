"""State-machine transitions: art-proof revision loop, estimate accept/supersede,
the QC fork, invalid transitions, terminal lockdown, and cross-entity bubble-ups.

Queue A (difficulty) instances get two tests each; queue B (corner) instances
get one.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_sign_project_payload, create_art_proof_payload, create_estimate_payload,
    create_project, create_project_with_approved_proof, create_sent_estimate,
    create_fabrication_project, create_installed_project, set_clock,
    get_project_version,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
DES = TEST_USERS["designer_headers"]
CUST = TEST_USERS["customer_headers"]


# ═══ Queue A: non_linear_state_machine / art_proof_reject_revision_cycle ═══════

def test_rejected_proof_superseded_when_new_revision_created(api):
    """PRD §3.1: "When a new revision is created and the project already holds a
    proof sitting in REJECTED, that rejected proof is closed out to SUPERSEDED as
    the new DRAFT revision takes over the loop."

    Design: Difficulty/non_linear_state_machine/art_proof_reject_revision_cycle
    """
    project = create_project(customer_name="Loop Co", site_address="2 Spin St")
    proof1 = get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES))
    api.submit_art_proof(project["id"], proof1["id"], DES)
    api.decide_art_proof(project["id"], proof1["id"],
                         {"decision": "REJECT", "reject_reason": "wrong font"}, CUST)

    proof2 = validate_success(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES), 201)
    assert proof2["status"] == "DRAFT"

    proofs = {p["id"]: p for p in
              validate_success(api.list_art_proofs(project["id"], DES), 200)}
    assert proofs[proof1["id"]]["status"] == "SUPERSEDED"


def test_new_revision_takes_prior_max_plus_one(api):
    """PRD §3.1: "the very first proof of a project is revision 1, and each
    successive proof takes the prior maximum revision number plus one."

    Design: Difficulty/non_linear_state_machine/art_proof_reject_revision_cycle
    """
    project = create_project(customer_name="Loop2 Co", site_address="2 Spin St")
    proof1 = get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES))
    api.submit_art_proof(project["id"], proof1["id"], DES)
    api.decide_art_proof(project["id"], proof1["id"],
                         {"decision": "REJECT", "reject_reason": "wrong font"}, CUST)

    proof2 = validate_success(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES), 201)
    assert proof2["revision_no"] == 2


# ═══ Queue A: non_linear_state_machine / fabrication_work_order_qc_fork_branch ═

def test_qc_decide_fail_loops_back_to_in_production(api):
    """PRD §3.4: "when qc_pass is false, the work order loops back
    QC_HOLD → IN_PRODUCTION for rework, with no project phase change."

    Design: Difficulty/non_linear_state_machine/fabrication_work_order_qc_fork_branch
    """
    project, estimate, survey, wo = create_fabrication_project(
        customer_name="QC Co", site_address="3 Test Ln")
    api.start_work_order(project["id"], wo["id"], SM)
    api.qc_hold_work_order(project["id"], wo["id"], SM)
    res = api.qc_decide_work_order(project["id"], wo["id"], {"qc_pass": False}, SM)
    updated = validate_success(res, 200)
    assert updated["status"] == "IN_PRODUCTION"


def test_qc_decide_fail_leaves_project_phase_in_fabrication(api):
    """PRD §3.4: "when qc_pass is false, the work order loops back
    QC_HOLD → IN_PRODUCTION for rework, with no project phase change."

    Design: Difficulty/non_linear_state_machine/fabrication_work_order_qc_fork_branch
    """
    project, estimate, survey, wo = create_fabrication_project(
        customer_name="QC2 Co", site_address="3 Test Ln")
    api.start_work_order(project["id"], wo["id"], SM)
    api.qc_hold_work_order(project["id"], wo["id"], SM)
    api.qc_decide_work_order(project["id"], wo["id"], {"qc_pass": False}, SM)
    project_after = validate_success(api.get_sign_project(project["id"], SM), 200)
    assert project_after["phase"] == "FABRICATION"


# ═══ Queue B: corner state_machines ══════════════════════════════════════════

def test_submit_already_submitted_proof_invalid_state(api):
    """PRD §3.1: "A Designer submits a DRAFT proof for review, moving it
    DRAFT → SUBMITTED; submission is only valid while the proof is in DRAFT and
    the project is still in DESIGN."
    PRD §3.9: "the target resource must actually be in a state from which the
    transition is defined, yielding ERR_INVALID_STATE when it is not."

    Design: Corner/state_machines/submit_art_proof_from_submitted_returns_invalid_state
    """
    project = create_project(customer_name="St Co", site_address="7 State St")
    proof = get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES))
    api.submit_art_proof(project["id"], proof["id"], DES)
    res = api.submit_art_proof(project["id"], proof["id"], DES)
    validate_error(res, "ERR_INVALID_STATE")


def test_second_proof_approval_when_one_already_approved_rejected(api):
    """PRD §3.1: "A decision of approval drives the proof SUBMITTED → APPROVED,
    but only if no other proof of the project is already APPROVED; an attempt to
    approve a second proof when one is already approved is rejected with
    ERR_PROOF_ALREADY_APPROVED."

    Design: Corner/state_machines/second_proof_approval_when_one_already_approved_rejected
    """
    project = create_project(customer_name="Two Co", site_address="8 Dup St")
    # Both proofs must be SUBMITTED while the project is still in DESIGN
    # (submission "is only valid while the proof is in DRAFT and the project is
    # still in DESIGN" per §3.1), because approving proof_a bubbles the project
    # out of DESIGN. With both already SUBMITTED, approving proof_a leaves
    # proof_b SUBMITTED and eligible for the approval attempt that the
    # already-approved guard must reject.
    proof_a = get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES))
    api.submit_art_proof(project["id"], proof_a["id"], DES)
    proof_b = get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES))
    api.submit_art_proof(project["id"], proof_b["id"], DES)
    api.decide_art_proof(project["id"], proof_a["id"], {"decision": "APPROVE"}, CUST)
    res = api.decide_art_proof(project["id"], proof_b["id"], {"decision": "APPROVE"}, CUST)
    validate_error(res, "ERR_PROOF_ALREADY_APPROVED")


def test_proof_approval_bubbles_project_to_estimating(api):
    """PRD §3.1: "Approving the first proof bubbles the project up from DESIGN to
    ESTIMATING."

    Design: Corner/state_machines/proof_approval_bubbles_project_to_estimating
    """
    project = create_project(customer_name="Bub Co", site_address="9 Up St")
    proof = get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES))
    api.submit_art_proof(project["id"], proof["id"], DES)
    decided = validate_success(api.decide_art_proof(
        project["id"], proof["id"], {"decision": "APPROVE"}, CUST), 200)
    assert decided["status"] == "APPROVED"
    project_after = validate_success(api.get_sign_project(project["id"], SM), 200)
    assert project_after["phase"] == "ESTIMATING"


def test_estimate_accept_supersedes_other_sent_estimate(api):
    """PRD §3.2: "A successful accept drives the estimate SENT → ACCEPTED, and as
    side effects it sets the project's approved_estimate_id to this estimate,
    sets the project's contract_total_cents to this estimate's total_cents,
    supersedes every other SENT or DRAFT estimate of the project to SUPERSEDED,
    bubbles the project up from ESTIMATING to PERMITTING, and increments the
    project's version by one."

    Design: Corner/state_machines/estimate_accept_supersedes_other_sent_estimate
    """
    project, proof, e1 = create_sent_estimate(
        color_count=3, substrate="ALUMINUM",
        customer_name="Sup Co", site_address="10 Win St")
    # Second SENT estimate against the same approved proof.
    e2 = get_success_data(api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="STEEL"), SM))
    e2 = get_success_data(api.send_estimate(project["id"], e2["id"], SM))

    pv = get_project_version(project["id"])
    accepted = validate_success(api.accept_estimate(
        project["id"], e1["id"], {"expected_sign_project_version": pv}, CUST), 200)
    assert accepted["status"] == "ACCEPTED"

    e2_after = validate_success(api.get_estimate_by_id(e2["id"], SM), 200)
    assert e2_after["status"] == "SUPERSEDED"
    project_after = validate_success(api.get_sign_project(project["id"], SM), 200)
    assert project_after["approved_estimate_id"] == e1["id"]
    assert project_after["phase"] == "PERMITTING"


def test_estimate_auto_expires_on_accept_after_valid_until(api):
    """PRD §3.2: "an accept at or after valid_until_iso first expires the estimate
    and is rejected with ERR_ESTIMATE_EXPIRED."

    Design: Corner/state_machines/estimate_auto_expires_on_accept_after_valid_until
    """
    set_clock("2026-05-01T00:00:00Z")
    project, proof, est = create_sent_estimate(
        color_count=3, substrate="ALUMINUM",
        valid_until_iso="2026-06-01T00:00:00Z",
        customer_name="Exp Co", site_address="11 Late St")
    set_clock("2026-06-02T00:00:00Z")
    pv = get_project_version(project["id"])
    res = api.accept_estimate(
        project["id"], est["id"], {"expected_sign_project_version": pv}, CUST)
    validate_error(res, "ERR_ESTIMATE_EXPIRED")


def test_resolve_from_denied_claim_invalid_state(api):
    """PRD §3.7: "a denial drives the claim OPEN → DENIED" and "An APPROVED claim
    is later resolved by a ShopManager, moving it APPROVED → RESOLVED."
    PRD §3.9: "the target resource must actually be in a state from which the
    transition is defined, yielding ERR_INVALID_STATE when it is not."

    Design: Corner/state_machines/terminal_warranty_claim_resolve_from_denied_rejected
    """
    set_clock("2026-06-01T10:00:00Z")
    project, wo, crew, equip, job = create_installed_project(
        placement_height_ft=12, customer_name="Den Co", site_address="12 No St")
    claim = get_success_data(api.create_warranty_claim(
        project["id"],
        {"install_job_id": job["id"], "defect_kind": "COSMETIC",
         "reported_iso": "2026-06-10T10:00:00Z"}, CUST))
    api.decide_warranty_claim(project["id"], claim["id"], {"decision": "DENY"}, SM)
    res = api.resolve_warranty_claim(project["id"], claim["id"], SM)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_project_from_fabrication_rejected(api):
    """PRD §3.7: "From FABRICATION onward a project can no longer be cancelled,
    and the attempt is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_project_from_fabrication_rejected
    """
    project, estimate, survey, wo = create_fabrication_project(
        customer_name="Lock Co", site_address="13 No St")
    assert project["phase"] == "FABRICATION"
    res = api.cancel_sign_project(project["id"], SM)
    validate_error(res, "ERR_INVALID_STATE")
