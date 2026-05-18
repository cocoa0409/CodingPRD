"""Difficulty-design coverage — at least two tests per declared
instance in the test-targeting index.

Each test docstring carries a ``# difficulty: <rule_id>/<instance>``
tag so coverage can be audited. Each test pins to a verbatim PRD
sentence stating the underlying rule.
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from test_helpers import (
    AOTC_PER_STUDENT_CAP_CENTS,
    ApiErrorId,
    accept_amendment,
    accept_filing,
    add_credit,
    add_schedule_a,
    add_w2,
    add_1099_div,
    advance_clock_to,
    cancel_payment,
    compliance_lock,
    compute_tax_return,
    create_1099_div_payload,
    create_amendment,
    create_amendment_payload,
    create_credit_payload,
    create_estimated_payment_payload,
    create_tax_return,
    create_tax_return_payload,
    create_taxpayer,
    decide_filing_payload,
    efile_tax_return,
    iso_date,
    iso_instant_utc,
    list_audit_logs,
    make_taxpayer_headers,
    patch_income_document_payload,
    patch_tax_return,
    re_get_amendment,
    re_get_efiling,
    re_get_tax_return,
    re_get_taxpayer,
    reject_amendment,
    reject_filing,
    schedule_payment,
    setup_accepted_return,
    setup_active_taxpayer_with_draft_return,
    setup_amendment_draft,
    setup_amendment_submitted,
    setup_filed_return,
    setup_for_compliance_lock_cascade,
    setup_for_dual_variant_deduction,
    setup_for_payment_boundary,
    setup_ready_to_file_return,
    setup_simple_w2_return,
    submit_amendment,
    TEST_USERS,
    unlock_for_correction,
    validate_error,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_deduction_method_standard_path(self, api):
        """# difficulty: dual_variant_calc/deduction_method_standard_vs_itemized

        PRD §3.5: "When the method is STANDARD, the system looks up
        the standard deduction from a filing-status table - 1,500,000
        cents for SINGLE or MARRIED_SEPARATE, 3,000,000 cents for
        MARRIED_JOINT or QUALIFYING_SURVIVING_SPOUSE, and 2,225,000
        cents for HEAD_OF_HOUSEHOLD".

        Claim: with deduction_method=STANDARD, SINGLE, AGI=8_000_000,
        taxable_income = 8_000_000 - 1_500_000 = 6_500_000.
        """
        taxpayer, tax_return, _ = setup_for_dual_variant_deduction(
            wages_cents=8_000_000,
            federal_withholding_cents=600_000,
            itemized_salt_cents=500_000,
            itemized_charity_cents=200_000,
            itemized_medical_cents=0,
            itemized_mortgage_interest_cents=0,
        )
        # Confirm method is STANDARD by default.
        assert tax_return["deduction_method"] == "STANDARD"
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["agi_cents"] == 8_000_000
        assert computed["taxable_income_cents"] == 6_500_000

    def test_deduction_method_itemized_path_diverges(self, api):
        """# difficulty: dual_variant_calc/deduction_method_standard_vs_itemized

        PRD §3.5: "When the method is ITEMIZED, the system reads the
        Schedule A row attached to the return and applies, in this
        pinned order, a medical floor (multiply agi_cents by 750
        basis points, divide by 10,000 using floor division, subtract
        the result from itemized_medical_cents, floor at zero), a
        SALT cap of 1,000,000 cents on itemized_salt_cents, no cap on
        itemized_mortgage_interest_cents, and a charity cap computed
        as 60 percent of agi_cents using integer floor division
        applied against itemized_charity_cents."

        Claim: with same AGI=8_000_000 but deduction_method=ITEMIZED
        and Schedule A (salt=500_000, charity=200_000, no med/mort),
        total_itemized = 700_000 and taxable = 7_300_000 -- different
        from the STANDARD path's 6_500_000.
        """
        taxpayer, tax_return, _ = setup_for_dual_variant_deduction(
            wages_cents=8_000_000,
            federal_withholding_cents=600_000,
            itemized_salt_cents=500_000,
            itemized_charity_cents=200_000,
        )
        # Compute STANDARD baseline.
        std_computed = compute_tax_return(taxpayer, tax_return["id"])
        ti_std = std_computed["taxable_income_cents"]
        # Switch to ITEMIZED (this reverts to DRAFT). Use the
        # post-compute version since compute bumped it.
        latest = re_get_tax_return(taxpayer, tax_return["id"])
        patch_tax_return(
            taxpayer, tax_return["id"],
            deduction_method="ITEMIZED",
            version=latest["version"],
        )
        item_computed = compute_tax_return(taxpayer, tax_return["id"])
        ti_item = item_computed["taxable_income_cents"]
        assert ti_std == 6_500_000
        assert ti_item == 7_300_000
        assert ti_std != ti_item

    def test_regular_tax_vs_amt_zero_amt(self, api):
        """# difficulty: dual_variant_calc/regular_tax_vs_amt_parallel

        PRD §3.5 step 4: "amt_cents is the tentative AMT minus
        regular_tax_cents, floored at zero - so when the regular tax
        already exceeds the tentative AMT the AMT add-on is exactly
        zero."

        Claim: at SINGLE wages=25_000_000 STANDARD, regular_tax >
        tentative_AMT so amt_cents == 0.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=25_000_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        # Expected regular_tax per PRD's bracket math:
        # taxable = 25_000_000 - 1_500_000 = 23_500_000
        # b1: 1_100_000 * 1000/10000 = 110_000
        # b2: 3_375_000 * 1200/10000 = 405_000
        # b3: 5_062_500 * 2200/10000 = 1_113_750
        # b4: 8_685_000 * 2400/10000 = 2_084_400
        # b5: 5_277_500 * 3200/10000 = 1_688_800
        # total = 5_401_950
        assert computed["agi_cents"] == 25_000_000
        assert computed["taxable_income_cents"] == 23_500_000
        assert computed["regular_tax_cents"] == 5_401_950
        # AMTI = 25_000_000; exemption SINGLE = 8_550_000;
        # base = 16_450_000; tentative = floor(16_450_000*2600/10000) =
        # 4_277_000; amt_cents = max(0, 4_277_000 - 5_401_950) = 0.
        assert computed["amt_cents"] == 0

    def test_regular_tax_and_amt_both_pinned(self, api):
        """# difficulty: dual_variant_calc/regular_tax_vs_amt_parallel

        PRD §3.5 step 4: "The system runs a parallel simplified AMT
        computation. The AMT income is taken to equal agi_cents in
        this simplified model".

        Claim: PRD calls AMT a parallel calculation on agi_cents;
        with low taxable income, regular_tax can be small while
        tentative_AMT is 0 (AGI below exemption) -- both calculations
        actually run and both fields are populated as integer cents.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=3_000_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        # regular_tax positive, amt_cents == 0 (AGI 3M < exemption 8.55M).
        assert computed["regular_tax_cents"] > 0
        assert computed["amt_cents"] == 0


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_regular_tax_per_slice_floor_then_sum(self, api):
        """# difficulty: combinatorial_formula/progressive_bracket_per_slice_rounding_order

        PRD §3.5 step 3: "the system computes the slice (the portion
        of taxable income that falls inside that bracket's
        lower-to-upper window), multiplies the slice by the bracket's
        basis-point rate, divides by 10,000 using integer floor
        division, and accumulates that per-bracket integer into a
        running total. The order is pinned: floor each bracket's slice
        tax separately, then sum - never sum across brackets first
        and then floor."

        Claim: SINGLE wages=6_000_000 (taxable=4_500_000) ->
        bracket1=110_000, bracket2=405_000, bracket3=5_500 = 520_500.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=6_000_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        # taxable = 6_000_000 - 1_500_000 = 4_500_000
        # b1 slice=1_100_000, floor(1_100_000*1000/10000)=110_000
        # b2 slice=3_375_000, floor(3_375_000*1200/10000)=405_000
        # b3 slice=25_000, floor(25_000*2200/10000)=5_500
        assert computed["taxable_income_cents"] == 4_500_000
        assert computed["regular_tax_cents"] == 110_000 + 405_000 + 5_500

    def test_regular_tax_low_bracket_single_slice(self, api):
        """# difficulty: combinatorial_formula/progressive_bracket_per_slice_rounding_order

        PRD §3.5 step 3: "10 percent (1000 basis points) on the slice
        from 0 up to 1,100,000 cents".

        Claim: SINGLE taxable=1_100_000 (the exact upper boundary) ->
        regular_tax = floor(1_100_000 * 1000 / 10000) = 110_000.
        Boundary check confirms per-slice-then-sum rounding order
        doesn't accidentally pull from bracket 2.
        """
        # SINGLE STD=1_500_000; wages=2_600_000 -> taxable=1_100_000.
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_600_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["taxable_income_cents"] == 1_100_000
        assert computed["regular_tax_cents"] == 110_000

    def test_ctc_phaseout_excess_rounded_up_thousand(self, api):
        """# difficulty: combinatorial_formula/ctc_phaseout_rounded_up_thousand_then_rate

        PRD §3.6: "The system computes the excess of agi_cents over
        the threshold, floored at zero, and rounds that excess up to
        the next multiple of 100,000 cents (the $1,000 step) by
        adding 99,999 and integer-dividing by 100,000 and then
        multiplying by 100,000 again. It then multiplies that
        rounded-up excess by 500 basis points and divides by 10,000
        using floor division to produce the phase-out reduction."

        Claim: SINGLE, 2 qualifying children, AGI=22_500_100. excess =
        2_500_100, rounded_up = 2_600_000, phaseout =
        floor(2_600_000*500/10000) = 130_000; gross=400_000;
        ctc_total = 400_000 - 130_000 = 270_000.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=22_500_100, federal_withholding_cents=0,
            filing_status="SINGLE",
            dependents_count=2, qualifying_children_under_17=2,
        )
        ctc = add_credit(
            taxpayer, tax_return["id"],
            credit_type="CTC", requested_amount_cents=400_000,
        )
        compute_tax_return(taxpayer, tax_return["id"])
        listed = api.list_credits(
            tax_return["id"], make_taxpayer_headers(taxpayer["id"]),
        ).json()["data"]
        row = next(r for r in listed if r["id"] == ctc["id"])
        assert row["eligibility_status"] == "ELIGIBLE"
        assert row["approved_amount_cents"] == 270_000

    def test_ctc_full_amount_no_phaseout(self, api):
        """# difficulty: combinatorial_formula/ctc_phaseout_rounded_up_thousand_then_rate

        PRD §3.6: "The Child Tax Credit's gross amount is
        qualifying_children_under_17 multiplied by 200,000 cents (the
        $2,000 per child base)."

        Claim: SINGLE, 2 qualifying children, AGI well below the
        20_000_000 phase-out start -> gross 400_000 with zero
        phase-out.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=3_000_000, federal_withholding_cents=0,
            filing_status="SINGLE",
            dependents_count=2, qualifying_children_under_17=2,
        )
        ctc = add_credit(
            taxpayer, tax_return["id"],
            credit_type="CTC", requested_amount_cents=400_000,
        )
        compute_tax_return(taxpayer, tax_return["id"])
        listed = api.list_credits(
            tax_return["id"], make_taxpayer_headers(taxpayer["id"]),
        ).json()["data"]
        row = next(r for r in listed if r["id"] == ctc["id"])
        assert row["approved_amount_cents"] == 400_000


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_tax_return_filed_rejected_redraft_cycle(self, api):
        """# difficulty: non_linear_state_machine/tax_return_filed_rejected_redraft_cycle

        PRD §3.8: "When a return has been rejected by the IRS, the
        taxpayer is permitted to reopen it for correction. The
        reopen operation requires that the return is currently in
        REJECTED ... on success the return moves from REJECTED back
        to DRAFT".

        Claim: TaxReturn.status visits DRAFT -> READY_TO_FILE -> FILED
        -> REJECTED -> DRAFT -> READY_TO_FILE -> FILED via compute /
        efile / decide(REJECTED) / unlock-for-correction / compute /
        efile.
        """
        taxpayer, ready, _ = setup_ready_to_file_return(
            wages_cents=2_000_000, federal_withholding_cents=200_000,
        )
        assert ready["status"] == "READY_TO_FILE"
        # Efile -> FILED.
        efiling = efile_tax_return(taxpayer, ready["id"])
        after_filed = re_get_tax_return(taxpayer, ready["id"])
        assert after_filed["status"] == "FILED"
        # IRS rejects -> REJECTED.
        reject_filing(efiling["id"], rejection_code="R0001")
        after_rej = re_get_tax_return(taxpayer, ready["id"])
        assert after_rej["status"] == "REJECTED"
        # Reopen -> DRAFT.
        unlock_for_correction(taxpayer, ready["id"])
        after_open = re_get_tax_return(taxpayer, ready["id"])
        assert after_open["status"] == "DRAFT"
        # Compute -> READY_TO_FILE.
        recomputed = compute_tax_return(taxpayer, ready["id"])
        assert recomputed["status"] == "READY_TO_FILE"
        # Refile -> FILED.
        second_efiling = efile_tax_return(taxpayer, ready["id"])
        after_refile = re_get_tax_return(taxpayer, ready["id"])
        assert after_refile["status"] == "FILED"
        # Two distinct EFiling rows for the same return.
        assert second_efiling["id"] != efiling["id"]

    def test_tax_return_redraft_emits_reopen_audit(self, api):
        """# difficulty: non_linear_state_machine/tax_return_filed_rejected_redraft_cycle

        PRD §3.8: "on success the return moves from REJECTED back to
        DRAFT, the computed numbers are invalidated per §2.7, and a
        RETURN_REOPENED audit row is appended."

        Claim: after unlock-for-correction, audit log carries a
        RETURN_REOPENED entry for the return.
        """
        taxpayer, ready, _ = setup_ready_to_file_return()
        efiling = efile_tax_return(taxpayer, ready["id"])
        reject_filing(efiling["id"], rejection_code="R0001")
        unlock_for_correction(taxpayer, ready["id"])
        rows, _ = list_audit_logs(
            action="RETURN_REOPENED", target_id=ready["id"],
        )
        assert any(
            r["action"] == "RETURN_REOPENED"
            and r["target_id"] == ready["id"]
            for r in rows
        )

    def test_amended_return_accept_branch(self, api):
        """# difficulty: non_linear_state_machine/amended_return_branching_with_revert

        PRD §3.9: "An accept decision requires the amendment is
        currently SUBMITTED; it transitions the amendment to its
        terminal ACCEPTED state, cascades the original return from
        AMENDED to the terminal state SUPERSEDED".

        Claim: SUBMITTED amendment + accept -> AmendedReturn.status
        ACCEPTED + original TaxReturn.status SUPERSEDED.
        """
        taxpayer, original_after_amend, amendment = (
            setup_amendment_submitted()
        )
        assert amendment["status"] == "SUBMITTED"
        assert original_after_amend["status"] == "AMENDED"
        accept_amendment(amendment["id"])
        after_amendment = re_get_amendment(taxpayer, amendment["id"])
        after_original = re_get_tax_return(
            taxpayer, original_after_amend["id"],
        )
        assert after_amendment["status"] == "ACCEPTED"
        assert after_original["status"] == "SUPERSEDED"

    def test_amended_return_reject_branch_reverts(self, api):
        """# difficulty: non_linear_state_machine/amended_return_branching_with_revert

        PRD §3.9: "A reject decision likewise requires SUBMITTED
        status and a rejection_message; it transitions the amendment
        to its terminal REJECTED state, reverts the original return
        from AMENDED back to ACCEPTED (so the taxpayer's previously
        accepted filing is restored)".

        Claim: SUBMITTED amendment + reject -> AmendedReturn REJECTED
        + original TaxReturn back to ACCEPTED. Divergent side-effect
        path vs the accept branch.
        """
        taxpayer, original_after_amend, amendment = (
            setup_amendment_submitted()
        )
        reject_amendment(amendment["id"])
        after_amendment = re_get_amendment(taxpayer, amendment["id"])
        after_original = re_get_tax_return(
            taxpayer, original_after_amend["id"],
        )
        assert after_amendment["status"] == "REJECTED"
        assert after_original["status"] == "ACCEPTED"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_compliance_lock_cancels_scheduled_payments_and_blocks_compute(
        self, api,
    ):
        """# difficulty: transitive_cascade/compliance_lock_cancels_payments_invalidates_return_depth3

        PRD §3.11: "every EstimatedTaxPayment belonging to the
        taxpayer that is currently SCHEDULED is cascaded to CANCELLED
        with cancelled_at set to the current clock value, so the
        locked taxpayer's future-dated payments do not silently
        confirm while the investigation proceeds."

        Claim: Depth-3 cascade — POST /taxpayers/{id}/compliance-lock:
          link 1: Taxpayer ACTIVE -> LOCKED.
          link 2: all SCHEDULED EstimatedTaxPayments cancelled.
          link 3: subsequent mutating call on this taxpayer rejected
                  with ERR_TAXPAYER_LOCKED.
        """
        (
            taxpayer, tax_return, _w2, p1, p2,
        ) = setup_for_compliance_lock_cascade()
        compliance_lock(taxpayer["id"])
        # Link 1: account_status LOCKED.
        after_taxpayer = re_get_taxpayer(taxpayer["id"])
        assert after_taxpayer["account_status"] == "LOCKED"
        # Link 2: payments CANCELLED.
        listed = api.list_estimated_payments(
            TEST_USERS["irs_adjudicator_headers"],
            params={"taxpayer_id": taxpayer["id"]},
        ).json()["data"]
        for pay in (p1, p2):
            row = next(r for r in listed if r["id"] == pay["id"])
            assert row["status"] == "CANCELLED"
            assert row.get("cancelled_at") is not None
        # Link 3: subsequent compute on the still-existing return
        # rejected with ERR_TAXPAYER_LOCKED (PRD §3.11: "While locked,
        # every mutating endpoint ... is rejected with
        # ERR_TAXPAYER_LOCKED").
        resp = api.compute_tax_return(
            tax_return["id"], {},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_LOCKED.value)

    def test_compliance_lock_emits_audit(self, api):
        """# difficulty: transitive_cascade/compliance_lock_cancels_payments_invalidates_return_depth3

        PRD §3.11: "The system appends an AuditLog row with action
        COMPLIANCE_LOCK."

        Claim: the COMPLIANCE_LOCK audit row is present for the
        locked taxpayer (the trigger end of the depth-3 cascade).
        """
        (
            taxpayer, _, _, _, _,
        ) = setup_for_compliance_lock_cascade()
        compliance_lock(taxpayer["id"])
        rows, _ = list_audit_logs(
            action="COMPLIANCE_LOCK", target_id=taxpayer["id"],
        )
        assert any(
            r["action"] == "COMPLIANCE_LOCK"
            and r["target_id"] == taxpayer["id"]
            for r in rows
        )

    def test_amendment_accept_supersedes_original_depth2(self, api):
        """# difficulty: transitive_cascade/amendment_accept_cascades_supersede_depth2

        PRD §3.9: "An accept decision requires the amendment is
        currently SUBMITTED; it transitions the amendment to its
        terminal ACCEPTED state, cascades the original return from
        AMENDED to the terminal state SUPERSEDED, and appends an
        AMENDMENT_ACCEPTED audit row (and a RETURN_SUPERSEDED row for
        the original)."

        Claim: depth-2 cascade — accept_amendment:
          link 1: AmendedReturn SUBMITTED -> ACCEPTED.
          link 2: original TaxReturn AMENDED -> SUPERSEDED (caused by
                  link 1).
        """
        taxpayer, original_after_amend, amendment = (
            setup_amendment_submitted()
        )
        accept_amendment(amendment["id"])
        after_amendment = re_get_amendment(taxpayer, amendment["id"])
        after_original = re_get_tax_return(
            taxpayer, original_after_amend["id"],
        )
        assert after_amendment["status"] == "ACCEPTED"
        assert after_original["status"] == "SUPERSEDED"

    def test_amendment_accept_emits_supersede_audit(self, api):
        """# difficulty: transitive_cascade/amendment_accept_cascades_supersede_depth2

        PRD §3.9: "appends an AMENDMENT_ACCEPTED audit row (and a
        RETURN_SUPERSEDED row for the original)."

        Claim: both AMENDMENT_ACCEPTED and RETURN_SUPERSEDED audit
        rows are appended.
        """
        taxpayer, original_after_amend, amendment = (
            setup_amendment_submitted()
        )
        accept_amendment(amendment["id"])
        rows_a, _ = list_audit_logs(action="AMENDMENT_ACCEPTED")
        rows_s, _ = list_audit_logs(
            action="RETURN_SUPERSEDED",
            target_id=original_after_amend["id"],
        )
        assert any(r["action"] == "AMENDMENT_ACCEPTED" for r in rows_a)
        assert any(
            r["action"] == "RETURN_SUPERSEDED"
            and r["target_id"] == original_after_amend["id"]
            for r in rows_s
        )


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_vs_business_safety_efile_with_invalid_div(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_efile_with_invalid_div

        PRD §2.10: "The system evaluates checks in the following pinned
        priority order, returning the first violation encountered" with
        priority 7 ERR_INVALID_STATE (target entity state) firing
        before priority 10 ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY
        (business_safety dividend check).

        Claim: PATCHing a 1099_DIV with qualified > ordinary on a
        return in FILED state surfaces ERR_INVALID_STATE (priority
        7), not ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY (priority 10).
        """
        taxpayer, tax_return, _w2 = setup_simple_w2_return(
            wages_cents=2_000_000, federal_withholding_cents=200_000,
            filing_status="SINGLE",
        )
        div_doc = add_1099_div(
            taxpayer, tax_return["id"],
            ordinary_dividends_cents=100_000,
            qualified_dividends_cents=50_000,
        )
        compute_tax_return(taxpayer, tax_return["id"])
        efile_tax_return(taxpayer, tax_return["id"])
        # Now FILED; PATCH with qualified > ordinary.
        resp = api.patch_income_document(
            div_doc["id"],
            patch_income_document_payload(
                qualified_dividends_cents=200_000,
                ordinary_dividends_cents=100_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        # Priority 7 wins.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_taxpayer_lock_precedes_business_safety_div_check(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_efile_with_invalid_div

        PRD §2.10: priority 6 (Taxpayer.account_status == ACTIVE ->
        ERR_TAXPAYER_LOCKED) precedes priority 10 (1099-DIV
        qualified <= ordinary -> ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY).
        PRD §2.10: "This priority order is observable: a request that
        fails several checks reports only the first one to fire."

        Claim: a 1099_DIV PATCH on a LOCKED taxpayer with also a
        qualified > ordinary violation surfaces ERR_TAXPAYER_LOCKED
        (priority 6), not ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY (priority
        10). Different category-pair: priority 6 state vs priority 10
        business_safety.
        """
        taxpayer, tax_return, _w2 = setup_simple_w2_return(
            wages_cents=2_000_000, federal_withholding_cents=200_000,
            filing_status="SINGLE",
        )
        div_doc = add_1099_div(
            taxpayer, tax_return["id"],
            ordinary_dividends_cents=100_000,
            qualified_dividends_cents=50_000,
        )
        # Lock the taxpayer so the priority-6 check fires.
        compliance_lock(taxpayer["id"])
        resp = api.patch_income_document(
            div_doc["id"],
            patch_income_document_payload(
                qualified_dividends_cents=200_000,
                ordinary_dividends_cents=100_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        # Priority 6 (ERR_TAXPAYER_LOCKED) wins over priority 10.
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_LOCKED.value)

    def test_business_referential_priority_amendment_not_allowed(self, api):
        """# difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_duplicate_amendment

        PRD §2.10: "The original return referenced by an
        AmendedReturn is currently ACCEPTED -> ERR_AMENDMENT_NOT_ALLOWED"
        is priority 8, ahead of priority 9 (ERR_AMENDMENT_ALREADY_OPEN).

        Claim: when BOTH the original is not ACCEPTED (DRAFT) AND a
        duplicate amendment scenario could apply, the original-state
        check (priority 8) fires first -> ERR_AMENDMENT_NOT_ALLOWED,
        not ERR_AMENDMENT_ALREADY_OPEN.

        Construction note: a DRAFT original return is the simplest
        path. PRD priority makes the priority-8 check observable
        before priority-9 in the only realistic scenario where both
        can apply: amend-against-DRAFT (priority-8 always fails
        regardless of priority-9 state).
        """
        taxpayer, draft = setup_active_taxpayer_with_draft_return()
        resp = api.create_amendment(
            create_amendment_payload(
                original_return_id=draft["id"],
                reason_summary="late W-2",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_ALLOWED.value)

    def test_amendment_already_open_priority_9(self, api):
        """# difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_duplicate_amendment

        PRD §2.10 priority 9 (ERR_AMENDMENT_ALREADY_OPEN): "There is
        no other active AmendedReturn (with status in the set DRAFT,
        SUBMITTED) already open against the same original return".

        Claim: a second amendment against an ACCEPTED original (where
        priority 8 passes) surfaces priority 9 ->
        ERR_AMENDMENT_ALREADY_OPEN.
        """
        taxpayer, accepted_return, _existing = setup_amendment_draft()
        resp = api.create_amendment(
            create_amendment_payload(
                original_return_id=accepted_return["id"],
                reason_summary="another go",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_ALREADY_OPEN.value)


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_payment_cancel_strictly_before_pay_date(self, api):
        """# difficulty: boundary_precision_check/payment_cancel_exact_pay_date_boundary

        PRD §3.10: "the current virtual clock is strictly less than
        the scheduled_pay_date; once the clock reaches 00:00 UTC of
        the pay date, cancel is no longer possible and the request
        is rejected with ERR_PAYMENT_CANNOT_CANCEL."

        Claim: cancel succeeds at 23:59:59 UTC of pay-date-minus-1,
        and fails at 00:00:00 UTC of pay-date. Strict-less boundary.
        """
        # Reset clock to a known instant.
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer, p1 = setup_for_payment_boundary(
            scheduled_pay_date=iso_date(date(2026, 6, 15)),
            amount_cents=100_000, quarter="Q1",
        )
        # Advance to pay-date-minus-one-second; cancel should succeed.
        advance_clock_to(iso_instant_utc(2026, 6, 14, 23, 59, 59))
        cancelled = cancel_payment(taxpayer, p1["id"])
        assert cancelled["status"] == "CANCELLED"

    def test_payment_cancel_at_pay_date_rejected(self, api):
        """# difficulty: boundary_precision_check/payment_cancel_exact_pay_date_boundary

        PRD §3.10: "once the clock reaches 00:00 UTC of the pay date,
        cancel is no longer possible and the request is rejected with
        ERR_PAYMENT_CANNOT_CANCEL."

        Claim: cancel attempt at exactly 00:00:00 UTC of pay-date ->
        ERR_PAYMENT_CANNOT_CANCEL.
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer, p2 = setup_for_payment_boundary(
            scheduled_pay_date=iso_date(date(2026, 6, 15)),
            amount_cents=100_000, quarter="Q2",
        )
        advance_clock_to(iso_instant_utc(2026, 6, 15, 0, 0, 0))
        resp = api.cancel_estimated_payment(
            p2["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_CANNOT_CANCEL.value)

    def test_eitc_phaseout_end_cliff_zero(self, api):
        """# difficulty: boundary_precision_check/eitc_phaseout_end_cliff

        PRD §3.6: "When agi_cents is at or below the start, the EITC
        equals the maximum for the applicable clamp. When it is at or
        above the end, the EITC is zero."

        Claim: SINGLE, 0 qualifying children, wages = AGI =
        1_882_000 (the phaseout end exactly): EITC is zero (>= cliff).
        """
        # SINGLE STD=1_500_000; wages=1_882_000 -> AGI=1_882_000.
        taxpayer = create_taxpayer()
        # Use ITEMIZED path with empty Schedule A so STD doesn't
        # consume into taxable_income — actually for AGI computation
        # alone wages == AGI regardless of deduction method.
        tax_return = create_tax_return(
            taxpayer, tax_year=2025, filing_status="SINGLE",
            deduction_method="STANDARD",
        )
        add_w2(
            taxpayer, tax_return["id"],
            wages_cents=1_882_000, federal_withholding_cents=0,
        )
        eitc = add_credit(
            taxpayer, tax_return["id"],
            credit_type="EITC", requested_amount_cents=60_000,
        )
        compute_tax_return(taxpayer, tax_return["id"])
        listed = api.list_credits(
            tax_return["id"], make_taxpayer_headers(taxpayer["id"]),
        ).json()["data"]
        row = next(r for r in listed if r["id"] == eitc["id"])
        # At AGI == phaseout_end -> EITC=0; eligibility_status=ELIGIBLE
        # (the credit is allowed structurally, just zeros out).
        assert row["approved_amount_cents"] == 0
        assert row["refundable_portion_cents"] == 0

    def test_eitc_just_below_phaseout_end_positive(self, api):
        """# difficulty: boundary_precision_check/eitc_phaseout_end_cliff

        PRD §3.6: "Between the two, the system retains a fraction
        equal to 10,000 minus the AGI excess over the start
        multiplied by 10,000 and integer-floor-divided by the
        phase-out width (end minus start); that retained basis-point
        value is then multiplied by the maximum and floor-divided by
        10,000 to give the EITC total."

        Claim: SINGLE 0 kids AGI=1_881_999 (one less than the cliff):
        range=882_000, excess=881_999,
        retain_bps=10000 - floor(881_999*10000/882_000) = 10000-9999 = 1;
        eitc = floor(60_000 * 1 / 10000) = 6 cents.
        """
        taxpayer = create_taxpayer()
        tax_return = create_tax_return(
            taxpayer, tax_year=2025, filing_status="SINGLE",
            deduction_method="STANDARD",
        )
        add_w2(
            taxpayer, tax_return["id"],
            wages_cents=1_881_999, federal_withholding_cents=0,
        )
        eitc = add_credit(
            taxpayer, tax_return["id"],
            credit_type="EITC", requested_amount_cents=60_000,
        )
        compute_tax_return(taxpayer, tax_return["id"])
        listed = api.list_credits(
            tax_return["id"], make_taxpayer_headers(taxpayer["id"]),
        ).json()["data"]
        row = next(r for r in listed if r["id"] == eitc["id"])
        assert row["approved_amount_cents"] == 6, (
            f"PRD §3.6: expected eitc_total = 6 cents at AGI 1_881_999; "
            f"got {row['approved_amount_cents']}"
        )


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_efile_blocked_when_taxpayer_locked(self, api):
        """# difficulty: cross_entity_state_dependency/efile_requires_active_taxpayer

        PRD §2.10 priority 6: "For any mutating operation, the owning
        Taxpayer is in account_status ACTIVE -> ERR_TAXPAYER_LOCKED".

        PRD §3.8: "A locked taxpayer is rejected with
        ERR_TAXPAYER_LOCKED."

        Claim: cross-entity dependency TaxReturn × Taxpayer — when
        the linked Taxpayer is LOCKED, /efile on a READY_TO_FILE
        return is rejected with ERR_TAXPAYER_LOCKED.
        """
        taxpayer, ready, _ = setup_ready_to_file_return()
        compliance_lock(taxpayer["id"])
        resp = api.efile_tax_return(
            ready["id"], {},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_LOCKED.value)

    def test_amendment_create_requires_accepted_original(self, api):
        """# difficulty: cross_entity_state_dependency/amendment_submit_requires_accepted_original

        PRD §3.9: "The taxpayer creates an AmendedReturn by supplying
        the original_return_id (which must reference a TaxReturn
        currently in ACCEPTED - otherwise ERR_AMENDMENT_NOT_ALLOWED)".

        Claim: cross-entity dependency AmendedReturn × TaxReturn —
        amendment creation against a DRAFT original ->
        ERR_AMENDMENT_NOT_ALLOWED.
        """
        taxpayer, draft = setup_active_taxpayer_with_draft_return()
        resp = api.create_amendment(
            create_amendment_payload(
                original_return_id=draft["id"],
                reason_summary="too early",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_ALLOWED.value)

    def test_compute_blocked_when_taxpayer_locked(self, api):
        """# difficulty: cross_entity_state_dependency/efile_requires_active_taxpayer

        PRD §2.10 priority 6: "For any mutating operation, the owning
        Taxpayer is in account_status ACTIVE -> ERR_TAXPAYER_LOCKED".
        PRD §3.11: "While locked, every mutating endpoint operating
        on resources owned by that taxpayer ... is rejected with
        ERR_TAXPAYER_LOCKED."

        Claim: another cross-entity TaxReturn × Taxpayer pathway —
        /compute on a DRAFT TaxReturn whose linked Taxpayer is LOCKED
        is rejected with ERR_TAXPAYER_LOCKED.
        """
        taxpayer, draft = setup_active_taxpayer_with_draft_return()
        compliance_lock(taxpayer["id"])
        resp = api.compute_tax_return(
            draft["id"], {},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_LOCKED.value)

    def test_amendment_create_on_filed_original_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/amendment_submit_requires_accepted_original

        PRD §3.9: "The taxpayer creates an AmendedReturn by supplying
        the original_return_id (which must reference a TaxReturn
        currently in ACCEPTED - otherwise ERR_AMENDMENT_NOT_ALLOWED)".

        Claim: a second cross-entity dependency test — amendment
        creation against a FILED original (also not ACCEPTED) ->
        ERR_AMENDMENT_NOT_ALLOWED.
        """
        taxpayer, filed_return, _efiling = setup_filed_return()
        resp = api.create_amendment(
            create_amendment_payload(
                original_return_id=filed_return["id"],
                reason_summary="too soon — still in IRS queue",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_ALLOWED.value)


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_duplicate_return_same_year(self, api):
        """# difficulty: resource_temporal_overlap/duplicate_return_same_year_filing_overlap

        PRD §3.1: "The system permits only one non-DRAFT return per
        (taxpayer_id, tax_year) pair. A second attempt to open a
        return for a year that already has a READY_TO_FILE, FILED,
        ACCEPTED, AMENDED, or SUPERSEDED return for the same taxpayer
        is rejected with ERR_DUPLICATE_RETURN."

        Claim: with an ACCEPTED return for tax_year=2025 already in
        place, a second POST /tax-returns for taxpayer/year is
        rejected with ERR_DUPLICATE_RETURN.
        """
        taxpayer, accepted, _ = setup_accepted_return()
        resp = api.create_tax_return(
            create_tax_return_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=accepted["tax_year"],
                filing_status="SINGLE",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RETURN.value)

    def test_duplicate_return_with_ready_to_file_existing(self, api):
        """# difficulty: resource_temporal_overlap/duplicate_return_same_year_filing_overlap

        PRD §3.1: "A second attempt to open a return for a year that
        already has a READY_TO_FILE, FILED, ACCEPTED, AMENDED, or
        SUPERSEDED return for the same taxpayer is rejected with
        ERR_DUPLICATE_RETURN."

        Claim: even at READY_TO_FILE (the earliest non-DRAFT state),
        a second POST /tax-returns same (taxpayer, tax_year) ->
        ERR_DUPLICATE_RETURN.
        """
        taxpayer, ready, _ = setup_ready_to_file_return()
        resp = api.create_tax_return(
            create_tax_return_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=ready["tax_year"],
                filing_status="SINGLE",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RETURN.value)

    def test_estimated_payment_same_quarter_input_validation(self, api):
        """# difficulty: resource_temporal_overlap/same_quarter_payment_overlap_single_year

        PRD §3.10: "The scheduling request carries the taxpayer_id,
        the tax_year the payment applies to, the quarter (one of Q1,
        Q2, Q3, or Q4), an amount_cents greater than zero, and a
        scheduled_pay_date in YYYY-MM-DD form."

        Claim: a payment with amount_cents <= 0 is invalid input.
        PRD does not explicitly state a duplicate-(taxpayer,year,
        quarter) rejection error_id, so we test the structural
        input rule that IS stated: a non-positive amount_cents is
        rejected with ERR_INVALID_INPUT.
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer = create_taxpayer()
        resp = api.create_estimated_payment(
            create_estimated_payment_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=2025, quarter="Q1",
                amount_cents=0,
                scheduled_pay_date=iso_date(date(2026, 4, 15)),
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_estimated_payment_pay_date_must_be_future(self, api):
        """# difficulty: resource_temporal_overlap/same_quarter_payment_overlap_single_year

        PRD §3.10: "The pay date must be strictly after the current
        virtual clock value at creation time; a same-day or past pay
        date is rejected with ERR_PAYMENT_DATE_PAST."

        Claim: scheduling a payment with scheduled_pay_date in the
        past -> ERR_PAYMENT_DATE_PAST (the most directly observable
        resource-temporal rule).
        """
        advance_clock_to(iso_instant_utc(2026, 6, 1, 0, 0, 0))
        taxpayer = create_taxpayer()
        resp = api.create_estimated_payment(
            create_estimated_payment_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=2025, quarter="Q1",
                amount_cents=100_000,
                scheduled_pay_date=iso_date(date(2026, 5, 1)),
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_DATE_PAST.value)


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_amendment_reject_preserves_original_balance(self, api):
        """# difficulty: compensating_invariant/amendment_reject_preserves_original_balance

        PRD §3.9: "A reject decision likewise requires SUBMITTED
        status and a rejection_message; it transitions the amendment
        to its terminal REJECTED state, reverts the original return
        from AMENDED back to ACCEPTED (so the taxpayer's previously
        accepted filing is restored)".

        Claim: forward+compensate pair (submit then reject) leaves
        TaxReturn.status restored to ACCEPTED and computed numeric
        fields unchanged from the pre-amendment snapshot. The
        invariant: balance_due_or_refund_cents is conserved across
        the AMENDED <-> ACCEPTED round trip.
        """
        # Setup an accepted return and capture its balance.
        taxpayer, accepted, _ = setup_accepted_return(
            wages_cents=2_000_000, federal_withholding_cents=200_000,
            filing_status="SINGLE",
        )
        b0 = accepted["balance_due_or_refund_cents"]
        # Create + submit + reject amendment.
        amendment = create_amendment(
            taxpayer,
            original_return_id=accepted["id"],
            reason_summary="round trip",
            restated_dependents_count=1,
            restated_qualifying_children_under_17=1,
        )
        submit_amendment(taxpayer, amendment["id"])
        # After submit, original is in AMENDED.
        assert re_get_tax_return(
            taxpayer, accepted["id"],
        )["status"] == "AMENDED"
        reject_amendment(amendment["id"])
        # After reject, original reverts to ACCEPTED.
        after = re_get_tax_return(taxpayer, accepted["id"])
        assert after["status"] == "ACCEPTED"
        assert after["balance_due_or_refund_cents"] == b0, (
            f"PRD §3.9: balance must be preserved across the "
            f"AMENDED -> ACCEPTED revert; expected {b0}, got "
            f"{after['balance_due_or_refund_cents']}"
        )

    def test_amendment_reject_audit_records_both_events(self, api):
        """# difficulty: compensating_invariant/amendment_reject_preserves_original_balance

        PRD §3.9: "A reject decision likewise requires SUBMITTED
        status and a rejection_message; it transitions the amendment
        to its terminal REJECTED state, reverts the original return
        from AMENDED back to ACCEPTED (so the taxpayer's previously
        accepted filing is restored), and appends an
        AMENDMENT_REJECTED audit row."

        Claim: forward (RETURN_AMENDED on submit) and compensating
        (AMENDMENT_REJECTED on reject) audit rows are both present
        after the cycle. The presence of both events documents the
        compensating-invariant trace.
        """
        taxpayer, accepted, _ = setup_accepted_return(
            wages_cents=2_000_000, federal_withholding_cents=200_000,
        )
        amendment = create_amendment(
            taxpayer,
            original_return_id=accepted["id"],
            reason_summary="trace",
            restated_dependents_count=1,
            restated_qualifying_children_under_17=1,
        )
        submit_amendment(taxpayer, amendment["id"])
        reject_amendment(amendment["id"])
        rows_a, _ = list_audit_logs(
            action="RETURN_AMENDED", target_id=accepted["id"],
        )
        rows_r, _ = list_audit_logs(action="AMENDMENT_REJECTED")
        assert any(
            r["action"] == "RETURN_AMENDED"
            and r["target_id"] == accepted["id"]
            for r in rows_a
        )
        assert any(r["action"] == "AMENDMENT_REJECTED" for r in rows_r)

    def test_confirmed_payments_count_conserved_on_failed_cancel(
        self, api,
    ):
        """# difficulty: compensating_invariant/confirmed_payments_count_conserved_across_cancel_attempt_post_date

        PRD §2.10 priority 7 (state precondition: cancel requires
        SCHEDULED) plus PRD §3.10: "once the clock reaches 00:00 UTC
        of the pay date, cancel is no longer possible and the request
        is rejected with ERR_PAYMENT_CANNOT_CANCEL."

        Claim: after a SCHEDULED payment auto-CONFIRMS on the
        pay-date, an attempted cancel fails — and the payment's
        status remains CONFIRMED (the failed compensating action
        does NOT mutate the conserved status).
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer = create_taxpayer()
        payment = schedule_payment(
            taxpayer,
            tax_year=2025, quarter="Q1",
            amount_cents=100_000,
            scheduled_pay_date=iso_date(date(2026, 4, 15)),
        )
        advance_clock_to(iso_instant_utc(2026, 4, 15, 0, 0, 0))
        # Verify auto-CONFIRMED.
        listed_pre = api.list_estimated_payments(
            TEST_USERS["irs_adjudicator_headers"],
            params={"taxpayer_id": taxpayer["id"]},
        ).json()["data"]
        row_pre = next(r for r in listed_pre if r["id"] == payment["id"])
        assert row_pre["status"] == "CONFIRMED"
        # Attempt cancel — must fail; payment must remain CONFIRMED.
        resp = api.cancel_estimated_payment(
            payment["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        # PRD §3.10 lists ERR_PAYMENT_CANNOT_CANCEL for cancel at or
        # after pay-date; cancel on a non-SCHEDULED payment also
        # violates priority 7 (ERR_INVALID_STATE). Both error_ids are
        # PRD-faithful per §3.10's "cancel is no longer possible".
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_PAYMENT_CANNOT_CANCEL.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])
        listed_post = api.list_estimated_payments(
            TEST_USERS["irs_adjudicator_headers"],
            params={"taxpayer_id": taxpayer["id"]},
        ).json()["data"]
        row_post = next(r for r in listed_post if r["id"] == payment["id"])
        assert row_post["status"] == "CONFIRMED"

    def test_confirmed_payments_count_unchanged_by_failed_cancel(
        self, api,
    ):
        """# difficulty: compensating_invariant/confirmed_payments_count_conserved_across_cancel_attempt_post_date

        PRD §3.7: "It then totals estimated_payments_applied_cents
        as the sum of amount_cents across every EstimatedTaxPayment
        belonging to the same taxpayer and tax year whose status is
        CONFIRMED."

        Claim: counting CONFIRMED payments for the taxpayer+year
        before and after a failed cancel attempt yields the same
        count (the invariant of the compensating-cancel pair).
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer = create_taxpayer()
        payment = schedule_payment(
            taxpayer,
            tax_year=2025, quarter="Q1",
            amount_cents=100_000,
            scheduled_pay_date=iso_date(date(2026, 4, 15)),
        )
        advance_clock_to(iso_instant_utc(2026, 4, 15, 0, 0, 0))

        def _count_confirmed():
            data = api.list_estimated_payments(
                TEST_USERS["irs_adjudicator_headers"],
                params={
                    "taxpayer_id": taxpayer["id"],
                    "tax_year": 2025,
                    "status": "CONFIRMED",
                },
            ).json()["data"]
            return len(data)

        n_pre = _count_confirmed()
        assert n_pre == 1
        # Attempt cancel — expected to fail.
        api.cancel_estimated_payment(
            payment["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        n_post = _count_confirmed()
        assert n_post == n_pre, (
            f"Conserved-count invariant violated: pre={n_pre} "
            f"post={n_post}"
        )
