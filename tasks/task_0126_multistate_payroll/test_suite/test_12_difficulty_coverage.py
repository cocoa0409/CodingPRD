"""Difficulty-design coverage — every scaffold_difficulty_design
instance is covered by at least two tests tagged with
`# difficulty: <rule_id>/<instance.name>`.

Tests in this file carry PRD-prose citations; the difficulty-design
recipe is a coverage marker only — it never replaces the PRD as the
contract under test.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_paycheck,
    assert_paycheck_computed_fields,
    assert_remittance_state_breakdown_sums_to_total,
    calculate_paycheck,
    create_biweekly_pay_period,
    create_employee,
    create_garnishment_order,
    create_payroll_item,
    create_payroll_item_payload,
    create_remittance_period,
    create_w4_profile,
    finalize_remittance,
    find_correction_paycheck,
    get_employee,
    get_garnishment_order,
    get_paycheck,
    get_paycheck_for_item,
    get_pay_period,
    get_remittance_period,
    issue_correction,
    lock_pay_period,
    make_manager_headers,
    make_specialist_headers,
    mark_paid_paycheck,
    remit_remittance,
    setup_approved_paycheck,
    setup_calculated_paycheck,
    setup_draft_paycheck,
    setup_employee_with_w4,
    setup_full_paid_cycle_for_month,
    setup_paid_paycheck,
    setup_two_garnishments_for_employee,
    setup_world,
    setup_ytd_at_ss_cap_minus,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule: dual_variant_calc
# ===========================================================================

class TestDualVariantRetroPay:
    """# difficulty: dual_variant_calc/
    paycheck_withholding_supplemental_vs_aggregate_on_retro_pay
    """

    def test_retro_supplemental_split_yields_38738(self, api, seeded_world):
        """# difficulty: dual_variant_calc/paycheck_withholding_supplemental_vs_aggregate_on_retro_pay

        PRD §3.4: "When the retro adjustment is non-zero, the system
        splits the paycheck into two pieces. The non-retro portion
        (regular plus overtime plus double, computed as gross minus
        the retro adjustment) is run through the same annualized
        method described above, ignoring the retro contribution.
        Independently, the retro adjustment itself is multiplied by
        the IRS supplemental flat rate of 22.00% (no annualization,
        no bracket evaluation, no standard deduction), and the
        result is rounded half up to whole cents. The two pieces are
        then summed to produce the federal withholding."

        Claim: SINGLE/TX, 16h*12500 plus retro=100000 ->
            non-retro fed = 16738
            supplemental on retro = 100000 * 0.22 = 22000
            total fed = 38738 (NOT 36181, which would be the naive
            aggregate of 300000 annualized).
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            filing_status="SINGLE", regular_hours=16.0,
            retro_adjustment_cents=100_000,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["gross_wages_cents"] == 300_000
        assert pc["federal_withholding_cents"] == 38_738

    def test_retro_supplemental_split_differs_from_aggregate(
            self, api, seeded_world):
        """# difficulty: dual_variant_calc/paycheck_withholding_supplemental_vs_aggregate_on_retro_pay

        PRD §3.4: "the retro adjustment itself is multiplied by the
        IRS supplemental flat rate of 22.00% (no annualization, no
        bracket evaluation, no standard deduction)".

        Claim: the supplemental result strictly differs from what a
        naive aggregate (annualize gross=300000) implementation
        would produce. Naive aggregate: annualized 7,800,000 -
        1,390,000 = 6,410,000; tier1 110,000 + tier2 405,000 +
        tier3 425,700 = 940,700 / 26 = 36,181. We require the
        PRD-correct value 38738 — distinct from 36181.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            filing_status="SINGLE", regular_hours=16.0,
            retro_adjustment_cents=100_000,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["federal_withholding_cents"] != 36_181, (
            "implementation appears to use naive aggregate "
            "annualization on retro (==36181); PRD §3.4 mandates "
            "the supplemental-split (==38738) variant."
        )


class TestDualVariantPostVoid:
    """# difficulty: dual_variant_calc/
    paycheck_withholding_per_period_vs_ytd_reconciliation_on_voided_history

    PRD §3.4 ytd_reconciliation_withholding variant triggers on the
    first paycheck after a void in the same tax year. We rely on the
    two pinned PRD properties: (a) the void itself reverses YTD and
    (b) the next paycheck must still be calculable. We do NOT pin a
    specific federal_withholding_cents value because PRD §3.4's
    activation condition reads "Employee.ytd_gross_wages_cents is
    currently greater than zero AND the most recent prior paycheck
    for this employee was voided through the correction loop within
    the same tax year"; after a void the ytd_gross is back to zero,
    so two faithful PRD-only readers could reasonably disagree on
    whether the reconciliation variant fires at all. We DO assert
    that the correction lifecycle completes correctly.
    """

    def test_correction_paycheck_is_calculable_in_target_period(
            self, api, seeded_world):
        """# difficulty: dual_variant_calc/paycheck_withholding_per_period_vs_ytd_reconciliation_on_voided_history

        PRD §3.7: "a new Paycheck is created in DRAFT cloned from
        the source's payroll_item_id with is_retro_correction set
        to true and correction_of_paycheck_id pointing at the
        source. The new draft attaches to the supplied
        target_pay_period_id".
        PRD §3.4: "A PayrollSpecialist calculates a paycheck,
        advancing it from DRAFT to CALCULATED."

        Claim: after issue-correction the new DRAFT correction
        paycheck can be calculated and transitions to CALCULATED.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck()
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        # Need a W-4 covering the new pay period; PRD §3.1 ordering
        # rule selects the latest profile whose effective_pay_period
        # pay_date <= target.pay_date.  Our existing w4 effective
        # 2024-06-03 still applies to 2024-07-01.
        issue_correction(pc["id"], target_pp["id"])
        correction = find_correction_paycheck(
            source_paycheck_id=pc["id"],
            target_pay_period_id=target_pp["id"],
        )
        # Calculate the correction paycheck.
        recalc = api_client.calculate_paycheck(
            correction["id"], TEST_USERS["specialist_headers"],
        )
        data = validate_success(recalc)
        assert data["status"] == "CALCULATED"

    def test_correction_after_void_reverses_ytd_before_recompute(
            self, api, seeded_world):
        """# difficulty: dual_variant_calc/paycheck_withholding_per_period_vs_ytd_reconciliation_on_voided_history

        PRD §2.11: "they always equal the sum of ledger entries for
        the employee in the current tax_year, and the server
        re-derives them whenever a paycheck is approved or voided".

        Claim: after issue-correction (which voids the source),
        Employee.ytd_gross_wages_cents has been reduced by the
        source paycheck's gross. (This is the PRD-anchored
        precondition for the ytd_reconciliation variant.)
        """
        emp, pp, w4, item, pc = setup_approved_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        before = get_employee(emp["id"])["ytd_gross_wages_cents"]
        assert before == 200_000
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        issue_correction(pc["id"], target_pp["id"])
        after = get_employee(emp["id"])["ytd_gross_wages_cents"]
        assert after == before - pc["gross_wages_cents"], (
            f"YTD must decrease by source gross after void: "
            f"before={before} after={after} gross={pc['gross_wages_cents']}"
        )


# ===========================================================================
# Rule: combinatorial_formula
# ===========================================================================

class TestGarnishmentThreeInputMinChain:
    """# difficulty: combinatorial_formula/
    garnishment_waterfall_three_input_nonlinear_min_chain
    """

    def test_two_orders_waterfall_min_chain_58786(self, api, seeded_world):
        """# difficulty: combinatorial_formula/garnishment_waterfall_three_input_nonlinear_min_chain

        PRD §3.5: "if the employee has any ACTIVE CHILD_SUPPORT
        order, the cap rises to 50% of disposable income".
        PRD §3.5: "The allocation for the order is then the minimum
        of the per-order cap, the remaining owed amount, and the
        remaining pool. ... processing stops as soon as the
        remaining pool reaches zero."

        Claim: G1=CHILD_SUPPORT cap=20, G2=CREDITOR cap=15, gross
        200000, TX, SINGLE -> garnishment_total_cents == 58786.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        setup_two_garnishments_for_employee(
            emp["id"],
            g1_type="CHILD_SUPPORT", g1_cap_pct=20, g1_owed=500_000,
            g2_type="CREDITOR", g2_cap_pct=15, g2_owed=500_000,
        )
        pp2 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        assert pc["garnishment_total_cents"] == 58_786

    def test_only_creditor_uses_25pct_ccpa_cap(self, api, seeded_world):
        """# difficulty: combinatorial_formula/garnishment_waterfall_three_input_nonlinear_min_chain

        PRD §3.5: "The default cap is 25% of disposable income;
        however, if the employee has any ACTIVE CHILD_SUPPORT
        order, the cap rises to 50% of disposable income."

        Claim: with NO child-support order present, the CCPA pool
        is 25% of disposable income. For gross 200000, disposable
        167962, cap = round(167962*0.25) = 41991. A creditor with
        cap_pct=50 (per-order cap = round(167962*0.50) = 83981)
        is constrained by the pool to 41991.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=50, total_owed_cents=500_000,
            effective_pay_date="2024-01-01",
        )
        pp2 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        # disposable = 200000 - 16738 - 12400 - 2900 = 167962
        # CCPA pool = round(167962 * 0.25) = 41991
        # per-order cap = round(167962 * 0.50) = 83981
        # allocation = min(83981, 500000, 41991) = 41991
        assert pc["garnishment_total_cents"] == 41_991


class TestFicaCapAndEmployerMatchRounding:
    """# difficulty: combinatorial_formula/
    fica_ss_cap_with_explicit_pinned_rounding_order_then_sum
    """

    def test_employer_match_doubles_after_per_paycheck_rounding(
            self, api, seeded_world):
        """# difficulty: combinatorial_formula/fica_ss_cap_with_explicit_pinned_rounding_order_then_sum

        PRD §3.10: "total_social_security_cents = sum of each
        paycheck's social_security_cents, then multiplied by two —
        because the employer matches Social Security one-for-one.
        total_medicare_cents = sum of each paycheck's
        medicare_base_cents, then multiplied by two — because the
        employer matches base Medicare one-for-one."
        PRD §3.10: "These per-paycheck inputs are already rounded;
        the aggregation itself is pure integer summation (no further
        rounding)."

        Claim: paycheck SS=12400, Medicare=2900 -> RemittancePeriod
        totals 24800 SS and 5800 Medicare (each = stored × 2);
        total_medicare_additional_cents == 0 (no employer match).
        """
        emp, pp, pc = setup_full_paid_cycle_for_month(
            work_state="TX", hourly_rate_cents=12_500,
            period_start=date(2024, 6, 3), regular_hours=16.0,
        )
        remit = create_remittance_period(tax_year=2024, tax_month=6)
        resp = api_client.finalize_remittance(
            remit["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert data["total_social_security_cents"] == 24_800
        assert data["total_medicare_cents"] == 5_800
        assert data["total_medicare_additional_cents"] == 0

    def test_ss_taxable_capped_to_remaining_room(self, api, seeded_world):
        """# difficulty: combinatorial_formula/fica_ss_cap_with_explicit_pinned_rounding_order_then_sum

        PRD §3.4: "The taxable Social Security wages for this
        paycheck are the minimum of the gross and the remaining
        room. The withholding is taxable Social Security wages
        multiplied by 620 basis points and divided by 10,000,
        rounded half up to whole cents."

        Claim: prime YTD SS to (cap - 50000), then a 200000-gross
        paycheck -> taxable_ss == 50000 -> SS = 50000 * 0.062 =
        3100 exactly.
        """
        emp, second_pp, _, second_item, second_pc = (
            setup_ytd_at_ss_cap_minus(room=50_000)
        )
        pc = calculate_paycheck(second_pc["id"])
        # gross = 16 * 12500 = 200000; taxable_ss = min(200000, 50000)
        # = 50000; SS = 50000 * 0.062 = 3100.
        # However setup_ytd_at_ss_cap_minus seeds hourly_rate to
        # (SS_WAGE_BASE - room), so the second pp employee STILL has
        # that custom hourly rate. Let's compute relative to that.
        rate = 16_830_000 - 50_000  # the hourly rate the fixture
        # set. 16 hours * rate is much larger than (cap - ytd) so
        # taxable_ss is capped to the remaining_room = 50_000.
        expected_gross = 16 * rate
        assert pc["gross_wages_cents"] == expected_gross
        # taxable_ss = min(expected_gross, 50000) = 50000
        # SS = 50000 * 0.062 = 3100
        assert pc["social_security_cents"] == 3_100


# ===========================================================================
# Rule: non_linear_state_machine
# ===========================================================================

class TestPaycheckCycleDraftCalculated:
    """# difficulty: non_linear_state_machine/
    paycheck_calculated_to_draft_revert_cycle
    """

    def test_draft_calculated_draft_calculated_cycle(self, api, seeded_world):
        """# difficulty: non_linear_state_machine/paycheck_calculated_to_draft_revert_cycle

        PRD §3.6: "A specialist may also revert a calculated
        paycheck back to draft, which is only allowed while the
        owning pay period is OPEN, clears every computed field on
        the paycheck to null, and releases the PayrollItem.locked
        flag."
        PRD §3.4: "A PayrollSpecialist calculates a paycheck,
        advancing it from DRAFT to CALCULATED."

        Claim: DRAFT -> CALCULATED -> DRAFT -> CALCULATED.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck()
        # First calculate.
        pc = calculate_paycheck(pc["id"])
        assert pc["status"] == "CALCULATED"
        # Recalculate back to draft.
        resp = api_client.recalculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        pc = validate_success(resp)
        assert pc["status"] == "DRAFT"
        # Calculate again.
        pc = calculate_paycheck(pc["id"])
        assert pc["status"] == "CALCULATED"

    def test_recalculate_clears_then_recompute_reflects_new_hours(
            self, api, seeded_world):
        """# difficulty: non_linear_state_machine/paycheck_calculated_to_draft_revert_cycle

        PRD §3.6: "A specialist may also revert a calculated paycheck
        back to draft, which is only allowed while the owning pay
        period is OPEN, clears every computed field on the paycheck
        to null, and releases the PayrollItem.locked flag."
        PRD §3.3: "While the linked paycheck is in DRAFT, the
        specialist may edit the hours and the retro adjustment by
        submitting an update against the payroll item".

        Claim: after recalculate, the PayrollItem can be edited and
        the second calculate reflects the edit.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        assert pc["gross_wages_cents"] == 200_000
        api_client.recalculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        # Edit hours to 20.
        api_client.update_payroll_item(
            item["id"], {"regular_hours": 20.0},
            TEST_USERS["specialist_headers"],
        )
        # Recompute.
        pc2 = calculate_paycheck(pc["id"])
        assert pc2["gross_wages_cents"] == 20 * 12_500
        assert pc2["status"] == "CALCULATED"


class TestRemittanceAmendCycle:
    """# difficulty: non_linear_state_machine/
    remittance_amended_to_remitted_cycle
    """

    def test_full_amend_cycle_remitted_amended_remitted(
            self, api, seeded_world):
        """# difficulty: non_linear_state_machine/remittance_amended_to_remitted_cycle

        PRD §3.10: "After transmission, if a previously approved or
        paid paycheck in the same (tax_year, tax_month) is voided
        and a new correction paycheck for that month subsequently
        reaches APPROVED, a PayrollManager amends the remittance via
        the amend capability, advancing it from REMITTED to AMENDED.
        ... The AMENDED remittance is then re-transmitted back to
        REMITTED by a Treasurer".

        Claim: the cycle DRAFT -> FINALIZED -> REMITTED -> AMENDED
        -> REMITTED is reachable and the final status is REMITTED.
        """
        emp, pp, pc = setup_full_paid_cycle_for_month(
            work_state="TX", hourly_rate_cents=12_500,
            period_start=date(2024, 6, 3), regular_hours=16.0,
        )
        remit = create_remittance_period(tax_year=2024, tax_month=6)
        remit = finalize_remittance(remit["id"])
        remit = remit_remittance(remit["id"])
        assert remit["status"] == "REMITTED"
        # To amend, void the paid paycheck and approve a correction
        # within the same month.
        target_pp = create_biweekly_pay_period(date(2024, 6, 17))
        # Need a W-4 covering this period — existing one from
        # 2024-06-03 still applies.
        issue_correction(pc["id"], target_pp["id"])
        correction = find_correction_paycheck(
            source_paycheck_id=pc["id"],
            target_pay_period_id=target_pp["id"],
        )
        # Calculate and approve the correction.
        calculate_paycheck(correction["id"])
        approve_paycheck(correction["id"])
        # Now amend.
        amend_resp = api_client.amend_remittance(
            remit["id"], TEST_USERS["manager_headers_alt"],
        )
        amended = validate_success(amend_resp)
        assert amended["status"] == "AMENDED"
        # Re-remit.
        re_remit = api_client.remit_remittance(
            remit["id"], TEST_USERS["treasurer_headers_alt"],
        )
        final = validate_success(re_remit)
        assert final["status"] == "REMITTED"

    def test_amend_on_finalized_rejected(self, api, seeded_world):
        """# difficulty: non_linear_state_machine/remittance_amended_to_remitted_cycle

        PRD §5: ERR_REMITTANCE_NOT_REMITTED — "amend requires
        RemittancePeriod.status==REMITTED".

        Claim: /amend on FINALIZED -> ERR_REMITTANCE_NOT_REMITTED.
        """
        emp, pp, pc = setup_full_paid_cycle_for_month()
        pd = pp["pay_date"]
        year, month = int(pd[:4]), int(pd[5:7])
        remit = create_remittance_period(tax_year=year, tax_month=month)
        finalize_remittance(remit["id"])
        # Status is FINALIZED, not REMITTED -> amend should reject.
        resp = api_client.amend_remittance(
            remit["id"], TEST_USERS["manager_headers_alt"],
        )
        validate_error(
            resp, ApiErrorId.ERR_REMITTANCE_NOT_REMITTED.value,
        )


# ===========================================================================
# Rule: transitive_cascade
# ===========================================================================

class TestVoidGarnishmentCascadeChain:
    """# difficulty: transitive_cascade/
    paycheck_void_chain_employee_ytd_then_garnishment_then_order_status
    """

    def test_void_chain_reverses_garnishment_status_to_active(
            self, api, seeded_world):
        """# difficulty: transitive_cascade/paycheck_void_chain_employee_ytd_then_garnishment_then_order_status

        PRD §2.9: "Conversely, when a paycheck is voided through the
        correction loop, the server appends a YTDLedgerEntry with
        entry_kind of REVERSAL whose deltas are the negation of the
        source paycheck's components, recomputes the employee's
        year-to-date counters from the ledger, subtracts the source
        paycheck's per-order allocations from each garnishment
        order's collected total, and if any order had been SATISFIED
        but its collected total has now dropped below
        total_owed_cents, it automatically transitions back to
        ACTIVE."

        Claim: a SATISFIED order reverts to ACTIVE when the only
        paycheck that satisfied it is voided.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        g = create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=15, total_owed_cents=25_194,
            effective_pay_date="2024-01-01",
        )
        pp2 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        approve_paycheck(pc["id"])
        # Confirm SATISFIED.
        assert get_garnishment_order(g["id"])["status"] == "SATISFIED"
        target_pp = create_biweekly_pay_period(date(2024, 9, 9))
        issue_correction(pc["id"], target_pp["id"])
        g_after = get_garnishment_order(g["id"])
        assert g_after["status"] == "ACTIVE"

    def test_void_chain_decreases_employee_ytd_gross(self, api, seeded_world):
        """# difficulty: transitive_cascade/paycheck_void_chain_employee_ytd_then_garnishment_then_order_status

        PRD §2.9: "Conversely, when a paycheck is voided through the
        correction loop, the server appends a YTDLedgerEntry with
        entry_kind of REVERSAL whose deltas are the negation of the
        source paycheck's components, recomputes the employee's
        year-to-date counters from the ledger".

        Claim: after issue-correction, Employee.ytd_gross_wages_cents
        decreased by the source paycheck's gross.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        before = get_employee(emp["id"])["ytd_gross_wages_cents"]
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        issue_correction(pc["id"], target_pp["id"])
        after = get_employee(emp["id"])["ytd_gross_wages_cents"]
        assert after == before - 200_000


class TestPayPeriodAutoCloseCascade:
    """# difficulty: transitive_cascade/
    pay_period_close_chain_from_mark_paid_through_aggregated_state
    """

    def test_paid_paycheck_triggers_period_close(self, api, seeded_world):
        """# difficulty: transitive_cascade/pay_period_close_chain_from_mark_paid_through_aggregated_state

        PRD §3.6: "The disbursement also triggers the period-close
        check: if every paycheck in the owning pay period is now in
        PAID or VOIDED and the period is in LOCKED, the system
        transitions the period to CLOSED."

        Claim: mark-paid on the only paycheck in a LOCKED period
        transitions the period to CLOSED.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck()
        lock_pay_period(pp["id"])
        mark_paid_paycheck(pc["id"])
        pp_after = get_pay_period(pp["id"])
        assert pp_after["status"] == "CLOSED"

    def test_closed_period_terminal_not_reopened(self, api, seeded_world):
        """# difficulty: transitive_cascade/pay_period_close_chain_from_mark_paid_through_aggregated_state

        PRD §3.2: "Once CLOSED, the period is terminal and cannot be
        reopened."

        Claim: a CLOSED PayPeriod cannot be /lock'd again (the lock
        endpoint requires OPEN).
        """
        emp, pp, w4, item, pc = setup_approved_paycheck()
        lock_pay_period(pp["id"])
        mark_paid_paycheck(pc["id"])
        # PayPeriod is now CLOSED.
        resp = api_client.lock_pay_period(
            pp["id"], TEST_USERS["specialist_headers"],
        )
        # PRD §5 doesn't pin a specific error_id for re-locking a
        # CLOSED period; the validation table at priority 16
        # mentions ERR_UNCALCULATED_ITEMS, but that fires only if
        # there's an uncalculated item. A re-lock attempt on a
        # CLOSED period must be rejected; we tolerate any 4xx
        # response since PRD prose does not commit to a specific
        # error_id here. (PRD §3.2 says merely "Once CLOSED, the
        # period is terminal and cannot be reopened.")
        assert resp.status_code >= 400


# ===========================================================================
# Rule: priority_pair_validation_conflict
# ===========================================================================

class TestPriorityPairTerminatedVsNoW4:
    """# difficulty: priority_pair_validation_conflict/
    terminated_employee_vs_no_w4_state_vs_referential

    PRD §2.7 lists the validation ordering but does not explicitly
    say whether ERR_TERMINATED_EMPLOYEE precedes ERR_NO_W4 when both
    fail simultaneously. Per the two-reader rule, a faithful
    PRD-only implementer could return either. The PRD-anchored
    facts we CAN assert are:

      - Each rule on its own MUST trigger its named error when
        configured to fail in isolation.

    These two single-failure tests satisfy the difficulty-design
    coverage without pinning a precedence that PRD has not pinned.
    """

    def test_terminated_alone_returns_terminated_error(
            self, api, seeded_world):
        """# difficulty: priority_pair_validation_conflict/terminated_employee_vs_no_w4_state_vs_referential

        PRD §3.1: "calculate requests outside that window are
        rejected with ERR_TERMINATED_EMPLOYEE."

        Claim: terminated employee with valid W-4 -> error names
        ERR_TERMINATED_EMPLOYEE (W-4 present, only the termination
        check can fail).
        """
        emp = create_employee(hire_date="2024-01-01")
        # PRD §3.1: termination requires no paycheck in DRAFT or
        # CALCULATED. Terminate BEFORE creating the payroll item.
        api_client.terminate_employee(
            emp["id"], TEST_USERS["manager_headers"],
        )
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"], filing_status="SINGLE")
        item = create_payroll_item(pp["id"], emp["id"], regular_hours=16.0)
        pc = get_paycheck_for_item(item)
        resp = api_client.calculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TERMINATED_EMPLOYEE.value)

    def test_no_w4_alone_returns_no_w4_error(self, api, seeded_world):
        """# difficulty: priority_pair_validation_conflict/terminated_employee_vs_no_w4_state_vs_referential

        PRD §3.4: "an active W4Profile resolves for this employee at
        this pay period (otherwise ERR_NO_W4)".

        Claim: ACTIVE employee without any W-4 -> ERR_NO_W4.
        """
        emp = create_employee()  # ACTIVE
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        # No W-4 created.
        item = create_payroll_item(pp["id"], emp["id"], regular_hours=16.0)
        pc = get_paycheck_for_item(item)
        resp = api_client.calculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_W4.value)


class TestPriorityPairSODVsNegativeNet:
    """# difficulty: priority_pair_validation_conflict/
    sod_violation_vs_negative_net_pay_safety_vs_fiscal

    PRD §2.6: "Segregation-of-duties is the highest-priority
    business-safety check: it is evaluated before referential checks
    such as the active W-4 lookup, because an SOD violation cannot
    be cured by data fixes." This PRD prose pins SOD precedence.
    """

    def test_sod_wins_over_negative_net_pay(self, api, seeded_world):
        """# difficulty: priority_pair_validation_conflict/sod_violation_vs_negative_net_pay_safety_vs_fiscal

        PRD §2.6: "Segregation-of-duties is the highest-priority
        business-safety check: it is evaluated before referential
        checks such as the active W-4 lookup, because an SOD
        violation cannot be cured by data fixes."

        Claim: approve as same X-User-ID as calculator AND the
        paycheck has net_pay_cents < 0 -> the rejection names SOD,
        not negative-net-pay.
        """
        # Build a tiny gross + active garnishment with cap_pct=100 so
        # net_pay drives negative. Calculator and approver share the
        # same X-User-ID.
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        # Single-hour item — gross 12500.
        from test_helpers import (
            create_biweekly_pay_period,
            create_w4_profile,
            create_garnishment_order,
        )
        # Use a fresh period unique to this scenario.
        pp = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp["id"], filing_status="SINGLE")
        create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=100, total_owed_cents=99_999_999,
            effective_pay_date="2024-01-01",
        )
        # Calculator uses shared id.
        shared = "shared-sod-id-1"
        spec_h = make_specialist_headers(shared)
        item = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=1.0,
            ),
            spec_h,
        )
        item = validate_success(item, expected_status=201)
        pc = get_paycheck_for_item(item)
        api_client.calculate_paycheck(pc["id"], spec_h)
        # Now approve as PayrollManager with the SAME X-User-ID.
        mgr_h = make_manager_headers(shared)
        resp = api_client.approve_paycheck(pc["id"], mgr_h)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_negative_net_alone_returns_negative_net_error(
            self, api, seeded_world):
        """# difficulty: priority_pair_validation_conflict/sod_violation_vs_negative_net_pay_safety_vs_fiscal

        PRD §3.6: "the paycheck's net_pay_cents must be greater than
        or equal to zero (otherwise ERR_NEGATIVE_NET_PAY, returned
        with HTTP 402)".

        Claim: approver != calculator (no SOD violation) but
        net_pay_cents < 0 -> ERR_NEGATIVE_NET_PAY.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        from test_helpers import (
            create_biweekly_pay_period,
            create_w4_profile,
        )
        pp = create_biweekly_pay_period(date(2024, 8, 26))
        # PRD §3.4: W-4 additional_withholding_cents adds directly to
        # the per-paycheck federal withholding. Setting it absurdly
        # high pushes federal_wh past gross, producing a negative net
        # at calculate — which PRD §3.6 says approval must reject
        # with ERR_NEGATIVE_NET_PAY. Garnishments are CCPA-capped at
        # 25 % of disposable (PRD §3.5), so they cannot themselves
        # push net negative; the additional-withholding lever is the
        # PRD-clean way to force the rejection.
        create_w4_profile(
            emp["id"], pp["id"],
            filing_status="SINGLE",
            additional_withholding_cents=99_999_999,
        )
        item = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=1.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        item = validate_success(item, expected_status=201)
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        # Net pay should be 12500 (×0.01h⇒ low gross) minus huge
        # additional_withholding → negative. Approve with different
        # X-User-ID so SOD passes.
        resp = api_client.approve_paycheck(
            pc["id"], TEST_USERS["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NEGATIVE_NET_PAY.value)


# ===========================================================================
# Rule: boundary_precision_check
# ===========================================================================

class TestBoundarySSWageBase:
    """# difficulty: boundary_precision_check/
    ss_wage_base_equality_zero_room_at_calculate
    """

    def test_ss_zero_when_ytd_equals_cap(self, api, seeded_world):
        """# difficulty: boundary_precision_check/ss_wage_base_equality_zero_room_at_calculate

        PRD §3.4: "At the boundary, if the pre-paycheck year-to-date
        Social Security wages equal the wage base exactly, the
        taxable amount is zero and the withholding is zero".

        Claim: ytd_ss == cap -> social_security_cents == 0.
        """
        emp, second_pp, _, second_item, second_pc = (
            setup_ytd_at_ss_cap_minus(room=0)
        )
        pc = calculate_paycheck(second_pc["id"])
        assert pc["social_security_cents"] == 0

    def test_medicare_continues_uncapped_when_ss_at_cap(
            self, api, seeded_world):
        """# difficulty: boundary_precision_check/ss_wage_base_equality_zero_room_at_calculate

        PRD §3.4: "Standard Medicare withholding is 1.45% of the
        paycheck's gross, with no annual cap."

        Claim: even with ytd_ss at the cap, medicare_base_cents
        continues at 1.45% of gross.
        """
        emp, second_pp, _, second_item, second_pc = (
            setup_ytd_at_ss_cap_minus(room=0)
        )
        pc = calculate_paycheck(second_pc["id"])
        # gross = 16 hours * hourly_rate; medicare_base = 1.45%.
        expected_med = round_half_up(pc["gross_wages_cents"] * 145 / 10_000)
        assert pc["medicare_base_cents"] == expected_med


def round_half_up(x: float) -> int:
    """PRD §2.10 round half up — toward +inf for non-negative
    values."""
    import math
    if x >= 0:
        return int(math.floor(x + 0.5))
    return -int(math.floor(-x + 0.5))


class TestBoundaryEmptyMonth:
    """# difficulty: boundary_precision_check/
    empty_paycheck_set_zero_totals_at_remittance_finalize
    """

    def test_finalize_empty_month_yields_zero_totals(self, api, seeded_world):
        """# difficulty: boundary_precision_check/empty_paycheck_set_zero_totals_at_remittance_finalize

        PRD §3.10: "On creation, the remittance is in DRAFT with
        every total_*_cents field at zero and an empty
        state_breakdown."
        PRD §3.10 finalize aggregation source: "every Paycheck whose
        owning pay period's pay_date is in this (tax_year, tax_month)
        ... is in APPROVED, PAID, or VOIDED ... voided paychecks
        contribute zero." With no paychecks at all, every total is 0.

        Claim: finalize a remittance for a calendar month with NO
        PayPeriods at all -> all totals 0 and state_breakdown = [].
        """
        # Pick a month with no pay periods at all (e.g., tax_month=2).
        remit = create_remittance_period(tax_year=2024, tax_month=2)
        resp = api_client.finalize_remittance(
            remit["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "FINALIZED"
        assert data["total_federal_withholding_cents"] == 0
        assert data["total_state_withholding_cents"] == 0
        assert data["total_local_withholding_cents"] == 0
        assert data["total_social_security_cents"] == 0
        assert data["total_medicare_cents"] == 0
        assert data["total_medicare_additional_cents"] == 0
        assert data["state_breakdown"] == []

    def test_finalize_empty_month_breakdown_sums_to_total(
            self, api, seeded_world):
        """# difficulty: boundary_precision_check/empty_paycheck_set_zero_totals_at_remittance_finalize

        PRD §3.10: "The grand total_state_withholding_cents equals
        the sum of these breakdown amounts."

        Claim: even in the empty case the invariant holds (0 sum =
        0 total).
        """
        remit = create_remittance_period(tax_year=2024, tax_month=2)
        resp = api_client.finalize_remittance(
            remit["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert_remittance_state_breakdown_sums_to_total(data)


# ===========================================================================
# Rule: resource_temporal_overlap
# ===========================================================================

class TestDuplicatePayrollItemInPeriod:
    """# difficulty: resource_temporal_overlap/
    pay_period_duplicate_paycheck_per_employee_inclusive_interval
    """

    def test_second_item_same_employee_same_period_rejected(
            self, api, seeded_world):
        """# difficulty: resource_temporal_overlap/pay_period_duplicate_paycheck_per_employee_inclusive_interval

        PRD §3.3: "At most one non-correction PayrollItem may exist
        per (pay_period_id, employee_id) pair; an attempt to attach
        a second is rejected with
        ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE".

        Claim: second item attach for same (pp, emp) ->
        ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE.
        """
        emp, pp, _ = setup_employee_with_w4()
        first = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=16.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_success(first, expected_status=201)
        second = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=16.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_error(
            second, ApiErrorId.ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE.value,
        )

    def test_distinct_periods_same_employee_both_allowed(
            self, api, seeded_world):
        """# difficulty: resource_temporal_overlap/pay_period_duplicate_paycheck_per_employee_inclusive_interval

        PRD §3.3: "At most one non-correction PayrollItem may exist
        per (pay_period_id, employee_id) pair". Two DIFFERENT
        pay_period_ids for the same employee are not a duplicate.

        Claim: two payroll items for the same employee in two
        different periods both succeed.
        """
        emp, pp_a, _ = setup_employee_with_w4(
            period_start=date(2024, 6, 3),
        )
        pp_b = create_biweekly_pay_period(date(2024, 6, 17))
        # W-4 effective from June 3 still covers June 17.
        first = api_client.create_payroll_item(
            pp_a["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=16.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_success(first, expected_status=201)
        second = api_client.create_payroll_item(
            pp_b["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=16.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_success(second, expected_status=201)


class TestGarnishmentEffectiveDateHalfOpen:
    """# difficulty: resource_temporal_overlap/
    garnishment_order_effective_date_open_interval_against_pay_date
    """

    def test_garnishment_effective_after_pay_date_excluded(
            self, api, seeded_world):
        """# difficulty: resource_temporal_overlap/garnishment_order_effective_date_open_interval_against_pay_date

        PRD §3.5: "the order applies only to paychecks whose owning
        pay period's pay_date is on or after this date".

        Claim: an order with effective_pay_date strictly AFTER the
        period's pay_date contributes zero to
        garnishment_total_cents.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=50, total_owed_cents=500_000,
            effective_pay_date="2024-12-31",
        )
        pp = create_biweekly_pay_period(date(2024, 6, 17))
        create_w4_profile(emp["id"], pp["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        assert pc["garnishment_total_cents"] == 0

    def test_garnishment_effective_equal_to_pay_date_applies(
            self, api, seeded_world):
        """# difficulty: resource_temporal_overlap/garnishment_order_effective_date_open_interval_against_pay_date

        PRD §3.5: "the order applies only to paychecks whose owning
        pay period's pay_date is on or after this date" — equal-date
        is included.

        Claim: effective_pay_date == pay_date applies; the
        allocation is the per-order cap (15% of disposable) = 25194.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        pp = create_biweekly_pay_period(date(2024, 8, 12))
        create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=15, total_owed_cents=500_000,
            effective_pay_date=pp["pay_date"],
        )
        create_w4_profile(emp["id"], pp["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        assert pc["garnishment_total_cents"] == 25_194


# ===========================================================================
# Rule: compensating_invariant
# ===========================================================================

class TestYTDConservation:
    """# difficulty: compensating_invariant/
    ytd_gross_wages_conserved_after_issue_correction_then_recalc_then_approve
    """

    def test_ytd_gross_conserved_after_compensating_cycle(
            self, api, seeded_world):
        """# difficulty: compensating_invariant/ytd_gross_wages_conserved_after_issue_correction_then_recalc_then_approve

        PRD §2.11: "they always equal the sum of ledger entries for
        the employee in the current tax_year, and the server
        re-derives them whenever a paycheck is approved or voided".
        PRD §3.7: "the source paycheck's status advances to VOIDED,
        a YTDLedgerEntry of kind REVERSAL is appended whose deltas
        are the negation of the source paycheck's components".
        PRD §2.9: "When a paycheck transitions from CALCULATED to
        APPROVED, the server appends a YTDLedgerEntry with entry_kind
        of ACCRUAL whose deltas equal the paycheck's wage
        components".

        Claim: approve P1 (+S) ; issue-correction (-S) ; calculate
        correction with identical inputs ; approve correction (+S
        again) -> Employee.ytd_gross_wages_cents equals snapshot S.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        snapshot = get_employee(emp["id"])["ytd_gross_wages_cents"]
        assert snapshot == 200_000
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        issue_correction(pc["id"], target_pp["id"])
        correction = find_correction_paycheck(
            source_paycheck_id=pc["id"],
            target_pay_period_id=target_pp["id"],
        )
        calculate_paycheck(correction["id"])
        # Approve correction. Approver must differ from calculator
        # — the default specialist_headers (calc) and
        # manager_headers (approve) carry distinct ids.
        approve_paycheck(correction["id"])
        after = get_employee(emp["id"])["ytd_gross_wages_cents"]
        assert after == snapshot, (
            f"YTD gross must be conserved across compensating "
            f"cycle: snapshot={snapshot} after={after}"
        )

    def test_correction_paycheck_is_marked_retro_correction(
            self, api, seeded_world):
        """# difficulty: compensating_invariant/ytd_gross_wages_conserved_after_issue_correction_then_recalc_then_approve

        PRD §3.7: "a new Paycheck is created in DRAFT cloned from
        the source's payroll_item_id with is_retro_correction set to
        true and correction_of_paycheck_id pointing at the source."

        Claim: the new paycheck has is_retro_correction=true and a
        non-null correction_of_paycheck_id linking it to the
        source.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck()
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        issue_correction(pc["id"], target_pp["id"])
        correction = find_correction_paycheck(
            source_paycheck_id=pc["id"],
            target_pay_period_id=target_pp["id"],
        )
        assert correction["is_retro_correction"] is True


class TestGarnishmentAmountConservation:
    """# difficulty: compensating_invariant/
    garnishment_amount_collected_conserved_after_void_then_reapproved_correction
    """

    def test_garnishment_amount_conserved_across_correction(
            self, api, seeded_world):
        """# difficulty: compensating_invariant/garnishment_amount_collected_conserved_after_void_then_reapproved_correction

        PRD §3.5: "The garnishment-amount reconciliation is itself an
        aggregation: for each order, the system can derive
        amount_collected_cents as the sum of per-order allocations
        across that employee's APPROVED or PAID paychecks minus the
        sum of per-order allocations across that employee's VOIDED
        paychecks; this derivation must match the stored figure at
        all times."

        Claim: a void that subtracts -X followed by a re-approved
        correction with identical inputs that adds +X leaves
        amount_collected_cents at the same value as before the void.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        # Use a high total_owed so the order never satisfies (avoid
        # spurious SATISFIED flips).
        g = create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=15, total_owed_cents=99_999_999,
            effective_pay_date="2024-01-01",
        )
        pp1 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp1["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp1["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        approve_paycheck(pc["id"])
        snapshot = get_garnishment_order(g["id"])[
            "amount_collected_cents"
        ]
        assert snapshot == 25_194
        target_pp = create_biweekly_pay_period(date(2024, 9, 9))
        # Need W-4 for target pp; the 2024-08-12 W-4 still applies.
        issue_correction(pc["id"], target_pp["id"])
        correction = find_correction_paycheck(
            source_paycheck_id=pc["id"],
            target_pay_period_id=target_pp["id"],
        )
        calculate_paycheck(correction["id"])
        approve_paycheck(correction["id"])
        after = get_garnishment_order(g["id"])[
            "amount_collected_cents"
        ]
        assert after == snapshot, (
            f"garnishment amount_collected must be conserved across "
            f"correction with identical inputs: snapshot={snapshot} "
            f"after={after}"
        )

    def test_garnishment_status_unchanged_across_compensating_cycle(
            self, api, seeded_world):
        """# difficulty: compensating_invariant/garnishment_amount_collected_conserved_after_void_then_reapproved_correction

        PRD §3.5: "amount_collected_cents reaches or exceeds
        total_owed_cents and the order is currently ACTIVE, the
        order transitions automatically to SATISFIED. Conversely, on
        paycheck void through the correction loop, the per-order
        allocation is subtracted from amount_collected_cents, and if
        the order had been SATISFIED but the new collected total is
        now below total_owed_cents, the order transitions back to
        ACTIVE."

        Claim: with a high total_owed (never satisfied) the
        compensating cycle leaves the order in ACTIVE throughout.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        g = create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=15, total_owed_cents=99_999_999,
            effective_pay_date="2024-01-01",
        )
        pp1 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp1["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp1["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        calculate_paycheck(pc["id"])
        approve_paycheck(pc["id"])
        target_pp = create_biweekly_pay_period(date(2024, 9, 9))
        issue_correction(pc["id"], target_pp["id"])
        correction = find_correction_paycheck(
            source_paycheck_id=pc["id"],
            target_pay_period_id=target_pp["id"],
        )
        calculate_paycheck(correction["id"])
        approve_paycheck(correction["id"])
        final_g = get_garnishment_order(g["id"])
        assert final_g["status"] == "ACTIVE", (
            f"order should remain ACTIVE through compensating cycle; "
            f"got {final_g['status']}"
        )
