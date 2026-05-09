"""Claim review-axis lifecycle: create, submit_review, return_to_match,
approve, reject — including SoD and waiting-period gates (PRD §3.4, §3.5).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    ClaimReviewStatus,
    ClaimPayoutStatus,
    SegmentEligibility,
    RejectionReason,
    create_insurer,
    create_policy,
    create_flight,
    create_ticket,
    create_claim,
    create_claim_payload,
    submit_review,
    submit_review_payload,
    approve_claim,
    approve_claim_payload,
    reject_claim,
    reject_claim_payload,
    return_to_match,
    setup_basic_insurer_with_policy,
    setup_basic_claim_in_matched,
    setup_claim_under_review,
    setup_claim_approved,
    setup_flight_with_delay,
    make_claims_reviewer_headers,
    make_claims_approver_headers,
    fresh_operator_id,
    assert_claim,
    finalize_flight_landed,
    finalize_flight_cancelled,
    advance_clock_to,
)


# ---------------------------------------------------------------------------
# Claim creation
# ---------------------------------------------------------------------------

class TestClaimCreation:
    def test_new_claim_with_attached_ticket_auto_matches(self, api):
        """PRD §3.4: "If every supplied ticket is in ATTACHED or CHANGED and
        is bound to this same policy, the system promotes review_status
        directly to MATCHED".

        Claim: claim on an ATTACHED ticket bound to the same policy →
        review_status=MATCHED, payout_status=NOT_PAYABLE.
        """
        insurer, policy, flight, ticket, claim = setup_basic_claim_in_matched()
        assert_claim(claim)
        assert claim["review_status"] == ClaimReviewStatus.MATCHED.value
        assert claim["payout_status"] == ClaimPayoutStatus.NOT_PAYABLE.value

    def test_claim_creates_one_segment_per_ticket(self, api):
        """PRD §3.4: "On creation, one ClaimSegment is materialised per
        ticket, each carrying the ticket_id and a flight_id pulled from that
        ticket."

        Claim: a claim with one ticket has exactly one segment with the
        right ticket_id and flight_id.
        """
        insurer, policy, flight, ticket, claim = setup_basic_claim_in_matched()
        from test_helpers import get_claim
        full = get_claim(insurer["id"], claim["id"])
        assert "segments" in full
        assert len(full["segments"]) == 1
        seg = full["segments"][0]
        assert seg["ticket_id"] == ticket["id"]
        assert seg["flight_id"] == flight["id"]


# ---------------------------------------------------------------------------
# submit_review preconditions (PRD §3.4)
# ---------------------------------------------------------------------------

class TestSubmitReviewPreconditions:
    def test_submit_review_blocked_while_flight_scheduled(self, api):
        """PRD §3.4: "Submission requires that every segment's flight is
        finalised (i.e., its status is one of LANDED, CANCELLED, DIVERTED,
        or RETURNED — otherwise ERR_FLIGHT_NOT_FINALIZED)".

        Claim: submit_review on a SCHEDULED-flight claim →
        ERR_FLIGHT_NOT_FINALIZED.
        """
        insurer, policy = setup_basic_insurer_with_policy()
        flight = create_flight(
            insurer["id"],
            scheduled_departure_epoch_ms=10_000_000,
            scheduled_arrival_epoch_ms=15_000_000,
        )
        ticket = create_ticket(
            insurer["id"], flight_id=flight["id"],
            passenger_doc_id=policy["policy_holder_doc_id"],
        )
        claim = create_claim(insurer["id"], policy["id"], ticket_ids=[ticket["id"]])
        rid = fresh_operator_id("rev")
        resp = api.submit_review(
            insurer["id"], claim["id"],
            submit_review_payload(assigned_reviewer_id=rid),
            make_claims_reviewer_headers(rid),
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_FINALIZED.value)

    def test_submit_review_blocked_when_waiting_period_unmet(self, api):
        """PRD §3.4: "the ticket's scheduled_departure_epoch_ms is at least
        policy.effective_from_epoch_ms + policy.waiting_period_ms (otherwise
        ERR_WAITING_PERIOD_NOT_MET)".

        Claim: a claim on a ticket whose scheduled_departure is BEFORE
        effective_from + waiting_period yields ERR_WAITING_PERIOD_NOT_MET.
        """
        insurer = create_insurer()
        # Policy with a huge waiting period.
        policy = create_policy(
            insurer["id"],
            effective_from_epoch_ms=0,
            waiting_period_ms=10_000_000_000,  # 10 billion ms — far exceeds 10_000_000
        )
        flight = setup_flight_with_delay(
            insurer["id"],
            scheduled_departure_epoch_ms=10_000_000,
            scheduled_arrival_epoch_ms=15_000_000,
            departure_delay_minutes=200,
        )
        ticket = create_ticket(
            insurer["id"], flight_id=flight["id"],
            passenger_doc_id=policy["policy_holder_doc_id"],
        )
        claim = create_claim(insurer["id"], policy["id"], ticket_ids=[ticket["id"]])
        rid = fresh_operator_id("rev")
        resp = api.submit_review(
            insurer["id"], claim["id"],
            submit_review_payload(assigned_reviewer_id=rid),
            make_claims_reviewer_headers(rid),
        )
        validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_NOT_MET.value)

    def test_submit_review_blocked_when_ticket_refunded(self, api, policy_admin_headers):
        """PRD §3.4: "every referenced ticket has status in ATTACHED or
        CHANGED (otherwise ERR_TICKET_NOT_BOUND; tickets in REFUNDED or
        UNMATCHED block submission)".

        Claim: refunding the underlying ticket then submit_review →
        ERR_TICKET_NOT_BOUND. We refund BEFORE the claim is created so no
        ERR_TICKET_LOCKED_BY_CLAIM gate trips, then create the claim
        directly bound via policy_id.
        """
        insurer, policy = setup_basic_insurer_with_policy()
        flight = setup_flight_with_delay(insurer["id"], departure_delay_minutes=200)
        ticket = create_ticket(
            insurer["id"], flight_id=flight["id"],
            passenger_doc_id=policy["policy_holder_doc_id"],
        )
        # Refund the ticket — no claim references it yet, so the refund
        # succeeds and the ticket lands in REFUNDED. PRD §3.4 says claims
        # whose tickets are REFUNDED are auto-rejected at creation
        # (rejection_reason=MATCHING_FAILED) — that path covers a different
        # claim creation behaviour. To exercise the submit_review-time gate
        # alone, we mint the claim first then drive the ticket to REFUNDED
        # via change-confirm-refund order isn't possible while UNDER_REVIEW.
        # Instead we use direct policy_id binding to a CHANGED ticket and
        # then refund — PRD §3.3: "refunds from CHANGED perform no such
        # cascade" so the claim stays MATCHED, then submit_review must fail
        # ERR_TICKET_NOT_BOUND because ticket.status=REFUNDED.
        # f2 must also be finalised so the ONLY precondition that trips at
        # submit_review time is the ticket-bound check (PRD §3.4 lists three
        # gates: flight finalised, waiting period, ticket bound — we want to
        # isolate the third).
        f2 = setup_flight_with_delay(
            insurer["id"],
            scheduled_departure_epoch_ms=20_000_000,
            scheduled_arrival_epoch_ms=25_000_000,
            departure_delay_minutes=200,
        )
        api.change_ticket(
            insurer["id"], ticket["id"],
            {"flight_id": f2["id"]},
            policy_admin_headers,
        )
        # Create the claim while ticket is CHANGED — should auto-MATCH.
        claim_resp = api.create_claim(
            insurer["id"], policy["id"],
            create_claim_payload(ticket_ids=[ticket["id"]]),
            TEST_USERS["claims_reviewer_headers"],
        )
        claim = validate_success(claim_resp, expected_status=201)
        # Refund — PRD §3.3 says refund-from-CHANGED has no cascade, so the
        # claim's review_status remains MATCHED.
        refund_resp = api.refund_ticket(
            insurer["id"], ticket["id"], policy_admin_headers,
        )
        validate_success(refund_resp)
        # Now submit_review must reject — ticket is REFUNDED.
        rid = fresh_operator_id("rev")
        resp = api.submit_review(
            insurer["id"], claim["id"],
            submit_review_payload(assigned_reviewer_id=rid),
            make_claims_reviewer_headers(rid),
        )
        validate_error(resp, ApiErrorId.ERR_TICKET_NOT_BOUND.value)


# ---------------------------------------------------------------------------
# Review-axis cycle (PRD §3.4)
# ---------------------------------------------------------------------------

class TestReturnToMatchCycle:
    def test_return_to_match_clears_reviewer_id(self, api):
        """PRD §3.4: "Returning the claim to MATCHED is a cyclic transition:
        it is restricted to the user whose X-User-ID equals the recorded
        assigned_reviewer_id, clears the assigned_reviewer_id, and allows
        the reviewer to gather new evidence and resubmit later."

        Claim: return_to_match by the recorded reviewer drops review_status
        back to MATCHED and clears assigned_reviewer_id.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review()
        resp = api.return_to_match(
            insurer["id"], claim_uw["id"], make_claims_reviewer_headers(rid)
        )
        data = validate_success(resp)
        assert data["review_status"] == ClaimReviewStatus.MATCHED.value
        assert data.get("assigned_reviewer_id") in (None, "")

    def test_return_to_match_rejected_for_non_reviewer(self, api):
        """PRD §3.4: "Returning the claim to MATCHED ... is restricted to
        the user whose X-User-ID equals the recorded assigned_reviewer_id".

        Claim: a different X-User-ID attempting return_to_match is rejected.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review()
        other = fresh_operator_id("rev")
        assert other != rid
        resp = api.return_to_match(
            insurer["id"], claim_uw["id"], make_claims_reviewer_headers(other)
        )
        # PRD does not name a specific error_id for this restriction; either
        # SoD or INVALID_STATE/FORBIDDEN_FOR_ROLE could be returned.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_SOD_VIOLATION.value,
            ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


# ---------------------------------------------------------------------------
# Approve preconditions (PRD §3.4)
# ---------------------------------------------------------------------------

class TestApprove:
    def test_approve_under_review_with_eligible_segment_succeeds(self, api):
        """PRD §3.4: "On approval the system pins estimated_payout_cents
        (the sum of eligible-segment gross_segment_payout_cents reduced by
        policy.deductible_cents floored at 0 and capped at
        policy.policy_limit_cents, per §3.6), increases
        policy.reserve_balance_cents by that amount, appends a
        ReserveAdjustment with reason APPROVE_DEBIT and a positive
        delta_cents equal to the pinned amount, automatically flips
        payout_status from NOT_PAYABLE to PAYABLE".

        Claim: approve a UNDER_REVIEW claim with an ELIGIBLE segment →
        review_status=APPROVED, payout_status=PAYABLE,
        estimated_payout_cents>0.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        aid = fresh_operator_id("apr")
        resp = api.approve_claim(
            insurer["id"], claim_uw["id"],
            approve_claim_payload(assigned_approver_id=aid),
            make_claims_approver_headers(aid),
        )
        data = validate_success(resp)
        assert data["review_status"] == ClaimReviewStatus.APPROVED.value
        assert data["payout_status"] == ClaimPayoutStatus.PAYABLE.value
        assert data["estimated_payout_cents"] > 0

    def test_approve_with_reviewer_id_violates_sod(self, api):
        """PRD §3.4: "The approver's X-User-ID must differ from the claim's
        assigned_reviewer_id (otherwise ERR_SOD_VIOLATION)."

        Claim: same X-User-ID for reviewer and approver → ERR_SOD_VIOLATION.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review()
        # Re-use the reviewer's id as approver — should be rejected.
        resp = api.approve_claim(
            insurer["id"], claim_uw["id"],
            approve_claim_payload(assigned_approver_id=rid),
            make_claims_approver_headers(rid),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_approve_excluded_cause_rejected_with_ineligible(self, api):
        """PRD §3.5: "when the parent policy's excluded_delay_causes contains
        the flight's classified_cause, the segment's eligibility is set to
        EXCLUDED_CAUSE."
        PRD §3.5: "A claim whose flight cause is excluded by policy fails
        approval with ERR_CLAIM_NOT_ELIGIBLE (hint EXCLUDED_CAUSE)."

        Claim: flight with WEATHER cause + policy excluding WEATHER → approve
        returns ERR_CLAIM_NOT_ELIGIBLE.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            excluded_delay_causes=["WEATHER"],
            cause="WEATHER",
            departure_delay_minutes=200,
        )
        aid = fresh_operator_id("apr")
        resp = api.approve_claim(
            insurer["id"], claim_uw["id"],
            approve_claim_payload(assigned_approver_id=aid),
            make_claims_approver_headers(aid),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ELIGIBLE.value)

    def test_approve_quota_exhausted(self, api):
        """PRD §3.4: "approving the claim would not cause
        policy.claim_quota_used_cents + estimated_payout_cents to exceed
        policy.claim_quota_total_cents (otherwise ERR_QUOTA_EXHAUSTED)".

        Claim: a policy with claim_quota_total_cents tiny enough that
        estimated_payout exceeds the quota fails with ERR_QUOTA_EXHAUSTED.
        """
        # 200-min DEPARTURE delay → TIER_B → gross 25000; deductible 2500 →
        # estimated 22500. Set quota to 22499 so approval just exceeds it.
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
            claim_quota_total_cents=22499,
        )
        aid = fresh_operator_id("apr")
        resp = api.approve_claim(
            insurer["id"], claim_uw["id"],
            approve_claim_payload(assigned_approver_id=aid),
            make_claims_approver_headers(aid),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTA_EXHAUSTED.value)


# ---------------------------------------------------------------------------
# Reject (PRD §3.4)
# ---------------------------------------------------------------------------

class TestReject:
    def test_reject_under_review_sets_rejection_reason(self, api):
        """PRD §3.4: "A reject from UNDER_REVIEW (issued by a ClaimsReviewer
        or a ClaimsApprover) requires a rejection_reason in the request body
        drawn from EXCLUDED_CAUSE, WAITING_PERIOD, DELAY_BELOW_THRESHOLD, or
        MANUAL_DENY; reserve is unaffected and an AuditLog entry is written."

        Claim: reject with rejection_reason=MANUAL_DENY transitions the
        claim to REJECTED and records the reason.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review()
        rejected = reject_claim(
            insurer["id"], claim_uw["id"],
            rejection_reason=RejectionReason.MANUAL_DENY.value,
            reviewer_id=rid,
        )
        assert rejected["review_status"] == ClaimReviewStatus.REJECTED.value
        assert rejected["rejection_reason"] == RejectionReason.MANUAL_DENY.value

    def test_reject_without_rejection_reason_invalid_request(self, api):
        """PRD §3.4: "A reject from UNDER_REVIEW (issued by a ClaimsReviewer
        or a ClaimsApprover) requires a rejection_reason in the request body
        drawn from EXCLUDED_CAUSE, WAITING_PERIOD, DELAY_BELOW_THRESHOLD, or
        MANUAL_DENY".

        Claim: reject without rejection_reason → ERR_INVALID_REQUEST.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review()
        resp = api.reject_claim(
            insurer["id"], claim_uw["id"],
            {},  # no rejection_reason
            make_claims_reviewer_headers(rid),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
