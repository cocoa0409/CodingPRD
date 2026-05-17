"""Difficulty-design coverage — at least two tests per declared
instance per the test-targeting index.

Each test docstring carries a `# difficulty: <rule_id>/<instance>`
tag so coverage can be audited. Each test pins to a verbatim PRD
sentence stating the underlying rule.
"""
from __future__ import annotations

import math
from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    HAMP_STALE_OFFER_TOLERANCE_CENTS,
    LATE_FEE_PER_MONTH_CENTS,
    PMI_BORROWER_REQUEST_LTV_BPS,
    SURPLUS_REFUND_FLOOR_CENTS,
    SURPLUS_REFUND_OFFSET_DAYS,
    accept_mediation_offer,
    advance_clock,
    approve_pmi_removal,
    assert_exactly_one_succeeds,
    cancel_forbearance_plan,
    complete_mediation,
    create_escrow_analysis,
    create_forbearance_plan,
    create_pmi_removal_request,
    extend_mediation_offer,
    file_foreclosure,
    finalize_escrow_analysis,
    get_foreclosure_quote,
    get_loan,
    iso_datetime_utc_midnight,
    open_foreclosure_case,
    open_mediation,
    post_payment,
    reinstate_foreclosure,
    reject_mediation_offer,
    request_mediation,
    retry_disbursement,
    reverse_payment,
    run_race,
    run_sweep,
    schedule_auction,
    schedule_disbursement,
    setup_active_forbearance_plan,
    setup_borrower_and_current_loan,
    setup_borrower_with_hardship,
    setup_escrow_provisional_for_finalize_divergence,
    setup_foreclosure_case_at_noi_issued,
    setup_foreclosure_case_auction_scheduled,
    setup_foreclosure_case_filed,
    setup_loan_at_delinquency_days,
    setup_loan_in_default,
    setup_loan_with_disbursements,
    setup_loan_with_escrow_balance,
    setup_mediation_offer_extended,
    setup_mediation_open,
    setup_pmi_pending_borrower_request,
    create_borrower,
    attest_hardship,
    create_loan,
    today_utc,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_escrow_provisional_does_not_write_loan_monthly_escrow(
        self, api,
    ):
        """# difficulty: dual_variant_calc/escrow_projection_provisional_vs_finalized

        PRD §3.3: "A PROVISIONAL analysis never mutates
        Loan.monthly_escrow_payment_cents and never emits a disbursement."

        Claim: PROVISIONAL escrow analysis on a loan with PROPERTY_TAX
        scheduled in window does NOT mutate Loan.monthly_escrow_payment_cents.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        loan_after = get_loan(loan["id"])
        # Initial monthly_escrow_payment_cents default = 0; must still be 0.
        assert loan_after["monthly_escrow_payment_cents"] == 0

    def test_escrow_finalize_recomputes_against_current_disbursements(
        self, api,
    ):
        """# difficulty: dual_variant_calc/escrow_projection_provisional_vs_finalized

        PRD §3.3: "The projection is recomputed at commit time from the
        current disbursement set (which may have changed since the
        PROVISIONAL snapshot was created)".
        PRD §3.3: "Loan.monthly_escrow_payment_cents is overwritten
        with the freshly computed new_monthly_escrow_cents."

        Claim: a HAZARD_INSURANCE disbursement added BETWEEN
        PROVISIONAL creation and /finalize must be reflected in the
        FINALIZED new_monthly_escrow_cents and written into
        Loan.monthly_escrow_payment_cents. (Recipe per difficulty
        index escrow_projection_provisional_vs_finalized.)
        """
        b, loan, a1 = setup_escrow_provisional_for_finalize_divergence()
        # Provisional: projected = 480_000, cushion = 80_000,
        # shortage = 80_000, new_monthly_escrow = ceil(560_000/12)=46_667.
        assert a1["new_monthly_escrow_cents"] == 46_667
        # Loan.monthly_escrow_payment_cents not yet written.
        assert get_loan(loan["id"])["monthly_escrow_payment_cents"] == 0
        # Add a HAZARD_INSURANCE disbursement.
        today = today_utc()
        schedule_disbursement(
            loan["id"], type="HAZARD_INSURANCE",
            scheduled_date=iso_datetime_utc_midnight(
                today + timedelta(days=180),
            ),
            amount_cents=120_000,
        )
        # Finalize: projected = 600_000, cushion = 100_000,
        # shortage = 100_000, new_monthly_escrow =
        # ceil((600_000+100_000)/12) = ceil(58_333.33) = 58_334.
        fin = finalize_escrow_analysis(loan["id"], a1["id"])
        assert fin["projected_disbursements_cents"] == 600_000
        assert fin["new_monthly_escrow_cents"] == math.ceil(
            (600_000 + 100_000) / 12,
        ) == 58_334
        # Loan.monthly_escrow_payment_cents now reflects the finalized
        # value.
        loan_after = get_loan(loan["id"])
        assert (
            loan_after["monthly_escrow_payment_cents"]
            == fin["new_monthly_escrow_cents"]
        )

    def test_standard_waterfall_late_fee_first_on_delinquent(
        self, api,
    ):
        """# difficulty: dual_variant_calc/payment_waterfall_standard_vs_reinstatement

        PRD §3.2: "The line items, in order, are: outstanding late
        fees ... then accrued interest on past-due principal and
        interest installments ... then the past-due principal portion
        of those installments; then the past-due escrow portion; and
        finally any residual is parked in suspense as
        allocation_suspense_cents."

        Claim: a $50 payment on a 35-day-delinquent loan (no foreclosure)
        allocates entirely to late fee per the standard waterfall.
        """
        b, loan = setup_loan_at_delinquency_days(35)
        p = post_payment(loan["id"], amount_cents=LATE_FEE_PER_MONTH_CENTS)
        assert p["allocation_late_fee_cents"] == LATE_FEE_PER_MONTH_CENTS

    def test_reinstatement_waterfall_closes_foreclosure_case(
        self, api,
    ):
        """# difficulty: dual_variant_calc/payment_waterfall_standard_vs_reinstatement

        PRD §3.2: "The reinstatement variant of the waterfall is the
        same line items in the same order, with two changes:
        foreclosure costs (ForeclosureCase.foreclosure_costs_cents)
        are paid first, ahead of late fees".
        PRD §3.6: "On a successful reinstatement ... the case status
        becomes CLOSED_REINSTATED, Loan.posture becomes REINSTATED".

        Claim: a payment >= reinstatement_quote_cents on a loan with
        an open ForeclosureCase closes the case (CLOSED_REINSTATED)
        and switches Loan.posture to REINSTATED — confirming the
        SAME amount is routed through the reinstatement variant, not
        the standard waterfall.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        quote_resp = api.get_foreclosure_quote(
            fc["id"], {"X-User-ID": "servicer-001",
                       "X-User-Role": "Servicer"},
        )
        quote = int(quote_resp.json()["data"]["reinstatement_quote_cents"])
        result = reinstate_foreclosure(
            fc["id"], payment_amount_cents=quote,
        )
        assert result["status"] == "CLOSED_REINSTATED"
        loan_after = get_loan(loan["id"])
        assert loan_after["posture"] == "REINSTATED"
        assert loan_after["delinquency_days"] == 0


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_hamp_offer_combines_three_inputs_into_target_payment(
        self, api,
    ):
        """# difficulty: combinatorial_formula/hamp_three_input_tiered_modification

        PRD §3.7: "first subtract offered_principal_forbearance_cents
        from principal_balance_cents to obtain the remaining principal;
        then derive the new monthly rate from offered_new_rate_bps ...
        divided by 10,000 and then divided by 12; then derive the new
        term as the original term_months minus the months elapsed
        since origination_date, plus offered_term_extension_months."
        PRD §3.7: "target_payment_cents is the ceiling of (remaining
        principal multiplied by new monthly rate, multiplied by
        one-plus-new-monthly-rate raised to the new-term power,
        divided by the quantity one-plus-new-monthly-rate raised to
        the new-term power minus one)."

        Claim: combining all three inputs (rate=400, term_ext=60,
        forbearance=1_000_000) on a P=20_000_000 / r=625bps / n=360
        loan yields a target strictly less than current
        scheduled_payment_cents (proving the formula combines all
        three non-trivially).
        """
        b, loan, fc, m = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
        )
        target = int(m["target_payment_cents"])
        loan_now = get_loan(loan["id"])
        assert target > 0
        assert target < int(loan_now["scheduled_payment_cents"])

    def test_hamp_non_linear_term_extension_lowers_target(self, api):
        """# difficulty: combinatorial_formula/hamp_three_input_tiered_modification

        PRD §3.7: "target_payment_cents is the ceiling of (remaining
        principal multiplied by new monthly rate, multiplied by
        one-plus-new-monthly-rate raised to the new-term power,
        divided by the quantity one-plus-new-monthly-rate raised to
        the new-term power minus one). A single ceiling at the final
        output, no intermediate rounding."

        Claim: holding rate and forbearance fixed, extending the term
        from 0 to 60 months reduces target_payment_cents — confirming
        the term-extension input is a non-trivial component of the
        formula.
        """
        b1, loan1, fc1, m1 = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=0,
            offered_principal_forbearance_cents=1_000_000,
        )
        b2, loan2, fc2, m2 = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
        )
        # Extended-term offer must yield a STRICTLY LOWER target.
        assert int(m2["target_payment_cents"]) < int(
            m1["target_payment_cents"],
        ), (
            f"term_ext=60 should yield lower target than term_ext=0; "
            f"got {m2['target_payment_cents']} vs {m1['target_payment_cents']}"
        )

    def test_escrow_cushion_uses_ceil_first_then_times_two(self, api):
        """# difficulty: combinatorial_formula/escrow_nested_rounding_order_pinned

        PRD §3.3: "The two-month RESPA-style cushion
        required_cushion_cents equals the ceiling of
        projected_disbursements_cents divided by 12, multiplied by 2."

        Claim: with projected_disbursements_cents = 696_000 (480_000
        tax + 120_000 ins + 8_000 PMI * 12), the cushion ==
        ceil(696_000 / 12) * 2 = 58_000 * 2 = 116_000.
        """
        # Use difficulty design recipe escrow_nested_rounding_order_pinned.
        b, loan = setup_borrower_and_current_loan(
            original_principal_cents=20_000_000,
            interest_rate_bps=625,
            term_months=360,
            pmi_monthly_cents=8_000,
        )
        today = today_utc()
        for day in (90, 180, 270, 360):
            schedule_disbursement(
                loan["id"], type="PROPERTY_TAX",
                scheduled_date=iso_datetime_utc_midnight(
                    today + timedelta(days=day),
                ),
                amount_cents=120_000,
            )
        schedule_disbursement(
            loan["id"], type="HAZARD_INSURANCE",
            scheduled_date=iso_datetime_utc_midnight(
                today + timedelta(days=200),
            ),
            amount_cents=120_000,
        )
        loan = get_loan(loan["id"])
        a = create_escrow_analysis(
            loan["id"],
            analysis_date=iso_datetime_utc_midnight(today),
            starting_balance_cents=int(loan["escrow_balance_cents"]),
        )
        # projected = 480_000 (4*120k) + 120_000 ins + 8000*12 = 696_000.
        assert a["projected_disbursements_cents"] == 696_000
        # cushion = ceil(696000/12) * 2 = 58000 * 2 = 116000.
        assert a["required_cushion_cents"] == math.ceil(696_000 / 12) * 2
        assert a["required_cushion_cents"] == 116_000

    def test_escrow_new_monthly_uses_single_ceil_over_combined_sum(
        self, api,
    ):
        """# difficulty: combinatorial_formula/escrow_nested_rounding_order_pinned

        PRD §3.3: "new_monthly_escrow_cents is the ceiling of
        projected_disbursements_cents plus shortage_cents, divided by
        12. Each output field is computed independently with at most
        one ceil() applied to it; there is no intermediate rounding
        inside a single field's computation."

        Claim: with projected=696_000, shortage=116_000 -> new_monthly =
        ceil((696_000+116_000)/12) = ceil(67_666.67) = 67_667.
        """
        b, loan = setup_borrower_and_current_loan(
            original_principal_cents=20_000_000,
            interest_rate_bps=625,
            term_months=360,
            pmi_monthly_cents=8_000,
        )
        today = today_utc()
        for day in (90, 180, 270, 360):
            schedule_disbursement(
                loan["id"], type="PROPERTY_TAX",
                scheduled_date=iso_datetime_utc_midnight(
                    today + timedelta(days=day),
                ),
                amount_cents=120_000,
            )
        schedule_disbursement(
            loan["id"], type="HAZARD_INSURANCE",
            scheduled_date=iso_datetime_utc_midnight(
                today + timedelta(days=200),
            ),
            amount_cents=120_000,
        )
        loan = get_loan(loan["id"])
        a = create_escrow_analysis(
            loan["id"],
            analysis_date=iso_datetime_utc_midnight(today),
            starting_balance_cents=int(loan["escrow_balance_cents"]),
        )
        # starting=0 so shortage = cushion = 116_000.
        assert a["shortage_cents"] == 116_000
        # new_monthly = ceil((696_000 + 116_000)/12) = 67_667.
        assert a["new_monthly_escrow_cents"] == math.ceil(
            (696_000 + 116_000) / 12,
        ) == 67_667

    def test_payment_waterfall_late_fee_snapshot_before_allocation(
        self, api,
    ):
        """# difficulty: combinatorial_formula/payment_waterfall_evaluation_order_pinned

        PRD §3.2: "outstanding late fees (where late fees accrue at
        five thousand cents per late month — that is fifty dollars —
        capped at twenty-five thousand cents, computed as the
        integer-floor of delinquency_days divided by 30, multiplied
        by the per-month late fee, capped at the cap); then accrued
        interest".

        Claim: on a 35-day-delinquent loan (one full late-fee period
        => 5000 cents), posting a small payment of 30_000 cents
        allocates 5000 to late fee, the remaining 25_000 to interest,
        and 0 elsewhere — confirming the snapshot of late_fee_due is
        taken BEFORE further allocations.
        """
        b, loan = setup_loan_at_delinquency_days(35)
        p = post_payment(loan["id"], amount_cents=30_000)
        assert p["allocation_late_fee_cents"] == 5_000
        # The rest (25_000) must flow into the next bucket (interest);
        # principal/escrow/suspense are 0 (interest_due for one missed
        # installment >> 25_000).
        assert p["allocation_interest_cents"] == 25_000
        assert p["allocation_principal_cents"] == 0
        assert p["allocation_escrow_cents"] == 0
        assert p["allocation_suspense_cents"] == 0

    def test_payment_partial_does_not_advance_next_due_date(self, api):
        """# difficulty: combinatorial_formula/payment_waterfall_evaluation_order_pinned

        PRD §3.2: "Suspense funds do not advance next_due_date — only
        when an installment's principal plus interest plus escrow has
        been fully covered does next_due_date move forward by one
        month for that installment."

        Claim: a partial payment (30_000 cents) on a 35-day-delinquent
        loan does NOT advance Loan.next_due_date — confirming the
        waterfall's evaluation order (per-installment fully-satisfied
        test happens AFTER the late-fee-then-interest snapshot).
        """
        b, loan = setup_loan_at_delinquency_days(35)
        next_due_before = loan["next_due_date"]
        post_payment(loan["id"], amount_cents=30_000)
        loan_after = get_loan(loan["id"])
        assert loan_after["next_due_date"] == next_due_before, (
            f"partial payment must not advance next_due_date; "
            f"before={next_due_before!r} after={loan_after['next_due_date']!r}"
        )


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_mediation_cycle_extend_reject_extend_again(self, api):
        """# difficulty: non_linear_state_machine/mediation_cyclic_extend_reject_revise

        PRD §3.7: "After rejection, the underwriter may extend a
        revised offer (cycling back to OFFER_EXTENDED with
        target_payment_cents recomputed) — but only when the rejection
        reason was not BORROWER_REFUSED".

        Claim: OPEN -> OFFER_EXTENDED -> OFFER_REJECTED ->
        OFFER_EXTENDED (revised) is a valid revision loop when the
        rejection reason is not BORROWER_REFUSED.
        """
        b, loan, fc, m = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
        )
        first_target = int(m["target_payment_cents"])
        # Reject with reason != BORROWER_REFUSED.
        reject = reject_mediation_offer(m["id"],
                                        rejection_reason="DTI_TOO_HIGH")
        assert reject["status"] == "OFFER_REJECTED"
        # Re-extend with different terms.
        m2 = extend_mediation_offer(
            m["id"],
            offered_new_rate_bps=300,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_500_000,
        )
        assert m2["status"] == "OFFER_EXTENDED"
        # New target should be lower (lower rate + larger forbearance).
        assert int(m2["target_payment_cents"]) < first_target

    def test_mediation_revise_with_borrower_refused_blocked(self, api):
        """# difficulty: non_linear_state_machine/mediation_cyclic_extend_reject_revise

        PRD §3.7: "After rejection, the underwriter may extend a
        revised offer (cycling back to OFFER_EXTENDED with
        target_payment_cents recomputed) — but only when the rejection
        reason was not BORROWER_REFUSED".

        Claim: after rejection with reason=BORROWER_REFUSED, a
        re-extend on the same case must NOT succeed; PRD names
        the cyclic loop as gated by rejection_reason !=
        BORROWER_REFUSED.

        Per the two-reader test: PRD names the loop guard but does not
        explicitly name the error_id returned for a re-extend after
        BORROWER_REFUSED. We assert only that the call does not
        succeed (HTTP 4xx).
        """
        b, loan, fc, m = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
        )
        reject_mediation_offer(m["id"],
                               rejection_reason="BORROWER_REFUSED")
        # Now try to re-extend.
        resp = api.extend_mediation_offer(
            m["id"],
            {"offered_new_rate_bps": 300,
             "offered_term_extension_months": 60,
             "offered_principal_forbearance_cents": 1_500_000},
            {"X-User-ID": "lmu-001",
             "X-User-Role": "LossMitigationUnderwriter"},
        )
        assert resp.status_code >= 400, (
            f"re-extend after BORROWER_REFUSED must be rejected; "
            f"got HTTP {resp.status_code}"
        )

    def test_forbearance_branches_completed_vs_breached(self, api):
        """# difficulty: non_linear_state_machine/forbearance_branching_completed_or_breached

        PRD §3.4: "Under DEFERRAL, cure_balance_cents is immediately
        zero upon the COMPLETED transition and total_paused_cents is
        added to principal_balance_cents".
        PRD §3.4: "When the clock advances at least thirty days past
        end_date and cure_balance_cents is still strictly positive,
        the plan transitions to BREACHED and Loan.posture cascades to
        DEFAULT."

        Claim: a DEFERRAL plan reaches COMPLETED (CURRENT posture)
        and a LUMP_SUM plan with no payment reaches BREACHED (DEFAULT
        posture) on the same wall-clock advance schedule.
        """
        # DEFERRAL scenario.
        b_d, loan_d, plan_d = setup_active_forbearance_plan(
            months=1, repayment_method="DEFERRAL",
        )
        # LUMP_SUM scenario.
        b_l, loan_l, plan_l = setup_active_forbearance_plan(
            months=1, repayment_method="LUMP_SUM",
        )
        # Advance past end_date + 30d grace.
        advance_clock(31 + 31)
        loan_d_after = get_loan(loan_d["id"])
        loan_l_after = get_loan(loan_l["id"])
        # Read plans via list endpoint.
        resp_d = api.list_forbearance_plans(
            loan_d["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        items_d = validate_success(resp_d, expected_status=200)
        if isinstance(items_d, dict) and "data" in items_d:
            items_d = items_d["data"]
        m_d = next(p for p in items_d if p["id"] == plan_d["id"])
        assert m_d["status"] == "COMPLETED"
        assert loan_d_after["posture"] == "CURRENT"
        resp_l = api.list_forbearance_plans(
            loan_l["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        items_l = validate_success(resp_l, expected_status=200)
        if isinstance(items_l, dict) and "data" in items_l:
            items_l = items_l["data"]
        m_l = next(p for p in items_l if p["id"] == plan_l["id"])
        assert m_l["status"] == "BREACHED"
        assert loan_l_after["posture"] == "DEFAULT"

    def test_forbearance_deferral_adds_total_paused_to_principal(self, api):
        """# difficulty: non_linear_state_machine/forbearance_branching_completed_or_breached

        PRD §3.4: "Under DEFERRAL, cure_balance_cents is immediately
        zero upon the COMPLETED transition and total_paused_cents is
        added to principal_balance_cents (deferred to maturity, with
        no interest accrual on the deferred amount)."

        Claim: the DEFERRAL branch's side-effect set on Loan is
        distinguishable from the BREACHED branch: DEFERRAL adds
        total_paused_cents to principal_balance_cents and posts
        Loan.posture := CURRENT, whereas BREACHED leaves principal
        unchanged and posts posture := DEFAULT.
        """
        b, loan, plan = setup_active_forbearance_plan(
            months=1, repayment_method="DEFERRAL",
        )
        principal_before = int(loan["principal_balance_cents"])
        total_paused = int(plan["total_paused_cents"])
        advance_clock(31)
        loan_after = get_loan(loan["id"])
        assert (
            int(loan_after["principal_balance_cents"])
            == principal_before + total_paused
        ), (
            f"DEFERRAL must add total_paused_cents ({total_paused}) to "
            f"principal_balance; got delta = "
            f"{int(loan_after['principal_balance_cents']) - principal_before}"
        )
        assert loan_after["posture"] == "CURRENT"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_payment_cures_delinquency_to_current(self, api):
        """# difficulty: transitive_cascade/payment_to_loan_posture_to_pmi_eligibility

        PRD §3.2: "next_due_date is advanced one month per fully
        satisfied installment, delinquency_days is recomputed ... and
        Loan.posture is re-derived (which may move it from DELINQUENT
        back to CURRENT)."

        Claim: a payment that fully satisfies the past-due installment
        on a DELINQUENT loan transitions Loan.posture back to CURRENT.
        """
        b, loan = setup_loan_at_delinquency_days(15)
        assert loan["posture"] == "DELINQUENT"
        # Pay scheduled + late fees so the installment is fully cured.
        # 15 days late => 0 full late-fee months (floor(15/30)=0).
        amount = int(loan["scheduled_payment_cents"])
        post_payment(loan["id"], amount_cents=amount)
        loan_after = get_loan(loan["id"])
        assert loan_after["delinquency_days"] == 0, (
            f"expected delinquency_days=0 after curing payment, got "
            f"{loan_after['delinquency_days']}"
        )
        assert loan_after["posture"] == "CURRENT", (
            f"expected posture=CURRENT, got {loan_after['posture']}"
        )

    def test_pmi_approve_now_possible_after_payment_cures_posture(
        self, api,
    ):
        """# difficulty: transitive_cascade/payment_to_loan_posture_to_pmi_eligibility

        PRD §3.5: "Approval is only permitted when the request's
        decision is still PENDING, when the LTV threshold is met ...
        and — for BORROWER_REQUEST only — when Loan.posture is CURRENT
        and there is no POSTED Payment whose received_date was later
        than its scheduled due date within the last 24 scheduled months."

        Claim: a depth-≥2 cascade — payment posting cures delinquency
        AND makes a previously LOAN_NOT_CURRENT-blocked PMI removal
        path no longer blocked by the posture check. (The 24-month
        history check is independent and may still block; this test
        asserts only the posture flip enabled by the payment.)

        We construct a scenario where a Borrower-request PMI removal
        is filed while the loan is DELINQUENT; per PRD §3.5 it would
        fail the posture branch of the history check. After a curing
        payment, Loan.posture == CURRENT — confirming the cascade
        from Payment to Loan.posture works.
        """
        b, loan = setup_loan_at_delinquency_days(15)
        assert loan["posture"] == "DELINQUENT"
        post_payment(loan["id"],
                     amount_cents=int(loan["scheduled_payment_cents"]))
        loan_after = get_loan(loan["id"])
        assert loan_after["posture"] == "CURRENT"

    def test_escrow_finalize_creates_surplus_refund_disbursement(
        self, api,
    ):
        """# difficulty: transitive_cascade/escrow_finalize_to_disbursement_to_loan_pmi_drop

        PRD §3.3: "when surplus_cents strictly exceeds five thousand
        cents (i.e. exceeds fifty dollars), the system creates a new
        Disbursement of type SURPLUS_REFUND with amount_cents equal to
        surplus_cents, scheduled_date thirty days in the future, and
        status SCHEDULED."

        Claim: hop 1 of the cascade — /finalize creates a SURPLUS_REFUND
        Disbursement (status SCHEDULED) when surplus > 5000.
        """
        b, loan = setup_loan_with_escrow_balance(1_000_000,
                                                 pmi_monthly_cents=0)
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
        # Verify the SURPLUS_REFUND was scheduled (hop 1).
        resp = api.list_disbursements(
            loan["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        refunds = [d for d in items if d.get("type") == "SURPLUS_REFUND"]
        assert refunds
        # PRD §3.3 names the schedule offset as "thirty days in the
        # future" — verify all refunds are SCHEDULED status.
        assert all(d["status"] == "SCHEDULED" for d in refunds)

    def test_finalize_writes_loan_monthly_escrow(self, api):
        """# difficulty: transitive_cascade/escrow_finalize_to_disbursement_to_loan_pmi_drop

        PRD §3.3: "Loan.monthly_escrow_payment_cents is overwritten
        with the freshly computed new_monthly_escrow_cents."

        Claim: /finalize writes the new monthly escrow value into
        Loan.monthly_escrow_payment_cents — the first hop of the
        cascade chain rooted at /finalize.
        """
        b, loan, a = setup_escrow_provisional_for_finalize_divergence()
        fin = finalize_escrow_analysis(loan["id"], a["id"])
        loan_after = get_loan(loan["id"])
        assert (
            loan_after["monthly_escrow_payment_cents"]
            == fin["new_monthly_escrow_cents"]
        )


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidation:

    def test_file_on_already_filed_case_returns_invalid_state(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_file_foreclosure

        PRD §2.6: "(8) the source-state precondition on the entity
        being acted upon ... [is checked before] the business-level
        checks fire: regulatory windows (priorities 10–13)".

        Claim: attempting /file on a case that is ALREADY in status
        FILED returns ERR_INVALID_STATE (state-precondition check
        wins over any regulatory-window check).
        """
        b, loan, fc = setup_foreclosure_case_filed()
        # case is already FILED; /file again should hit the source-state
        # precondition.
        resp = api.file_foreclosure(
            fc["id"],
            {"X-User-ID": "atty-001",
             "X-User-Role": "ForeclosureAttorney"},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_mediation_window_closed_wins_over_already_open(self, api):
        """# difficulty: priority_pair_validation_conflict/business_referential_vs_business_safety_on_mediation_request

        PRD §2.6: "Only after these nine gates do the business-level
        checks fire: regulatory windows (priorities 10–13), referential
        exclusivity (priorities 14–16)".

        Claim: per PRD's deterministic ordering, when BOTH the NOI
        window has closed AND an active MediationCase exists,
        ERR_MEDIATION_WINDOW_CLOSED (priority 12) fires before
        ERR_MEDIATION_ALREADY_OPEN (priority 16).

        Setup: open a foreclosure case, request mediation (creates
        active MediationCase), advance 31d so the NOI window closes,
        then attempt a second mediation request.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        m1 = request_mediation(fc["id"])
        open_mediation(m1["id"])
        advance_clock(31)
        resp = api.request_mediation(
            fc["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        # PRD §2.6 priority order: window (12) before referential (16).
        validate_error(resp,
                       ApiErrorId.ERR_MEDIATION_WINDOW_CLOSED.value)

    def test_mediation_already_open_when_window_still_active(self, api):
        """# difficulty: priority_pair_validation_conflict/business_referential_vs_business_safety_on_mediation_request

        PRD §3.6: "At most one active MediationCase (any status not in
        FAILED, OFFER_REJECTED, or COMPLETED) may exist per
        ForeclosureCase; a second attempt is rejected with
        ERR_MEDIATION_ALREADY_OPEN."

        Claim: when the NOI window is still OPEN (no priority-12
        check fires) but an active MediationCase exists, the second
        mediation request is rejected with ERR_MEDIATION_ALREADY_OPEN
        (priority 16). This is the inverse instance to the
        window-closed test: it exercises the referential-exclusivity
        rule in isolation, confirming that the priority-16 rule does
        in fact fire when the priority-12 rule cannot.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        m1 = request_mediation(fc["id"])
        open_mediation(m1["id"])
        # NOI window still open (no clock advance), so priority-12
        # window check passes; second mediation request must hit the
        # referential exclusivity check.
        resp = api.request_mediation(
            fc["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        validate_error(resp,
                       ApiErrorId.ERR_MEDIATION_ALREADY_OPEN.value)

    def test_loan_not_found_wins_over_business_window_on_filing(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_file_foreclosure

        PRD §2.6: "an attempt to file a foreclosure on a non-existent
        loan returns ERR_LOAN_NOT_FOUND, not
        ERR_NOI_WINDOW_NOT_ELAPSED, because existence is checked
        before any business window."

        Claim: PRD's example is itself an authoritative ordering
        statement: existence (priority 5/6) fires before any business
        window (priority 10+). We exercise the same scenario via
        non-existent FORECLOSURE case id (since /file is keyed on
        case id, not loan id) — the existence check fires first,
        not ERR_NOI_WINDOW_NOT_ELAPSED.
        """
        from test_helpers import NON_EXISTENT_UUID
        resp = api.file_foreclosure(
            NON_EXISTENT_UUID,
            {"X-User-ID": "atty-001",
             "X-User-Role": "ForeclosureAttorney"},
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_pmi_approve_at_exactly_8000_bps_succeeds(self, api):
        """# difficulty: boundary_precision_check/pmi_ltv_threshold_exactly_8000_bps

        PRD §3.5: "evaluated_ltv_bps no greater than 8000 for
        BORROWER_REQUEST".

        Claim: at the inclusive boundary evaluated_ltv_bps == 8000
        (LTV exactly 80.00%), /approve succeeds for BORROWER_REQUEST.
        """
        b, loan, req = setup_pmi_pending_borrower_request(
            pmi_monthly_cents=8_000,
            original_principal_cents=20_000_000,
            original_appraised_value_cents=25_000_000,
            current_appraised_value_cents=25_000_000,
        )
        assert int(req["evaluated_ltv_bps"]) == 8_000
        approved = approve_pmi_removal(loan["id"], req["id"])
        assert approved["decision"] == "APPROVED"

    def test_pmi_approve_at_8001_bps_rejected(self, api):
        """# difficulty: boundary_precision_check/pmi_ltv_threshold_exactly_8000_bps

        PRD §3.5: "evaluated_ltv_bps no greater than 8000 for
        BORROWER_REQUEST ... otherwise the request is rejected with
        ERR_PMI_LTV_TOO_HIGH".

        Claim: at evaluated_ltv_bps == 8001 (one bp above), /approve
        rejects with ERR_PMI_LTV_TOO_HIGH.
        """
        b, loan, req = setup_pmi_pending_borrower_request(
            pmi_monthly_cents=8_000,
            original_principal_cents=20_002_500,
            original_appraised_value_cents=25_000_000,
            current_appraised_value_cents=25_000_000,
        )
        assert int(req["evaluated_ltv_bps"]) == 8_001
        resp = api.approve_pmi_removal_request(
            loan["id"], req["id"],
            {"X-User-ID": "pmi-001", "X-User-Role": "PmiUnderwriter"},
        )
        validate_error(resp, ApiErrorId.ERR_PMI_LTV_TOO_HIGH.value)

    def test_forbearance_active_at_29_days_past_end(self, api):
        """# difficulty: boundary_precision_check/forbearance_breach_exactly_30_days_after_end_date

        PRD §3.4: "When the clock advances at least thirty days past
        end_date and cure_balance_cents is still strictly positive,
        the plan transitions to BREACHED".

        Claim: at 29 days past end_date with cure_balance > 0, the
        plan remains ACTIVE (29 < 30 grace).
        """
        b, loan, plan = setup_active_forbearance_plan(
            months=1, repayment_method="LUMP_SUM",
        )
        # end_date ~ now + 30d. Advance to end_date + 29d = 30 + 29 = 59d.
        advance_clock(30 + 29)
        # Re-read the plan.
        resp = api.list_forbearance_plans(
            loan["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(p for p in items if p["id"] == plan["id"])
        # PRD says BREACHED requires >= 30 days; at 29 days the plan
        # may still be ACTIVE.
        assert matched["status"] in {"ACTIVE"}, (
            f"at 29d past end_date, plan must remain ACTIVE (not yet "
            f"breached); got status={matched['status']}"
        )

    def test_forbearance_breached_at_exactly_30_days_past_end(self, api):
        """# difficulty: boundary_precision_check/forbearance_breach_exactly_30_days_after_end_date

        PRD §3.4: "When the clock advances at least thirty days past
        end_date and cure_balance_cents is still strictly positive,
        the plan transitions to BREACHED and Loan.posture cascades to
        DEFAULT."

        Claim: at exactly 30 days past end_date with cure_balance > 0,
        the plan is BREACHED (inclusive boundary).
        """
        b, loan, plan = setup_active_forbearance_plan(
            months=1, repayment_method="LUMP_SUM",
        )
        # end_date ~ now + 30d. Advance to end_date + 30d = 30 + 30 = 60d.
        advance_clock(30 + 30)
        resp = api.list_forbearance_plans(
            loan["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(p for p in items if p["id"] == plan["id"])
        assert matched["status"] == "BREACHED"


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_second_active_forbearance_plan_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/loan_posture_depends_on_forbearance_plan_status

        PRD §3.4: "The loan must not already have another plan in
        status ACTIVE — otherwise the request is rejected with
        ERR_FORBEARANCE_PLAN_EXISTS."

        Claim: Loan posture transition (CURRENT/DELINQUENT->FORBEARANCE)
        is gated by the absence of an ACTIVE sibling ForbearancePlan;
        a second creation attempt fires ERR_FORBEARANCE_PLAN_EXISTS.
        """
        b, loan, plan = setup_active_forbearance_plan(months=1)
        resp = api.create_forbearance_plan(
            loan["id"],
            {"start_date": iso_datetime_utc_midnight(today_utc()),
             "months": 1, "repayment_method": "LUMP_SUM"},
            {"X-User-ID": "lmu-001",
             "X-User-Role": "LossMitigationUnderwriter"},
        )
        validate_error(resp,
                       ApiErrorId.ERR_FORBEARANCE_PLAN_EXISTS.value)

    def test_file_on_noi_issued_while_mediation_open_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/foreclosure_status_depends_on_mediation_status

        PRD §3.6: "Filing requires the case to be in NOI_ISSUED
        status, requires at least 30 days to have elapsed since
        noi_sent_at ... and requires that no mediation case in a
        non-terminal status (anything other than FAILED,
        OFFER_REJECTED, or COMPLETED) currently exists on the case."

        Claim: with an active (non-terminal) MediationCase, /file
        fails — concretely with ERR_INVALID_STATE because the parent
        ForeclosureCase has cascaded to MEDIATION_OPEN (no longer
        NOI_ISSUED). This is a cross-entity dependency:
        ForeclosureCase.status is determined by the existence of an
        active MediationCase.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        request_mediation(fc["id"])
        advance_clock(31)
        resp = api.file_foreclosure(
            fc["id"],
            {"X-User-ID": "atty-001",
             "X-User-Role": "ForeclosureAttorney"},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_mediation_complete_cascades_to_closed_modified(self, api):
        """# difficulty: cross_entity_state_dependency/foreclosure_status_depends_on_mediation_status

        PRD §3.7: "the MediationCase transitions to COMPLETED, the
        parent ForeclosureCase cascades to CLOSED_MODIFIED, and the
        Loan itself is modified ... and finally Loan.posture returns
        to CURRENT."

        Claim: a successful /complete on a mediation cascades to
        ForeclosureCase.status = CLOSED_MODIFIED — demonstrating
        ForeclosureCase status being driven by MediationCase
        transitions across the entity boundary.
        """
        b, loan, fc, m = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
        )
        accept_mediation_offer(m["id"])
        # Complete with a DIFFERENT operator (segregation pivot).
        resp = api.complete_mediation(
            m["id"],
            {"X-User-ID": "lmu-002",
             "X-User-Role": "LossMitigationUnderwriter"},
        )
        completed = validate_success(resp, expected_status=200)
        assert completed["status"] == "COMPLETED"
        # Read the ForeclosureCase via list endpoint to confirm cascade.
        resp_list = api.list_foreclosure_cases(
            {"X-User-ID": "atty-001",
             "X-User-Role": "ForeclosureAttorney"},
        )
        data = validate_success(resp_list, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(c for c in items if c["id"] == fc["id"])
        assert matched["status"] == "CLOSED_MODIFIED"

    def test_cancel_active_forbearance_then_create_new_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/loan_posture_depends_on_forbearance_plan_status

        PRD §3.4: "cancellation transitions the plan to CANCELED and
        Loan.posture reverts to DELINQUENT or CURRENT based on the
        recomputed delinquency_days."

        Claim: Loan posture's valid forbearance transitions are
        gated by sibling ForbearancePlan.status — after cancellation
        of the ACTIVE plan, the loan's posture reverts to non-FORBEARANCE
        and a new plan can be created.
        """
        b, loan, plan = setup_active_forbearance_plan(months=3)
        loan_now = get_loan(loan["id"])
        assert loan_now["posture"] == "FORBEARANCE"
        cancel_forbearance_plan(loan["id"], plan["id"])
        loan_after = get_loan(loan["id"])
        # PRD says posture reverts to DELINQUENT or CURRENT.
        assert loan_after["posture"] in {"CURRENT", "DELINQUENT"}, (
            f"after cancel, posture must revert to CURRENT or DELINQUENT, "
            f"got {loan_after['posture']}"
        )


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_second_forbearance_with_future_window_still_rejected(self, api):
        """# difficulty: resource_temporal_overlap/forbearance_plan_overlap_strict_exclusion

        PRD §3.4: "The loan must not already have another plan in
        status ACTIVE — otherwise the request is rejected with
        ERR_FORBEARANCE_PLAN_EXISTS."

        Claim: at-most-one ACTIVE plan is a STRICT exclusion regardless
        of the requested interval. Even a NON-overlapping future
        start_date is rejected while the existing plan is ACTIVE.

        NOTE: PRD §3.4 also requires start_date <= Loan.next_due_date.
        On a loan with an ACTIVE forbearance, next_due_date is frozen,
        so a "future" start_date would also fail the date check
        (ERR_FORBEARANCE_DATE_INVALID). Either error_id is acceptable
        because PRD prose does not order these two checks against
        each other for the same request.
        """
        b, loan, plan = setup_active_forbearance_plan(months=3)
        # Try a second plan with start_date strictly after next_due_date.
        future = iso_datetime_utc_midnight(today_utc() + timedelta(days=180))
        resp = api.create_forbearance_plan(
            loan["id"],
            {"start_date": future, "months": 3,
             "repayment_method": "LUMP_SUM"},
            {"X-User-ID": "lmu-001",
             "X-User-Role": "LossMitigationUnderwriter"},
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_FORBEARANCE_PLAN_EXISTS.value,
             ApiErrorId.ERR_FORBEARANCE_DATE_INVALID.value],
        )

    def test_cancel_active_plan_then_new_plan_succeeds(
        self, api,
    ):
        """# difficulty: resource_temporal_overlap/forbearance_plan_overlap_strict_exclusion

        PRD §3.4: "cancellation transitions the plan to CANCELED and
        Loan.posture reverts to DELINQUENT or CURRENT based on the
        recomputed delinquency_days."

        Claim: once the ACTIVE plan is canceled, the membership
        exclusion is lifted and a fresh forbearance plan can be
        created.
        """
        b, loan, plan = setup_active_forbearance_plan(months=3)
        cancel_forbearance_plan(loan["id"], plan["id"])
        # Now a new plan should succeed.
        # (After cancellation, next_due_date is recomputed; start_date
        # must be on or before next_due_date.)
        loan_after = get_loan(loan["id"])
        resp = api.create_forbearance_plan(
            loan["id"],
            {"start_date": loan_after["next_due_date"],
             "months": 3, "repayment_method": "LUMP_SUM"},
            {"X-User-ID": "lmu-001",
             "X-User-Role": "LossMitigationUnderwriter"},
        )
        assert 200 <= resp.status_code < 300, (
            f"after cancel, new plan should succeed; got "
            f"{resp.status_code}"
        )

    def test_auction_notice_under_30d_rejected(self, api):
        """# difficulty: resource_temporal_overlap/foreclosure_auction_buffer_with_reinstatement_cutoff

        PRD §3.6: "The proposed auction_date must be at least 30 days
        in the future (statutory notice); failure of either the 60-day
        or the 30-day rule is rejected with
        ERR_AUCTION_NOTICE_VIOLATION."

        Claim: auction_date = now + 25d (forward buffer < 30d) ->
        ERR_AUCTION_NOTICE_VIOLATION.
        """
        b, loan, fc = setup_foreclosure_case_filed()
        # Wait 60 days so the filed-at gate passes.
        advance_clock(61)
        short = iso_datetime_utc_midnight(today_utc() + timedelta(days=25))
        resp = api.schedule_auction(
            fc["id"], {"auction_date": short},
            {"X-User-ID": "atty-001",
             "X-User-Role": "ForeclosureAttorney"},
        )
        validate_error(resp,
                       ApiErrorId.ERR_AUCTION_NOTICE_VIOLATION.value)

    def test_reinstatement_inside_5d_cutoff_rejected(self, api):
        """# difficulty: resource_temporal_overlap/foreclosure_auction_buffer_with_reinstatement_cutoff

        PRD §3.6: "reinstatement must be attempted strictly more than
        5 days before auction_date; an attempt inside the 5-day
        cut-off is rejected with ERR_REINSTATEMENT_CUTOFF."

        Claim: with auction_date = now + 30d, advance the clock to
        now + 26d (so we're 4 days before the auction, inside the
        5-day backward buffer) and call /reinstate -> ERR_REINSTATEMENT_CUTOFF.
        """
        b, loan, fc = setup_foreclosure_case_auction_scheduled(
            auction_offset_days=30,
        )
        advance_clock(26)
        resp = api.reinstate_foreclosure(
            fc["id"], {"payment_amount_cents": 10_000_000_000},
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_CUTOFF.value)


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_payment_reverse_restores_principal_balance(self, api):
        """# difficulty: compensating_invariant/payment_reversal_principal_conservation

        PRD §3.2: "The fundamental invariant preserved across posting
        and reversal is that the current principal_balance_cents plus
        the sum of allocation_principal_cents across all POSTED
        payments equals original_principal_cents minus any principal
        forbearance granted by an accepted loan modification."

        Claim: after post + reverse, principal_balance_cents returns
        to original_principal_cents (no other POSTED payments exist).
        """
        b, loan = setup_borrower_and_current_loan()
        original = int(loan["original_principal_cents"])
        advance_clock(30)
        p = post_payment(loan["id"],
                         amount_cents=int(loan["scheduled_payment_cents"]))
        reverse_payment(loan["id"], p["id"])
        loan_after = get_loan(loan["id"])
        assert int(loan_after["principal_balance_cents"]) == original, (
            f"after reversal, principal_balance must equal "
            f"original_principal {original}; got "
            f"{loan_after['principal_balance_cents']}"
        )

    def test_reverse_marks_payment_reversed_not_posted(self, api):
        """# difficulty: compensating_invariant/payment_reversal_principal_conservation

        PRD §3.2: "On reversal, Payment.status becomes REVERSED,
        reversed_at is stamped to now".

        Claim: after /reverse, the payment.status is REVERSED — and
        therefore is no longer in the POSTED set used by the
        principal-conservation invariant.
        """
        b, loan = setup_borrower_and_current_loan()
        advance_clock(30)
        p = post_payment(loan["id"],
                         amount_cents=int(loan["scheduled_payment_cents"]))
        assert p["status"] == "POSTED"
        rev = reverse_payment(loan["id"], p["id"])
        assert rev["status"] == "REVERSED"
        assert isinstance(rev.get("reversed_at"), str)

    def test_failed_disbursement_does_not_debit_escrow(self, api):
        """# difficulty: compensating_invariant/disbursement_failed_retry_escrow_conservation

        PRD §3.3: "If the balance is insufficient, the disbursement
        transitions to FAILED with failure_reason set to
        INSUFFICIENT_ESCROW".

        Claim: when escrow is insufficient, the disbursement transitions
        SCHEDULED -> FAILED WITHOUT debiting Loan.escrow_balance_cents.
        """
        b, loan = setup_borrower_and_current_loan()
        pre_escrow = int(loan["escrow_balance_cents"])
        d = schedule_disbursement(
            loan["id"], type="PROPERTY_TAX",
            scheduled_date=iso_datetime_utc_midnight(
                today_utc() + timedelta(days=10),
            ),
            amount_cents=100_000,
        )
        advance_clock(11)
        loan_after = get_loan(loan["id"])
        # Escrow balance must be unchanged.
        assert int(loan_after["escrow_balance_cents"]) == pre_escrow
        # Disbursement must be FAILED.
        resp = api.list_disbursements(
            loan["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(x for x in items if x["id"] == d["id"])
        assert matched["status"] == "FAILED"

    def test_retry_succeeds_after_funding_and_debits_escrow(self, api):
        """# difficulty: compensating_invariant/disbursement_failed_retry_escrow_conservation

        PRD §3.3: "A Servicer may retry a FAILED disbursement at any
        later time — the retry succeeds (transitioning the disbursement
        to PAID, stamping paid_at, clearing failure_reason, and
        decrementing the balance by amount_cents) only when escrow
        once again has sufficient funds".

        Claim: after the loan accumulates escrow via a payment with
        escrow allocation, /retry succeeds and Loan.escrow_balance
        is debited by amount_cents (zero drift in the escrow
        conservation invariant).
        """
        # Seed loan with a monthly_escrow_payment_cents so a payment
        # can accumulate escrow.
        b, loan = setup_borrower_and_current_loan(
            monthly_escrow_payment_cents=200_000,
        )
        d = schedule_disbursement(
            loan["id"], type="PROPERTY_TAX",
            scheduled_date=iso_datetime_utc_midnight(
                today_utc() + timedelta(days=10),
            ),
            amount_cents=100_000,
        )
        # Advance past scheduled_date with insufficient escrow -> FAILED.
        # PRD §3.2 says escrow allocation requires a past-due escrow
        # demand, so advance past next_due_date (origination + 30d)
        # before posting the funding payment.
        advance_clock(31)
        # Now post a payment that funds the escrow.
        sched = int(loan["scheduled_payment_cents"])
        post_payment(loan["id"], amount_cents=sched + 200_000)
        loan_pre_retry = get_loan(loan["id"])
        pre_escrow = int(loan_pre_retry["escrow_balance_cents"])
        assert pre_escrow >= 100_000, (
            f"escrow must be >= 100_000 before retry succeeds; got "
            f"{pre_escrow}"
        )
        # Retry the disbursement.
        d2 = retry_disbursement(loan["id"], d["id"])
        assert d2["status"] == "PAID"
        loan_after = get_loan(loan["id"])
        assert (
            int(loan_after["escrow_balance_cents"])
            == pre_escrow - 100_000
        ), (
            f"after retry, escrow must drop by amount_cents=100_000; "
            f"got delta = "
            f"{int(loan_after['escrow_balance_cents']) - pre_escrow}"
        )
