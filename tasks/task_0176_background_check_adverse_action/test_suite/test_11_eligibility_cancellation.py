"""eligibility_posture recompute + order cancellation — PRD §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_business_days_and_sweep,
    create_order_payload,
    criminal_raw_finding,
    education_raw_finding,
    get_candidate,
    get_order,
    make_candidate_headers,
    record_consent_as_recruiter,
    setup_candidate_with_consent,
    setup_order_in_awaiting_adjudication,
    setup_order_in_intake,
    setup_order_in_verification,
    setup_order_terminated_adverse,
    start_verification,
    upsert_jurisdiction_policy,
    validate_error,
    validate_success,
)


# ===========================================================================
# eligibility_posture recompute — PRD §3.9
# ===========================================================================
class TestEligibilityPostureRecompute:
    """PRD §3.9: "The rule is purely aggregate: if any order remains in
    a non-terminal status — anything other than `COMPLETED_CLEAR`,
    `TERMINATED_ADVERSE`, or `CANCELLED` — the posture is
    `UNDER_REVIEW`. Otherwise, if any `TERMINATED_ADVERSE` order exists
    where the elapsed time since `final_adverse_action_at` is at most
    365 days, the posture is `LOCKED`; that lock window expires the
    day after the 365th day. Otherwise, if any historical
    `TERMINATED_ADVERSE` order exists at all, the posture is
    `ADVERSE`. Otherwise, the posture is `ELIGIBLE`."
    """

    def test_initial_posture_is_eligible(self, api, recruiter_headers):
        """PRD §3.1: "On a successful registration the candidate's
        initial `eligibility_posture` is `ELIGIBLE`".

        Claim: a freshly-created candidate's eligibility_posture
        is ELIGIBLE.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        assert cand["eligibility_posture"] == "ELIGIBLE"

    def test_open_order_moves_posture_to_under_review(
        self, api, recruiter_headers,
    ):
        """PRD §3.3: "The candidate's `eligibility_posture` is
        recomputed to `UNDER_REVIEW`".

        Claim: after order creation the candidate's posture is
        UNDER_REVIEW.
        """
        cand, cons, order = setup_order_in_intake(
            residence_jurisdiction="CA",
        )
        cand_after = get_candidate(cand["id"])
        assert cand_after["eligibility_posture"] == "UNDER_REVIEW"

    def test_completed_clear_returns_posture_to_eligible(
        self, api, recruiter_headers,
    ):
        """PRD §3.5: "the candidate's `eligibility_posture` is
        recomputed back to `ELIGIBLE`".

        Claim: after the sole order auto-promotes to COMPLETED_CLEAR,
        the candidate's posture is ELIGIBLE again.
        """
        cand, cons, order, items = setup_order_in_awaiting_adjudication(
            residence_jurisdiction="CA",
            requested_packages=["EDUCATION"],
            findings_by_kind={
                "EDUCATION": education_raw_finding(
                    institution="Test U", claim_verified=True,
                ),
            },
        )
        assert order["status"] == "COMPLETED_CLEAR"
        cand_after = get_candidate(cand["id"])
        assert cand_after["eligibility_posture"] == "ELIGIBLE"

    def test_terminated_adverse_recomputes_posture_to_locked(
        self, api, recruiter_headers,
    ):
        """PRD §3.8: "The candidate's `eligibility_posture` is
        recomputed to `ADVERSE` and then promoted to `LOCKED` if every
        sibling order of the candidate has reached a terminal state."

        Claim: after Final Adverse on the sole order, posture is
        LOCKED.
        """
        cand, cons, order, items, flow = setup_order_terminated_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={
                "criminal_lookback_years": 7,
                "adverse_action_waiting_business_days": 5,
            },
        )
        cand_after = get_candidate(cand["id"])
        assert cand_after["eligibility_posture"] == "LOCKED"


# ===========================================================================
# Cancel — PRD §3.9
# ===========================================================================
class TestOrderCancel:

    def test_cancel_from_intake_is_unconditional(
        self, api, recruiter_headers,
    ):
        """PRD §3.9: "From `INTAKE` the cancel is unconditional."

        Claim: POST /fcra/orders/{id}/cancel on an INTAKE order ->
        200 with order.status==CANCELLED.
        """
        cand, cons, order = setup_order_in_intake(
            residence_jurisdiction="CA",
        )
        assert order["status"] == "INTAKE"
        resp = api.cancel_order(order["id"], recruiter_headers)
        validate_success(resp)
        order_after = get_order(order["id"])
        assert order_after["status"] == "CANCELLED"

    def test_cancel_recomputes_posture_back_to_eligible(
        self, api, recruiter_headers,
    ):
        """PRD §3.9: "the candidate's `eligibility_posture` is
        recomputed (returning to `ELIGIBLE` if no other open orders
        remain)".

        Claim: cancelling the sole order in IN_VERIFICATION returns
        posture to ELIGIBLE.
        """
        # From IN_VERIFICATION the cancel requires either consent
        # REVOKED or no items adjudicated. Items in IN_PROGRESS have
        # not been adjudicated yet, so the cancel is legal.
        cand, cons, order, items = setup_order_in_verification(
            residence_jurisdiction="CA",
        )
        resp = api.cancel_order(order["id"], recruiter_headers)
        validate_success(resp)
        cand_after = get_candidate(cand["id"])
        assert cand_after["eligibility_posture"] == "ELIGIBLE"


# ===========================================================================
# Sibling cascade on Final Adverse — PRD §3.8 — NOT EXERCISED.
#
# PRD §3.8: "The cascade also cancels every non-terminal sibling order
# of the same candidate, moving each from its current non-terminal
# status to `CANCELLED`."
#
# Two-reader analysis: PRD §3.3 says "The candidate's current
# `eligibility_posture` must be `ELIGIBLE` — neither `UNDER_REVIEW`,
# `ADVERSE`, nor `LOCKED`" when opening a new order. A candidate with
# an open non-terminal order has posture `UNDER_REVIEW`, so PRD-
# prescribed endpoints cannot produce a state with two simultaneously
# non-terminal orders on the same candidate. The cascade sentence
# therefore has no PRD-prescribed setup path; a faithful PRD-only
# implementer who never reaches that state cannot fail any test built
# on it. Silence-pattern category: branch-asymmetry. Logged in the
# summary report.
