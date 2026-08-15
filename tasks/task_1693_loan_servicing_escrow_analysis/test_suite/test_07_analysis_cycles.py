"""Annual escrow analysis: projections, pinned orders, boundaries, OCC."""
from test_helpers import (
    CO1,
    EA1,
    ApiErrorId,
    add_line_item,
    compute_cycle,
    create_analysis_payload,
    get_account,
    get_ledger,
    get_success_data,
    open_analysis_cycle,
    post_deposit,
    setup_active_account,
    setup_computed_analysis,
    setup_effective_analysis,
    validate_error,
    validate_paginated,
    validate_success,
)

# Surplus-scenario expense picture: annual 120000, cushion 20000, base 10000.
SURPLUS_LINE_ITEMS = [
    {"expense_type": "PROPERTY_TAX", "expected_annual_amount_cents": 60_000,
     "installments_per_year": 1, "first_due_date": "2027-08-10"},
    {"expense_type": "HAZARD_INSURANCE", "expected_annual_amount_cents": 60_000,
     "installments_per_year": 1, "first_due_date": "2027-07-10"},
]

# Rounding-probe expense picture: three lines of 100001/yr each.
ROUNDING_LINE_ITEMS = [
    {"expense_type": "PROPERTY_TAX", "expected_annual_amount_cents": 100_001,
     "installments_per_year": 1, "first_due_date": "2027-01-15"},
    {"expense_type": "HAZARD_INSURANCE", "expected_annual_amount_cents": 100_001,
     "installments_per_year": 1, "first_due_date": "2027-01-15"},
    {"expense_type": "FLOOD_INSURANCE", "expected_annual_amount_cents": 100_001,
     "installments_per_year": 1, "first_due_date": "2027-01-15"},
]


class TestProjectionMethodVariants:
    def _setup_dual_method(self, api):
        """Account balance 84000: a posted 60000 deposit (eff 2026-08-10) plus
        a posted forward-effective 24000 deposit (eff 2026-09-20)."""
        ctx = setup_active_account(loan_number="LN-DV-1",
                                   deposits=[(60_000, "2026-08-10"),
                                             (24_000, "2026-09-20")])
        assert get_account(ctx["account"]["id"])["balance_cents"] == 84_000
        return ctx

    def test_prospective_opens_from_posted_balance(self, api):
        """PRD: "Under `PROSPECTIVE`, `start_balance_cents` is the account's
        current posted `balance_cents` at compute time — every posted ledger
        entry counts, regardless of its `effective_date`, including
        forward-effective ones."

        Design: Difficulty/dual_variant_calc/analysis_projection_prospective_vs_ledger_actual
        """
        ctx = self._setup_dual_method(api)
        ana = open_analysis_cycle(ctx["account"]["id"], method="PROSPECTIVE")
        computed = compute_cycle(ana["id"])
        assert computed["start_balance_cents"] == 84_000, (
            "the forward-effective 24000 deposit counts under PROSPECTIVE")
        assert computed["projected_annual_disbursements_cents"] == 360_000
        assert computed["lowest_projected_balance_cents"] == 24_000
        assert computed["shortage_cents"] == 36_000

    def test_ledger_actual_excludes_forward_effective_entries(self, api):
        """PRD: "Under `LEDGER_ACTUAL`, `start_balance_cents` is the
        chronological replay of only those entries whose `effective_date` is
        strictly before `projection_start_date`, replayed in `effective_date`
        ascending, `created_at` ascending order; forward-effective entries are
        excluded."

        Design: Difficulty/dual_variant_calc/analysis_projection_prospective_vs_ledger_actual
        """
        ctx = self._setup_dual_method(api)
        ana1 = open_analysis_cycle(ctx["account"]["id"], method="PROSPECTIVE")
        prospective = compute_cycle(ana1["id"])
        get_success_data(api.void_analysis(ana1["id"], CO1))

        ana2 = open_analysis_cycle(ctx["account"]["id"], method="LEDGER_ACTUAL")
        ledger_actual = compute_cycle(ana2["id"])
        assert ledger_actual["start_balance_cents"] == 60_000, (
            "only the 2026-08-10 deposit is strictly before 2026-09-01")
        assert ledger_actual["lowest_projected_balance_cents"] == 0
        assert ledger_actual["shortage_cents"] == 60_000
        assert prospective["shortage_cents"] != ledger_actual["shortage_cents"]


class TestPinnedRoundingOrder:
    def test_activation_payment_rounds_per_line_then_sums(self, api):
        """PRD: "for each `ACTIVE` line item, divide its
        `expected_annual_amount_cents` by 12 and round that line's monthly
        share half-up to whole cents first; only then sum across lines.
        Rounding after summing is the wrong order — three lines of 100001 cents
        each yield 3 × 8333 = 24999 cents per month under the pinned order,
        versus 25000 if the annual total is divided first."

        Design: Difficulty/combinatorial_formula/monthly_payment_per_line_rounding_order
        """
        ctx = setup_active_account(loan_number="LN-RND-1",
                                   line_items=ROUNDING_LINE_ITEMS)
        account = get_account(ctx["account"]["id"])
        assert account["monthly_escrow_cents"] == 24_999, (
            "activation applies the same pinned per-line-then-sum order")
        assert account["monthly_escrow_cents"] != 25_000

    def test_analysis_base_payment_and_cushion_use_pinned_order(self, api):
        """PRD: "`base_monthly_escrow_cents` repeats the per-line-then-sum
        rule of §3.3: each `ACTIVE` line's annual amount divided by 12, rounded
        half-up per line, then summed."
        PRD: "`cushion_target_cents` is that total divided by 6, rounded
        half-up."

        Design: Difficulty/combinatorial_formula/monthly_payment_per_line_rounding_order
        """
        ctx = setup_computed_analysis(loan_number="LN-RND-1",
                                      line_items=ROUNDING_LINE_ITEMS,
                                      deposits=[])
        computed = ctx["analysis"]
        assert computed["base_monthly_escrow_cents"] == 24_999
        assert computed["base_monthly_escrow_cents"] != 25_000, (
            "sum-then-round would give 25000 and is the forbidden order")
        # projected annual = 3 x 100001 = 300003; cushion = round(300003/6).
        assert computed["projected_annual_disbursements_cents"] == 300_003
        assert computed["cushion_target_cents"] == 50_001


class TestPinnedEvaluationOrder:
    def test_projection_uses_old_payment_for_all_twelve_months(self, api):
        """PRD: "One evaluation order is pinned and non-negotiable: all twelve
        months are projected using the account's current `monthly_escrow_cents`
        — the old payment — for every month, including months after any notice
        effective date; only after the projection completes are the shortage,
        deficiency, and surplus derived; and only after those are derived is
        the new monthly payment computed."
        PRD: "`lowest_projected_balance_cents` is the minimum of the twelve
        month-end running balances."

        Design: Difficulty/combinatorial_formula/shortage_projection_pinned_evaluation_order
        """
        ctx = setup_computed_analysis(loan_number="LN-CIRC-1")
        computed = ctx["analysis"]
        assert computed["projected_annual_disbursements_cents"] == 360_000
        assert computed["cushion_target_cents"] == 60_000
        # Projected with the OLD payment 30000: the June tax installment drains
        # the trough to exactly 0 (feeding the new 35000 back in would give
        # 50000 and is the forbidden order).
        assert computed["lowest_projected_balance_cents"] == 0
        assert computed["shortage_cents"] == 60_000
        assert computed["deficiency_cents"] == 0

    def test_spread_and_new_payment_derived_after_projection(self, api):
        """PRD: "`spread_monthly_cents` is that total divided by 12 rounded
        down, and `spread_first_month_cents` is the total minus eleven times
        the monthly spread, so the remainder loads onto the first month.
        `new_monthly_escrow_cents` is the base plus the monthly spread under
        the spread-over-twelve assumption"

        Design: Difficulty/combinatorial_formula/shortage_projection_pinned_evaluation_order
        """
        ctx = setup_computed_analysis(loan_number="LN-CIRC-1")
        computed = ctx["analysis"]
        assert computed["spread_monthly_cents"] == 5_000, "floor(60000 / 12)"
        assert computed["spread_first_month_cents"] == 5_000, "60000 - 11 * 5000"
        assert computed["base_monthly_escrow_cents"] == 30_000
        assert computed["new_monthly_escrow_cents"] == 35_000


class TestSurplusBoundary:
    def test_surplus_exactly_5000_posts_refund(self, api):
        """PRD: "a `surplus_cents` of 5000 cents ($50.00) or more posts a
        `SURPLUS_REFUND` ledger entry of negative `surplus_cents` refunding the
        borrower, while a surplus strictly between zero and 5000 cents posts
        nothing and stays credited in the account — the boundary is exact, 5000
        refunds and 4999 does not."

        Design: Difficulty/boundary_precision_check/surplus_exactly_5000_refunds
        """
        ctx = setup_effective_analysis(loan_number="LN-SUR-1",
                                       line_items=SURPLUS_LINE_ITEMS,
                                       deposits=[(25_000, "2026-08-10")])
        assert ctx["analysis"]["status"] == "EFFECTIVE"
        computed = get_success_data(api.get_analysis(ctx["analysis"]["id"], EA1))
        assert computed["surplus_cents"] == 5_000, "25000 start - 20000 target"

        refunds = [e for e in get_ledger(ctx["account"]["id"])
                   if e["entry_type"] == "SURPLUS_REFUND"]
        assert len(refunds) == 1 and refunds[0]["amount_cents"] == -5_000, (
            "surplus at exactly 5000 is refunded at finalize")
        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 20_000, (
            "the refund brings the balance exactly to the cushion target")

    def test_surplus_4999_stays_credited(self, api):
        """PRD: "a surplus strictly between zero and 5000 cents posts nothing
        and stays credited in the account"

        Design: Difficulty/boundary_precision_check/surplus_exactly_5000_refunds
        """
        ctx = setup_effective_analysis(loan_number="LN-SUR-2",
                                       line_items=SURPLUS_LINE_ITEMS,
                                       deposits=[(24_999, "2026-08-10")])
        computed = get_success_data(api.get_analysis(ctx["analysis"]["id"], EA1))
        assert computed["surplus_cents"] == 4_999

        refunds = [e for e in get_ledger(ctx["account"]["id"])
                   if e["entry_type"] == "SURPLUS_REFUND"]
        assert refunds == [], "the credit-only path posts no ledger entry"
        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 24_999, "balance unchanged by finalize"


class TestComputeHoldGate:
    def test_compute_blocked_while_account_on_hold(self, api):
        """PRD: "While `hold_status` is `COMPLIANCE_HOLD`, three operations are
        blocked with `ERR_ACCOUNT_ON_HOLD`: releasing a disbursement, computing
        an analysis, and finalizing an analysis."

        Design: Difficulty/cross_entity_state_dependency/analysis_compute_blocked_by_compliance_hold
        """
        ctx = setup_active_account(loan_number="LN-XDS-2")
        acct_id = ctx["account"]["id"]
        get_success_data(api.hold_escrow_account(acct_id, CO1))
        ana = open_analysis_cycle(acct_id)

        resp = api.compute_analysis(ana["id"], EA1)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD)

        ana_after = validate_success(api.get_analysis(ana["id"], EA1), 200)
        assert ana_after["status"] == "DRAFT", "rejected compute changes nothing"

    def test_compute_succeeds_after_hold_released(self, api):
        """PRD: "Computing the cycle — allowed from `DRAFT` and again from
        `REOPENED` — requires the account hold to be `NONE`
        (`ERR_ACCOUNT_ON_HOLD`) and the account `ACTIVE`
        (`ERR_INVALID_STATE_TRANSITION`)"

        Design: Difficulty/cross_entity_state_dependency/analysis_compute_blocked_by_compliance_hold
        """
        ctx = setup_active_account(loan_number="LN-XDS-2")
        acct_id = ctx["account"]["id"]
        get_success_data(api.hold_escrow_account(acct_id, CO1))
        ana = open_analysis_cycle(acct_id)
        validate_error(api.compute_analysis(ana["id"], EA1),
                       ApiErrorId.ERR_ACCOUNT_ON_HOLD)

        get_success_data(api.release_hold_escrow_account(acct_id, CO1))
        computed = validate_success(api.compute_analysis(ana["id"], EA1), 200)
        assert computed["status"] == "COMPUTED"
        assert computed["computed_at"] is not None


class TestAnalysisWindowOverlap:
    def _setup_computed_window(self, api, loan_number):
        ctx = setup_computed_analysis(loan_number=loan_number)
        assert ctx["analysis"]["window_end_date"] == "2027-08-31", (
            "window is projection_start_date + 364 days")
        return ctx

    def test_shared_boundary_day_is_an_overlap(self, api):
        """PRD: "its projection window is the closed interval from
        `projection_start_date` through `window_end_date`, which is exactly 364
        days later, both ends inclusive. That window may not overlap the window
        of any other non-terminal cycle of the account — a still-`DRAFT`
        predecessor is instead superseded by the creation — and an overlap is
        rejected with `ERR_ANALYSIS_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/analysis_window_closed_interval_overlap
        """
        ctx = self._setup_computed_window(api, "LN-OVL-2")
        acct_id = ctx["account"]["id"]
        version = get_account(acct_id)["version"]

        # The true boundary day 2027-08-31 can never be a projection start
        # (month-first rule, checked earlier in the §2.9 order). The nearest
        # legal start inside the existing [2026-09-01, 2027-08-31] window is
        # 2027-08-01; its window [2027-08-01, 2028-07-30] overlaps and must be
        # rejected.
        resp = api.create_analysis(
            acct_id,
            create_analysis_payload(version, analysis_year=2028,
                                    projection_start_date="2027-08-01"),
            EA1)
        validate_error(resp, ApiErrorId.ERR_ANALYSIS_WINDOW_OVERLAP)

    def test_tiling_window_starting_next_day_is_allowed(self, api):
        """PRD: "That window may not overlap the window of any other
        non-terminal cycle of the account — a still-`DRAFT` predecessor is
        instead superseded by the creation"

        Design: Difficulty/resource_temporal_overlap/analysis_window_closed_interval_overlap
        """
        ctx = self._setup_computed_window(api, "LN-OVL-2")
        acct_id = ctx["account"]["id"]
        version = get_account(acct_id)["version"]

        # [2027-09-01, 2028-08-30] tiles without sharing a day. The end is
        # exactly 364 days after the start; the span includes 2028-02-29
        # (leap year), so 2027-09-01 + 364 days lands on 2028-08-30.
        created = validate_success(api.create_analysis(
            acct_id,
            create_analysis_payload(version, analysis_year=2028,
                                    projection_start_date="2027-09-01"),
            EA1), 201)
        assert created["status"] == "DRAFT"
        assert created["window_end_date"] == "2028-08-30"


class TestAnalysisLifecycle:
    def test_projection_start_must_be_month_boundary(self, api):
        """PRD: "The `projection_start_date` must be the first day of a month,
        else `ERR_PROJECTION_START_INVALID` (HTTP 422)."

        Design: Corner/entities/analysis_projection_start_invalid_rejected
        """
        ctx = setup_active_account(loan_number="LN-ENT-3")
        version = get_account(ctx["account"]["id"])["version"]
        resp = api.create_analysis(
            ctx["account"]["id"],
            create_analysis_payload(version, projection_start_date="2026-09-15"),
            EA1)
        validate_error(resp, ApiErrorId.ERR_PROJECTION_START_INVALID)

        analyses, meta = validate_paginated(
            api.list_analyses(ctx["account"]["id"], EA1))
        assert analyses == [] and meta["total_count"] == 0, "no cycle is created"

    def test_reopen_then_recompute_cycle(self, api):
        """PRD: "An `EFFECTIVE` cycle can be reopened — by a `ComplianceOfficer`
        directly, or by the error-correction cascade of §3.9 — moving
        `EFFECTIVE` → `REOPENED`"
        PRD: "A reopened cycle recomputes back to `COMPUTED` with all computed
        fields repopulated and `computed_at` refreshed."

        Design: Corner/state_machines/analysis_reopen_recompute_cycle
        """
        ctx = setup_effective_analysis(loan_number="LN-SM-7")
        ana_id = ctx["analysis"]["id"]

        reopened = validate_success(api.reopen_analysis(ana_id, CO1), 200)
        assert reopened["status"] == "REOPENED"

        recomputed = validate_success(api.compute_analysis(ana_id, EA1), 200)
        assert recomputed["status"] == "COMPUTED"
        assert recomputed["shortage_cents"] == 60_000, (
            "the loop back through the machine repopulates the computed fields")


class TestCushionAggregation:
    def test_activation_sets_cushion_payment_and_due_date(self, api):
        """PRD: "`target_cushion_cents` is the sum of
        `expected_annual_amount_cents` over the account's `ACTIVE` line items
        (removed items never count), divided by 6 — the statutory maximum of
        one-sixth of annual disbursements — rounded half-up to whole cents."
        PRD: "Upon activation the account's initial `monthly_escrow_cents` is
        set to the per-line monthly sum defined in §3.3, `target_cushion_cents`
        is recomputed, `next_analysis_due_date` is set to the loan's
        `closing_date` plus 12 months"

        Design: Corner/calculations/cushion_constant_one_sixth_applied
        """
        ctx = setup_active_account(loan_number="LN-CAL-1", deposits=None)
        account = get_account(ctx["account"]["id"])
        assert account["target_cushion_cents"] == 60_000, (
            "round_half_up(360000 / 6)")
        assert account["monthly_escrow_cents"] == 30_000, "20000 + 10000 per line"
        assert account["next_analysis_due_date"] == "2027-08-01", (
            "closing_date 2026-08-01 plus 12 months")
        assert account["last_analysis_year"] is None

    def test_removed_line_item_excluded_from_cushion(self, api):
        """PRD: "removed items never count"
        PRD: "removing a line item (`ACTIVE` → `REMOVED`) each recompute the
        cushion"

        Design: Corner/calculations/removed_line_item_excluded_from_cushion
        """
        ctx = setup_active_account(loan_number="LN-CAL-2", deposits=None)
        acct_id = ctx["account"]["id"]
        flood = add_line_item(acct_id, ctx["payee"]["id"],
                              expense_type="FLOOD_INSURANCE",
                              expected_annual_amount_cents=60_000,
                              installments_per_year=1, first_due_date="2027-05-01")
        assert get_account(acct_id)["target_cushion_cents"] == 70_000, (
            "420000 / 6 with the FLOOD item ACTIVE")

        removed = validate_success(api.remove_line_item(flood["id"], EA1), 200)
        assert removed["status"] == "REMOVED"
        assert get_account(acct_id)["target_cushion_cents"] == 60_000, (
            "the REMOVED item no longer feeds the cushion")


class TestSpreadRemainder:
    def test_spread_remainder_loads_first_month(self, api):
        """PRD: "`spread_monthly_cents` is that total divided by 12 rounded
        down, and `spread_first_month_cents` is the total minus eleven times
        the monthly spread, so the remainder loads onto the first month."
        PRD: "`deficiency_cents` is the amount by which the lowest projected
        balance dips below zero — zero when it never does."

        Design: Corner/calculations/shortage_spread_remainder_on_first_month
        """
        # Annual 360060, cushion 60010, base 30005; the projection trough dips
        # to -10, so shortage 60010 + deficiency 10 = 60020 to spread.
        line_items = [
            {"expense_type": "PROPERTY_TAX", "expected_annual_amount_cents": 240_060,
             "installments_per_year": 2, "first_due_date": "2026-12-15"},
            {"expense_type": "HAZARD_INSURANCE", "expected_annual_amount_cents": 120_000,
             "installments_per_year": 1, "first_due_date": "2027-03-01"},
        ]
        ctx = setup_computed_analysis(loan_number="LN-CAL-3", line_items=line_items,
                                      deposits=[(60_000, "2026-08-10")])
        computed = ctx["analysis"]
        assert computed["lowest_projected_balance_cents"] == -10
        assert computed["deficiency_cents"] == 10
        assert computed["shortage_cents"] == 60_010
        assert computed["spread_monthly_cents"] == 5_001, "floor(60020 / 12)"
        assert computed["spread_first_month_cents"] == 5_009, "60020 - 11 * 5001"
        assert computed["base_monthly_escrow_cents"] == 30_005
        assert computed["new_monthly_escrow_cents"] == 35_006, "30005 + 5001"


class TestAnalysisCreateOcc:
    def test_second_create_with_stale_account_version_rejected(self, api):
        """PRD: "Opening an analysis cycle on an escrow account requires
        `expected_escrow_account_version` equal to the account's current
        `version`."
        PRD: "if the account's version has advanced since the client last read
        it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_analysis_create_stale_version
        """
        ctx = setup_active_account(loan_number="LN-OCC-1")
        acct_id = ctx["account"]["id"]
        observed = get_account(acct_id)["version"]

        first = validate_success(api.create_analysis(
            acct_id, create_analysis_payload(observed), EA1), 201)
        assert first["status"] == "DRAFT"

        version_after = get_account(acct_id)["version"]
        assert version_after > observed, (
            "creating a cycle increments the account's version")

        # The second create carries the pre-first-create version: stale.
        resp = api.create_analysis(
            acct_id,
            create_analysis_payload(observed, analysis_year=2028,
                                    projection_start_date="2027-09-01"),
            EA1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
