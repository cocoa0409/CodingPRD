"""State-machine behavior: cyclic loops (concept revision, retainer pause/resume),
valid/invalid transitions, idempotency, terminal lockdown, cross-entity bubbles,
branching, and conditional cascades."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    create_active_retainer,
    create_and_activate_project,
    create_project_in_concept,
    create_project_in_delivery,
    create_presented_concept,
    setup_closed_care_cycle,
    setup_project_with_issued_invoice,
    issue_invoice,
)

SO = TEST_USERS["studio_ops_headers"]
DES = TEST_USERS["designer_headers"]
BO = TEST_USERS["billing_ops_headers"]


# --- Cyclic state machines (difficulty: non_linear_state_machine) ---

def test_concept_revision_loop_increments_rounds_to_two(api):
    """PRD §3.4: "the designer answers a revision by presenting again, moving the
    concept from IN_REVISION back to PRESENTED (again only while the project is in
    CONCEPT). This presented–revision loop is the cyclic heart of the concept
    lifecycle."
    PRD §3.4: "When a revision request is accepted, the concept's rounds_used is
    incremented by one, recording the round just taken."

    Design: Difficulty/non_linear_state_machine/concept_cyclic_revision_loop_presented_in_revision_presented
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid, revision_limit=3)
    ch = make_client_headers(cid)

    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))  # round 1
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    data = validate_success(api.request_concept_revision(sid, pid, con["id"], ch))  # round 2

    assert data["status"] == "IN_REVISION"
    assert data["rounds_used"] == 2


def test_concept_returns_to_presented_after_revision(api):
    """PRD §3.4: "the designer answers a revision by presenting again, moving the
    concept from IN_REVISION back to PRESENTED"

    Design: Difficulty/non_linear_state_machine/concept_cyclic_revision_loop_presented_in_revision_presented
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid, revision_limit=3)
    ch = make_client_headers(cid)

    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))
    data = validate_success(api.present_concept(sid, pid, con["id"], DES))
    assert data["status"] == "PRESENTED"
    assert data["rounds_used"] == 1


def test_retainer_pause_then_resume_returns_to_active(api):
    """PRD §3.10: "A StudioOps operator pauses an active retainer, moving it from
    ACTIVE to PAUSED, and resumes it, moving it from PAUSED back to ACTIVE."

    Design: Difficulty/non_linear_state_machine/retainer_cyclic_pause_resume_active_paused_active
    """
    sid, cid, retainer = create_active_retainer(monthly_fee_cents=100000)
    rid = retainer["id"]
    paused = validate_success(api.pause_retainer(sid, rid, SO))
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_retainer(sid, rid, SO))
    assert resumed["status"] == "ACTIVE"


def test_retainer_status_paused_after_pause(api):
    """PRD §3.10: "A StudioOps operator pauses an active retainer, moving it from
    ACTIVE to PAUSED"

    Design: Difficulty/non_linear_state_machine/retainer_cyclic_pause_resume_active_paused_active
    """
    sid, cid, retainer = create_active_retainer(monthly_fee_cents=100000)
    paused = validate_success(api.pause_retainer(sid, retainer["id"], SO))
    assert paused["status"] == "PAUSED"


# --- Invalid / valid transitions, idempotency, terminal lockdown (corner) ---

def test_approve_draft_moodboard_invalid_state(api):
    """PRD §3.3: "approving it moves it from `SUBMITTED` to `APPROVED`," — a DRAFT
    moodboard has no defined transition to APPROVED.
    PRD §3.6: "paying an invoice in any other state is an undefined transition and is rejected with `ERR_INVALID_STATE`." (the same ERR_INVALID_STATE governs all
    undefined transitions per §2.12).

    Design: Corner/state_machines/moodboard_approve_from_draft_invalid_state
    """
    studio, client, project, _ = create_and_activate_project([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    mb = get_success_data(api.create_moodboard(sid, pid, {"title": "MB"}, DES))
    resp = api.approve_moodboard(sid, pid, mb["id"], make_client_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_moodboard_starts_in_draft(api):
    """PRD §3.3: "A Designer creates a moodboard under the project with a title; it
    begins in DRAFT."

    Design: Corner/state_machines/moodboard_initial_state_is_draft
    """
    studio, client, project, _ = create_and_activate_project([10000], deposit_pct=0.30)
    mb = validate_success(
        api.create_moodboard(studio["id"], project["id"], {"title": "MB"}, DES), expected_status=201
    )
    assert mb["status"] == "DRAFT"


def test_completed_project_rejects_further_transition(api):
    """PRD §3.5: "`COMPLETED` and `CANCELLED` are the two terminal project states."
    PRD §2.12: "then the generic "is this transition defined from the current
    state" check (`ERR_INVALID_STATE`)" — a terminal project has no defined cancel
    transition.

    Design: Corner/state_machines/project_terminal_completed_locked_no_further_transition
    """
    # Full happy path through to COMPLETED, deposit_pct 0.0 so deposit gate is 0.
    studio, client, project, _, deliverable = _project_through_completed(api)
    resp = api.cancel_project(studio["id"], project["id"], SO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def _project_through_completed(api):
    """Drive a project all the way to COMPLETED (deposit_pct 0.0). Returns
    (studio, client, project, milestones, deliverable)."""
    from test_helpers import create_project_in_handoff
    studio, client, project, milestones, deliverable = create_project_in_handoff(
        [10000], deposit_pct=0.0, tax_rate=0.0, asset_type="BRAND_GUIDE"
    )
    # one milestone of 10000 still PENDING; complete is blocked by open invoices only
    # if an invoice is ISSUED/OVERDUE. None issued here -> complete directly.
    project = get_success_data(api.complete_project(studio["id"], project["id"], SO))
    assert project["status"] == "COMPLETED"
    return studio, client, project, milestones, deliverable


def test_double_approve_moodboard_rejected(api):
    """PRD §3.3: "The `APPROVED` state is terminal for a moodboard."

    Design: Corner/state_machines/moodboard_double_approve_idempotency_rejected
    """
    studio, client, project, _ = create_and_activate_project([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    ch = make_client_headers(cid)
    mb = get_success_data(api.create_moodboard(sid, pid, {"title": "MB"}, DES))
    get_success_data(api.submit_moodboard(sid, pid, mb["id"], DES))
    get_success_data(api.approve_moodboard(sid, pid, mb["id"], ch))
    resp = api.approve_moodboard(sid, pid, mb["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_moodboard_reject_then_resubmit_returns_to_submitted(api):
    """PRD §3.3: "the same submit action also returns a previously REJECTED
    moodboard to SUBMITTED for another look."

    Design: Corner/state_machines/moodboard_reject_then_resubmit_cyclic_revert
    """
    studio, client, project, _ = create_and_activate_project([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    ch = make_client_headers(cid)
    mb = get_success_data(api.create_moodboard(sid, pid, {"title": "MB"}, DES))
    get_success_data(api.submit_moodboard(sid, pid, mb["id"], DES))
    get_success_data(api.reject_moodboard(sid, pid, mb["id"], ch))
    data = validate_success(api.submit_moodboard(sid, pid, mb["id"], DES))
    assert data["status"] == "SUBMITTED"


def test_pay_invoice_bubbles_milestone_to_paid(api):
    """PRD §3.6: "Paying the invoice bubbles up to its milestone, moving that
    milestone to PAID."

    Design: Corner/state_machines/invoice_pay_bubbles_milestone_to_paid
    """
    studio, client, project, milestone, invoice = setup_project_with_issued_invoice(
        amount_cents=40000, deposit_pct=0.30, tax_rate=0.0, deposit_cents=12000
    )
    sid, pid, mid = studio["id"], project["id"], milestone["id"]
    paid = validate_success(api.pay_invoice(sid, invoice["id"], BO))
    assert paid["status"] == "PAID"
    ms = validate_success(api.get_milestone(sid, pid, mid, SO))
    assert ms["status"] == "PAID"


def test_complete_waives_zero_amount_pending_milestones(api):
    """PRD §3.5: "every milestone still in PENDING whose amount_cents is zero
    transitions to WAIVED, clearing out the no-charge line items so the project
    closes cleanly."

    Design: Corner/state_machines/complete_waives_zero_amount_milestones_conditional_cascade
    """
    from test_helpers import create_project_in_handoff
    # project in HANDOFF (deposit_pct 0.0) with a paid 10000 milestone and a zero
    # PENDING milestone; build manually to control milestone set.
    studio, client, project, milestones = create_project_in_delivery(
        [10000, 0], deposit_pct=0.0, tax_rate=0.0
    )
    sid, pid, cid = studio["id"], project["id"], client["id"]
    mpaid, mzero = milestones
    # accept a required deliverable, pay the non-zero milestone, advance to HANDOFF
    deliverable = get_success_data(
        api.create_deliverable(sid, pid, {"asset_type": "BRAND_GUIDE", "is_required_for_handoff": True}, DES)
    )
    get_success_data(api.deliver_deliverable(sid, pid, deliverable["id"], DES))
    get_success_data(api.accept_deliverable(sid, pid, deliverable["id"], make_client_headers(cid)))
    inv = issue_invoice(sid, mpaid["id"], "2026-04-01T00:00:00Z")
    get_success_data(api.pay_invoice(sid, inv["id"], BO))
    get_success_data(api.advance_project(sid, pid, SO))

    completed = validate_success(api.complete_project(sid, pid, SO))
    assert completed["status"] == "COMPLETED"
    zero = validate_success(api.get_milestone(sid, pid, mzero["id"], SO))
    assert zero["status"] == "WAIVED", "zero-amount PENDING milestone is waived"
    paid = validate_success(api.get_milestone(sid, pid, mpaid["id"], SO))
    assert paid["status"] == "PAID", "paid milestone is unaffected by the waive cascade"


def test_care_cycle_close_before_period_end_rejected(api):
    """PRD §3.10: "A StudioOps operator closes a cycle, moving it from OPEN to
    CLOSED, but only once the logical clock has reached or passed the cycle's
    period_end; closing earlier is rejected with ERR_CYCLE_NOT_ENDED."

    Design: Corner/state_machines/care_cycle_close_before_period_end_rejected
    """
    from test_helpers import setup_open_care_cycle, set_clock
    sid, retainer, cc = setup_open_care_cycle(
        period_start="2026-03-01T00:00:00Z", period_end="2026-04-01T00:00:00Z", hours_used=4,
    )
    set_clock("2026-03-15T00:00:00Z", SO)
    resp = api.close_care_cycle(sid, retainer["id"], cc["id"], SO)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ENDED.value)


def test_care_cycle_bill_closed_to_billed(api):
    """PRD §3.10: "Finally a BillingOps operator bills a closed cycle, moving it
    from CLOSED to BILLED, the terminal cycle state."

    Design: Corner/state_machines/care_cycle_bill_closed_to_billed_valid
    """
    sid, retainer, cc = setup_closed_care_cycle(
        monthly_fee_cents=100000, included_hours=10, hours_used=8,
    )
    billed = validate_success(api.bill_care_cycle(sid, retainer["id"], cc["id"], BO))
    assert billed["status"] == "BILLED"
    assert billed["billed_cents"] == 100000, "monthly fee only; overage 0"


def test_deliverable_request_revision_then_redeliver(api):
    """PRD §3.5: "the same deliver action also moves an asset back from
    REVISION_REQUESTED to DELIVERED after rework."

    Design: Corner/state_machines/deliverable_request_revision_then_redeliver_branch
    """
    studio, client, project, _ = create_project_in_delivery([10000], deposit_pct=0.0, tax_rate=0.0)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    ch = make_client_headers(cid)
    deliverable = get_success_data(
        api.create_deliverable(sid, pid, {"asset_type": "LOGO_PRIMARY", "is_required_for_handoff": True}, DES)
    )
    get_success_data(api.deliver_deliverable(sid, pid, deliverable["id"], DES))
    get_success_data(api.request_deliverable_revision(sid, pid, deliverable["id"], ch))
    data = validate_success(api.deliver_deliverable(sid, pid, deliverable["id"], DES))
    assert data["status"] == "DELIVERED"


def test_change_order_reject_leaves_contract_value_unchanged(api):
    """PRD §3.8: "A change order may instead be rejected by the Client, moving it
    from PROPOSED to REJECTED; rejection carries no precondition and does not touch
    the ledger."

    Design: Corner/state_machines/change_order_reject_branch_no_ledger_change
    """
    from test_helpers import create_and_activate_project, propose_change_order
    studio, client, project, _ = create_and_activate_project(
        [100000], deposit_pct=0.30, service_type="IDENTITY"
    )
    sid, pid, cid = studio["id"], project["id"], client["id"]
    co = propose_change_order(sid, pid, 50000, project["version"], reason="SCOPE_ADD")
    rejected = validate_success(api.reject_change_order(sid, co["id"], make_client_headers(cid)))
    assert rejected["status"] == "REJECTED"
    data = validate_success(api.get_project(sid, pid, SO))
    assert data["contract_value_cents"] == 100000, "rejection does not touch the ledger"
