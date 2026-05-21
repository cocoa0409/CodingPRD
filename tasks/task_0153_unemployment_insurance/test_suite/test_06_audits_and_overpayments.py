"""Certification audits, the OVERPAID cascade, and overpayment
lifecycle — PRD §3.5.

Covers the depth-4 cascade (cert -> payment -> charges -> employer rate)
plus repay / waive / write-off transitions on Overpayment.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    STATUTE_OF_LIMITATIONS_DAYS,
    TEST_USERS,
    advance_clock_by_days,
    approve_one_weekly_certification,
    assert_overpayment,
    audit_certification,
    create_eligible_claim,
    get_claim,
    get_claimant,
    get_employer,
    get_overpayment,
    list_claim_overpayments,
    list_employer_charges,
    make_adjudicator_headers,
    make_claimant_headers,
    repay_overpayment,
    repay_overpayment_payload,
    setup_employer_with_active_charge,
    setup_outstanding_overpayment,
    validate_error,
    validate_success,
    waive_overpayment,
    waive_overpayment_payload,
    write_off_overpayment,
)


class TestAuditCascadeDepth4:

    def test_audit_cascades_all_four_links(self, api):
        """PRD §3.5: "First, the BenefitPayment is mutated: status flips
        to REVERSED and reversed_reason is populated from the audit's
        reason. Second, an Overpayment is created whose claim_id and
        certification_id link back to the parent records, whose
        principal_cents equals the reversed BenefitPayment.amount_cents,
        whose balance_cents equals that principal, whose classification
        comes from the audit body, and whose status is OUTSTANDING.
        Third, every EmployerCharge whose payment_id matches the
        reversed payment and whose status is currently ACTIVE is
        updated: its status flips to REVERSED, and each affected
        employer's experience_rate_bps is recomputed against the new
        net-charges total."

        # difficulty: transitive_cascade/audit_overpaid_cascade_depth_4
        # difficulty: non_linear_state_machine/claim_exhausted_cycle_via_audit_revert
        """
        scenario = setup_employer_with_active_charge(
            reserve_basis_cents=1_000_000,
            taxable_payroll_cents=10_000_000,
            charge_amount_cents=300_000,
        )
        emp_before = get_employer(scenario["employer"]["id"])
        # Link starting state: 180 bps.
        assert emp_before["experience_rate_bps"] == 180

        cert = scenario["certification"]
        audited = audit_certification(
            cert["id"], classification="NON_FRAUD", reason="audit",
        )
        # Link 1: WC status flipped to OVERPAID.
        assert audited["status"] == "OVERPAID"

        # Link 2 (caused by Link 1): BenefitPayment.status REVERSED.
        # We read it indirectly via the cert (payment_id) — and we
        # observe via overpayment which references the payment.
        ops = list_claim_overpayments(scenario["claim"]["id"])
        assert ops, "audit must create an Overpayment"
        op = ops[0]
        assert_overpayment(op)
        assert op["status"] == "OUTSTANDING"
        assert op["balance_cents"] == op["principal_cents"]

        # Link 3 (caused by Link 2): EmployerCharge.status REVERSED.
        charges = list_employer_charges(scenario["employer"]["id"])
        reversed_charges = [c for c in charges if c["status"] == "REVERSED"]
        assert reversed_charges, (
            "expected at least one EmployerCharge with status REVERSED "
            "after audit cascade"
        )

        # Link 4 (caused by Link 3): experience_rate_bps recomputed
        # back to floor (no ACTIVE charges -> ratio=0.10 -> 100 bps).
        emp_after = get_employer(scenario["employer"]["id"])
        assert emp_after["experience_rate_bps"] == 100, (
            f"after audit cascade the experience_rate_bps should "
            f"recompute to 100; got {emp_after['experience_rate_bps']}"
        )

    def test_audit_creates_overpayment_with_principal_equal_amount(self, api):
        """PRD §3.5: "an Overpayment is created whose ...
        principal_cents equals the reversed BenefitPayment.amount_cents,
        whose balance_cents equals that principal."

        # difficulty: compensating_invariant/payment_dollar_conservation_invariant
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        assert op["principal_cents"] == op["balance_cents"]
        # Conservation: overpayment principal equals payment amount.
        # The payment amount equals the WBA when earnings=0.
        wba = bundle["claim"]["weekly_benefit_amount_cents"]
        # The bundle's claim is post-audit, so weekly_benefit_amount_cents
        # is the same; payment was amount == wba.
        assert op["principal_cents"] == wba

    def test_audit_updates_lifetime_overpayment_balance(self, api):
        """PRD §3.5: "Recompute Claimant.lifetime_overpayment_balance_cents".
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        cm = get_claimant(bundle["claimant"]["id"])
        # After audit, lifetime balance equals the outstanding
        # principal (no repayments yet).
        assert cm["lifetime_overpayment_balance_cents"] == bundle[
            "overpayment"
        ]["principal_cents"]

    def test_audit_decrements_weeks_paid(self, api):
        """PRD §3.5: "the claim is reconciled: weeks_paid is decremented
        by one, weeks_remaining is recomputed."

        # difficulty: compensating_invariant/weeks_paid_round_trip_invariant
        """
        bundle = create_eligible_claim()
        approve_one_weekly_certification(bundle)
        claim_after_approve = get_claim(bundle["claim"]["id"])
        assert claim_after_approve["weeks_paid"] == 1

        # Now find the cert and audit it.
        from test_helpers import api_client as ac
        resp = ac.list_weekly_certifications(
            bundle["claim"]["id"], TEST_USERS["system_admin_headers"],
        )
        certs = resp.json()["data"]
        approved = next(c for c in certs if c["status"] == "APPROVED")
        audit_certification(approved["id"], classification="NON_FRAUD")
        claim_after_audit = get_claim(bundle["claim"]["id"])
        assert claim_after_audit["weeks_paid"] == 0, (
            "weeks_paid must decrement back to 0 after audit"
        )


class TestOverpaymentRepay:

    def test_repay_full_balance_transitions_to_repaid(self, api):
        """PRD §3.5: "When accepted, balance_cents is decremented by
        the repaid amount; if it reaches zero, the overpayment
        transitions OUTSTANDING -> REPAID."
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        result = repay_overpayment(
            op["id"], bundle["claimant"]["id"],
            amount_cents=op["balance_cents"],
        )
        assert result["status"] == "REPAID"
        assert result["balance_cents"] == 0

    def test_repay_partial_keeps_outstanding(self, api):
        """PRD §3.5: "balance_cents is decremented by the repaid
        amount; if it reaches zero, the overpayment transitions
        OUTSTANDING -> REPAID."
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        half = max(1, op["balance_cents"] // 2)
        result = repay_overpayment(
            op["id"], bundle["claimant"]["id"], amount_cents=half,
        )
        assert result["status"] == "OUTSTANDING"
        assert result["balance_cents"] == op["balance_cents"] - half

    def test_repay_more_than_balance_rejected(self, api):
        """PRD §3.5: "The repayment is accepted only if amount_cents is
        strictly greater than zero and is no greater than the
        overpayment's current balance_cents; otherwise it is rejected
        with ERR_REPAY_EXCEEDS_BALANCE."

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_overpayment
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        resp = api.repay_overpayment(
            op["id"],
            repay_overpayment_payload(op["balance_cents"] + 1),
            make_claimant_headers(bundle["claimant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPAY_EXCEEDS_BALANCE.value)

    def test_zero_repayment_rejected(self, api):
        """PRD §3.5: "accepted only if amount_cents is strictly greater
        than zero".
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        resp = api.repay_overpayment(
            op["id"],
            repay_overpayment_payload(0),
            make_claimant_headers(bundle["claimant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPAY_EXCEEDS_BALANCE.value)


class TestOverpaymentWaive:

    def test_waive_non_fraud_succeeds(self, api):
        """PRD §3.5: "An Adjudicator may waive an outstanding
        overpayment whose classification is in the set of AGENCY_ERROR
        or NON_FRAUD."
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        result = waive_overpayment(op["id"])
        assert result["status"] == "WAIVED"
        assert result["balance_cents"] == 0

    def test_waive_agency_error_succeeds(self, api):
        """PRD §3.5: "in the set of AGENCY_ERROR or NON_FRAUD."
        """
        bundle = setup_outstanding_overpayment(classification="AGENCY_ERROR")
        op = bundle["overpayment"]
        result = waive_overpayment(op["id"])
        assert result["status"] == "WAIVED"

    def test_waive_fraud_rejected(self, api):
        """PRD §3.5: "any attempt to waive an overpayment whose
        classification is FRAUD is rejected with
        ERR_FRAUD_NOT_WAIVABLE."
        """
        bundle = setup_outstanding_overpayment(classification="FRAUD")
        op = bundle["overpayment"]
        resp = api.waive_overpayment(
            op["id"], waive_overpayment_payload(),
            make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FRAUD_NOT_WAIVABLE.value)


class TestOverpaymentWriteOff:

    def test_write_off_before_statute_rejected(self, api):
        """PRD §3.5: "A write-off attempted earlier is rejected with
        ERR_STATUTE_NOT_REACHED."

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_overpayment
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        resp = api.write_off_overpayment(
            op["id"], make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STATUTE_NOT_REACHED.value)

    def test_write_off_after_statute_succeeds(self, api):
        """PRD §3.5: "the difference between SystemClock.now and the
        overpayment's created_at must be at least 1825 days (a full
        five years)."
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        # Advance the clock past the statute (1825 days + 1).
        advance_clock_by_days(STATUTE_OF_LIMITATIONS_DAYS + 1)
        result = write_off_overpayment(op["id"])
        assert result["status"] == "WRITTEN_OFF"
        assert result["balance_cents"] == 0


class TestOverpaymentReadAccess:

    def test_claimant_reads_own_overpayment(self, api):
        """PRD §4: "GET /overpayments/{id} ... Claimant, Adjudicator,
        AppealOfficer, SystemAdmin."
        PRD §2.1 ownership.
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        resp = api.get_overpayment(
            op["id"], make_claimant_headers(bundle["claimant"]["id"]),
        )
        data = validate_success(resp)
        assert data["id"] == op["id"]

    def test_audit_nonexistent_certification_not_found(self, api):
        """PRD §2.7 path validation."""
        from test_helpers import audit_weekly_certification_payload
        resp = api.audit_weekly_certification(
            NON_EXISTENT_UUID,
            audit_weekly_certification_payload("NON_FRAUD"),
            make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
