"""Case dismissal — from MEETING_SCHEDULED, PLAN_PROPOSED, and
IN_REPAYMENT (three-strikes rule).

PRD §3.5 / §3.11.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DISMISSAL_MISSED_THRESHOLD,
    TEST_USERS,
    dismiss_case,
    re_get_case,
    re_get_claim,
    re_get_plan,
    record_payment,
    setup_ch13_in_repayment,
    setup_ch13_plan_confirmed,
    setup_ch13_plan_proposed,
    setup_ch13_with_missed_payments,
    setup_meeting_scheduled_case,
    validate_error,
)


# ===========================================================================
# Dismiss from MEETING_SCHEDULED — PRD §3.5
# ===========================================================================
class TestDismissFromMeetingScheduled:
    """PRD §3.5: 'If the trustee instead chooses to dismiss the case
    while it is still in MEETING_SCHEDULED, the case transitions to
    DISMISSED, the stay lifts, and the dismissal completes without
    further cascades. There is no precondition on this early-dismissal
    branch beyond authorization and the case being in
    MEETING_SCHEDULED.'"""

    def test_dismiss_from_meeting_scheduled(self, api):
        """PRD §3.5: "If the trustee instead chooses to dismiss the
        case while it is still in MEETING_SCHEDULED, the case
        transitions to DISMISSED, the stay lifts, and the dismissal
        completes without further cascades."

        Claim: dismiss from MEETING_SCHEDULED -> status=DISMISSED,
        automatic_stay_active=false.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        result = dismiss_case(case=case)
        assert result["status"] == "DISMISSED"
        assert result["automatic_stay_active"] is False


# ===========================================================================
# Dismiss from PLAN_PROPOSED — PRD §3.11
# ===========================================================================
class TestDismissFromPlanProposed:
    """PRD §3.11: 'A PLAN_PROPOSED case may likewise be dismissed by
    the trustee with no further precondition; the case moves to
    DISMISSED and the stay lifts.'"""

    def test_dismiss_from_plan_proposed(self, api):
        """PRD §3.11: "A PLAN_PROPOSED case may likewise be dismissed
        by the trustee with no further precondition; the case moves
        to DISMISSED and the stay lifts."

        Claim: dismiss from PLAN_PROPOSED -> DISMISSED;
        automatic_stay_active=false.
        """
        debtor, case, _mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert case["status"] == "PLAN_PROPOSED"
        result = dismiss_case(case=case)
        assert result["status"] == "DISMISSED"
        assert result["automatic_stay_active"] is False


# ===========================================================================
# Dismiss from PLAN_CONFIRMED (not IN_REPAYMENT) — state wins over
# business_constraint per PRD §2.6 priority.
# ===========================================================================
class TestDismissFromPlanConfirmedWrongState:
    """PRD §2.6: 'When a single request would surface multiple
    validation failures, the server evaluates checks in a fixed
    precedence order and returns the first failure encountered. ...
    State-machine eligibility is checked fourth: a target resource in
    a state from which the requested transition is undefined yields
    ERR_INVALID_STATE.'

    The state-machine declares dismiss transitions from
    MEETING_SCHEDULED, PLAN_PROPOSED, and IN_REPAYMENT — but NOT from
    PLAN_CONFIRMED. PRD §3.11 fires ERR_DISMISSAL_NOT_WARRANTED only
    'from IN_REPAYMENT' branch."""

    def test_dismiss_from_plan_confirmed_yields_invalid_state(self, api):
        """PRD §2.6: "State-machine eligibility is checked fourth: a
        target resource in a state from which the requested
        transition is undefined yields ERR_INVALID_STATE."

        Claim: dismiss against a Ch13 case in PLAN_CONFIRMED (no
        APPLIED payments yet, so still PLAN_CONFIRMED not
        IN_REPAYMENT) -> ERR_INVALID_STATE (priority 4 wins over the
        priority-15 business_constraint that would also have failed).
        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_at_dismiss
        """
        debtor, case, _mtr, _plan, _cr, _cl = setup_ch13_plan_confirmed(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert case["status"] == "PLAN_CONFIRMED"
        # PRD §2.6 fixes the precedence such that state (priority 4)
        # wins over business_constraint (priority 15) — see the
        # docstring above which quotes "Only after these five gates
        # pass does the server evaluate the remaining
        # business-referential, business-temporal, business-fiscal,
        # and business-constraint rules in the order spelled out
        # across §3."
        resp = api.dismiss_case(
            case["id"], None, TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Three-strikes dismissal from IN_REPAYMENT — PRD §3.11 (BOUNDARY)
# ===========================================================================
class TestThreeStrikesDismissal:
    """PRD §3.11: 'When a Chapter 13 plan goes into prolonged default,
    the trustee may dismiss the case from IN_REPAYMENT. The single
    precondition is that missed_payment_count must be at least 3 —
    this is the strict three-strikes boundary, and a count of 1 or 2
    missed payments is not enough to dismiss
    (ERR_DISMISSAL_NOT_WARRANTED).'"""

    def test_dismiss_with_two_misses_rejected(self, api):
        """PRD §3.11: "The single precondition is that
        missed_payment_count must be at least 3 — this is the strict
        three-strikes boundary, and a count of 1 or 2 missed payments
        is not enough to dismiss (ERR_DISMISSAL_NOT_WARRANTED)."

        Claim: at missed_payment_count=2 dismissal ->
        ERR_DISMISSAL_NOT_WARRANTED.
        # difficulty: boundary_precision_check/dismissal_three_strikes_strict_greater_or_equal
        """
        debtor, case, _mtr, plan = setup_ch13_with_missed_payments(
            monthly_payment_cents=10_000, plan_months=36,
            missed_count=2,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert plan["missed_payment_count"] == 2
        resp = api.dismiss_case(
            case["id"], None, TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DISMISSAL_NOT_WARRANTED.value)

    def test_dismiss_with_three_misses_succeeds(self, api):
        """PRD §3.11: "missed_payment_count must be at least 3 —
        this is the strict three-strikes boundary".

        Claim: at missed_payment_count=3 (inclusive boundary)
        dismissal succeeds -> Case.status=DISMISSED.
        # difficulty: boundary_precision_check/dismissal_three_strikes_strict_greater_or_equal
        """
        debtor, case, _mtr, plan = setup_ch13_with_missed_payments(
            monthly_payment_cents=10_000, plan_months=36,
            missed_count=3,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert plan["missed_payment_count"] == 3
        result = dismiss_case(case=case)
        assert result["status"] == "DISMISSED"

    def test_dismiss_from_in_repayment_lifts_stay_and_defaults_plan(self, api):
        """PRD §3.11: "When the dismissal commits, the plan's status
        flips to DEFAULTED, automatic_stay_active flips to false, and
        every claim still in ALLOWED is transitioned to
        NON_DISCHARGEABLE_REMAINS."

        Claim: post-dismissal Plan.status=DEFAULTED,
        case.automatic_stay_active=false.
        """
        debtor, case, _mtr, plan = setup_ch13_with_missed_payments(
            monthly_payment_cents=10_000, plan_months=36,
            missed_count=3,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        dismiss_case(case=case)
        plan_after = re_get_plan(case["id"], plan["id"])
        case_after = re_get_case(case["id"])
        assert plan_after["status"] == "DEFAULTED"
        assert case_after["automatic_stay_active"] is False

    def test_dismissal_preserves_allowed_claim_amount_total(self, api):
        """PRD §3.11: "Crucially, dismissal does not discharge
        anything; the allowed-claim aggregate amount remains
        unchanged across the dismissal action — the partition merely
        renames ALLOWED claims as NON_DISCHARGEABLE_REMAINS while
        preserving total amount_cents."

        Claim: pre-dismissal sum of ALLOWED amount_cents equals
        post-dismissal sum of NON_DISCHARGEABLE_REMAINS amount_cents.
        """
        # Build IN_REPAYMENT case with one ALLOWED claim. Then put
        # plan in default by missing 3 payments and dismiss.
        from test_helpers import (
            setup_ch13_in_repayment, create_creditor, file_claim,
        )
        # Use the meeting_held path that pre-files a claim so it's
        # ALLOWED after conduct.
        debtor, case, mtr, plan_first, _cr, claims_in = setup_ch13_in_repayment(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
            claims=[{"amount_cents": 500_000,
                     "is_dischargeable": True,
                     "claim_class": "GENERAL_UNSECURED"}],
        )
        # Record three MISSED.
        for seq in (2, 3, 4):
            record_payment(
                case=case, plan=plan_first, debtor=debtor,
                sequence_number=seq, amount_cents=0, status="MISSED",
            )
        plan_now = re_get_plan(case["id"], plan_first["id"])
        assert plan_now["missed_payment_count"] == 3
        # The single claim is ALLOWED at this point (it was filed in
        # MEETING_SCHEDULED and cascaded to ALLOWED on conduct_341).
        assert claims_in[0]["status"] == "ALLOWED"
        pre_total = claims_in[0]["amount_cents"]
        dismiss_case(case=case)
        post_claim = re_get_claim(case["id"], claims_in[0]["id"])
        # Per PRD §3.11 partition rule, formerly-ALLOWED claim becomes
        # NON_DISCHARGEABLE_REMAINS.
        assert post_claim["status"] == "NON_DISCHARGEABLE_REMAINS"
        assert post_claim["amount_cents"] == pre_total
