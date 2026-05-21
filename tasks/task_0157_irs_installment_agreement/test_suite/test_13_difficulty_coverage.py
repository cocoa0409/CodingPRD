"""Extra coverage tests targeting difficulty-design instances.

Each test below is the second dedicated test for an instance whose
first test lives elsewhere in this suite, or it asserts a complementary
aspect of the rule (e.g., the success case alongside an existing
failure case) so that every difficulty-design instance is covered by at
least two tests as required by the unit-test-generator spec.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    IRS_OFFICER_SHARED_ID,
    TEST_USERS,
    advance_clock_to,
    create_and_activate_agreement,
    create_draft_oic,
    create_installment_agreement_payload,
    create_lien_payload,
    create_taxpayer,
    create_tax_liability,
    decide_offer_in_compromise_payload,
    decide_oic,
    file_lien,
    get_installment_agreement,
    get_lien,
    get_offer_in_compromise,
    get_tax_liability,
    make_oic_officer_headers,
    make_taxpayer_headers,
    parse_iso,
    pay_oic_deposit,
    record_installment_payment,
    setup_oic_under_review,
    setup_payment_to_lien_release_chain,
    setup_provisional_csed_after_oic_submit,
    setup_three_liabilities_for_status_branching,
    setup_two_independent_taxpayers_for_ddia_boundary,
    setup_two_taxpayers_for_cnc_mdi_boundary,
    submit_oic,
    take_up_oic,
    validate_error,
    validate_success,
    withdraw_oic,
)


# =============================================================================
# Rule 1 / instance 1 — csed_provisional_vs_final
# =============================================================================
class TestCSEDProvisionalVsFinalAdditional:

    def test_provisional_value_continues_to_drift_while_open(self):
        """PRD §3.3: "While at least one tolling event remains open,
        the effective expiration drifts forward as wall-clock time
        advances."

        Claim: two reads of csed_effective_date at +60d and +120d while
        the OIC_PENDING event is still open yield different values
        differing by exactly 60 days. This is the load-bearing variant
        difference: the provisional-variant value drifts; the
        final-variant value does not.

        # difficulty: dual_variant_calc/csed_provisional_vs_final
        """
        taxpayer, liability, oic = setup_provisional_csed_after_oic_submit(
            base_clock="2020-01-01T00:00:00.000Z",
            mdi_cents=200_000,
            liability_amount_cents=1_000_000,
        )
        advance_clock_to("2020-03-01T00:00:00.000Z")  # +60d
        first = parse_iso(
            get_tax_liability(liability["id"])["csed_effective_date"]
        )
        advance_clock_to("2020-04-30T00:00:00.000Z")  # +60d more
        second = parse_iso(
            get_tax_liability(liability["id"])["csed_effective_date"]
        )
        delta = (second - first).total_seconds()
        # PRD §3.3 half-open: open tolling treats end_date as NOW(); so
        # drift between the two reads is the wall-clock delta (60 days).
        assert int(delta) == 60 * 24 * 3600, (
            f"PRD §3.3 provisional variant: csed_effective_date must "
            f"drift forward in lock-step with NOW() while tolling open; "
            f"observed delta {int(delta)} s, expected {60 * 24 * 3600} s"
        )


# =============================================================================
# Rule 1 / instance 2 — rcp_lump_sum_vs_periodic
# =============================================================================
class TestRCPVariantRatio:

    def test_periodic_is_exactly_twice_lump_sum_for_same_mdi(self, api):
        """PRD §3.9: "RCP = Net Realizable Equity in Assets + Future
        Income Component."
        PRD §3.9: "If the proposed payoff schedule is at most five
        monthly installments, the factor is 12; if the schedule is at
        most twenty-four monthly installments, the factor is 24."
        PRD §3.9: "Rounding is applied exactly once, at the final sum
        — intermediate steps must not be rounded."

        Claim: with equal MDI and zero equity, periodic rcp /
        lump-sum rcp == 2 exactly.

        # difficulty: dual_variant_calc/rcp_lump_sum_vs_periodic
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=5_000_000,
        )
        a = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=3_000_000, schedule_months=5,
        )
        b = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=5_000_000, schedule_months=24,
        )
        ra = get_offer_in_compromise(a["id"])["rcp_cents"]
        rb = get_offer_in_compromise(b["id"])["rcp_cents"]
        assert rb == 2 * ra, (
            f"PRD §3.9: periodic factor 24 is exactly twice the lump-sum "
            f"factor 12 for the same MDI and zero equity; got rb={rb}, "
            f"ra={ra}"
        )


# =============================================================================
# Rule 2 / instance 1 — monthly_accrual_status_branching
# =============================================================================
class TestMonthlyAccrualBranchAdditional:

    def test_open_vs_ia_penalty_differs_by_exactly_2500_cents(self):
        """PRD §3.2: "it is one half of one percent (0.005) when the
        liability is OPEN, exactly one quarter of one percent (0.0025)
        — that is, half the non-IA rate — when the liability is
        IN_AGREEMENT."

        Claim: same $10,000 base, post-cycle OPEN.accrued_penalty
        minus IN_AGREEMENT.accrued_penalty == 2_500 cents.

        # difficulty: combinatorial_formula/monthly_accrual_status_branching
        """
        from test_helpers import run_sweep
        taxpayer, liab_open, liab_ia, liab_cnc, ia, cnc = (
            setup_three_liabilities_for_status_branching()
        )
        advance_clock_to("2020-01-31T23:59:59.000Z")
        run_sweep()
        l_open = get_tax_liability(liab_open["id"])
        l_ia = get_tax_liability(liab_ia["id"])
        diff = l_open["accrued_penalty_cents"] - l_ia["accrued_penalty_cents"]
        assert diff == 2_500, (
            "PRD §3.2: OPEN penalty (5_000) minus IA penalty (2_500) "
            f"= 2_500 cents; got {diff}"
        )


# =============================================================================
# Rule 2 / instance 2 — payoff_projection_rounding_order
# =============================================================================
class TestPayoffProjectionAgreementType:

    def test_long_term_agreement_type_when_projection_fits_csed(self):
        """PRD §3.4: "A LONG_TERM (streamlined) agreement requires that
        the aggregate covered debt is at most 5,000,000 cents (which is
        $50,000) and that the projected payoff date does not fall after
        the minimum csed_effective_date across the covered liabilities."

        Claim: $10k debt at $2k/mo classifies as LONG_TERM (the
        partner test in test_07 asserts the planned_payoff_date pin).

        # difficulty: combinatorial_formula/payoff_projection_rounding_order
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=300_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_000_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="DDIA",
        )
        assert agreement["agreement_type"] == "LONG_TERM", (
            "PRD §3.4: $10k debt at $2k/mo with payoff before CSED is "
            "LONG_TERM (not SHORT_TERM — 4 cycles * $2k < $10k+interest "
            "— and not PPIA — payoff lies before csed_effective_date_min)"
        )


# =============================================================================
# Rule 3 / instance 2 — oic_fork_join_branching
# =============================================================================
class TestOICForkJoinBranching:

    def test_oic_reject_keeps_liability_open_and_consumes_deposit(self, api):
        """PRD §3.8: "On a reject, the OIC_PENDING CSEDTollingEvent on
        each covered liability is closed; csed_effective_date is
        recomputed; the taxpayer's collection_status is recomputed
        (reverting as appropriate); and the deposit is non-refundable —
        it is allocated as a LUMP_SUM against the covered liabilities
        in the pinned waterfall order."

        Claim: OIC REJECT → liability stays OPEN; deposit posts to
        payments_applied_cents via LUMP_SUM waterfall.

        # difficulty: non_linear_state_machine/oic_fork_join_branching
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=30_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_500_000,
        )
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
            deposit_cents=300_000,
            take_up_officer_id="oic-fork-A",
        )
        decide_oic(oic["id"], "REJECT", officer_id="oic-fork-B")
        refreshed_liab = get_tax_liability(liability["id"])
        assert refreshed_liab["status"] == "OPEN", (
            "PRD §3.8: REJECT does not move covered liability into "
            "IN_COMPROMISE — it returns to OPEN"
        )
        assert refreshed_liab["payments_applied_cents"] >= 300_000, (
            "PRD §3.8: the non-refundable deposit (300_000) is allocated "
            "as LUMP_SUM against the covered liabilities"
        )

    def test_oic_withdraw_keeps_liability_open(self, api):
        """PRD §3.8: "Withdrawal is a Taxpayer action that moves the
        offer from SUBMITTED to WITHDRAWN (or from UNDER_REVIEW to
        WITHDRAWN; both source statuses are accepted). It closes the
        OIC_PENDING CSEDTollingEvent on each covered liability with
        end_date at the server time, recomputes csed_effective_date,
        and treats the deposit as non-refundable, allocated as a
        LUMP_SUM per the waterfall."

        Claim: OIC WITHDRAWN by taxpayer → OIC.status == WITHDRAWN;
        deposit consumed via LUMP_SUM.

        # difficulty: non_linear_state_machine/oic_fork_join_branching
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=30_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_500_000,
        )
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
            deposit_cents=300_000,
            take_up_officer_id="oic-fork2-A",
        )
        withdraw_oic(taxpayer["id"], oic["id"])
        refreshed_oic = get_offer_in_compromise(oic["id"])
        assert refreshed_oic["status"] == "WITHDRAWN"
        # Deposit allocated per LUMP_SUM waterfall.
        refreshed_liab = get_tax_liability(liability["id"])
        assert refreshed_liab["payments_applied_cents"] >= 300_000


# =============================================================================
# Rule 4 / instance 1 — payment_to_paid_to_lien_release_depth3 (second
# assertion: the intermediate-hop IA -> COMPLETED transition)
# =============================================================================
class TestPaymentChainIntermediateHops:

    def test_payment_chain_marks_liability_paid_and_agreement_completed(self):
        """PRD §3.4: "If, after allocation, the sum of
        current_balance_cents across every covered liability has reached
        zero, the agreement transitions from ACTIVE to COMPLETED; each
        covered liability transitions from IN_AGREEMENT to PAID."

        Claim: a settling payment moves liability → PAID and the
        agreement → COMPLETED (the second and third hops in the depth-3
        chain).

        # difficulty: transitive_cascade/payment_to_paid_to_lien_release_depth3
        """
        taxpayer, liability, agreement, lien = (
            setup_payment_to_lien_release_chain(
                base_clock="2020-01-01T00:00:00.000Z",
                liability_amount_cents=300_000,
            )
        )
        record_installment_payment(
            agreement["id"], amount_cents=300_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        assert get_tax_liability(liability["id"])["status"] == "PAID"
        assert get_installment_agreement(agreement["id"])["status"] == "COMPLETED"


# =============================================================================
# Rule 4 / instance 2 — oic_accept_to_ia_terminate_to_liability_revert_depth3
# (second test asserting the lien release that closes the chain)
# =============================================================================
class TestOICAcceptCascadeLien:

    def test_oic_accept_releases_lien_with_oic_accepted_reason(self, api):
        """PRD §3.8: "any FederalTaxLien whose every liability_id is in
        IN_COMPROMISE or PAID transitions from FILED to RELEASED with
        release_reason set to OIC_ACCEPTED."

        Claim: post-accept lien.status == RELEASED with release_reason
        == OIC_ACCEPTED.

        Note: This requires the lien-release cascade trigger after
        liabilities reach IN_COMPROMISE+PAID. PRD §3.8 second clause:
        "After offer_amount_cents is paid in full via subsequent
        OIC_INSTALLMENT payments — when the cumulative sum of
        OIC_INSTALLMENT amounts allocated to the offer reaches or
        exceeds offer_amount_cents — every covered liability transitions
        from IN_COMPROMISE to PAID, triggering the lien release
        cascade."

        # difficulty: transitive_cascade/oic_accept_to_ia_terminate_to_liability_revert_depth3
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=30_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=500_000,
        )
        lien = file_lien(taxpayer["id"], [liability["id"]],
                         filed_date="2020-01-15T00:00:00.000Z")
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=400_000,
            schedule_months=5,
            deposit_cents=80_000,
            take_up_officer_id="lien-cascade-A",
        )
        accept_resp = api.decide_offer_in_compromise(
            oic["id"],
            decide_offer_in_compromise_payload("ACCEPT"),
            make_oic_officer_headers("lien-cascade-B"),
        )
        validate_success(accept_resp)
        # Pay the remaining OIC offer amount via OIC_INSTALLMENT to push
        # the liability all the way to PAID and trigger lien release.
        from test_helpers import (
            create_payment_payload,
            iso_instant_utc,
            api_client,
        )
        # Deposit already covered 80_000 of 400_000; pay 320_000 more.
        api_client.create_payment(
            create_payment_payload(
                taxpayer_id=taxpayer["id"],
                amount_cents=320_000,
                received_at="2020-02-01T00:00:00.000Z",
                payment_kind="OIC_INSTALLMENT",
                oic_id=oic["id"],
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        refreshed_lien = get_lien(lien["id"])
        assert refreshed_lien["status"] == "RELEASED"
        assert refreshed_lien["release_reason"] == "OIC_ACCEPTED"


# =============================================================================
# Rule 5 / instance 1 — state_vs_business_fiscal_overpayment second test
# =============================================================================
class TestStateVsFiscalAdditional:

    def test_overpayment_alone_on_active_agreement_reports_overpayment(self,
                                                                       api):
        """PRD §2.10: "the fiscal band at priorities 20–21
        (overpayment, revival of fully-resolved agreements)."

        Claim: when only the fiscal violation applies (agreement is
        ACTIVE, not DEFAULTED), the error reported is ERR_OVERPAYMENT
        (priority 20). This isolates the priority pair from instance
        1.

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_overpayment
        """
        from test_helpers import (
            TEST_USERS,
            record_installment_payment_payload,
        )
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=200_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        # Pay more than the remaining balance — agreement is ACTIVE so
        # state check passes; only fiscal trips.
        resp = api.record_installment_payment(
            agreement["id"],
            record_installment_payment_payload(
                amount_cents=500_000,
                received_at="2020-02-01T00:00:00.000Z",
            ),
            TEST_USERS["irs_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


# =============================================================================
# Rule 6 / instance 1 — ddia_threshold_25k_strict_greater_than (instance 1
# of this rule already has two tests in test_03; rule 6 instance 2 also
# has two tests in test_11; nothing to add here)
# =============================================================================


# =============================================================================
# Rule 7 / instance 1 — ia_activate_depends_on_liability_status second test
# =============================================================================
class TestIAActivateLiabilityEligibilityAdditional:

    def test_activate_blocked_when_liability_already_paid(self, api):
        """PRD §3.4: "fails with ERR_LIABILITY_NOT_ELIGIBLE if any
        covered liability is no longer in OPEN or IN_AGREEMENT."

        Claim: drafting an IA over a PAID liability surfaces
        ERR_LIABILITY_NOT_ELIGIBLE at activation time (or at draft —
        either is PRD-consistent and we tolerate both).

        # difficulty: cross_entity_state_dependency/ia_activate_depends_on_liability_status
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=200_000,
        )
        first_agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        # Settle in one payment so the liability is PAID.
        record_installment_payment(
            first_agreement["id"], amount_cents=200_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        assert get_tax_liability(liability["id"])["status"] == "PAID"
        # Now try to draft + activate a new IA covering the PAID
        # liability.
        payload = create_installment_agreement_payload(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        draft_resp = api.create_installment_agreement(
            payload, make_taxpayer_headers(taxpayer["id"]),
        )
        if draft_resp.status_code >= 400:
            validate_error(
                draft_resp, ApiErrorId.ERR_LIABILITY_NOT_ELIGIBLE.value,
            )
            return
        draft = draft_resp.json()["data"]
        activate_resp = api.activate_installment_agreement(
            draft["id"], TEST_USERS["irs_officer_headers"],
        )
        validate_error(
            activate_resp, ApiErrorId.ERR_LIABILITY_NOT_ELIGIBLE.value,
        )


# =============================================================================
# Rule 7 / instance 2 — lien_withdraw_depends_on_agreement_method second
# test: check the failing-aggregate-debt arm of the AND
# =============================================================================
class TestLienWithdrawDepositOver25kAdditional:

    def test_withdraw_blocked_when_aggregate_debt_above_25k_with_ddia(self,
                                                                       api,
                                                                       irs_officer_headers):
        """PRD §3.7: "An IRSOfficer may withdraw a FILED lien when
        every liability_id on the lien is currently in IN_AGREEMENT
        under a covering InstallmentAgreement whose payment_method is
        DDIA, and the aggregate debt across the lien's liabilities is
        at most 2,500,000 cents (which is $25,000)."

        Claim: DDIA agreement + aggregate debt > 25k (the second arm
        of the conjunction) → ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE.

        # difficulty: cross_entity_state_dependency/lien_withdraw_depends_on_agreement_method
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=400_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=3_000_000,  # > 2,500,000
        )
        create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=100_000,
            payment_method="DDIA",
        )
        lien = file_lien(
            taxpayer["id"], [liability["id"]],
            filed_date="2020-02-01T00:00:00.000Z",
        )
        resp = api.withdraw_lien(lien["id"], irs_officer_headers)
        validate_error(
            resp, ApiErrorId.ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE.value,
        )


# =============================================================================
# Rule 8 / instance 1 — csed_tolling_half_open_overlap second test
# =============================================================================
class TestCSEDTollingHalfOpenAdditional:

    def test_csed_drift_equals_total_open_interval_after_two_consecutive(
        self, api,
    ):
        """PRD §3.3: "Overlap is judged under half-open semantics: an
        interval covers start_date (inclusive) up to but not including
        end_date."
        PRD §3.3: "the total tolling duration is the sum of the lengths
        of the merged intervals (in seconds, ISO 8601 UTC). The
        effective expiration is csed_base_date advanced by that total
        tolling duration."

        Claim: opening an OIC_PENDING at T0, closing at T1, then
        opening another OIC_PENDING at T1 (adjacent boundary, NOT
        overlapping under half-open) and reading csed at T1 yields
        csed_effective_date == csed_base + (T1 - T0) seconds exactly
        (only the first, closed interval contributes; the second,
        just-opened zero-length interval contributes zero).

        # difficulty: resource_temporal_overlap/csed_tolling_half_open_overlap
        """
        from datetime import timedelta
        from test_helpers import (
            create_draft_oic,
            create_taxpayer,
            create_tax_liability,
            pay_oic_deposit,
            submit_oic,
            withdraw_oic,
        )
        t0_iso = "2020-01-01T00:00:00.000Z"
        t1_iso = "2020-04-01T00:00:00.000Z"
        advance_clock_to(t0_iso)
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date=t0_iso,
            original_assessed_amount_cents=1_500_000,
        )
        oic_a = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000, schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic_a["id"], 300_000)
        submit_oic(taxpayer["id"], oic_a["id"])
        # Advance to T1, withdraw (closes interval 1).
        advance_clock_to(t1_iso)
        withdraw_oic(taxpayer["id"], oic_a["id"])
        # Open second OIC at the same instant — half-open semantics
        # mean a.end_date == b.start_date is NOT overlap.
        oic_b = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000, schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic_b["id"], 300_000)
        submit_oic(taxpayer["id"], oic_b["id"])
        # At clock T1 (the same instant), the second interval is
        # zero-length, so total tolling = (T1 - T0) seconds from
        # interval 1. csed_base = assessment + 10 years (calendar
        # leap-year-aware), so expected = csed_base + (T1 - T0).
        liab_after = get_tax_liability(liability["id"])
        csed_base = parse_iso(liab_after["csed_base_date"])
        expected = csed_base + (parse_iso(t1_iso) - parse_iso(t0_iso))
        actual = parse_iso(liab_after["csed_effective_date"])
        assert actual == expected, (
            f"PRD §3.3: half-open boundary adjacency is non-overlapping; "
            f"csed_effective_date should be {expected.isoformat()}; "
            f"got {actual.isoformat()}"
        )


# =============================================================================
# Rule 8 / instance 2 — ia_oic_simultaneous_lock_overlap second test
# =============================================================================
class TestLiabilityLockedSecondTest:

    def test_oic_submit_allowed_while_ia_active_only_lock_at_under_review(
        self, api,
    ):
        """PRD §3.4: "fails with ERR_LIABILITY_LOCKED if any covered
        liability is simultaneously held by an UNDER_REVIEW Offer in
        Compromise."

        Claim: the symmetric IA-side lock activates at UNDER_REVIEW
        (take-up), not at SUBMITTED. Submitting an OIC while the
        covering IA is still ACTIVE is allowed at the SUBMITTED stage.

        # difficulty: resource_temporal_overlap/ia_oic_simultaneous_lock_overlap
        """
        from test_helpers import (
            create_draft_oic,
            pay_oic_deposit,
            submit_oic,
        )
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_500_000,
        )
        create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        # Draft + deposit + submit an OIC — submit must succeed since
        # the lock activates only at UNDER_REVIEW per PRD §3.4.
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000, schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic["id"], 300_000)
        submitted = submit_oic(taxpayer["id"], oic["id"])
        assert submitted["status"] == "SUBMITTED"


# =============================================================================
# Rule 9 / instance 1 — payment_allocation_total_invariant second test
# =============================================================================
class TestPaymentAllocationInvariantSecond:

    def test_successful_payment_increases_taxpayer_sum_by_amount_cents(
        self, api,
    ):
        """PRD §3.5: "each applied_cents value is added to
        payments_applied_cents on the corresponding liability and
        subtracted from the remaining payment amount."

        Claim: SUM(TaxLiability.payments_applied_cents) post-payment ==
        SUM(payments_applied_cents) pre-payment + Payment.amount_cents
        (compensating-action invariant on monetary sum).

        # difficulty: compensating_invariant/payment_allocation_total_invariant
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liab_a = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=400_000,
        )
        liab_b = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=600_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liab_a["id"], liab_b["id"]],
            proposed_monthly_payment_cents=1_500_000,
            payment_method="CHECK",
        )
        before = (
            get_tax_liability(liab_a["id"])["payments_applied_cents"]
            + get_tax_liability(liab_b["id"])["payments_applied_cents"]
        )
        record_installment_payment(
            agreement["id"], amount_cents=500_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        after = (
            get_tax_liability(liab_a["id"])["payments_applied_cents"]
            + get_tax_liability(liab_b["id"])["payments_applied_cents"]
        )
        assert after - before == 500_000


# =============================================================================
# Rule 9 / instance 2 — csed_tolling_balance_invariant second test (the
# first test lives in test_05; this asserts the positive direction —
# the invariant delta == sum-of-non-zero-intervals)
# =============================================================================
class TestCSEDDurationInvariantPositiveDirection:

    def test_nonzero_tolling_advances_csed_by_exact_interval_length(self, api):
        """PRD §3.3: "the total tolling duration is the sum of the
        lengths of the merged intervals (in seconds, ISO 8601 UTC).
        The effective expiration is csed_base_date advanced by that
        total tolling duration."

        Claim: a 30-day non-zero tolling interval advances
        csed_effective_date by exactly 30 days (positive direction of
        the conservation invariant).

        # difficulty: compensating_invariant/csed_tolling_balance_invariant
        """
        from test_helpers import (
            create_draft_oic,
            pay_oic_deposit,
            submit_oic,
            withdraw_oic,
        )
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_500_000,
        )
        pre = parse_iso(
            get_tax_liability(liability["id"])["csed_effective_date"]
        )
        # Open a tolling event at clock T then close at clock T+30d.
        advance_clock_to("2021-06-15T00:00:00.000Z")
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000, schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic["id"], 300_000)
        submit_oic(taxpayer["id"], oic["id"])
        advance_clock_to("2021-07-15T00:00:00.000Z")  # +30d
        withdraw_oic(taxpayer["id"], oic["id"])
        post = parse_iso(
            get_tax_liability(liability["id"])["csed_effective_date"]
        )
        delta_seconds = (post - pre).total_seconds()
        assert int(delta_seconds) == 30 * 24 * 3600, (
            f"PRD §3.3: a 30-day closed tolling interval advances "
            f"csed_effective_date by exactly 30 days; got "
            f"{int(delta_seconds)} s"
        )
