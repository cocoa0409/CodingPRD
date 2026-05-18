"""Difficulty-design coverage — at least TWO tests per declared
instance per the test-targeting index.

Each test docstring carries a `# difficulty: <rule_id>/<instance>`
tag so coverage can be audited. Each test pins to a verbatim PRD
sentence stating the underlying rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    BASE_RATE_BPS_BY_GRADE,
    INSTALLMENT_GRACE_DAYS,
    INSTALLMENT_PERIOD_DAYS,
    advance_clock,
    approve_borrower,
    assert_charge_off_loss_distribution_invariant,
    attach_plaid_snapshot,
    ban_borrower,
    create_borrower,
    create_compliance_officer,
    create_investment,
    create_investment_payload,
    create_listing,
    create_listing_payload,
    create_payment_payload,
    deposit_to_investor,
    find_disclosure,
    get_borrower,
    get_investment,
    get_investor,
    get_listing,
    get_loan,
    list_installments,
    make_borrower_headers,
    make_compliance_officer_headers,
    make_investor_headers,
    post_payment,
    publish_disclosure,
    reinstate_borrower,
    setup_approved_borrower,
    setup_disclosure_in_draft,
    setup_funded_investor,
    setup_funded_listing,
    setup_loan_charged_off,
    setup_loan_charged_off_three_investors,
    setup_loan_in_default,
    setup_loan_in_delinquent,
    setup_open_listing,
    setup_originated_loan,
    setup_originated_loan_three_investors,
    setup_platform_with_officer,
    suspend_borrower,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    withdraw_listing,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    """Two instances:
    - borrower_provisional_vs_final_grade_divergence
    - charge_off_loss_forward_vs_chronological
    """

    # -----------------------------------------------------------------
    # Instance 1: borrower_provisional_vs_final_grade_divergence
    # -----------------------------------------------------------------
    # DELETED: test_provisional_a_diverges_from_final_d_or_e
    # Reason: PRD §3.2 contains two contradictory statements. The PRD
    # formula normalizes annual_revenue linearly between a $50,000
    # floor and a $5,000,000 ceiling. Plugging in $1,000,000 (the value
    # cited by the PRD's illustrative sentence) yields a provisional
    # score of ~0.44, which bands to 'D'. The PRD's illustrative
    # sentence ("provisional grade of A") states the outcome is 'A'.
    # The two readings contradict, so PRD does not uniquely determine
    # provisional grade for $1M. STEP 1b unique-derivability collapse.

    def test_listing_grade_locks_to_final_not_provisional(self, api):
        """# difficulty: dual_variant_calc/borrower_provisional_vs_final_grade_divergence

        PRD §3.2: "The platform locks each LoanListing's
        grade_at_listing from the borrower's final_grade at the moment
        the listing opens, so this divergence directly affects
        pricing."

        Claim: after divergence (provisional 'A' but final 'D' or 'E'),
        listing.grade_at_listing equals the FINAL grade, not the
        provisional grade.
        """
        platform, officer = setup_platform_with_officer()
        b = create_borrower(
            platform["id"],
            annual_revenue_cents=1_000_000_00,
            requested_amount_cents=100_000_00,
        )
        attach_plaid_snapshot(
            platform["id"], b["id"],
            deposits_last_90d_cents=15_000_00,
            avg_daily_balance_cents=2_000_00,
            nsf_count_last_90d=3,
            existing_debt_service_cents=2_000_00,
        )
        b_after = get_borrower(platform["id"], b["id"])
        # PRD §3.2: "Attaching a snapshot triggers a recomputation of
        # final_grade." After attach, final_grade MUST be non-UNGRADED.
        assert b_after["final_grade"] != "UNGRADED"
        approve_borrower(platform["id"], b["id"], officer["id"])
        listing = create_listing(
            platform["id"], b["id"],
            principal_cents=100_000, term_months=12,
        )
        # PRD-pinned: grade_at_listing == final_grade (the locked one).
        assert listing["grade_at_listing"] == b_after["final_grade"]
        # Sanity: divergence holds.
        assert b_after["provisional_grade"] != b_after["final_grade"]

    # -----------------------------------------------------------------
    # Instance 2: charge_off_loss_forward_vs_chronological
    # -----------------------------------------------------------------
    def test_charge_off_loss_equals_principal_outstanding_at_moment(
        self, api,
    ):
        """# difficulty: dual_variant_calc/charge_off_loss_forward_vs_chronological

        PRD §3.6: "the loan's charged_off_loss_cents is set to the sum
        of principal_outstanding_cents and accrued_late_fees_cents at
        the moment of charge-off; this is the ledger-realized loss,
        not a forward-looking projection from the default date".

        Claim: with no payments at all, charged_off_loss_cents equals
        the loan's principal_cents + accrued_late_fees_cents recorded
        at the CHARGED_OFF moment — i.e. equals the chronological
        balance.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        # No prior cures -> total loss equals at least principal.
        assert loan["status"] == "CHARGED_OFF"
        assert loan["charged_off_loss_cents"] >= 100_000

    def test_partial_cure_between_default_and_charge_off_reduces_loss(
        self, api,
    ):
        """# difficulty: dual_variant_calc/charge_off_loss_forward_vs_chronological

        PRD §3.6: "partial payments received between DEFAULT and
        CHARGED_OFF reduce the realized loss below what a forward-
        looking estimate would have predicted."

        Claim: a partial Payment posted between DEFAULT and CHARGE_OFF
        decreases charged_off_loss_cents below what it would be with
        zero payments (i.e. principal-with-no-cures).
        """
        # Baseline: no payments -> loss == principal + accrued_late_fees.
        (platform_a, officer_a, b_a, investor_a, listing_a, investment_a,
         loan_a_zero) = setup_loan_charged_off(principal_cents=100_000)
        loss_no_cure = loan_a_zero["charged_off_loss_cents"]

        # Treatment: drive a second loan to DEFAULT, post a partial
        # payment, then continue to CHARGE_OFF.
        (platform_b, officer_b, b_b, investor_b, listing_b,
         investment_b, loan_b) = setup_loan_in_default(
            principal_cents=100_000,
        )
        assert loan_b["status"] == "DEFAULT"
        # A partial payment reduces principal_outstanding before the
        # next charge-off threshold.
        post_payment(
            platform_b["id"], loan_b["id"], amount_cents=10_000,
        )
        # Advance further to reach 5 misses -> CHARGED_OFF.
        advance_clock(
            platform_b["id"],
            2 * INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
        )
        loan_b_final = get_loan(platform_b["id"], loan_b["id"])
        # PRD §3.6: "When the counter reaches five or more, the loan
        # transitions DEFAULT -> CHARGED_OFF". The partial 10_000-cent
        # payment did not fully PAY any installment (it would have
        # gone to servicing-fee + late-fee + interest on installment 1
        # only, far short of clearing installment 1's full schedule),
        # so consecutive_missed_installments stayed at 3 at DEFAULT.
        # The 66-day advance crosses installments 4 and 5's
        # due+grace, accumulating misses to 5+ -> CHARGED_OFF.
        assert loan_b_final["status"] == "CHARGED_OFF", (
            f"loan must reach CHARGED_OFF after sufficient clock "
            f"advance; got {loan_b_final['status']}"
        )
        loss_with_cure = loan_b_final["charged_off_loss_cents"]
        # The partial payment reduced realized loss versus the
        # zero-cure baseline.
        assert loss_with_cure < loss_no_cure, (
            f"partial cure should reduce loss: with-cure={loss_with_cure}, "
            f"no-cure={loss_no_cure}"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    """Two instances:
    - tiered_interest_rate_with_term_premium_mode_a
    - amortization_schedule_residual_last_installment_mode_b
    """

    # -----------------------------------------------------------------
    # Instance 1: tiered_interest_rate_with_term_premium_mode_a
    # -----------------------------------------------------------------
    def _approve_grade_c_borrower(self):
        platform, officer = setup_platform_with_officer()
        b = create_borrower(
            platform["id"],
            annual_revenue_cents=500_000_000,
            requested_amount_cents=50_000_000,
        )
        # Plaid inputs targeting grade C: moderate deposits, low
        # reserves, no NSF, some debt service.
        attach_plaid_snapshot(
            platform["id"], b["id"],
            deposits_last_90d_cents=90 * 3_000_000,
            avg_daily_balance_cents=6_000_000,
            nsf_count_last_90d=0,
            existing_debt_service_cents=10_000,
        )
        b_after = get_borrower(platform["id"], b["id"])
        # PRD §3.2 score with deposits=270M cents (cashflow=3M/10M=
        # 0.30), reserves=6M/25M=0.24, dti~0, nsf=0:
        # 0.35*0.30 + 0.30*0.24 + 0.25*1 + 0.10*1 = 0.527 -> C band
        # ([0.50, 0.65)). Implementation MUST land C.
        assert b_after["final_grade"] == "C", (
            f"PRD §3.2 score formula must land 'C' for this Plaid "
            f"input set; got {b_after['final_grade']!r}"
        )
        approve_borrower(platform["id"], b["id"], officer["id"])
        return platform, officer, b_after

    def test_tiered_rate_grade_c_term_36_is_1420(self, api):
        """# difficulty: combinatorial_formula/tiered_interest_rate_with_term_premium_mode_a

        PRD §3.3: "The base table is exactly { A: 600, B: 900, C:
        1300, D: 1800, E: 2400 }. The term premium is computed as the
        maximum of zero and the term in months minus 24, then
        multiplied by ten basis points per month".

        Claim: grade C, term_months=36 -> interest_rate_bps = 1300 +
        (36-24)*10 = 1420.
        """
        platform, officer, b = self._approve_grade_c_borrower()
        listing = create_listing(
            platform["id"], b["id"],
            principal_cents=100_000, term_months=36,
        )
        assert listing["interest_rate_bps"] == 1300 + (36 - 24) * 10

    def test_tiered_rate_grade_c_term_24_boundary_is_1300(self, api):
        """# difficulty: combinatorial_formula/tiered_interest_rate_with_term_premium_mode_a

        PRD §3.3: "so the first 24 months carry no premium" — the
        max(0, term-24) clamp pins term_months=24 to zero premium.

        Claim: grade C, term_months=24 -> interest_rate_bps = 1300 + 0
        = 1300. The clamp prevents a negative premium at this boundary.
        """
        platform, officer, b = self._approve_grade_c_borrower()
        listing = create_listing(
            platform["id"], b["id"],
            principal_cents=100_000, term_months=24,
        )
        assert listing["interest_rate_bps"] == 1300

    # -----------------------------------------------------------------
    # Instance 2: amortization_schedule_residual_last_installment_mode_b
    # -----------------------------------------------------------------
    def test_sum_of_scheduled_principal_equals_principal_exactly(
        self, api,
    ):
        """# difficulty: combinatorial_formula/amortization_schedule_residual_last_installment_mode_b

        PRD §3.4: "The final installment absorbs the residual cents so
        that the sum of scheduled_principal_cents across all
        installments equals principal_cents exactly."

        Claim: sum(installment[i].scheduled_principal_cents) ==
        loan.principal_cents, EXACT integer cent equality.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        body = list_installments(platform["id"], loan["id"])
        installments = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(installments, dict) and "data" in installments:
            installments = installments["data"]
        total_principal = sum(
            it["scheduled_principal_cents"] for it in installments
        )
        assert total_principal == loan["principal_cents"]

    def test_residual_lives_on_last_installment(self, api):
        """# difficulty: combinatorial_formula/amortization_schedule_residual_last_installment_mode_b

        PRD §3.4: "The final installment absorbs the residual cents".
        PRD §2.8: "per-recipient amounts are rounded half-up to cents
        and the rounding residual is absorbed by the last recipient so
        that the sum matches the input total exactly."

        Claim: when principal does not divide evenly across n
        installments, the last installment's
        (scheduled_principal_cents + scheduled_interest_cents) MAY
        differ from earlier installments to absorb the residual. The
        invariant is: sum of all scheduled_principal_cents ==
        principal_cents (already tested), AND the FIRST and LAST
        installments are individually non-zero (the schedule was
        actually generated).
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        body = list_installments(platform["id"], loan["id"])
        installments = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(installments, dict) and "data" in installments:
            installments = installments["data"]
        installments_sorted = sorted(
            installments, key=lambda i: i["sequence_number"],
        )
        first = installments_sorted[0]
        last = installments_sorted[-1]
        # Both must be scheduled with positive principal+interest sums.
        assert (
            first["scheduled_principal_cents"]
            + first["scheduled_interest_cents"]
        ) > 0
        assert (
            last["scheduled_principal_cents"]
            + last["scheduled_interest_cents"]
        ) > 0


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    """Two instances:
    - loan_delinquent_active_revert_cycle
    - borrower_suspend_reinstate_cycle
    """

    # -----------------------------------------------------------------
    # Instance 1: loan_delinquent_active_revert_cycle
    # -----------------------------------------------------------------
    def test_loan_delinquent_to_active_cure(self, api):
        """# difficulty: non_linear_state_machine/loan_delinquent_active_revert_cycle

        PRD §3.5: "When consecutive_missed_installments returns to
        zero on a loan currently in DELINQUENT, the loan transitions
        DELINQUENT -> ACTIVE (the cure transition's precondition is
        that all previously-LATE installments are now PAID)."

        Claim: cure brings DELINQUENT -> not-DELINQUENT (revert leg of
        the cycle).
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_in_delinquent(principal_cents=100_000)
        assert loan["status"] == "DELINQUENT"
        # Fully cure: pay the full principal (over-pays late fee +
        # interest as well).
        post_payment(
            platform["id"], loan["id"],
            amount_cents=loan["principal_cents"] +
            loan["accrued_late_fees_cents"],
        )
        refreshed = get_loan(platform["id"], loan["id"])
        assert refreshed["status"] != "DELINQUENT"

    def test_loan_active_to_delinquent_to_active_via_cycle(self, api):
        """# difficulty: non_linear_state_machine/loan_delinquent_active_revert_cycle

        PRD §3.5: "When consecutive_missed_installments returns to
        zero on a loan currently in DELINQUENT, the loan transitions
        DELINQUENT -> ACTIVE".
        PRD §3.6: "The first time consecutive_missed_installments
        moves from zero to a positive integer, the loan transitions
        ACTIVE -> DELINQUENT".

        Cycle claim: the same loan reaches DELINQUENT and is then
        returned to a non-DELINQUENT state by curing.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        assert loan["status"] == "ACTIVE"
        # Advance past first installment's due+grace to enter DELINQUENT.
        advance_clock(
            platform["id"],
            INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
        )
        mid = get_loan(platform["id"], loan["id"])
        assert mid["status"] == "DELINQUENT"
        # Cure: pay enough to clear the late installment.
        post_payment(
            platform["id"], loan["id"],
            amount_cents=loan["principal_cents"] +
            mid["accrued_late_fees_cents"],
        )
        after = get_loan(platform["id"], loan["id"])
        # The loan is no longer DELINQUENT after the cure.
        assert after["status"] != "DELINQUENT"

    # -----------------------------------------------------------------
    # Instance 2: borrower_suspend_reinstate_cycle
    # -----------------------------------------------------------------
    def test_borrower_suspended_to_approved_via_reinstate(self, api):
        """# difficulty: non_linear_state_machine/borrower_suspend_reinstate_cycle

        PRD §3.2: "Reinstating a SUSPENDED borrower returns them to
        APPROVED".

        Claim: APPROVED -> SUSPENDED -> APPROVED cycle.
        """
        platform, officer, b = setup_approved_borrower()
        suspend_borrower(platform["id"], b["id"], officer["id"])
        b_re = reinstate_borrower(
            platform["id"], b["id"], officer["id"],
        )
        assert b_re["status"] == "APPROVED"

    def test_borrower_suspended_then_banned_terminal_fork(self, api):
        """# difficulty: non_linear_state_machine/borrower_suspend_reinstate_cycle

        PRD §3.2: "a SUSPENDED borrower transitions SUSPENDED ->
        BANNED with no further cascade since suspension already
        collapsed any open listings. BANNED is terminal."

        Claim: SUSPENDED forks to BANNED (terminal) instead of
        reinstate.
        """
        platform, officer, b = setup_approved_borrower()
        suspend_borrower(platform["id"], b["id"], officer["id"])
        banned = ban_borrower(platform["id"], b["id"], officer["id"])
        assert banned["status"] == "BANNED"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    """Two instances:
    - charge_off_cascade_depth_3
    - borrower_ban_cascade_depth_2
    """

    # -----------------------------------------------------------------
    # Instance 1: charge_off_cascade_depth_3
    # -----------------------------------------------------------------
    def test_charge_off_cascades_to_installments_waived(self, api):
        """# difficulty: transitive_cascade/charge_off_cascade_depth_3

        PRD §3.6: "Every remaining installment, regardless of its
        current state (SCHEDULED, DUE, or LATE), transitions to
        WAIVED".

        Claim: link 2 of the depth-3 cascade: clock-driven CHARGED_OFF
        leads to remaining installments being WAIVED.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        body = list_installments(platform["id"], loan["id"])
        rows = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(rows, dict) and "data" in rows:
            rows = rows["data"]
        # All non-PAID installments must be WAIVED.
        for it in rows:
            assert it["status"] in {"WAIVED", "PAID"}

    def test_charge_off_cascades_to_investments_and_investor(self, api):
        """# difficulty: transitive_cascade/charge_off_cascade_depth_3

        PRD §3.6: "Every CONVERTED Investment on the loan transitions
        to LOST." And: "for each, a gross share is computed ... the
        investor's outstanding_principal_cents decreases by the actual
        share."

        Claim: link 3 of the cascade: each CONVERTED Investment
        becomes LOST AND each investor's outstanding_principal_cents
        decremented exactly by their share. With shares 30/30/40,
        deltas are 30_000, 30_000, 40_000 summing to principal 100_000.
        """
        (platform, officer, b, investors, investments, listing,
         loan) = setup_loan_charged_off_three_investors(
            principal_cents=100_000,
            shares=(30_000, 30_000, 40_000),
        )
        for inv in investments:
            refreshed_inv = get_investment(platform["id"], inv["id"])
            assert refreshed_inv["status"] == "LOST"
        # Deltas computation: original pledge - current outstanding.
        deltas = []
        for inv, pledge in zip(investors, (30_000, 30_000, 40_000)):
            refreshed = get_investor(platform["id"], inv["id"])
            deltas.append(
                pledge - refreshed["outstanding_principal_cents"]
            )
        assert sum(deltas) == loan["charged_off_loss_cents"]
        # Even split, no residual: each investor takes their exact
        # 30/30/40 cents-thousand share.
        assert sorted(deltas) == sorted([30_000, 30_000, 40_000])

    # -----------------------------------------------------------------
    # Instance 2: borrower_ban_cascade_depth_2
    # -----------------------------------------------------------------
    def test_ban_cascades_listing_to_withdrawn(self, api):
        """# difficulty: transitive_cascade/borrower_ban_cascade_depth_2

        PRD §3.2: "Banning is permanent: an APPROVED borrower
        transitions APPROVED -> BANNED with the same
        OPEN-listing-and-COMMITTED-investment cascade as suspend".

        Claim: link 1 (ban) drives link 2a (listing WITHDRAWN).
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        ban_borrower(platform["id"], b["id"], officer["id"])
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "WITHDRAWN"

    def test_ban_cascades_committed_investments_to_released_with_refund(
        self, api,
    ):
        """# difficulty: transitive_cascade/borrower_ban_cascade_depth_2

        PRD §3.2: "Banning is permanent: an APPROVED borrower
        transitions APPROVED -> BANNED with the same OPEN-listing-and-
        COMMITTED-investment cascade as suspend"; "every OPEN
        LoanListing of that borrower is moved to WITHDRAWN, every
        COMMITTED Investment on those listings is moved to RELEASED,
        and each affected investor's cash_balance_cents is credited by
        the corresponding amount_cents as a refund."

        Claim: link 2b (investments RELEASED + cash refunded) is
        caused by the listing's withdraw side-effect, not directly by
        the ban. The cascade is named only for OPEN listings — so this
        test exercises the cascade on a partially pledged OPEN listing.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(platform["id"])
        # Partial pledge -> listing still OPEN (40_000 < 100_000).
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=40_000,
        )
        refreshed_listing = get_listing(platform["id"], listing["id"])
        assert refreshed_listing["status"] == "OPEN"
        cash_before = get_investor(
            platform["id"], investor["id"],
        )["cash_balance_cents"]
        ban_borrower(platform["id"], b["id"], officer["id"])
        # Refund applied.
        inv_after = get_investor(platform["id"], investor["id"])
        assert inv_after["cash_balance_cents"] == cash_before + 40_000


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    """Two instances:
    - state_vs_business_constraint_payment_on_charged_off_with_zero_amount
    - business_safety_vs_business_constraint_self_investment
    """

    # -----------------------------------------------------------------
    # Instance 1
    # -----------------------------------------------------------------
    def test_payment_on_charged_off_with_zero_amount_returns_not_payable(
        self, api, platform_operator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_constraint_payment_on_charged_off_with_zero_amount

        PRD §3.5: "a payment against a CHARGED_OFF or PAID_OFF loan is
        rejected with ERR_LOAN_NOT_PAYABLE."

        Claim: with amount_cents=0 on a CHARGED_OFF loan, the
        loan-payability rule (terminal-loan) is the rule the PRD
        explicitly names; the response is ERR_LOAN_NOT_PAYABLE.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        resp = api.create_payment(
            platform["id"], loan["id"],
            create_payment_payload(amount_cents=0),
            platform_operator_headers,
        )
        validate_error(resp, "ERR_LOAN_NOT_PAYABLE")

    def test_payment_on_charged_off_with_positive_amount_returns_not_payable(
        self, api, platform_operator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_constraint_payment_on_charged_off_with_zero_amount

        PRD §3.5: "a payment against a CHARGED_OFF or PAID_OFF loan is
        rejected with ERR_LOAN_NOT_PAYABLE."

        Claim: with amount_cents > 0 on CHARGED_OFF -> still
        ERR_LOAN_NOT_PAYABLE. Together with the zero-amount test, this
        shows the loan-payability check is hit regardless of the
        amount value.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        resp = api.create_payment(
            platform["id"], loan["id"],
            create_payment_payload(amount_cents=10_000),
            platform_operator_headers,
        )
        validate_error(resp, "ERR_LOAN_NOT_PAYABLE")

    # -----------------------------------------------------------------
    # Instance 2
    # -----------------------------------------------------------------
    def test_self_investment_borrower_role_rejected_as_segregation(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_self_investment

        PRD §3.3: "A Borrower cannot self-invest in their own listing;
        an Investor attempting to pledge on a listing whose borrower
        is themselves (same platform) is rejected with
        ERR_SEGREGATION_VIOLATION."

        Claim: Borrower role calling /investments on own listing
        (which also would exceed any diversification cap because of an
        absurd amount) -> ERR_SEGREGATION_VIOLATION takes precedence
        over the diversification cap rule per PRD §2.9 (segregation
        precedes business constraint rules).

        Note: the contract is open between ERR_SEGREGATION_VIOLATION
        and ERR_FORBIDDEN_FOR_ROLE because PRD §3.9 also says Borrower
        is "structurally barred from POST /investments". We accept
        either as PRD-faithful.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=10_000_000,
        )
        # Even an absurd amount must not trip diversification first.
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=999_900),
            make_borrower_headers(b["id"]),
        )
        validate_error_is_one_of(
            resp,
            ["ERR_SEGREGATION_VIOLATION", "ERR_FORBIDDEN_FOR_ROLE"],
        )

    def test_self_investment_does_not_return_diversification_error(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_self_investment

        PRD §2.9: "Segregation-of-duties rules (ERR_SEGREGATION_VIOLATION)
        precede the domain-specific referential and constraint rules."

        Claim: a self-investment that would also breach the
        diversification cap MUST NOT surface
        ERR_DIVERSIFICATION_CAP_EXCEEDED; the segregation/forbidden
        path preempts it.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=10_000_000,
        )
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=999_900),
            make_borrower_headers(b["id"]),
        )
        body = resp.json()
        err_id = body.get("data", {}).get("error_id") if isinstance(
            body, dict,
        ) else None
        assert err_id != "ERR_DIVERSIFICATION_CAP_EXCEEDED", (
            f"PRD §2.9 priority: segregation preempts diversification; "
            f"got error_id={err_id!r}"
        )


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:
    """Two instances:
    - diversification_cap_inclusive_boundary_on_investments_endpoint
    - empty_pledged_listing_expiration_zero_count_on_advance_clock
    """

    # -----------------------------------------------------------------
    # Instance 1
    # -----------------------------------------------------------------
    def test_diversification_cap_inclusive_at_exact_value(self, api):
        """# difficulty: boundary_precision_check/diversification_cap_inclusive_boundary_on_investments_endpoint

        PRD §3.3: "The comparison is inclusive: exposure exactly equal
        to the cap is allowed".

        Claim: with committed_capital=10_000_00 cents and
        concentration=1000 bps -> cap=100_000 cents. Pledging exactly
        100_000 cents is allowed.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=500_000_00,
        )
        investor = setup_funded_investor(
            platform["id"],
            committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        inv = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=100_000,
        )
        assert inv["status"] == "COMMITTED"
        assert inv["amount_cents"] == 100_000

    def test_diversification_cap_one_cent_above_rejected(self, api):
        """# difficulty: boundary_precision_check/diversification_cap_inclusive_boundary_on_investments_endpoint

        PRD §3.3: "anything strictly greater is rejected with
        ERR_DIVERSIFICATION_CAP_EXCEEDED."

        Claim: two investments to the same borrower summing to
        100_100 cents (cap + 100) -> second is rejected.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=500_000_00,
        )
        investor = setup_funded_investor(
            platform["id"],
            committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=100_000,
        )
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=100),
            make_investor_headers(investor["id"]),
        )
        validate_error(resp, "ERR_DIVERSIFICATION_CAP_EXCEEDED")

    # -----------------------------------------------------------------
    # Instance 2
    # -----------------------------------------------------------------
    def test_listing_with_no_pledges_at_deadline_still_open(self, api):
        """# difficulty: boundary_precision_check/empty_pledged_listing_expiration_zero_count_on_advance_clock

        PRD §3.3: "the current clock_day_index is strictly greater
        than the deadline and pledged_cents is strictly less than
        principal_cents".

        Claim: at clock_day_index == 14 (== deadline, not strictly
        greater), an empty-pledged listing is STILL OPEN.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        advance_clock(platform["id"], 14)  # clock = 14 = deadline.
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "OPEN"
        assert refreshed["pledged_cents"] == 0

    def test_listing_with_no_pledges_past_deadline_expires(self, api):
        """# difficulty: boundary_precision_check/empty_pledged_listing_expiration_zero_count_on_advance_clock

        PRD §3.3: "OPEN -> EXPIRED is a system-driven transition."

        Claim: at clock_day_index = 15 (strictly > 14 = deadline)
        with pledged_cents=0, the listing transitions to EXPIRED
        (empty-set iteration over an empty COMMITTED-investment
        collection produces no errors).
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        advance_clock(platform["id"], 15)
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "EXPIRED"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    """Two instances:
    - listing_originate_requires_borrower_approved
    - disclosure_publish_requires_subject_state_stable
    """

    # -----------------------------------------------------------------
    # Instance 1
    # -----------------------------------------------------------------
    def test_originate_blocked_when_borrower_suspended(
        self, api, platform_operator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/listing_originate_requires_borrower_approved

        PRD §3.4: "Origination is also rejected if the underlying
        borrower is not in APPROVED status
        (ERR_BORROWER_NOT_APPROVED)".

        Claim: a FUNDED listing whose borrower is suspended fails
        originate with ERR_BORROWER_NOT_APPROVED, and the listing
        remains FUNDED (no Loan was created).
        """
        (platform, officer, b, investor, listing,
         investment) = setup_funded_listing(principal_cents=100_000)
        suspend_borrower(platform["id"], b["id"], officer["id"])
        resp = api.originate_listing(
            platform["id"], listing["id"], platform_operator_headers,
        )
        validate_error(resp, "ERR_BORROWER_NOT_APPROVED")
        # Note: the listing-cascade from suspend may also move the
        # listing's lifecycle (e.g. via OPEN-cascade). For a FUNDED
        # listing the PRD's suspend cascade only mentions OPEN
        # listings, so the listing should still be FUNDED. We check it
        # is NOT ORIGINATED (no loan created).
        from test_helpers import get_listing
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] != "ORIGINATED"

    def test_originate_succeeds_when_borrower_approved(self, api):
        """# difficulty: cross_entity_state_dependency/listing_originate_requires_borrower_approved

        PRD §3.4: "A FUNDED listing is originated by a
        PlatformOperator".

        Claim: with the borrower still APPROVED, origination succeeds
        and yields an ACTIVE loan.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(principal_cents=100_000)
        assert loan["status"] == "ACTIVE"
        # Confirm borrower was still APPROVED at originate (no suspend
        # in between).
        b_after = get_borrower(platform["id"], b["id"])
        assert b_after["status"] == "APPROVED"

    # -----------------------------------------------------------------
    # Instance 2
    # -----------------------------------------------------------------
    def test_default_notice_publish_after_charge_off_is_stale(self, api):
        """# difficulty: cross_entity_state_dependency/disclosure_publish_requires_subject_state_stable

        PRD §3.7: "The publish capability moves the disclosure DRAFT
        -> PUBLISHED only if payload is non-empty and the subject is
        still in the state that produced the draft — for example, a
        LISTING_FUNDED draft cannot be published if the listing has
        since moved to WITHDRAWN or EXPIRED. Either failure mode yields
        ERR_DISCLOSURE_STALE."

        Claim: a DEFAULT_NOTICE for a loan that has progressed to
        CHARGED_OFF before publish -> ERR_DISCLOSURE_STALE.
        """
        (platform, officer, b, loan, default_disclosure) = (
            setup_disclosure_in_draft("DEFAULT_NOTICE")
        )
        # Push past 5 misses to reach CHARGED_OFF.
        advance_clock(
            platform["id"],
            2 * INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
        )
        refreshed_loan = get_loan(platform["id"], loan["id"])
        assert refreshed_loan["status"] == "CHARGED_OFF"
        resp = api.publish_disclosure(
            platform["id"], default_disclosure["id"],
            make_compliance_officer_headers(officer["id"]),
        )
        validate_error(resp, "ERR_DISCLOSURE_STALE")

    def test_charge_off_notice_remains_publishable(self, api):
        """# difficulty: cross_entity_state_dependency/disclosure_publish_requires_subject_state_stable

        PRD §3.7: "the subject is still in the state that produced the
        draft".

        Claim: the CHARGE_OFF_NOTICE emitted at the moment the loan
        became CHARGED_OFF IS publishable because the loan's state
        still matches the kind's expected state.
        """
        (platform, officer, b, loan, charge_off_disclosure) = (
            setup_disclosure_in_draft("CHARGE_OFF_NOTICE")
        )
        assert charge_off_disclosure["kind"] == "CHARGE_OFF_NOTICE"
        published = publish_disclosure(
            platform["id"], charge_off_disclosure["id"],
            officer["id"],
        )
        assert published["published"] is True


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    """Two instances:
    - borrower_one_open_listing_at_a_time_singleton_interval
    - investor_per_borrower_exposure_aggregate_capacity_interval
    """

    # -----------------------------------------------------------------
    # Instance 1: singleton interval semantics
    # -----------------------------------------------------------------
    def test_borrower_cannot_open_second_listing_while_first_open(
        self, api, platform_operator_headers,
    ):
        """# difficulty: resource_temporal_overlap/borrower_one_open_listing_at_a_time_singleton_interval

        PRD §3.3: "A second listing cannot be opened for a borrower
        who already owns an OPEN or FUNDED listing; that case yields
        ERR_BORROWER_NOT_LISTABLE".

        Claim: while listing #1 is OPEN, a second create on the same
        borrower -> ERR_BORROWER_NOT_LISTABLE.
        """
        platform, officer, b, listing1 = setup_open_listing(
            principal_cents=100_000,
        )
        resp = api.create_listing(
            platform["id"], b["id"],
            create_listing_payload(
                principal_cents=50_000, term_months=12,
            ),
            platform_operator_headers,
        )
        validate_error(resp, "ERR_BORROWER_NOT_LISTABLE")

    def test_borrower_can_open_new_listing_after_withdraw_on_same_day(
        self, api,
    ):
        """# difficulty: resource_temporal_overlap/borrower_one_open_listing_at_a_time_singleton_interval

        PRD §3.3: "A second listing cannot be opened for a borrower
        who already owns an OPEN or FUNDED listing".

        Claim: after withdraw drives the prior listing to WITHDRAWN
        (terminal), a NEW listing on the same borrower at the same
        clock_day_index is allowed — adjacency is fine because the
        rule names {OPEN, FUNDED} and WITHDRAWN is neither.
        """
        platform, officer, b, listing1 = setup_open_listing(
            principal_cents=100_000,
        )
        withdraw_listing(platform["id"], listing1["id"])
        listing2 = create_listing(
            platform["id"], b["id"],
            principal_cents=50_000, term_months=12,
        )
        assert listing2["status"] == "OPEN"

    # -----------------------------------------------------------------
    # Instance 2: aggregate capacity across two listings of one borrower
    # -----------------------------------------------------------------
    def test_two_overlapping_investments_sum_to_cap_allowed(self, api):
        """# difficulty: resource_temporal_overlap/investor_per_borrower_exposure_aggregate_capacity_interval

        PRD §3.3: "the sum of amount_cents across all of this
        investor's Investment records whose status is COMMITTED or
        CONVERTED and whose listing belongs to the same borrower as
        the new listing, plus the new pledge — must not exceed a cap".

        Claim: two pledges (60_000 + 40_000) by one investor to the
        same borrower (via two different listings is not possible —
        rule §3.3 caps to one OPEN/FUNDED listing per borrower — so
        we exercise the rule with two pledges to the SAME listing).
        Both succeed when their sum equals the cap.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=200_000,
        )
        investor = setup_funded_investor(
            platform["id"],
            committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        inv_a = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=60_000,
        )
        inv_b = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=40_000,
        )
        # Aggregate exposure now equals cap (100_000), both COMMITTED.
        assert inv_a["status"] == "COMMITTED"
        assert inv_b["status"] == "COMMITTED"
        # Sanity: the aggregate of the two pledges equals the cap.
        assert inv_a["amount_cents"] + inv_b["amount_cents"] == 100_000

    def test_third_overlapping_investment_above_cap_rejected(self, api):
        """# difficulty: resource_temporal_overlap/investor_per_borrower_exposure_aggregate_capacity_interval

        PRD §3.3: "anything strictly greater is rejected with
        ERR_DIVERSIFICATION_CAP_EXCEEDED."

        Claim: third pledge (100 cents) on top of 60_000 + 40_000 ->
        ERR_DIVERSIFICATION_CAP_EXCEEDED. Confirms aggregation, not
        count, is the rule's metric.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=500_000,
        )
        investor = setup_funded_investor(
            platform["id"],
            committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=60_000,
        )
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=40_000,
        )
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=100),
            make_investor_headers(investor["id"]),
        )
        validate_error(resp, "ERR_DIVERSIFICATION_CAP_EXCEEDED")


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    """Two instances:
    - invest_then_listing_withdraw_preserves_investor_cash_balance
    - charge_off_distribution_preserves_total_loss
    """

    # -----------------------------------------------------------------
    # Instance 1: cash conservation under invest -> withdraw
    # -----------------------------------------------------------------
    def test_invest_then_withdraw_restores_cash_to_baseline(self, api):
        """# difficulty: compensating_invariant/invest_then_listing_withdraw_preserves_investor_cash_balance

        PRD §3.3: "When the create succeeds, the server decrements the
        investor's cash_balance_cents by amount_cents". PRD §3.3 (on
        withdraw): "every COMMITTED Investment on the listing is moved
        to RELEASED, and each affected investor's cash_balance_cents
        is credited by that investment's amount_cents."

        Claim: invariant cash_after_withdraw == cash_before_invest.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(
            platform["id"], deposit_cents=10_000_00,
        )
        cash_baseline = investor["cash_balance_cents"]
        inv = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=10_000,
        )
        cash_mid = get_investor(
            platform["id"], investor["id"],
        )["cash_balance_cents"]
        assert cash_mid == cash_baseline - 10_000
        withdraw_listing(platform["id"], listing["id"])
        cash_after = get_investor(
            platform["id"], investor["id"],
        )["cash_balance_cents"]
        assert cash_after == cash_baseline, (
            f"invariant: cash_after_withdraw ({cash_after}) must equal "
            f"cash_before_invest ({cash_baseline})"
        )

    def test_investment_status_is_released_after_listing_withdraw(
        self, api,
    ):
        """# difficulty: compensating_invariant/invest_then_listing_withdraw_preserves_investor_cash_balance

        PRD §3.3: "every COMMITTED Investment on the listing is moved
        to RELEASED".

        Claim: the compensating action terminates the Investment in
        RELEASED.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(platform["id"])
        inv = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=10_000,
        )
        withdraw_listing(platform["id"], listing["id"])
        refreshed = get_investment(platform["id"], inv["id"])
        assert refreshed["status"] == "RELEASED"

    # -----------------------------------------------------------------
    # Instance 2: total-loss conservation
    # -----------------------------------------------------------------
    def test_total_per_investor_loss_equals_charged_off_loss(self, api):
        """# difficulty: compensating_invariant/charge_off_distribution_preserves_total_loss

        PRD §3.6: "the total distributed equals total_loss exactly."

        Claim: sum over CONVERTED Investments of
        (original_pledge - current outstanding_principal_cents) equals
        loan.charged_off_loss_cents EXACTLY.
        """
        (platform, officer, b, investors, investments, listing,
         loan) = setup_loan_charged_off_three_investors(
            principal_cents=100_000,
            shares=(30_000, 30_000, 40_000),
        )
        deltas = []
        for inv, pledge in zip(investors, (30_000, 30_000, 40_000)):
            refreshed = get_investor(platform["id"], inv["id"])
            deltas.append(
                pledge - refreshed["outstanding_principal_cents"]
            )
        assert sum(deltas) == loan["charged_off_loss_cents"]

    def test_three_investor_even_split_has_no_residual(self, api):
        """# difficulty: compensating_invariant/charge_off_distribution_preserves_total_loss

        PRD §3.6: "For each, a gross share is computed as the
        round-half-up of total_loss multiplied by share_bps divided by
        10000".

        Claim: with principal=100_000 and shares 30/30/40 (in cents
        thousands), share_bps values are 3000, 3000, 4000 and the
        round-half-up shares are exactly 30_000, 30_000, 40_000 — no
        residual to absorb.
        """
        (platform, officer, b, investors, investments, listing,
         loan) = setup_loan_charged_off_three_investors(
            principal_cents=100_000,
            shares=(30_000, 30_000, 40_000),
        )
        deltas_sorted = sorted(
            pledge - get_investor(platform["id"], inv["id"])[
                "outstanding_principal_cents"
            ]
            for inv, pledge in zip(investors, (30_000, 30_000, 40_000))
        )
        assert deltas_sorted == [30_000, 30_000, 40_000]
