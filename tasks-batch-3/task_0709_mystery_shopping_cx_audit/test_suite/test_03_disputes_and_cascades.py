"""Disputes and their cascades: the rejection-appeal overturn re-validates a shop
and ripples through wave counters; the payout void reverts batched reimbursements;
the dispute negotiation cycle increments round_index; a second live dispute is
rejected.

Covers difficulty rule transitive_cascade and the corner dispute instances.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, fixtures
from test_helpers.test_users import (
    make_shopper_headers,
    make_qa_validator_headers,
    make_finance_officer_headers,
    make_client_manager_headers,
)


def _build_rejected_with_appeal(api):
    """A submitted shop is REJECTED (reliability 100 -> 90); a REJECTION_APPEAL
    dispute is opened UNDER_REVIEW. Returns (client, wave_id, shopper_id, asg_id,
    dispute_id)."""
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-25T00:00:00Z", section_scores_json={"greeting": 88},
        fee_per_completed_shop_cents=15000,
    )
    aid, sid = cat["assignment"]["id"], cat["shopper"]["id"]
    validate_success(api.reject_assignment(aid, make_qa_validator_headers()))
    dispute = validate_success(
        api.open_dispute(aid, {"reason": "REJECTION_APPEAL"}, make_shopper_headers(sid)),
        expected_status=201,
    )
    return cat["client"], cat["wave"]["id"], sid, aid, dispute["id"]


# ---------------------------------------------------------------------------
# transitive_cascade / dispute_overturn_rejection_appeal_cascade_depth3
# ---------------------------------------------------------------------------
def test_rejection_appeal_overturn_revalidates_assignment(api):
    """PRD 3.8: "When the reason is REJECTION_APPEAL, the previously REJECTED
    assignment is re-validated. The platform recomputes the final reimbursement and
    the shopper fee, sets the assignment to VALIDATED, creates a Reimbursement in
    ACCRUED status whose amount_cents is the final reimbursable_cents plus
    shopper_fee_cents, increments the wave's validated_shop_count and recomputes its
    client_billable_cents, and restores the shopper's reliability_score by 10
    (capped at 100), undoing the rejection penalty."

    Design: Difficulty/transitive_cascade/dispute_overturn_rejection_appeal_cascade_depth3
    """
    client, wave_id, sid, aid, dispute_id = _build_rejected_with_appeal(api)
    resolved = validate_success(
        api.resolve_dispute(dispute_id, {"decision": "OVERTURN"}, make_finance_officer_headers())
    )
    assert resolved["status"] == "OVERTURNED", f"dispute expected OVERTURNED, got {resolved['status']}"
    asg = validate_success(api.get_assignment(aid, make_qa_validator_headers()))
    assert asg["status"] == "VALIDATED", (
        f"assignment expected VALIDATED after rejection-appeal overturn, got {asg['status']}"
    )
    shopper = validate_success(api.get_shopper(sid, make_qa_validator_headers()))
    assert shopper["reliability_score"] == 100, (
        f"reliability_score expected 100 (penalty restored), got {shopper['reliability_score']}"
    )


def test_rejection_appeal_overturn_increments_wave_counters(api):
    """PRD 3.8: "...increments the wave's validated_shop_count and recomputes its
    client_billable_cents..."
    PRD 3.6: "...counts the assignments in the wave whose status is VALIDATED,
    stores that count as validated_shop_count, and sets client_billable_cents to
    that count multiplied by the owning client's fee_per_completed_shop_cents (an
    exact integer multiply, no rounding)."

    Design: Difficulty/transitive_cascade/dispute_overturn_rejection_appeal_cascade_depth3
    """
    client, wave_id, sid, aid, dispute_id = _build_rejected_with_appeal(api)
    validate_success(
        api.resolve_dispute(dispute_id, {"decision": "OVERTURN"}, make_finance_officer_headers())
    )
    cm = make_client_manager_headers(client["id"])
    wave = validate_success(api.get_wave(wave_id, cm))
    assert wave["validated_shop_count"] == 1, (
        f"validated_shop_count expected 1, got {wave['validated_shop_count']}"
    )
    assert wave["client_billable_cents"] == 15000, (
        f"client_billable_cents expected 15000 (1 * 15000), got {wave['client_billable_cents']}"
    )


# ---------------------------------------------------------------------------
# transitive_cascade / payout_void_reverts_reimbursements_depth2
# ---------------------------------------------------------------------------
def test_void_open_batch_reverts_member_reimbursements_to_accrued(api):
    """PRD 3.9: "A FinanceOfficer may void an OPEN batch, moving it OPEN -> VOIDED;
    voiding returns each member reimbursement to ACCRUED and clears its
    payout_batch_id."

    Design: Difficulty/transitive_cascade/payout_void_reverts_reimbursements_depth2
    """
    cat = fixtures.setup_batched_reimbursement(due_at="2026-06-25T00:00:00Z")
    batch_id = cat["batch"]["id"]
    voided = validate_success(api.void_payout_batch(batch_id, make_finance_officer_headers()))
    assert voided["status"] == "VOIDED", f"batch expected VOIDED, got {voided['status']}"
    reimb = fixtures.get_assignment_reimbursement(cat["assignment"]["id"])
    assert reimb["status"] == "ACCRUED", (
        f"reimbursement expected ACCRUED after void, got {reimb['status']}"
    )


def test_void_open_batch_clears_payout_batch_id(api):
    """PRD 3.9: "A FinanceOfficer may void an OPEN batch, moving it OPEN -> VOIDED;
    voiding returns each member reimbursement to ACCRUED and clears its
    payout_batch_id."

    Design: Difficulty/transitive_cascade/payout_void_reverts_reimbursements_depth2
    """
    cat = fixtures.setup_batched_reimbursement(due_at="2026-06-25T00:00:00Z")
    validate_success(api.void_payout_batch(cat["batch"]["id"], make_finance_officer_headers()))
    reimb = fixtures.get_assignment_reimbursement(cat["assignment"]["id"])
    assert reimb["payout_batch_id"] is None, (
        f"payout_batch_id expected null after void, got {reimb['payout_batch_id']!r}"
    )


# ---------------------------------------------------------------------------
# state_machines / dispute_counter_respond_cycle_increments_round_index
# ---------------------------------------------------------------------------
def test_dispute_counter_then_respond_increments_round_index(api):
    """PRD 3.8: "The shopper who owns the parent assignment may respond to a
    COUNTERED dispute, which increments round_index by 1 and returns the dispute to
    UNDER_REVIEW, closing the UNDER_REVIEW -> COUNTERED -> UNDER_REVIEW loop."

    Design: Corner/state_machines/dispute_counter_respond_cycle_increments_round_index
    """
    cat = fixtures.setup_validated_assignment(due_at="2026-06-20T00:00:00Z")
    aid, sid = cat["assignment"]["id"], cat["shopper"]["id"]
    dispute = validate_success(
        api.open_dispute(aid, {"reason": "SCORE_CHALLENGE"}, make_shopper_headers(sid)),
        expected_status=201,
    )
    did = dispute["id"]
    countered = validate_success(api.counter_dispute(did, make_qa_validator_headers()))
    assert countered["status"] == "COUNTERED", f"expected COUNTERED, got {countered['status']}"
    responded = validate_success(api.respond_dispute(did, make_shopper_headers(sid)))
    assert responded["status"] == "UNDER_REVIEW", (
        f"expected UNDER_REVIEW after respond, got {responded['status']}"
    )
    assert responded["round_index"] == 2, (
        f"round_index expected 2 after respond, got {responded['round_index']}"
    )


# ---------------------------------------------------------------------------
# validations / dispute_already_open_second_dispute_rejected
# ---------------------------------------------------------------------------
def test_second_live_dispute_rejected(api):
    """PRD 3.8: "At most one dispute may be live on an assignment at a time: opening
    a second while one is still non-terminal is rejected with
    ERR_DISPUTE_ALREADY_OPEN."

    Design: Corner/validations/dispute_already_open_second_dispute_rejected
    """
    cat = fixtures.setup_validated_assignment(due_at="2026-06-20T00:00:00Z")
    aid, sid = cat["assignment"]["id"], cat["shopper"]["id"]
    validate_success(
        api.open_dispute(aid, {"reason": "SCORE_CHALLENGE"}, make_shopper_headers(sid)),
        expected_status=201,
    )
    resp = api.open_dispute(aid, {"reason": "REIMBURSE_SHORTFALL"}, make_shopper_headers(sid))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN.value)
