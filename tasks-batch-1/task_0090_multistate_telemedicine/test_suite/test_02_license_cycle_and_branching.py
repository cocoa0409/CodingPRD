"""License-status cycling, visit approval branching, and conserved-quantity invariants.

Depth coverage for the StateLicense ACTIVE<->SUSPENDED cycle, the Visit COMPLIANCE_CLEARED
fork to INSURANCE vs SELF_PAY (divergent side effects), and the two compensating invariants
(active_license_count conservation; committed plan-paid liability conservation).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    make_physician_headers,
    board_headers,
    officer_headers,
    set_clock,
    create_physician,
    issue_license,
    create_payer,
    create_patient,
    request_visit,
    setup_licensed_physician,
    setup_cleared_visit,
    setup_approved_visit,
)


class TestStateLicenseCycle:
    """ACTIVE -> SUSPENDED -> ACTIVE returns the license to ACTIVE and restores the count."""

    def test_suspend_then_reinstate_returns_to_active(self, api):
        """PRD §3.4: "Reinstatement clears the `suspension_reason` back to null, returns
        the license to `ACTIVE`, and increments the physician's `active_license_count` by
        one."

        Design: Difficulty/non_linear_state_machine/state_license_cycle_active_suspended_active
        """
        physician, license_ = setup_licensed_physician(state_code="CA")
        validate_success(api.suspend_state_license(license_["id"], {"suspension_reason": "audit"}, board_headers()), 200)
        reinstated = validate_success(api.reinstate_state_license(license_["id"], board_headers()), 200)
        assert reinstated["status"] == "ACTIVE", f"expected ACTIVE after reinstate, got {reinstated['status']}"
        assert reinstated["suspension_reason"] is None, (
            f"suspension_reason should clear to null, got {reinstated['suspension_reason']!r}"
        )

    def test_reinstate_restores_active_license_count(self, api):
        """PRD §3.4: "Reinstatement clears the `suspension_reason` back to null, returns
        the license to `ACTIVE`, and increments the physician's `active_license_count` by
        one."

        Design: Difficulty/non_linear_state_machine/state_license_cycle_active_suspended_active
        """
        physician, license_ = setup_licensed_physician(state_code="CA")
        api.suspend_state_license(license_["id"], {"suspension_reason": "audit"}, board_headers())
        api.reinstate_state_license(license_["id"], board_headers())
        phys_after = validate_success(api.get_physician(physician["id"], board_headers()), 200)
        assert phys_after["active_license_count"] == 1, (
            f"count should return to 1 after cycle, got {phys_after['active_license_count']}"
        )


class TestVisitApprovalBranching:
    """COMPLIANCE_CLEARED forks to APPROVED_INSURANCE (creates Claim) vs APPROVED_SELF_PAY (none)."""

    def test_insurance_fork_creates_claim(self, api):
        """PRD §3.5: "When the patient on the visit carries insurance — their
        `insurance_payer_id` is not null — approval routes to insurance: the visit moves
        from `COMPLIANCE_CLEARED` to `APPROVED_INSURANCE`, its `routing` is set to
        `INSURANCE`, and its `patient_cost_cents` is computed by the insurance cost path
        described below."
        PRD §3.5: "Only the insurance fork creates downstream billing."

        Design: Difficulty/non_linear_state_machine/visit_branching_cleared_to_insurance_or_self_pay
        """
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        assert ctx["visit"]["status"] == "APPROVED_INSURANCE", (
            f"expected APPROVED_INSURANCE, got {ctx['visit']['status']}"
        )
        data, meta = validate_paginated(api.list_visit_claims(ctx["visit"]["id"], officer_headers()))
        assert meta["total_count"] == 1, f"insurance branch should create one Claim, got {meta['total_count']}"

    def test_self_pay_fork_creates_no_claim(self, api):
        """PRD §3.5: "When the patient carries no insurance — `insurance_payer_id` is
        null — approval routes to self-pay: the visit moves to `APPROVED_SELF_PAY`, its
        `routing` is set to `SELF_PAY`, and `patient_cost_cents` is computed by the
        self-pay path."
        PRD §3.5: "The self-pay fork creates no claim at all."

        Design: Difficulty/non_linear_state_machine/visit_branching_cleared_to_insurance_or_self_pay
        """
        ctx = setup_approved_visit(insured=False, visit_overrides={"list_fee_cents": 10000})
        assert ctx["visit"]["status"] == "APPROVED_SELF_PAY", (
            f"expected APPROVED_SELF_PAY, got {ctx['visit']['status']}"
        )
        data, meta = validate_paginated(api.list_visit_claims(ctx["visit"]["id"], officer_headers()))
        assert meta["total_count"] == 0, f"self-pay branch should create no Claim, got {meta['total_count']}"


class TestActiveLicenseCountConservation:
    """Forward suspend (decrement) + compensating reinstate (increment) conserves the count."""

    def test_suspend_reinstate_conserves_count_with_two_licenses(self, api):
        """PRD §3.4: "it captures the supplied `suspension_reason`, moves the license to
        `SUSPENDED`, and decrements the physician's `active_license_count` by one
        (recomputed as the count of that physician's `ACTIVE` licenses)."
        PRD §3.4: "Reinstatement clears the `suspension_reason` back to null, returns the
        license to `ACTIVE`, and increments the physician's `active_license_count` by one."

        Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_active_license_count
        """
        set_clock("2026-04-01T09:00:00.000Z")
        physician = create_physician(imlc_eligible=True, home_state_code="CA")
        lic_ca = issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        issue_license(physician["id"], state_code="TX", issuance_type="COMPACT_EXPEDITED")
        before = validate_success(api.get_physician(physician["id"], board_headers()), 200)
        assert before["active_license_count"] == 2, f"expected 2 before, got {before['active_license_count']}"

        api.suspend_state_license(lic_ca["id"], {"suspension_reason": "temporary"}, board_headers())
        api.reinstate_state_license(lic_ca["id"], board_headers())
        after = validate_success(api.get_physician(physician["id"], board_headers()), 200)
        assert after["active_license_count"] == 2, (
            f"count should be restored to 2 after suspend+reinstate, got {after['active_license_count']}"
        )

    def test_suspended_license_returns_to_active_after_reinstate(self, api):
        """PRD §3.4: "Reinstatement clears the `suspension_reason` back to null, returns
        the license to `ACTIVE`, and increments the physician's `active_license_count` by
        one."

        Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_active_license_count
        """
        set_clock("2026-04-01T09:00:00.000Z")
        physician = create_physician(imlc_eligible=True, home_state_code="CA")
        lic_ca = issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        issue_license(physician["id"], state_code="TX", issuance_type="COMPACT_EXPEDITED")
        api.suspend_state_license(lic_ca["id"], {"suspension_reason": "temporary"}, board_headers())
        reinstated = validate_success(api.reinstate_state_license(lic_ca["id"], board_headers()), 200)
        assert reinstated["status"] == "ACTIVE", f"expected ACTIVE, got {reinstated['status']}"


class TestCommittedPlanPaidConservation:
    """approve+adjudicate commits plan liability; suspension-cascade reversal returns it to 0."""

    def _single_claim(self, api, visit_id):
        data, _ = validate_paginated(api.list_visit_claims(visit_id, officer_headers()))
        return data[0]

    def test_approve_adjudicate_commits_plan_paid(self, api):
        """PRD §3.6: "If the payer offers telehealth parity, the plan pays the allowed
        amount minus the payer's `copay_cents`, floored at zero — that is, `plan_paid_cents`
        is the allowed amount less the copay, but never below zero."

        Design: Difficulty/compensating_invariant/approve_then_suspend_reversal_conserves_committed_plan_paid
        """
        # allowed 8000, parity copay 2500 -> plan_paid 5500.
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        claim = self._single_claim(api, ctx["visit"]["id"])
        adjudicated = validate_success(api.adjudicate_claim(claim["id"], officer_headers()), 200)
        assert adjudicated["status"] == "ADJUDICATED", f"expected ADJUDICATED, got {adjudicated['status']}"
        assert adjudicated["plan_paid_cents"] == 5500, (
            f"committed plan_paid expected 5500, got {adjudicated['plan_paid_cents']}"
        )

    def test_suspension_reverses_claim_returning_committed_liability_to_zero(self, api):
        """PRD §3.4: "When the visit being voided is an `APPROVED_INSURANCE` visit, every
        `Claim` on that visit (matched by `visit_id`) whose `status` is `SUBMITTED` or
        `ADJUDICATED` transitions to `REVERSED`."

        Design: Difficulty/compensating_invariant/approve_then_suspend_reversal_conserves_committed_plan_paid
        """
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        claim = self._single_claim(api, ctx["visit"]["id"])
        api.adjudicate_claim(claim["id"], officer_headers())
        api.suspend_state_license(ctx["license"]["id"], {"suspension_reason": "board action"}, board_headers())
        after = validate_success(api.get_claim(claim["id"], officer_headers()), 200)
        assert after["status"] == "REVERSED", (
            f"claim should be REVERSED after suspension cascade, got {after['status']}"
        )
        # committed liability = sum(plan_paid WHERE status IN {SUBMITTED, ADJUDICATED}); REVERSED excludes it -> 0.
