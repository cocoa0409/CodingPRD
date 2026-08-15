"""Commission math, budget accrual gate, exhaustion boundary, period overlap (PRD §3.2, §3.7)."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    approve_plan,
    create_account,
    create_budget_payload,
    create_plan_for_block,
    get_budget,
    get_plan,
    list_allocations_for_plan,
    list_positions,
    post_plan,
    propose_plan,
    setup_filled_block,
    setup_posted_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]


class TestBudgetExactExhaustionBoundary:
    """Account budget exactly 1000; one line 100@2000 at 50bp -> commission exactly 1000."""

    def test_exact_equality_post_succeeds_and_accrues(self, api):
        """PRD §3.7: "Exact equality is allowed and, per §3.2, flips the budget to EXHAUSTED."
        PRD §3.2: "A posting that would push the accrual past the budgeted amount is rejected outright with `ERR_COMMISSION_BUDGET_EXCEEDED` — only exact equality exhausts, and overshoot never lands."

        Design: Difficulty/boundary_precision_check/budget_exact_exhaustion_boundary
        """
        scenario = setup_posted_plan(
            order_qtys=(100,), fills=((100, 2000),), budget_amount_cents=1000
        )
        assert scenario["plan"]["status"] == "POSTED", "Post at exact equality must be allowed"
        budget = get_budget(scenario["budgets"][0]["id"])
        assert budget["accrued_commission_cents"] == 1000
        assert budget["accrued_commission_cents"] == budget["budget_amount_cents"]

    def test_exact_equality_flips_budget_to_exhausted(self, api):
        """PRD §3.2: "When a posting brings the accrual to exactly the budgeted amount, the budget flips from OPEN to the terminal EXHAUSTED automatically and writes `BUDGET_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/budget_exact_exhaustion_boundary
        """
        scenario = setup_posted_plan(
            order_qtys=(100,), fills=((100, 2000),), budget_amount_cents=1000
        )
        budget = get_budget(scenario["budgets"][0]["id"])
        assert budget["status"] == "EXHAUSTED", (
            f"Accrual exactly == budget must flip status EXHAUSTED, got {budget['status']}"
        )


class TestCommissionPerLineRoundingOrder:
    """Two 3-unit lines at 155c with a 33bp broker: per-line round_half_up(1.5345) = 2."""

    def test_each_line_rounded_half_up_individually(self, api):
        """PRD §3.7: "Commissions are computed per line at the moment of posting: the line's notional — its `alloc_qty` multiplied by its `alloc_price_cents` — is multiplied by the routed broker's `commission_rate_bp` and divided by ten thousand, then rounded half-up to whole cents and stored as the line's `commission_cents`."

        Design: Difficulty/combinatorial_formula/commission_per_line_rounding_order
        """
        scenario = setup_posted_plan(
            order_qtys=(3, 3), fills=((6, 155),), commission_rate_bp=33
        )
        lines = list_allocations_for_plan(scenario["plan"]["id"])
        assert len(lines) == 2
        for line in lines:
            # round_half_up(3 * 155 * 33 / 10000) = round_half_up(1.5345) = 2
            assert line["commission_cents"] == 2, (
                f"Per-line rounded commission must be 2, got {line['commission_cents']}"
            )

    def test_budget_accrues_sum_of_rounded_lines(self, api):
        """PRD §3.7: "Each line is rounded individually and only afterwards summed per account for the accrual; rounding a summed notional once is forbidden, since per-line-rounded sums can differ by cents."

        Design: Difficulty/combinatorial_formula/commission_per_line_rounding_order
        """
        scenario = setup_posted_plan(
            order_qtys=(3, 3), fills=((6, 155),), commission_rate_bp=33
        )
        for budget in scenario["budgets"]:
            accrued = get_budget(budget["id"])["accrued_commission_cents"]
            # Sum of per-line-rounded commissions: 2 per account
            # (rounding the summed notional once would produce a different total).
            assert accrued == 2, f"Accrual must sum rounded line commissions (2), got {accrued}"


class TestBudgetPeriodOverlap:
    def test_adjacent_half_open_periods_coexist(self, api):
        """PRD §3.2: "Adjacency is not intersection — one budget's `period_end` may equal another's `period_start`, and the two coexist."

        Design: Difficulty/resource_temporal_overlap/budget_half_open_period_overlap
        """
        account = create_account()
        validate_success(
            api.create_commission_budget(
                account["id"],
                create_budget_payload(period_start="2026-01-01", period_end="2026-04-01"),
                ADMIN,
            ),
            201,
        )
        adjacent = api.create_commission_budget(
            account["id"],
            create_budget_payload(period_start="2026-04-01", period_end="2026-07-01"),
            ADMIN,
        )
        validate_success(adjacent, 201)

    def test_interior_intersection_rejected(self, api):
        """PRD §3.2: "Windows of the same account must be disjoint across its OPEN and EXHAUSTED budgets: a new budget whose half-open window intersects an existing one is rejected with `ERR_BUDGET_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/budget_half_open_period_overlap
        """
        account = create_account()
        validate_success(
            api.create_commission_budget(
                account["id"],
                create_budget_payload(period_start="2026-01-01", period_end="2026-04-01"),
                ADMIN,
            ),
            201,
        )
        validate_success(
            api.create_commission_budget(
                account["id"],
                create_budget_payload(period_start="2026-04-01", period_end="2026-07-01"),
                ADMIN,
            ),
            201,
        )
        # [2026-03-31, 2026-06-01) strictly intersects both existing windows.
        res = api.create_commission_budget(
            account["id"],
            create_budget_payload(
                period_start="2026-03-31", period_end="2026-06-01", budget_amount_cents=50000
            ),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_PERIOD_OVERLAP)


def test_post_without_covering_budget_rejected(api):
    """PRD §3.7: "Then the fiscal gate runs per distinct account in the plan: the account must have an OPEN budget whose half-open window covers the trade date — the calendar date of the latest `executed_at` among the covered fills — otherwise `ERR_NO_ACTIVE_BUDGET`; and the projected accrual, the budget's current `accrued_commission_cents` plus the sum of that account's line commissions, must not exceed `budget_amount_cents`, or the entire post is rejected `ERR_COMMISSION_BUDGET_EXCEEDED`."

    Design: Corner/validations/post_without_budget_rejected
    """
    scenario = setup_filled_block(order_qtys=(100,), fills=((100, 1000),), with_budgets=False)
    plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
    propose_plan(plan["id"])
    approve_plan(plan["id"])

    res = api.post_plan(plan["id"], TRADER)
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_BUDGET)

    assert get_plan(plan["id"])["status"] == "APPROVED", (
        "A rejected post must leave the plan APPROVED"
    )
    for line in list_allocations_for_plan(plan["id"]):
        assert line["status"] == "PROPOSED", f"No line may be POSTED after a rejected post, got {line['status']}"


def test_post_that_would_exceed_budget_rejected(api):
    """PRD §3.7: "Then the fiscal gate runs per distinct account in the plan: the account must have an OPEN budget whose half-open window covers the trade date — the calendar date of the latest `executed_at` among the covered fills — otherwise `ERR_NO_ACTIVE_BUDGET`; and the projected accrual, the budget's current `accrued_commission_cents` plus the sum of that account's line commissions, must not exceed `budget_amount_cents`, or the entire post is rejected `ERR_COMMISSION_BUDGET_EXCEEDED`."
    PRD §3.2: "A posting that would push the accrual past the budgeted amount is rejected outright with `ERR_COMMISSION_BUDGET_EXCEEDED` — only exact equality exhausts, and overshoot never lands."

    Design: Corner/validations/post_budget_would_exceed_rejected
    """
    scenario = setup_filled_block(
        order_qtys=(100,), fills=((100, 2000),), budget_amount_cents=999
    )
    plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
    propose_plan(plan["id"])
    approve_plan(plan["id"])

    # Projected accrual 0 + 1000 > 999 -> entire post rejected.
    res = api.post_plan(plan["id"], TRADER)
    validate_error(res, ApiErrorId.ERR_COMMISSION_BUDGET_EXCEEDED)

    budget = get_budget(scenario["budgets"][0]["id"])
    assert budget["accrued_commission_cents"] == 0, (
        f"All-or-nothing: accrual must stay 0, got {budget['accrued_commission_cents']}"
    )
    assert get_plan(plan["id"])["status"] == "APPROVED"
    _, meta = list_positions({"account_id": scenario["accounts"][0]["id"]})
    assert meta["total_count"] == 0, "All-or-nothing: no position may be created by a rejected post"
