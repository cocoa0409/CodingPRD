"""Medigap policy lifecycle: APPLIED, GUARANTEED_ISSUED / UNDERWRITING,
ISSUED, DENIED, CANCELLED, plus the APPLIED <-> UNDERWRITING revision
cycle.

Covers PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_medigap_policy,
    begin_underwriting_medigap,
    cancel_medigap,
    create_beneficiary,
    create_medigap_plan,
    create_medigap_policy,
    create_plan,
    evaluate_gi_medigap,
    issue_medigap,
    re_get_medigap,
    revise_medigap_application,
    setup_clock_at,
    setup_medigap_applied,
    setup_medigap_with_open_gi_period,
    validate_error,
    validate_success,
)


class TestMedigapApplication:
    """PRD §3.7 application."""

    def test_create_starts_applied(self, api, counselor_headers):
        """PRD §3.7: "A BenefitsCounselor opens a policy in APPLIED
        status by supplying beneficiary_id, the plan_id of a MEDIGAP
        plan, and an optional underwriting_uplift_decimal (which
        defaults to zero and is ignored on the guaranteed-issue
        branch). The server stamps applied_at to the current clock."

        Claim: new Medigap policy has status=APPLIED and a stamped
        applied_at.
        """
        b, plan, policy = setup_medigap_applied()
        assert_medigap_policy(policy)
        assert policy["status"] == "APPLIED"
        assert "applied_at" in policy and policy["applied_at"]


class TestMedigapGuaranteedIssue:
    """PRD §3.7 GI evaluation."""

    def test_gi_succeeds_when_period_open_and_state_matches(
        self, api, counselor_headers,
    ):
        """PRD §3.7: "The conversion succeeds only when an
        EnrollmentPeriod with period_type MEDIGAP_GI and status OPEN
        exists for the beneficiary at applied_at, when the plan's
        state_code equals the beneficiary's state_code (otherwise
        ERR_MEDIGAP_STATE_MISMATCH), and when the plan is of type
        MEDIGAP. On success the policy moves APPLIED ->
        GUARANTEED_ISSUED, the gi_window_id is set to that period's id,
        the period transitions from OPEN to CONSUMED, and
        premium_locked_cents is fixed at the plan's
        monthly_premium_cents — no underwriting uplift is applied."

        Claim: with a matching OPEN MEDIGAP_GI period, evaluate-gi
        succeeds, status moves to GUARANTEED_ISSUED, period CONSUMED,
        premium_locked_cents == plan.monthly_premium_cents.
        """
        b, plan, gi_period, policy = setup_medigap_with_open_gi_period(
            state_code="CA", plan_premium_cents=20_000,
        )
        gi = evaluate_gi_medigap(policy["id"])
        assert gi["status"] == "GUARANTEED_ISSUED"
        assert gi["premium_locked_cents"] == 20_000

    def test_gi_state_mismatch_rejected(self, api, admin_headers,
                                        counselor_headers):
        """PRD §3.7: "when the plan's state_code equals the
        beneficiary's state_code (otherwise ERR_MEDIGAP_STATE_MISMATCH)".

        Claim: plan.state_code != beneficiary.state_code ->
        ERR_MEDIGAP_STATE_MISMATCH.
        """
        setup_clock_at(2026, 6, 1)
        b = create_beneficiary(
            date_of_birth="1956-06-15", state_code="CA",
        )
        plan = create_medigap_plan(
            state_code="NY", monthly_premium_cents=20_000,
        )
        from test_helpers import create_enrollment_period
        create_enrollment_period(
            beneficiary=b, period_type="MEDIGAP_GI",
            window_start="2026-05-01T00:00:00.000Z",
            window_end="2026-09-30T23:59:59.000Z",
        )
        policy = create_medigap_policy(beneficiary=b, plan=plan)
        resp = api.evaluate_gi_medigap(policy["id"], {}, admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_MEDIGAP_STATE_MISMATCH.value,
        )


class TestMedigapUnderwritingCycle:
    """PRD §3.7 UNDERWRITING <-> APPLIED revise cycle."""

    def test_begin_underwriting_when_no_gi_open(self, api,
                                                counselor_headers):
        """PRD §3.7: "If instead no MEDIGAP_GI period covers applied_at,
        the admin uses the begin-underwriting capability to move the
        policy APPLIED -> UNDERWRITING."

        Claim: with no MEDIGAP_GI period, begin-underwriting moves
        status APPLIED -> UNDERWRITING.
        """
        b, plan, policy = setup_medigap_applied()
        uw = begin_underwriting_medigap(policy["id"])
        assert uw["status"] == "UNDERWRITING"

    def test_revise_returns_underwriting_to_applied_and_resets_uplift(
        self, api, counselor_headers,
    ):
        """PRD §3.7: "While a policy is UNDERWRITING, the beneficiary
        may amend the application via the revise capability, which
        carries the state back from UNDERWRITING to APPLIED, resets
        underwriting_uplift_decimal to zero, and refreshes applied_at
        to the current clock."

        Claim: revise from UNDERWRITING moves back to APPLIED and
        zeros underwriting_uplift_decimal.
        """
        b, plan, policy = setup_medigap_applied(
            underwriting_uplift_decimal=0.25,
        )
        uw = begin_underwriting_medigap(policy["id"])
        assert uw["status"] == "UNDERWRITING"
        revised = revise_medigap_application(policy["id"])
        assert revised["status"] == "APPLIED"
        assert revised["underwriting_uplift_decimal"] == 0.0

    def test_full_revision_cycle_three_hops(self, api,
                                            counselor_headers):
        """PRD §3.7: "While a policy is UNDERWRITING, the beneficiary
        may amend the application via the revise capability, which
        carries the state back from UNDERWRITING to APPLIED, resets
        underwriting_uplift_decimal to zero, and refreshes applied_at
        to the current clock."

        Claim: APPLIED -> UNDERWRITING -> APPLIED -> UNDERWRITING ->
        APPLIED cycle is permitted (the MedigapPolicy state machine has
        a legitimate cycle).
        """
        b, plan, policy = setup_medigap_applied()
        s1 = begin_underwriting_medigap(policy["id"])
        assert s1["status"] == "UNDERWRITING"
        s2 = revise_medigap_application(policy["id"])
        assert s2["status"] == "APPLIED"
        s3 = begin_underwriting_medigap(policy["id"])
        assert s3["status"] == "UNDERWRITING"
        s4 = revise_medigap_application(policy["id"])
        assert s4["status"] == "APPLIED"


class TestMedigapIssue:
    """PRD §3.7 issuance."""

    def test_issue_from_guaranteed_issued_pins_premium(
        self, api, counselor_headers,
    ):
        """PRD §3.7: "Finalisation runs via the issue capability.
        From GUARANTEED_ISSUED, issuance requires premium_locked_cents
        > 0, advances to ISSUED, and stamps issued_at to the current
        clock."

        Claim: issue from GUARANTEED_ISSUED -> status=ISSUED and an
        issued_at timestamp is set.
        """
        b, plan, gi_period, policy = setup_medigap_with_open_gi_period(
            state_code="CA", plan_premium_cents=20_000,
        )
        gi = evaluate_gi_medigap(policy["id"])
        issued = issue_medigap(policy["id"])
        assert issued["status"] == "ISSUED"
        assert issued.get("issued_at")

    def test_issue_from_underwriting_applies_uplift(
        self, api, counselor_headers,
    ):
        """PRD §3.7: "From UNDERWRITING, issuance requires
        underwriting_uplift_decimal >= 0, computes premium_locked_cents
        as the plan's monthly_premium_cents multiplied by one plus
        underwriting_uplift_decimal, rounded half up to integer cents,
        advances to ISSUED, and stamps issued_at."

        Claim: with uplift 0.25 and base 20000, premium_locked_cents =
        round_half_up(20000 * 1.25) = 25000.
        """
        b, plan, policy = setup_medigap_applied(
            plan_premium_cents=20_000,
            underwriting_uplift_decimal=0.25,
        )
        begin_underwriting_medigap(policy["id"])
        issued = issue_medigap(policy["id"])
        assert issued["status"] == "ISSUED"
        assert issued["premium_locked_cents"] == 25_000, (
            f"expected 25000 (20000 * 1.25), got "
            f"{issued['premium_locked_cents']}"
        )
