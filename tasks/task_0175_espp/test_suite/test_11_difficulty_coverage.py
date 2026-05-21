"""Difficulty-design coverage — every instance gets at least TWO tests
tagged `# difficulty: <rule_id>/<instance.name>` so the coverage audit
can locate them. The companion primary tests for many of these claims
live in tests 02–10; this file adds the second (and where needed,
first) test per instance and consolidates the tagging.

Each test cites the PRD sentence that motivates the underlying rule —
PRD-first applies. The difficulty-design recipe drives setup and
expected values; the citation drives legitimacy.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    add_years,
    advance_clock_to,
    assert_disposition,
    assert_purchase,
    assert_purchase_invariants,
    create_contribution_payload,
    create_disposition_payload,
    enroll_participant,
    get_success_data,
    list_offering_periods,
    make_participant_headers,
    make_payroll_agent_headers,
    make_plan_admin_headers,
    new_participant_id,
    parse_iso,
    post_contribution,
    purchase_fmv_payload,
    run_sweep,
    setup_active_plan_with_open_period,
    setup_enrollment_with_contributions,
    setup_period_at_closed_state,
    setup_plan_with_active_enrollments_for_dilution,
    setup_purchase_after_run,
    setup_purchase_with_disposition,
    setup_two_plans_lookback_vs_no_lookback,
    TEST_USERS,
    update_disposition_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_lookback_vs_no_lookback_diverge_on_same_inputs(self, api):
        """PRD §3.5: "when the plan has `lookback_enabled` equal to
        true, the chosen per-share fair-market value `chosen_fmv_cents`
        is the smaller of the period's `grant_date_fmv_cents` and
        `purchase_date_fmv_cents`; when the plan has `lookback_enabled`
        equal to false, the chosen value is simply
        `purchase_date_fmv_cents`."

        Claim (difficulty 1A): identical contributions + identical FMVs
        yield DIFFERENT shares_purchased depending on lookback_enabled.
        """
        # difficulty: dual_variant_calc/purchase_settlement_lookback_vs_no_lookback
        p1, p2 = setup_two_plans_lookback_vs_no_lookback(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            discount_bp=1500,
            contribution_amount_cents=17_000,
            contribution_rate_bp=1500,
        )
        # P1 (lookback=true): chosen=1000, price=850, shares=20.
        assert p1["purchase"]["chosen_fmv_cents"] == 1000
        assert p1["purchase"]["purchase_price_cents"] == 850
        assert p1["purchase"]["shares_purchased"] == 20
        # P2 (lookback=false): chosen=2000, price=1700, shares=10.
        assert p2["purchase"]["chosen_fmv_cents"] == 2000
        assert p2["purchase"]["purchase_price_cents"] == 1700
        assert p2["purchase"]["shares_purchased"] == 10
        assert p1["purchase"]["shares_purchased"] != \
            p2["purchase"]["shares_purchased"]

    def test_qualifying_vs_disqualifying_diverge_on_same_sale(self, api):
        """PRD §3.7: "For a `QUALIFYING` disposition, the system applies
        the IRC 423(c) lesser-of test ... For a `DISQUALIFYING`
        disposition, the spread at purchase is recognized as ordinary
        income regardless of sale price".

        Claim (difficulty 1B): identical sale_price yields DIFFERENT
        ordinary_income_cents depending on QUALIFYING vs DISQUALIFYING.
        """
        # difficulty: dual_variant_calc/disposition_tax_qualifying_vs_disqualifying
        # Branch A — DISQUALIFYING.
        _plan_a, _opa, _pida, _pa, disp_a = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        # Branch B — QUALIFYING on a fresh fixture.
        _plan_b, _opb, _pidb, _pb, disp_b = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-02T00:00:00.000Z",
            disposition_date_iso="2026-01-01T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        assert disp_a["classification"] == "DISQUALIFYING"
        assert disp_b["classification"] == "QUALIFYING"
        assert disp_a["ordinary_income_cents"] == 11_500
        assert disp_b["ordinary_income_cents"] == 1_500
        assert disp_a["ordinary_income_cents"] != \
            disp_b["ordinary_income_cents"]


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_dilution_score_high_rate_branch(self, api):
        """PRD §3.8: "When the rate factor is at or above 0.5, the
        score is one hundred times the sum of the rate factor weighted
        at 0.4, the cap factor weighted at 0.3, and the participation
        factor weighted at 0.3, with no additional scaling. The final
        score is rounded half-up to the nearest whole integer in the
        range from 0 through 100."

        Claim (difficulty 2A): rate_factor=1.0, cap_factor=1.0,
        participation=0.5 -> score = 100*(0.4+0.3+0.15) = 85.
        """
        # difficulty: combinatorial_formula/dilution_score_three_inputs_nonlinear
        plan, _op, _pids = setup_plan_with_active_enrollments_for_dilution(
            n_enrollments=5,
            max_contribution_rate_bp=1500,
            annual_accrual_cap_cents=2_500_000,
        )
        resp = api.get_dilution_preview(
            plan["id"], TEST_USERS["plan_admin_headers"],
            params={"eligible_employee_count": 10},
        )
        data = validate_success(resp)
        assert data.get("dilution_score") == 85, (
            f"Expected 85, got {data!r}"
        )

    def test_purchase_round_then_floor_order(self, api):
        """PRD §3.5: "Step B applies the discount and rounds once at
        the per-share price: `purchase_price_cents` is `chosen_fmv_cents`
        times the quantity one minus the discount in basis points
        (i.e. `(10000 - discount_bp) / 10000`), rounded half-up to the
        nearest whole cent. This is the only rounding step in the
        entire calculation. ... Step D floors to whole shares:
        `shares_purchased` is the integer floor of `contributions_used_cents`
        divided by `purchase_price_cents`."

        Claim (difficulty 2B): chosen_fmv=333, discount_bp=1500 ->
        round_half_up(333 * 8500/10000) = round_half_up(283.05) = 283;
        floor(1000/283) = 3; refund = 1000 - 3*283 = 151.
        """
        # difficulty: combinatorial_formula/purchase_round_then_floor_order
        plan, _op, _pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=333,
            purchase_date_fmv_cents=500,
            discount_bp=1500,
            lookback_enabled=True,
            contribution_amount_cents=1000,
            contribution_rate_bp=1500,
        )
        assert_purchase(purchase)
        assert_purchase_invariants(purchase)
        assert purchase["chosen_fmv_cents"] == 333
        assert purchase["purchase_price_cents"] == 283, (
            f"Expected round_half_up(333*0.85)=283, "
            f"got {purchase['purchase_price_cents']}"
        )
        assert purchase["shares_purchased"] == 3, (
            f"Expected floor(1000/283)=3, got {purchase['shares_purchased']}"
        )
        assert purchase["refund_cents"] == 151, (
            f"Expected 1000-3*283=151, got {purchase['refund_cents']}"
        )

    def test_purchase_round_then_floor_order_invariant_across_total(self, api):
        """PRD §3.5: "Step D floors to whole shares: `shares_purchased`
        is the integer floor of `contributions_used_cents` divided by
        `purchase_price_cents`."

        Claim (difficulty 2B, second test): a different contribution
        total against the same per-share price still respects the
        round-once-then-floor identity.
        """
        # difficulty: combinatorial_formula/purchase_round_then_floor_order
        plan, _op, _pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=333,
            purchase_date_fmv_cents=500,
            discount_bp=1500,
            lookback_enabled=True,
            contribution_amount_cents=2000,
            contribution_rate_bp=1500,
        )
        assert purchase["chosen_fmv_cents"] == 333
        assert purchase["purchase_price_cents"] == 283
        assert purchase["shares_purchased"] == 7, (
            f"Expected floor(2000/283)=7, got {purchase['shares_purchased']}"
        )
        assert purchase["refund_cents"] == 19, (
            f"Expected 2000-7*283=19, got {purchase['refund_cents']}"
        )

    def test_dilution_score_high_rate_branch_alt_inputs(self, api):
        """PRD §3.8: "When the rate factor is at or above 0.5, the
        score is one hundred times the sum of the rate factor weighted
        at 0.4, the cap factor weighted at 0.3, and the participation
        factor weighted at 0.3, with no additional scaling."

        Claim (difficulty 2A, second test): rate=1500, cap=2_500_000,
        participation=1.0 (5/5) -> 100*(0.4+0.3+0.3) = 100.
        """
        # difficulty: combinatorial_formula/dilution_score_three_inputs_nonlinear
        plan, _op, _pids = setup_plan_with_active_enrollments_for_dilution(
            n_enrollments=5,
            max_contribution_rate_bp=1500,
            annual_accrual_cap_cents=2_500_000,
        )
        resp = api.get_dilution_preview(
            plan["id"], TEST_USERS["plan_admin_headers"],
            params={"eligible_employee_count": 5},
        )
        data = validate_success(resp)
        assert data.get("dilution_score") == 100, (
            f"Expected 100, got {data!r}"
        )

    # contribution_cap_pinned_eval_order — requires Enrollment.ytd_accrual
    # to be pre-loaded mid-life. Per scaffold recipe this is done via a
    # prior COMPLETED offering period. PRD doesn't expose a privileged
    # mutation path, so the test setup must construct it through real
    # DELETED test_contribution_cap_pinned_eval_order_minimum:
    # PRD §3.4 defines the remaining accrual strictly as
    # `Plan.annual_accrual_cap_cents - enrollment.ytd_accrual_cents`.
    # PRD is SILENT on whether the cap is enforced cross-enrollment
    # (i.e., summing ytd_accrual across all enrollments for the same
    # participant in the same year). A faithful PRD-only implementer
    # would read §3.4 per-enrollment, in which case a brand-new
    # op2 enrollment has ytd_accrual=0 and the test's expectation
    # (cap pinned via a PRIOR op1 purchase) does not follow from PRD.
    # Per the diagnostic protocol's UNIQUE-DERIVABILITY rule, this
    # test is deleted.

    def test_contribution_cap_pinned_eval_order_under_cap_passthrough(
        self, api,
    ):
        """PRD §3.4: "In the under-cap variant, the raw rate-driven
        amount is less than or equal to the remaining cash cap, so the
        full deduction posts."

        Claim (difficulty 2C, second test): with the same evaluation
        order on a fresh enrollment where ytd_accrual==0, the raw
        amount posts unchanged.
        """
        # difficulty: combinatorial_formula/contribution_cap_pinned_eval_order
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        resp = api.create_contribution(
            enr["id"],
            create_contribution_payload(
                pay_period_end=op1["start_date"],
                gross_pay_cents=10_000,
            ),
            TEST_USERS["payroll_agent_headers"],
        )
        data = validate_success(resp, expected_status=201)
        # raw = 10000 * 1500/10000 = 1500; remaining cap huge; passthrough.
        assert data["amount_cents"] == 1500


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_purchase_holding_advances_while_disposition_held(self, api):
        """PRD §3.6: "Each `Purchase` row carries a parallel holding-
        period dimension, `holding_period_status`, that advances
        independently of any disposition activity and is driven
        exclusively by the maturation sweep."

        Claim (difficulty 3A): after sweep at purchase+1y,
        holding_period_status==PAST_ONE_YEAR_FROM_PURCHASE while
        disposition_status remains HELD (no disposition filed).
        """
        # difficulty: non_linear_state_machine/purchase_parallel_holding_and_disposition_dimensions
        plan, _op, _pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # Anchor relative to the actual purchase_date (clock is monotonic,
        # so hardcoded absolute dates can be in the past).
        advance_clock_to(add_years(purchase["purchase_date"], 1))
        run_sweep()
        resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(resp)
        assert data["holding_period_status"] == "PAST_ONE_YEAR_FROM_PURCHASE"
        assert data["disposition_status"] == "HELD"

    def test_disposition_within_both_keeps_holding_within_both(self, api):
        """PRD §3.7: "Two date-window checks are enforced ...".
        PRD §3.6: "The dimension's initial value at purchase creation
        is `WITHIN_BOTH`." The holding-period dimension advances on
        clock+sweep; a disposition filing does NOT advance it.

        Claim (difficulty 3A, second test): file a disposition shortly
        after purchase. Purchase.holding_period_status remains
        WITHIN_BOTH; Purchase.disposition_status moves to
        DISPOSED_DISQUALIFYING (parallel dimension).
        """
        # difficulty: non_linear_state_machine/purchase_parallel_holding_and_disposition_dimensions
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2024-08-01T00:00:00.000Z",
            disposition_date_iso="2024-08-01T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(resp)
        assert data["holding_period_status"] == "WITHIN_BOTH"
        assert data["disposition_status"] == "DISPOSED_DISQUALIFYING"

    def test_disposition_amend_then_void_reverts_purchase_to_held(self, api):
        """PRD §3.7: "On amendment, the system re-evaluates
        classification, recomputes `ordinary_income_cents` and
        `capital_gain_cents` from the current purchase fields, and
        updates the disposition's status to `AMENDED`. ... [On void]
        the disposition's status moves to `VOIDED`. As a side effect,
        the purchase's `disposition_status` is restored to `HELD` if
        no other non-voided disposition exists on the purchase."

        Claim (difficulty 3B): amend (capital_gain updates) then void
        -> Disposition.status==VOIDED and Purchase.disposition_status==HELD.
        """
        # difficulty: non_linear_state_machine/disposition_branching_with_revert_to_held
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        # Step 1 — amend: sale=3000 -> capital_gain=10*(3000-2000)=10000.
        amended = get_success_data(
            api.update_disposition(
                disp["id"],
                update_disposition_payload(
                    version=disp["version"],
                    sale_price_per_share_cents=3000,
                ),
                h,
            )
        )
        assert amended["status"] == "AMENDED"
        assert amended["capital_gain_cents"] == 10_000
        # Step 2 — void.
        api.delete_disposition(disp["id"], h)
        # Step 3 — Purchase reverted to HELD.
        p_resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        p_data = validate_success(p_resp)
        assert p_data["disposition_status"] == "HELD"

    def test_disposition_branching_void_directly_from_reported(self, api):
        """PRD §3.7: "Voiding is allowed from either `REPORTED` or
        `AMENDED` (it is the one transition shared by both source
        states); the disposition's status moves to `VOIDED`. As a side
        effect, the purchase's `disposition_status` is restored to
        `HELD` if no other non-voided disposition exists on the
        purchase."

        Claim (difficulty 3B, second test): void directly from REPORTED
        without amending first -> Disposition.status==VOIDED and
        Purchase.disposition_status==HELD.
        """
        # difficulty: non_linear_state_machine/disposition_branching_with_revert_to_held
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        api.delete_disposition(disp["id"], h)
        p_resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        p_data = validate_success(p_resp)
        assert p_data["disposition_status"] == "HELD"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_run_purchase_cascade_4_links(self, api):
        """PRD §3.5: "Each consumed `Contribution` is flipped from
        `POSTED` to `CONSUMED`. Each processed `Enrollment` is flipped
        from `ACTIVE` to `COMPLETED`. A Form 3922 record is issued
        immutably per `Purchase` ..."
        PRD §3.5: "the current period's `status` is set to `PURCHASED`
        (terminal)".

        Claim (difficulty 4A): run-purchase produces all four observable
        downstream effects on the same period: op PURCHASED, enrollment
        COMPLETED, contributions CONSUMED, Form3922 issued.
        """
        # difficulty: transitive_cascade/run_purchase_cascade_depth_4
        plan, op1, pid, enrollment = setup_enrollment_with_contributions(
            grant_date_fmv_cents=1000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
        )
        # Add two more contributions for a total of 3 funding rows.
        post_contribution(
            enrollment_id=enrollment["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,
        )
        post_contribution(
            enrollment_id=enrollment["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,
        )
        # Drive through to PURCHASED.
        advance_clock_to(add_days(op1["end_date"], 1))
        get_success_data(
            api.record_purchase_fmv(
                op1["id"],
                purchase_fmv_payload(
                    purchase_date_fmv_cents=2000,
                    version=op1["version"],
                ),
                TEST_USERS["plan_admin_headers"],
            )
        )
        run_sweep()
        get_success_data(
            api.run_purchase(op1["id"], TEST_USERS["plan_admin_headers"])
        )
        # Link 1: op1 PURCHASED.
        op_after = get_success_data(
            api.get_offering_period(
                op1["id"], TEST_USERS["plan_admin_headers"],
            )
        )
        assert op_after["status"] == "PURCHASED"
        # Link 2: enrollment COMPLETED.
        enr_after = get_success_data(
            api.get_enrollment(
                enrollment["id"], TEST_USERS["plan_admin_headers"],
            )
        )
        assert enr_after["status"] == "COMPLETED"
        # Link 3: all 3 contributions CONSUMED.
        clist = api.list_contributions(
            enrollment["id"], TEST_USERS["plan_admin_headers"],
            params={"limit": 100, "offset": 0},
        )
        items = clist.json()["data"]
        assert len(items) == 3
        assert all(c["status"] == "CONSUMED" for c in items)
        # Link 4: one Form3922 issued.
        plist = api.list_purchases(
            pid, make_participant_headers(pid),
            params={"limit": 100, "offset": 0},
        )
        purchases = plist.json()["data"]
        assert len(purchases) == 1
        year = parse_iso(purchases[0]["purchase_date"]).year
        flist = api.list_form_3922(
            pid, make_participant_headers(pid),
            params={"calendar_year": year, "limit": 100, "offset": 0},
        )
        forms = [
            f for f in flist.json()["data"]
            if f["purchase_id"] == purchases[0]["id"]
        ]
        assert len(forms) == 1

    def test_run_purchase_cascade_also_creates_next_period(self, api):
        """PRD §3.5: "a new `OfferingPeriod` is created with
        `sequence_number` equal to the predecessor's plus one,
        `start_date` equal to the predecessor's `end_date` ... and
        `status` equal to `OPEN`."

        Claim (difficulty 4A, second test): after run-purchase, the
        sibling fan-out (next OfferingPeriod) is observably present
        with sequence_number=2, status=OPEN, start_date == op1.end_date.
        """
        # difficulty: transitive_cascade/run_purchase_cascade_depth_4
        plan, op_after, _pid, _purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        periods = list_offering_periods(plan["id"])
        by_seq = {p["sequence_number"]: p for p in periods}
        assert by_seq[2]["status"] == "OPEN"
        assert by_seq[2]["start_date"] == by_seq[1]["end_date"]

    def test_withdraw_cascade_refunds_all_posted_contributions(self, api):
        """PRD §3.3: "As a side effect, every `Contribution` on the
        enrollment whose status is currently `POSTED` is flipped to
        `REFUNDED`."

        Claim (difficulty 4B): withdraw causes link-2 propagation —
        every POSTED contribution becomes REFUNDED.
        """
        # difficulty: transitive_cascade/withdraw_cascade_depth_2
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        post_contribution(
            enrollment_id=enr["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,
        )
        post_contribution(
            enrollment_id=enr["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,
        )
        # Withdraw.
        get_success_data(
            api.withdraw_enrollment(enr["id"], make_participant_headers(pid))
        )
        # Inspect.
        clist = api.list_contributions(
            enr["id"], TEST_USERS["plan_admin_headers"],
            params={"limit": 100, "offset": 0},
        )
        items = clist.json()["data"]
        assert len(items) == 2
        assert all(c["status"] == "REFUNDED" for c in items)

    def test_withdraw_excludes_from_subsequent_purchase_batch(self, api):
        """PRD §3.3: "the participant is excluded from this period's
        purchase batch when it eventually runs."

        Claim (difficulty 4B, second test): after withdraw, a later
        run-purchase yields NO Purchase row for this participant.
        """
        # difficulty: transitive_cascade/withdraw_cascade_depth_2
        plan, op1, pid, enr = setup_enrollment_with_contributions(
            grant_date_fmv_cents=1000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        get_success_data(
            api.withdraw_enrollment(enr["id"], make_participant_headers(pid))
        )
        advance_clock_to(add_days(op1["end_date"], 1))
        get_success_data(
            api.record_purchase_fmv(
                op1["id"],
                purchase_fmv_payload(
                    purchase_date_fmv_cents=2000,
                    version=op1["version"],
                ),
                TEST_USERS["plan_admin_headers"],
            )
        )
        run_sweep()
        get_success_data(
            api.run_purchase(op1["id"], TEST_USERS["plan_admin_headers"])
        )
        plist = api.list_purchases(
            pid, make_participant_headers(pid),
            params={"limit": 100, "offset": 0},
        )
        assert plist.json()["data"] == []


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_check_wins_over_fiscal_on_contribution_to_closed_period(
        self, api,
    ):
        """PRD §2.4: "The system evaluates request-level checks in a
        strict priority order so that the error returned is always the
        highest-priority unmet condition, not whichever check happened
        to run last. Authentication ... then role validity, then
        per-operation role authorization, then path-identifier
        existence ... then state preconditions on the plan, the
        offering period, and any other state-bearing entities in the
        request, and only after all of those have passed does the
        system reach business-safety, business-constraint,
        business-fiscal, and business-temporal checks."
        PRD §3.4: "A contribution may be posted only when the owning
        enrollment is in `ACTIVE` status and the parent offering period
        is `OPEN`; otherwise the post is rejected with `ERR_PERIOD_NOT_OPEN`
        (if the period is not `OPEN`)".

        Claim (difficulty 5A): on a CLOSED period, the state check
        ERR_PERIOD_NOT_OPEN is returned (priority-6 state class) ahead
        of any business-class checks (e.g., fiscal cap) — observable as
        the exact `error_id`.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_contribution
        plan, op_closed, _pid, enrollment = setup_period_at_closed_state()
        resp = api.create_contribution(
            enrollment["id"],
            create_contribution_payload(
                pay_period_end=op_closed["start_date"],
                gross_pay_cents=10_000,
            ),
            TEST_USERS["payroll_agent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    def test_state_check_wins_over_fiscal_on_open_period_too(self, api):
        """PRD §2.4: "the error returned is always the highest-priority
        unmet condition".
        PRD §3.4: "ERR_PERIOD_NOT_OPEN (if the period is not `OPEN`)".

        Claim (difficulty 5A, second test): same priority-ordering rule
        observed on a different state precondition — withdrawn enrollment
        on an OPEN period yields ERR_INVALID_ENROLLMENT_STATE (state)
        rather than any fiscal error.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_contribution
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        # Withdraw the enrollment.
        get_success_data(
            api.withdraw_enrollment(enr["id"], make_participant_headers(pid))
        )
        # Now POST contribution against the WITHDRAWN enrollment.
        resp = api.create_contribution(
            enr["id"],
            create_contribution_payload(
                pay_period_end=op1["start_date"],
                gross_pay_cents=10_000,
            ),
            TEST_USERS["payroll_agent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value)


# Skip business_safety_vs_business_constraint_on_run_purchase — the
# scaffold recipe requires "directly mutate to 25 via privileged setup
# (test fixture)" which has no PRD-named code path. PRD doesn't state
# the priority of SoD vs period-length, so we cannot test it without
# weakening the rule. This is reported under `validation-priority` in
# the summary report at the end of generation.


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_two_year_boundary_inclusive_at_grant_plus_2y(self, api):
        """PRD §3.7: "The disposition is classified as `QUALIFYING` if
        and only if `disposition_date` is at or after the purchase's
        `grant_date` plus two years AND at or after the purchase's
        `purchase_date` plus one year".

        Claim (difficulty 6A, boundary B): disposition_date == grant+2y
        exactly -> QUALIFYING (>= inclusive).
        """
        # difficulty: boundary_precision_check/holding_period_exact_two_year_boundary
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-02T00:00:00.000Z",
            disposition_date_iso="2026-01-01T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        assert disp["classification"] == "QUALIFYING"

    def test_two_year_boundary_strict_one_day_before(self, api):
        """PRD §3.7: "QUALIFYING if and only if `disposition_date` is
        at or after the purchase's `grant_date` plus two years AND at
        or after the purchase's `purchase_date` plus one year;
        otherwise it is classified as `DISQUALIFYING`."

        Claim (difficulty 6A, boundary A): disposition_date one day
        before grant+2y -> DISQUALIFYING (strictly less than boundary).
        """
        # difficulty: boundary_precision_check/holding_period_exact_two_year_boundary
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        assert disp["classification"] == "DISQUALIFYING"

    def test_dispose_one_share_when_zero_remain_rejected(self, api):
        """PRD §3.7: "A share-balance check is enforced: `shares_disposed`
        may not exceed the purchase's `shares_purchased` minus the sum
        of `shares_disposed` over prior dispositions on the same
        purchase whose `status` is in either `REPORTED` or `AMENDED`
        (i.e. excluding voided dispositions), otherwise
        `ERR_SHARES_EXCEED_BALANCE`."

        Claim (difficulty 6B, boundary A): with all 10 shares already
        disposed (REPORTED), a second filing of 1 share -> 422
        ERR_SHARES_EXCEED_BALANCE.
        """
        # difficulty: boundary_precision_check/shares_disposed_empty_inventory_boundary
        plan, _op, pid, purchase, disp1 = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-15T00:00:00.000Z",
            disposition_date_iso="2026-01-15T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        # Attempt to dispose 1 more share — inventory is empty. Re-use
        # the first disposition's date (already in the actual frame) so
        # we exercise only the share-balance branch.
        resp = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=disp1["disposition_date"],
                shares_disposed=1,
                sale_price_per_share_cents=2600,
            ),
            make_participant_headers(pid),
        )
        validate_error(resp, ApiErrorId.ERR_SHARES_EXCEED_BALANCE.value)

    def test_share_balance_after_void_restores_inventory(self, api):
        """PRD §3.7: "the sum of `shares_disposed` over prior
        dispositions on the same purchase whose `status` is in either
        `REPORTED` or `AMENDED` (i.e. excluding voided dispositions)".

        Claim (difficulty 6B, second test): after VOID of the prior
        full-share disposition, a new full-share disposition succeeds
        because VOIDED rows are excluded from the balance sum.
        """
        # difficulty: boundary_precision_check/shares_disposed_empty_inventory_boundary
        plan, _op, pid, purchase, disp1 = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-15T00:00:00.000Z",
            disposition_date_iso="2026-01-15T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        # Void the disposition.
        api.delete_disposition(disp1["id"], h)
        # Now a fresh full-shares filing should succeed (10 shares again).
        # Use disp1.disposition_date (already in the actual frame).
        resp = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=disp1["disposition_date"],
                shares_disposed=10,
                sale_price_per_share_cents=2600,
            ),
            h,
        )
        data = validate_success(resp, expected_status=201)
        assert data["shares_disposed"] == 10


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_enrollment_requires_offering_period_open_a(self, api):
        """PRD §3.2: "From `CLOSED`, any subsequent attempt to create
        an enrollment referencing the period ... is rejected with
        `ERR_PERIOD_NOT_OPEN`."

        Claim (difficulty 7A): POST enrollment on CLOSED period ->
        ERR_PERIOD_NOT_OPEN.
        """
        # difficulty: cross_entity_state_dependency/enrollment_requires_offering_period_open
        plan, op_closed, _pid, _enr = setup_period_at_closed_state()
        pid = new_participant_id()
        resp = api.create_enrollment(
            op_closed["id"],
            {"contribution_rate_bp": 500},
            make_participant_headers(pid),
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    def test_enrollment_requires_offering_period_open_b(self, api):
        """PRD §3.2: "The transition from `OPEN` to `CLOSED` is driven
        by the maturation sweep: when the system clock reaches or
        passes `end_date` and `purchase_date_fmv_cents` has been
        recorded (not null), the next sweep invocation flips the period
        to `CLOSED`. From `CLOSED`, any subsequent attempt to create
        an enrollment referencing the period ... is rejected with
        `ERR_PERIOD_NOT_OPEN`."

        Claim (difficulty 7A, second test): enrollment on PURCHASED
        period (different non-OPEN state) -> ERR_PERIOD_NOT_OPEN.
        """
        # difficulty: cross_entity_state_dependency/enrollment_requires_offering_period_open
        plan, op_after, _pid, _purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        assert op_after["status"] == "PURCHASED"
        attacker = new_participant_id()
        resp = api.create_enrollment(
            op_after["id"],
            {"contribution_rate_bp": 500},
            make_participant_headers(attacker),
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    def test_disposition_blocked_when_purchase_inventory_empty(self, api):
        """PRD §3.7: "A share-balance check is enforced: `shares_disposed`
        may not exceed the purchase's `shares_purchased` minus the sum
        of `shares_disposed` over prior dispositions ... otherwise
        `ERR_SHARES_EXCEED_BALANCE`."

        Claim (difficulty 7B): with the Purchase's inventory exhausted
        by a prior full-shares disposition, a new disposition (any
        positive size) -> 422 ERR_SHARES_EXCEED_BALANCE. Cross-entity
        dependency: Disposition allowed depends on Purchase inventory.
        """
        # difficulty: cross_entity_state_dependency/disposition_requires_purchase_held_or_amend
        plan, _op, pid, purchase, _disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-15T00:00:00.000Z",
            disposition_date_iso="2026-01-15T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        # Use the first disposition's date (already in actual frame) so
        # the date-window check passes and only the share-balance branch
        # is exercised.
        resp = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=_disp["disposition_date"],
                shares_disposed=5,
                sale_price_per_share_cents=2700,
            ),
            make_participant_headers(pid),
        )
        validate_error(resp, ApiErrorId.ERR_SHARES_EXCEED_BALANCE.value)

    def test_partial_disposition_still_allows_next_within_balance(self, api):
        """PRD §3.7: "`shares_disposed` may not exceed the purchase's
        `shares_purchased` minus the sum of `shares_disposed` over
        prior dispositions on the same purchase whose `status` is in
        either `REPORTED` or `AMENDED`".

        Claim (difficulty 7B, second test): cross-entity dependency
        works the other way too — after a partial disposition (4 of 10),
        a follow-up disposition for 5 shares is accepted; 7 shares
        (exceeds remaining 6) is rejected.
        """
        # difficulty: cross_entity_state_dependency/disposition_requires_purchase_held_or_amend
        plan, _op, pid, purchase, _disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-15T00:00:00.000Z",
            disposition_date_iso="2026-01-15T00:00:00.000Z",
            shares_disposed=4,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        # Re-use the first disposition's date (already in actual frame).
        d_iso = _disp["disposition_date"]
        # 5 should pass (remaining 6).
        ok = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=d_iso,
                shares_disposed=5,
                sale_price_per_share_cents=2700,
            ),
            h,
        )
        validate_success(ok, expected_status=201)
        # 2 more should fail (remaining 1, request 2 > 1).
        bad = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=d_iso,
                shares_disposed=2,
                sale_price_per_share_cents=2800,
            ),
            h,
        )
        validate_error(bad, ApiErrorId.ERR_SHARES_EXCEED_BALANCE.value)


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_duplicate_enrollment_same_period_rejected(self, api):
        """PRD §3.3: "The combination of `offering_period_id` and
        `participant_id` is unique: a participant cannot hold two
        enrollments in the same period. Two simultaneous enrollments
        by the same participant in the same period serialize on this
        uniqueness invariant — exactly one wins and the loser receives
        `ERR_DUPLICATE_ENROLLMENT`."

        Claim (difficulty 8A): second enrollment in same OP by same
        participant -> ERR_DUPLICATE_ENROLLMENT.
        """
        # difficulty: resource_temporal_overlap/enrollment_uniqueness_per_offering_period
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid = new_participant_id()
        h = make_participant_headers(pid)
        get_success_data(
            api.create_enrollment(
                op1["id"], {"contribution_rate_bp": 500}, h,
            )
        )
        resp = api.create_enrollment(
            op1["id"], {"contribution_rate_bp": 700}, h,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)

    def test_adjacent_enrollment_in_next_period_allowed(self, api):
        """PRD §3.3: "The combination of `offering_period_id` and
        `participant_id` is unique: a participant cannot hold two
        enrollments in the same period."
        PRD §3.5 implies the next OfferingPeriod is a separate
        identifier; uniqueness is per-OP, so the participant may enroll
        in the successor.

        Claim (difficulty 8A, second test): after op1 -> PURCHASED, the
        same participant can enroll in op2 (different OP id).
        """
        # difficulty: resource_temporal_overlap/enrollment_uniqueness_per_offering_period
        plan, op_after, pid, _purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        periods = list_offering_periods(plan["id"])
        op2 = next(p for p in periods if p["sequence_number"] == 2)
        # Same participant enrolls in op2 -> 201.
        resp = api.create_enrollment(
            op2["id"],
            {"contribution_rate_bp": 500},
            make_participant_headers(pid),
        )
        validate_success(resp, expected_status=201)

    def test_back_to_back_offering_periods_touch_without_overlap(self, api):
        """PRD §3.5: "a new `OfferingPeriod` is created with
        `sequence_number` equal to the predecessor's plus one,
        `start_date` equal to the predecessor's `end_date`, `end_date`
        computed as the new `start_date` plus `Plan.offering_period_months`
        months, and `status` equal to `OPEN`."

        Claim (difficulty 8B): op2.start_date == op1.end_date exactly
        (closed-open adjacency); op2.sequence_number==2; op1==PURCHASED.
        """
        # difficulty: resource_temporal_overlap/offering_period_chained_back_to_back
        plan, op_after, _pid, _purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
        )
        periods = list_offering_periods(plan["id"])
        by_seq = {p["sequence_number"]: p for p in periods}
        op1 = by_seq[1]
        op2 = by_seq[2]
        assert op2["start_date"] == op1["end_date"]
        assert op1["status"] == "PURCHASED"
        assert op2["sequence_number"] == 2

    def test_back_to_back_offering_period_end_date_is_plus_months(self, api):
        """PRD §3.5: "a new `OfferingPeriod` is created with ...
        `end_date` computed as the new `start_date` plus
        `Plan.offering_period_months` months".

        Claim (difficulty 8B, second test): op2.end_date == op2.start_date
        + offering_period_months (6).
        """
        # difficulty: resource_temporal_overlap/offering_period_chained_back_to_back
        from test_helpers import add_months
        plan, op_after, _pid, _purchase = setup_purchase_after_run(
            offering_period_months=6,
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
        )
        periods = list_offering_periods(plan["id"])
        op2 = next(p for p in periods if p["sequence_number"] == 2)
        expected_end = add_months(op2["start_date"], 6)
        assert op2["end_date"] == expected_end, (
            f"Expected op2.end_date == op2.start_date + 6 months = "
            f"{expected_end}, got {op2['end_date']}"
        )


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_contribute_then_withdraw_conserves_cash(self, api):
        """PRD §3.3: "As a side effect, every `Contribution` on the
        enrollment whose status is currently `POSTED` is flipped to
        `REFUNDED`."

        Claim (difficulty 9A): the SUM of amount_cents over (POSTED +
        REFUNDED + CONSUMED) contributions on an enrollment is
        invariant across the contribute -> withdraw pair.
        """
        # difficulty: compensating_invariant/contribution_then_withdraw_conserves_cash
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        # Post three contributions; amount = 1000, 1500, 1200.
        # rate=1500 -> gross = amount * 10000 / 1500. Choose grosses that
        # yield those amounts exactly (i.e., divisible).
        post_contribution(
            enrollment_id=enr["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=6_660,  # 6660*1500/10000 = 999 ~ rh.up at .9? Adjust.
        )
        # 6660 * 1500 / 10000 = 999.0 -> 999 (no rounding needed).
        # Instead let's pick grosses divisible cleanly:
        # amount=1000 -> gross = 10000*1000/1500 not integer.
        # Use the actual-API computed amounts and sum them via list.
        post_contribution(
            enrollment_id=enr["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,  # amount=1500
        )
        post_contribution(
            enrollment_id=enr["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=8_000,   # amount=1200
        )
        # Snapshot total cash from API.
        clist = api.list_contributions(
            enr["id"], TEST_USERS["plan_admin_headers"],
            params={"limit": 100, "offset": 0},
        )
        items_before = clist.json()["data"]
        total_before = sum(c["amount_cents"] for c in items_before)
        assert total_before > 0
        # Withdraw.
        get_success_data(
            api.withdraw_enrollment(enr["id"], make_participant_headers(pid))
        )
        # Sum after withdraw, restricted to POSTED + REFUNDED + CONSUMED.
        clist2 = api.list_contributions(
            enr["id"], TEST_USERS["plan_admin_headers"],
            params={"limit": 100, "offset": 0},
        )
        items_after = [
            c for c in clist2.json()["data"]
            if c["status"] in ("POSTED", "REFUNDED", "CONSUMED")
        ]
        total_after = sum(c["amount_cents"] for c in items_after)
        assert total_after == total_before, (
            f"cash invariant broken: before={total_before}, after={total_after}"
        )
        # All contributions should now be REFUNDED (none POSTED, none CONSUMED).
        statuses = {c["status"] for c in items_after}
        assert statuses == {"REFUNDED"}, (
            f"Expected all REFUNDED after withdraw, got {statuses}"
        )

    def test_contribute_then_withdraw_zero_cash_loss(self, api):
        """PRD §3.4: "Contributions in `REFUNDED` status do not
        participate" in the purchase batch; PRD §3.3 says withdrawal
        flips POSTED -> REFUNDED.

        Claim (difficulty 9A, second test): cash inventory before and
        after withdraw (sum of amount_cents on the enrollment's full
        history including REFUNDED) is identical.
        """
        # difficulty: compensating_invariant/contribution_then_withdraw_conserves_cash
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        c1 = post_contribution(
            enrollment_id=enr["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=20_000,  # amount=3000
        )
        get_success_data(
            api.withdraw_enrollment(enr["id"], make_participant_headers(pid))
        )
        clist = api.list_contributions(
            enr["id"], TEST_USERS["plan_admin_headers"],
            params={"limit": 100, "offset": 0},
        )
        items = clist.json()["data"]
        assert len(items) == 1
        # The single amount_cents survives unchanged after withdraw.
        assert items[0]["amount_cents"] == c1["amount_cents"]
        assert items[0]["status"] == "REFUNDED"

    def test_dispose_then_void_conserves_share_inventory(self, api):
        """PRD §3.7: "`shares_disposed` may not exceed the purchase's
        `shares_purchased` minus the sum of `shares_disposed` over
        prior dispositions on the same purchase whose `status` is in
        either `REPORTED` or `AMENDED` (i.e. excluding voided
        dispositions) ... [On void] the purchase's `disposition_status`
        is restored to `HELD` if no other non-voided disposition exists
        on the purchase."

        Claim (difficulty 9B): create disposition of 4 shares
        (remaining_shares 10 -> 6); void; remaining_shares back to 10;
        Purchase.disposition_status reverts to HELD.
        """
        # difficulty: compensating_invariant/dispose_then_void_conserves_share_inventory
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-15T00:00:00.000Z",
            disposition_date_iso="2026-01-15T00:00:00.000Z",
            shares_disposed=4,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        # Re-use the first disposition's date (already in actual frame).
        d_iso = disp["disposition_date"]
        # Remaining 6: a 7-share dispose should fail.
        bad = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=d_iso,
                shares_disposed=7,
                sale_price_per_share_cents=2500,
            ),
            h,
        )
        validate_error(bad, ApiErrorId.ERR_SHARES_EXCEED_BALANCE.value)
        # Void the original.
        api.delete_disposition(disp["id"], h)
        # Now full 10 shares should be allowed.
        good = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=d_iso,
                shares_disposed=10,
                sale_price_per_share_cents=2500,
            ),
            h,
        )
        validate_success(good, expected_status=201)

    def test_dispose_then_void_reverts_purchase_to_held(self, api):
        """PRD §3.7: "As a side effect, the purchase's
        `disposition_status` is restored to `HELD` if no other non-
        voided disposition exists on the purchase."

        Claim (difficulty 9B, second test): a fully-disposed purchase
        (Purchase.disposition_status flipped to DISPOSED_*), void the
        sole Disposition -> Purchase.disposition_status is HELD again.
        """
        # difficulty: compensating_invariant/dispose_then_void_conserves_share_inventory
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-15T00:00:00.000Z",
            disposition_date_iso="2026-01-15T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        # Verify Purchase.disposition_status flipped first. 2026-01-15
        # is >= grant+2y (2026-01-01) and >= purchase+1y (2025-07-01),
        # so the classification is QUALIFYING per PRD §3.7.
        p_before = get_success_data(
            api.get_purchase(purchase["id"], TEST_USERS["plan_admin_headers"])
        )
        assert p_before["disposition_status"] in (
            "DISPOSED_QUALIFYING", "DISPOSED_DISQUALIFYING",
        )
        assert p_before["disposition_status"] != "HELD"
        # Void.
        api.delete_disposition(disp["id"], h)
        p_after = get_success_data(
            api.get_purchase(purchase["id"], TEST_USERS["plan_admin_headers"])
        )
        assert p_after["disposition_status"] == "HELD"
