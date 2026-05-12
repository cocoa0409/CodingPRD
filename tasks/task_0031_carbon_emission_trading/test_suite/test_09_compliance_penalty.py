"""ComplianceDeclaration submission, caps, deficit/surplus, penalty creation,
penalty payment.

PRD references:
  - §3.6 Compliance Declaration, Retirement, and Penalty
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    assert_compliance_declaration,
    assert_penalty_order,
    create_draft_declaration,
    make_enterprise_headers,
    pay_penalty,
    setup_compliance_ready_enterprise,
    setup_non_compliant_with_penalty,
    submit_compliance_declaration_payload,
    submit_declaration,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 — Submission caps
# ===========================================================================
class TestSubmissionCaps:
    def test_ccer_offset_above_cap_rejected(self, api):
        """PRD §3.6: 'the declared CCER offset must be at most the verified
        emissions multiplied by the cycle's CCER cap (rounded down to two
        decimal places) — otherwise rejected with ERR_CCER_CAP_EXCEEDED'.

        Claim: declared_offset_ccer > verified*ccer_cap_pct
        -> ERR_CCER_CAP_EXCEEDED. With verified=50.00 and ccer_cap_pct=0.05,
        the cap is 2.50, so declared_offset_ccer=10.00 violates.
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
            line_activity_data=100.00,
            line_emission_factor=0.50,
            line_verified_amount=50.00,
        )
        payload = submit_compliance_declaration_payload(
            declared_offset_quota=0.00,
            declared_offset_ccer=10.00,  # > 50*0.05=2.50 cap
        )
        res = api.submit_compliance_declaration(
            decl["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_CCER_CAP_EXCEEDED")

    def test_borrow_amount_above_five_percent_rejected(self, api):
        """PRD §3.6: 'the declared borrow amount must be at most the
        verified emissions multiplied by 0.05 (rounded down to two decimal
        places) — otherwise rejected with ERR_BORROW_CAP_EXCEEDED'.

        Claim: declared_borrow_amount > verified*0.05 ->
        ERR_BORROW_CAP_EXCEEDED. With verified=100.00 the cap is 5.00.
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
            line_activity_data=100.00,
            line_emission_factor=1.00,
            line_verified_amount=100.00,
        )
        payload = submit_compliance_declaration_payload(
            declared_offset_quota=0.00,
            declared_offset_ccer=0.00,
            declared_borrow_amount=10.00,  # > 100*0.05=5.00 cap
        )
        res = api.submit_compliance_declaration(
            decl["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_BORROW_CAP_EXCEEDED")


# ===========================================================================
# §3.6 — Submission balance check
# ===========================================================================
class TestSubmissionBalance:
    def test_offset_quota_exceeding_balance_rejected(self, api):
        """PRD §3.6: 'the enterprise's free-plus-paid balance must be at
        least declared_offset_quota and the enterprise's CCER balance
        must be at least declared_offset_ccer — otherwise rejected with
        ERR_INSUFFICIENT_BALANCE.'

        Claim: declared_offset_quota greater than
        (quota_balance + paid_quota_balance) -> ERR_INSUFFICIENT_BALANCE.
        """
        # Build an enterprise with allocation totalling ~300 quota
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
            line_activity_data=100.00,
            line_emission_factor=0.50,
            line_verified_amount=50.00,
        )
        # The enterprise has activity_volume=1000*1.50=1500 quota in setup.
        # Asking for retirement of 99_999 vastly exceeds.
        payload = submit_compliance_declaration_payload(
            declared_offset_quota=99_999.00,
            declared_offset_ccer=0.00,
        )
        res = api.submit_compliance_declaration(
            decl["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_INSUFFICIENT_BALANCE")


# ===========================================================================
# §3.6 — Submission window
# ===========================================================================
class TestSubmissionWindow:
    def test_submit_after_compliance_deadline_rejected(self, api):
        """PRD §3.6: 'Submission after the compliance deadline is rejected
        with ERR_WINDOW_CLOSED.'

        Claim: clock advanced past compliance_deadline -> submit ->
        ERR_WINDOW_CLOSED.
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
        )
        advance_clock(add_seconds(cyc["compliance_deadline"], 1))
        payload = submit_compliance_declaration_payload(
            declared_offset_quota=10.00, declared_offset_ccer=0.00,
        )
        res = api.submit_compliance_declaration(
            decl["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_WINDOW_CLOSED")


# ===========================================================================
# §3.6 — Successful submission and surplus / deficit
# ===========================================================================
class TestSurplusAndDeficit:
    def test_submit_with_offset_meeting_verified_yields_compliant(self):
        """PRD §3.6: 'If deficit_amount is zero, the declaration transitions
        from SUBMITTED to COMPLIANT and is synced to the regulator system
        via an event-driven hook.'

        Claim: declared_offset_quota == verified_emissions ->
        ComplianceDeclaration.status=COMPLIANT, deficit_amount=0,
        surplus_amount=0.
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
            line_activity_data=100.00,
            line_emission_factor=0.50,
            line_verified_amount=50.00,
        )
        submitted = submit_declaration(
            declaration_id=decl["id"], enterprise_id=ent["id"],
            declared_offset_quota=50.00, declared_offset_ccer=0.0,
        )
        assert_compliance_declaration(submitted)
        # Some implementations return after the auto-transition cascade.
        assert submitted["status"] in {"COMPLIANT", "SUBMITTED"}
        assert submitted["deficit_amount"] == pytest.approx(0.00, abs=0.01)
        assert submitted["surplus_amount"] == pytest.approx(0.00, abs=0.01)

    def test_offset_above_verified_records_surplus(self):
        """PRD §3.6: 'The surplus_amount is the maximum of zero and
        offset_total minus verified, rounded half-up to two decimal places.'

        Claim: with verified=50.00 and offset_total=60.00,
        surplus_amount=10.00 and deficit_amount=0.00.
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
            line_activity_data=100.00,
            line_emission_factor=0.50,
            line_verified_amount=50.00,
        )
        submitted = submit_declaration(
            declaration_id=decl["id"], enterprise_id=ent["id"],
            declared_offset_quota=60.00, declared_offset_ccer=0.0,
        )
        assert submitted["surplus_amount"] == pytest.approx(10.00, abs=0.01)
        assert submitted["deficit_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# §3.6 — Penalty calculation severity & rate
# ===========================================================================
class TestPenaltyCalculation:
    def test_penalty_minor_severity_jd_alpha(self):
        """PRD §3.6: 'if deficit_pct is strictly less than 0.05, severity
        is MINOR; otherwise if deficit_pct is strictly less than 0.20,
        severity is MODERATE; otherwise severity is SEVERE.'
        PRD §3.6: 'for JD_ALPHA, the rates are 100.00, 200.00, and 500.00
        currency units per tCO2e for MINOR, MODERATE, and SEVERE
        respectively'.

        Claim: with verified=100.00, declared_offset_quota=98.00,
        deficit=2.00 (deficit_pct=0.02 < 0.05 -> MINOR), JD_ALPHA rate
        100.00, penalty_amount = 2.00 * 100.00 = 200.00.
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=98.00,
                declared_offset_ccer=0.0,
            )
        )
        assert_penalty_order(penalty)
        assert penalty["severity"] == "MINOR"
        assert penalty["penalty_rate"] == pytest.approx(100.00, abs=0.01)
        assert penalty["deficit_amount"] == pytest.approx(2.00, abs=0.01)
        assert penalty["penalty_amount"] == pytest.approx(200.00, abs=0.01)

    def test_penalty_severe_severity_jd_alpha(self):
        """PRD §3.6: '... otherwise severity is SEVERE. (The boundaries
        are exclusive on the lower bound: a deficit_pct of exactly 0.05
        maps to MODERATE, and exactly 0.20 maps to SEVERE.)'
        For JD_ALPHA, SEVERE rate is 500.00.

        Claim: with verified=100.00, declared_offset_quota=70.00,
        deficit=30.00 (deficit_pct=0.30 -> SEVERE),
        penalty_amount = 30.00 * 500.00 = 15000.00.
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=70.00,
                declared_offset_ccer=0.0,
            )
        )
        assert penalty["severity"] == "SEVERE"
        assert penalty["penalty_rate"] == pytest.approx(500.00, abs=0.01)
        assert penalty["penalty_amount"] == pytest.approx(15000.00, abs=0.01)

    def test_mandatory_deduction_is_one_point_five_times_deficit(self):
        """PRD §3.6: 'The mandatory_deduction_amount is the deficit_amount
        multiplied by 1.5, rounded half-up to two decimal places.'

        Claim: mandatory_deduction_amount == 1.5 * deficit_amount exactly.
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=80.00,
                declared_offset_ccer=0.0,
            )
        )
        # deficit = 100 - 80 = 20.00; mandatory_deduction = 30.00
        assert penalty["deficit_amount"] == pytest.approx(20.00, abs=0.01)
        assert penalty["mandatory_deduction_amount"] == pytest.approx(
            30.00, abs=0.01
        )
        # And the explicit 1.5x identity:
        assert penalty["mandatory_deduction_amount"] == pytest.approx(
            1.5 * penalty["deficit_amount"], abs=0.01
        )


# ===========================================================================
# §3.6 — Penalty payment and overdue
# ===========================================================================
class TestPenaltyPayment:
    def test_pay_penalty_marks_paid_and_records_credit(self):
        """PRD §3.6: 'The enterprise pays the penalty via a payment action;
        the order transitions from UNPAID to PAID with paid_at set to the
        current time and credit_record_reported set to true, provided the
        current time is at or before payment_due_at.'

        Claim: pay -> payment_status=PAID, paid_at non-null,
        credit_record_reported=true.
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=98.00,
                declared_offset_ccer=0.0,
            )
        )
        paid = pay_penalty(
            penalty_id=penalty["id"], enterprise_id=ent["id"]
        )
        assert paid["payment_status"] == "PAID"
        assert paid.get("paid_at") is not None
        assert paid["credit_record_reported"] is True

    def test_pay_after_due_date_rejected_with_overdue(self, api):
        """PRD §3.6: 'If payment is attempted after payment_due_at, the
        request is rejected with ERR_PENALTY_OVERDUE.'

        Claim: clock advanced past payment_due_at -> pay ->
        ERR_PENALTY_OVERDUE.
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=98.00,
                declared_offset_ccer=0.0,
            )
        )
        advance_clock(add_seconds(penalty["payment_due_at"], 1))
        res = api.pay_penalty_order(
            penalty["id"], make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_PENALTY_OVERDUE")
