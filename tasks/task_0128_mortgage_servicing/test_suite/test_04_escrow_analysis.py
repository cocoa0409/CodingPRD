"""Escrow analysis: provisional create, finalize, projection math,
surplus refund disbursement.

Coverage targets (PRD §3.3):
- ERR_ESCROW_BASELINE_MISMATCH when starting_balance != current
  escrow_balance OR analysis_date < origination_date.
- New analysis begins in PROVISIONAL.
- Projection: projected_disbursements_cents = sum of SCHEDULED tax/ins
  within [analysis_date, analysis_date+365d) + PMI*12 if ACTIVE.
- required_cushion_cents = ceil(projected/12)*2.
- new_monthly_escrow_cents = ceil((projected+shortage)/12).
- Finalize sets Loan.monthly_escrow_payment_cents and may emit SURPLUS_REFUND.
- A PROVISIONAL analysis NEVER writes Loan.monthly_escrow_payment_cents.
- Finalize a non-PROVISIONAL -> ERR_INVALID_STATE.
"""
from __future__ import annotations

import math
from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    SURPLUS_REFUND_FLOOR_CENTS,
    SURPLUS_REFUND_OFFSET_DAYS,
    advance_clock,
    assert_escrow_analysis,
    create_escrow_analysis,
    finalize_escrow_analysis,
    get_loan,
    iso_datetime_utc_midnight,
    schedule_disbursement,
    setup_borrower_and_current_loan,
    setup_escrow_provisional_for_finalize_divergence,
    setup_loan_with_disbursements,
    setup_loan_with_escrow_balance,
    today_utc,
    validate_error,
    validate_success,
)


class TestEscrowBaselineValidation:
    """PRD §3.3 baseline checks."""

    def test_baseline_mismatch_when_starting_balance_wrong(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "starting_balance_cents must equal the current
        Loan.escrow_balance_cents. A mismatch on either side is
        rejected with ERR_ESCROW_BASELINE_MISMATCH."

        Claim: starting_balance_cents != Loan.escrow_balance_cents ->
        ERR_ESCROW_BASELINE_MISMATCH.
        """
        b, loan = setup_borrower_and_current_loan()
        # Loan.escrow_balance_cents == 0 at creation.
        resp = api.create_escrow_analysis(
            loan["id"],
            {"analysis_date": iso_datetime_utc_midnight(today_utc()),
             "starting_balance_cents": 12345},
            servicer_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_ESCROW_BASELINE_MISMATCH.value)

    def test_analysis_before_origination_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "analysis_date must be on or after
        Loan.origination_date ... A mismatch on either side is rejected
        with ERR_ESCROW_BASELINE_MISMATCH."

        Claim: analysis_date < origination_date ->
        ERR_ESCROW_BASELINE_MISMATCH.
        """
        b, loan = setup_borrower_and_current_loan()
        # origination_date defaults to today_utc(); pick an analysis_date
        # one year before it.
        past_day = today_utc() - timedelta(days=365)
        resp = api.create_escrow_analysis(
            loan["id"],
            {"analysis_date": iso_datetime_utc_midnight(past_day),
             "starting_balance_cents": int(loan["escrow_balance_cents"])},
            servicer_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_ESCROW_BASELINE_MISMATCH.value)


class TestEscrowProvisional:
    """PRD §3.3 provisional creation."""

    def test_create_returns_provisional(self, api, servicer_headers):
        """PRD §3.3: "The newly created EscrowAnalysis begins in status
        PROVISIONAL".

        Claim: a freshly created analysis has status=PROVISIONAL.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        assert_escrow_analysis(a)
        assert a["status"] == "PROVISIONAL"
        assert a["finalized_at"] is None

    def test_provisional_does_not_mutate_loan_monthly_escrow(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "A PROVISIONAL analysis never mutates
        Loan.monthly_escrow_payment_cents and never emits a disbursement."

        Claim: after POST /escrow-analyses (no /finalize),
        Loan.monthly_escrow_payment_cents is unchanged from the value
        recorded on the loan prior to the call.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        loan_after = get_loan(loan["id"])
        # Loan was created without monthly_escrow_payment_cents -> default
        # value (0 per scaffold §1.1). After PROVISIONAL it must remain 0.
        assert (
            loan_after["monthly_escrow_payment_cents"]
            == loan["monthly_escrow_payment_cents"]
        )

    def test_projection_includes_only_window_disbursements(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "projected_disbursements_cents is the sum of
        amount_cents across every Disbursement in status SCHEDULED with
        type PROPERTY_TAX or HAZARD_INSURANCE whose scheduled_date
        falls in the half-open window from analysis_date up to but not
        including analysis_date plus 365 days, plus — only when
        pmi_status is ACTIVE — twelve times pmi_monthly_cents;
        SURPLUS_REFUND disbursements are excluded."

        Claim: with one PROPERTY_TAX 480_000 at +90d and pmi inactive,
        projected_disbursements_cents == 480_000.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        assert a["projected_disbursements_cents"] == 480_000


class TestEscrowCushionAndMonthly:
    """PRD §3.3 cushion + new_monthly_escrow math."""

    def test_cushion_is_ceil_projected_div_12_times_2(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "The two-month RESPA-style cushion
        required_cushion_cents equals the ceiling of
        projected_disbursements_cents divided by 12, multiplied by 2."

        Claim: projected=480_000 -> ceil(480000/12) * 2 = 40000 * 2
        = 80_000.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        expected = math.ceil(480_000 / 12) * 2
        assert a["required_cushion_cents"] == expected == 80_000

    def test_new_monthly_escrow_is_ceil_projected_plus_shortage_div_12(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "new_monthly_escrow_cents is the ceiling of
        projected_disbursements_cents plus shortage_cents, divided by 12."

        Claim: projected=480_000, starting=0 -> shortage = 80_000,
        new_monthly_escrow = ceil((480_000+80_000)/12) = 46_667.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        # shortage = max(0, cushion - starting) = 80000 - 0 = 80000
        assert a["shortage_cents"] == 80_000
        assert a["new_monthly_escrow_cents"] == math.ceil(
            (480_000 + 80_000) / 12,
        ) == 46_667


class TestEscrowFinalize:
    """PRD §3.3 finalize behavior."""

    def test_finalize_writes_loan_monthly_escrow(self, api, servicer_headers):
        """PRD §3.3: "Loan.monthly_escrow_payment_cents is overwritten
        with the freshly computed new_monthly_escrow_cents."

        Claim: after /finalize, Loan.monthly_escrow_payment_cents ==
        analysis.new_monthly_escrow_cents.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        fin = finalize_escrow_analysis(loan["id"], a["id"])
        assert fin["status"] == "FINALIZED"
        loan_after = get_loan(loan["id"])
        assert (
            loan_after["monthly_escrow_payment_cents"]
            == fin["new_monthly_escrow_cents"]
        )

    def test_finalize_supersede_blocks_finalize_again(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "Finalisation is only permitted when the source
        analysis is still PROVISIONAL ... otherwise the request is
        rejected with ERR_INVALID_STATE."

        Claim: a second /finalize on a now-FINALIZED analysis ->
        ERR_INVALID_STATE.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        finalize_escrow_analysis(loan["id"], a["id"])
        # Second finalize on the same record.
        resp = api.finalize_escrow_analysis(
            loan["id"], a["id"],
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSurplusRefundEmission:
    """PRD §3.3 surplus-refund disbursement emission."""

    def test_surplus_above_5000_cents_emits_surplus_refund(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "when surplus_cents strictly exceeds five thousand
        cents (i.e. exceeds fifty dollars), the system creates a new
        Disbursement of type SURPLUS_REFUND with amount_cents equal to
        surplus_cents, scheduled_date thirty days in the future, and
        status SCHEDULED."

        Claim: a finalized analysis with surplus > 5000 -> at least
        one SURPLUS_REFUND disbursement with amount == surplus.
        """
        # Build a loan with escrow_balance ~ 1_000_000 cents and a small
        # 120_000 PROPERTY_TAX disbursement so the projected+cushion
        # comes to roughly 140_000, leaving a surplus ~ 860_000.
        target_balance = 1_000_000
        b, loan = setup_loan_with_escrow_balance(target_balance,
                                                 pmi_monthly_cents=0)
        # Schedule a PROPERTY_TAX disbursement inside the window.
        today = today_utc()
        schedule_disbursement(
            loan["id"], type="PROPERTY_TAX",
            scheduled_date=iso_datetime_utc_midnight(
                today + timedelta(days=90),
            ),
            amount_cents=120_000,
        )
        loan = get_loan(loan["id"])
        a = create_escrow_analysis(
            loan["id"],
            analysis_date=iso_datetime_utc_midnight(today),
            starting_balance_cents=int(loan["escrow_balance_cents"]),
        )
        fin = finalize_escrow_analysis(loan["id"], a["id"])
        assert fin["surplus_cents"] > SURPLUS_REFUND_FLOOR_CENTS
        # List disbursements and look for the SURPLUS_REFUND record.
        resp = api.list_disbursements(loan["id"],
                                      servicer_headers)
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        refunds = [d for d in items if d.get("type") == "SURPLUS_REFUND"]
        assert refunds, (
            f"finalize produced surplus_cents={fin['surplus_cents']} > "
            f"{SURPLUS_REFUND_FLOOR_CENTS} but no SURPLUS_REFUND "
            f"Disbursement was created (PRD §3.3 requires emission)"
        )
        # Exactly one SURPLUS_REFUND should match the computed surplus.
        assert any(int(d["amount_cents"]) == int(fin["surplus_cents"])
                   for d in refunds), (
            f"no SURPLUS_REFUND disbursement matches surplus_cents="
            f"{fin['surplus_cents']}; got {[d['amount_cents'] for d in refunds]}"
        )

    def test_no_surplus_refund_when_surplus_is_zero(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "when surplus_cents strictly exceeds five thousand
        cents ... the system creates a new Disbursement of type
        SURPLUS_REFUND".

        Claim: when surplus_cents == 0 (starting_balance == 0,
        projected > 0), no SURPLUS_REFUND disbursement is created.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        fin = finalize_escrow_analysis(loan["id"], a["id"])
        assert fin["surplus_cents"] == 0
        resp = api.list_disbursements(loan["id"],
                                      servicer_headers)
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        refunds = [d for d in items if d.get("type") == "SURPLUS_REFUND"]
        assert not refunds, (
            f"surplus_cents=0 must not emit SURPLUS_REFUND; got {refunds}"
        )
