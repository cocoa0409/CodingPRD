"""Plan posting cascade, stale-batch guard, empty-batch boundary, block parallel
dimensions, and post-pipeline RBAC (PRD §3.4, §3.6, §3.7, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_plan,
    create_plan_for_block,
    get_block,
    get_budget,
    get_order,
    get_plan,
    list_allocations_for_plan,
    list_instructions_for_allocation,
    positions_for,
    post_plan,
    propose_plan,
    record_fill,
    setup_filled_block,
    setup_posted_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

TRADER = TEST_USERS["trader_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


class TestPlanPostTransitiveCascade:
    """Two accounts 100/300, one fill 400@2000, PRO_RATA; A1 budget exactly 1000."""

    def test_post_mutates_plan_lines_orders_and_block(self, api):
        """PRD §3.7: "On a successful post, every line moves `PROPOSED → POSTED`; each account's budget accrues its lines' commissions; a Position row is upserted per account-and-security pair with `net_qty` increased by the signed allocated quantity, positive for a BUY block and negative for a SELL block; every covered member order moves `BLOCKED → ALLOCATED` with its `allocated_qty` recomputed as the sum of `alloc_qty` over its lines in `POSTED`, `SETTLED`, or `ERROR_FLAGGED` and its `avg_executed_price_cents` recomputed as the quantity-weighted average of `alloc_price_cents` over the same line set, rounded half-up to whole cents and null until the order's first POSTED line, writing `ORDER_ALLOCATED`; the block's `allocated_through_seq` watermark advances to `covered_to_seq`, its `allocation_status` becomes `PARTIAL` — or `FULL` when the watermark now reaches the greatest `fill_seq` — and the block's `version` increments; exactly one settlement instruction per line is created in `PENDING` (§3.9); the plan's own `version` increments; and `PLAN_POSTED` lands."

        Design: Difficulty/transitive_cascade/plan_post_transitive_cascade
        """
        scenario = setup_posted_plan(
            order_qtys=(100, 300), fills=((400, 2000),),
            budget_amount_cents=(1000, 100000),
        )
        plan = scenario["plan"]
        o1 = scenario["orders"][0]

        assert plan["status"] == "POSTED"
        lines = list_allocations_for_plan(plan["id"])
        assert len(lines) == 2
        for line in lines:
            assert line["status"] == "POSTED", f"Every line must be POSTED, got {line['status']}"

        order1 = get_order(o1["id"])
        assert order1["status"] == "ALLOCATED"
        assert order1["allocated_qty"] == 100
        assert order1["avg_executed_price_cents"] == 2000

        block = scenario["block"]
        assert block["status"] == "FILLED"
        assert block["allocated_through_seq"] == 1
        assert block["allocation_status"] == "FULL"

    def test_post_reaches_budgets_positions_and_instructions(self, api):
        """PRD §3.2: "When a posting brings the accrual to exactly the budgeted amount, the budget flips from OPEN to the terminal EXHAUSTED automatically and writes `BUDGET_EXHAUSTED`."
        PRD §3.9: "Posting a plan — and, later, landing a correction — creates exactly one settlement instruction per POSTED line, starting in `PENDING` with `fail_count` at zero."
        PRD §3.9: "The instruction captures `custodian_name` copied from the account at creation, computes `trade_date` as the calendar date of the latest `executed_at` across the covered fills, and derives `settle_date` by adding the security's settlement lag in calendar days — one day for EQUITY, two days for FIXED_INCOME."
        PRD §3.9: "Positions close the loop. A Position row per `account_id`-and-`security_id` pair accumulates `net_qty` as the sum of signed allocated quantities — positive for BUY, negative for SELL — over exactly the lines in `POSTED`, `SETTLED`, or `ERROR_FLAGGED`; `PROPOSED` and `REVERSED` lines contribute nothing."

        Design: Difficulty/transitive_cascade/plan_post_transitive_cascade
        """
        scenario = setup_posted_plan(
            order_qtys=(100, 300), fills=((400, 2000),),
            budget_amount_cents=(1000, 100000),
        )
        a1, a2 = scenario["accounts"]
        b1, b2 = scenario["budgets"]

        budget1 = get_budget(b1["id"])
        # round_half_up(100 * 2000 * 50 / 10000) = 1000 -> exact equality exhausts
        assert budget1["accrued_commission_cents"] == 1000
        assert budget1["status"] == "EXHAUSTED", (
            f"Exact equality must flip the budget to EXHAUSTED, got {budget1['status']}"
        )
        budget2 = get_budget(b2["id"])
        assert budget2["accrued_commission_cents"] == 3000  # 300 * 2000 * 50 / 10000
        assert budget2["status"] == "OPEN"

        pos1 = positions_for(a1["id"], scenario["security"]["id"])
        assert len(pos1) == 1 and pos1[0]["net_qty"] == 100
        pos2 = positions_for(a2["id"], scenario["security"]["id"])
        assert len(pos2) == 1 and pos2[0]["net_qty"] == 300

        for line in scenario["allocations"]:
            instructions = list_instructions_for_allocation(line["id"])
            assert len(instructions) == 1, "Exactly one instruction per POSTED line"
            instruction = instructions[0]
            assert instruction["instruction_status"] == "PENDING"
            assert instruction["fail_count"] == 0
            assert instruction["custodian_name"] == "CUSTO"
            assert instruction["trade_date"] == "2026-08-01"
            assert instruction["settle_date"] == "2026-08-02", (
                f"EQUITY lag is one calendar day, got {instruction['settle_date']}"
            )


class TestPlanPostStateBeatsFiscal:
    """Budget 500 < required commission 1000; plan left PROPOSED for the conflict."""

    def _setup_proposed_plan_with_tight_budget(self, api):
        scenario = setup_filled_block(
            order_qtys=(100,), fills=((100, 2000),), budget_amount_cents=500
        )
        plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
        propose_plan(plan["id"])
        return scenario, plan

    def test_state_error_preempts_budget_error(self, api):
        """PRD §2.8: "When a single request violates several rules, the system does not choose arbitrarily: checks are evaluated in a fixed priority order and the first failure wins."
        PRD §3.7: "Posting is the point of no return, performed by a `Trader` on an `APPROVED` plan — any other plan state is rejected `ERR_PLAN_NOT_POSTABLE`."
        PRD §2.8: "12. Fiscal gates (HTTP 422): projected commission accrual fits the budget (`ERR_COMMISSION_BUDGET_EXCEEDED`), and the plan's fairness metric is within tolerance at approval (`ERR_UNFAIR_ALLOCATION`)."

        Design: Difficulty/priority_pair_validation_conflict/plan_post_state_beats_fiscal
        """
        scenario, plan = self._setup_proposed_plan_with_tight_budget(api)

        # The post violates both the from-state rule (plan PROPOSED, priority 6) and
        # the budget sufficiency rule (500 < 1000, priority 12); state must win.
        res = api.post_plan(plan["id"], TRADER)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_POSTABLE)

    def test_rejected_post_changes_nothing(self, api):
        """PRD §3.7: "Posting is the point of no return, performed by a `Trader` on an `APPROVED` plan — any other plan state is rejected `ERR_PLAN_NOT_POSTABLE`."
        PRD §3.2: "A fresh budget starts OPEN with `accrued_commission_cents` at zero and writes `BUDGET_CREATED`."

        Design: Difficulty/priority_pair_validation_conflict/plan_post_state_beats_fiscal
        """
        scenario, plan = self._setup_proposed_plan_with_tight_budget(api)
        validate_error(api.post_plan(plan["id"], TRADER), ApiErrorId.ERR_PLAN_NOT_POSTABLE)

        assert get_plan(plan["id"])["status"] == "PROPOSED"
        budget = get_budget(scenario["budgets"][0]["id"])
        assert budget["accrued_commission_cents"] == 0, (
            f"A rejected post must not accrue, got {budget['accrued_commission_cents']}"
        )

    def test_fiscal_gate_fires_once_state_check_passes(self, api):
        """PRD §3.7: "Then the fiscal gate runs per distinct account in the plan: the account must have an OPEN budget whose half-open window covers the trade date — the calendar date of the latest `executed_at` among the covered fills — otherwise `ERR_NO_ACTIVE_BUDGET`; and the projected accrual, the budget's current `accrued_commission_cents` plus the sum of that account's line commissions, must not exceed `budget_amount_cents`, or the entire post is rejected `ERR_COMMISSION_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/plan_post_state_beats_fiscal
        """
        scenario, plan = self._setup_proposed_plan_with_tight_budget(api)
        approve_plan(plan["id"])

        # Now only the fiscal rule is violated: commission 1000 > budget 500.
        res = api.post_plan(plan["id"], TRADER)
        validate_error(res, ApiErrorId.ERR_COMMISSION_BUDGET_EXCEEDED)
        assert get_plan(plan["id"])["status"] == "APPROVED"


class TestProposeEmptyBatchBoundary:
    def _setup_second_plan_without_new_fills(self, api):
        scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
        plan2 = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
        return scenario, plan2

    def test_propose_without_uncovered_fills_rejected(self, api):
        """PRD §3.7: "There must be something to allocate — at least one fill whose `fill_seq` lies beyond `covered_from_seq`, otherwise `ERR_NOTHING_TO_ALLOCATE` — and the block must still hold at least one member order (`ERR_EMPTY_BLOCK`)."

        Design: Difficulty/boundary_precision_check/propose_empty_batch_boundary
        """
        scenario, plan2 = self._setup_second_plan_without_new_fills(api)
        assert plan2["covered_from_seq"] == 1

        res = api.propose_plan(plan2["id"], TRADER)
        validate_error(res, ApiErrorId.ERR_NOTHING_TO_ALLOCATE)

    def test_rejected_propose_leaves_batch_fields_null(self, api):
        """PRD §3.7: "The new plan starts `DRAFT` with its batch fields — `covered_to_seq`, `batch_qty`, `batch_avg_price_cents`, and `max_deviation_bp` — all null until the first successful propose, and the block's `version` increments."

        Design: Difficulty/boundary_precision_check/propose_empty_batch_boundary
        """
        scenario, plan2 = self._setup_second_plan_without_new_fills(api)
        validate_error(api.propose_plan(plan2["id"], TRADER), ApiErrorId.ERR_NOTHING_TO_ALLOCATE)

        stayed = get_plan(plan2["id"])
        assert stayed["status"] == "DRAFT"
        assert stayed["covered_to_seq"] is None
        assert stayed["batch_qty"] is None
        assert stayed["batch_avg_price_cents"] is None
        assert stayed["max_deviation_bp"] is None


def test_block_parallel_dimensions_evolve_independently(api):
    """PRD §3.7: "On a successful post, every line moves `PROPOSED → POSTED`; each account's budget accrues its lines' commissions; a Position row is upserted per account-and-security pair with `net_qty` increased by the signed allocated quantity, positive for a BUY block and negative for a SELL block; every covered member order moves `BLOCKED → ALLOCATED` with its `allocated_qty` recomputed as the sum of `alloc_qty` over its lines in `POSTED`, `SETTLED`, or `ERROR_FLAGGED` and its `avg_executed_price_cents` recomputed as the quantity-weighted average of `alloc_price_cents` over the same line set, rounded half-up to whole cents and null until the order's first POSTED line, writing `ORDER_ALLOCATED`; the block's `allocated_through_seq` watermark advances to `covered_to_seq`, its `allocation_status` becomes `PARTIAL` — or `FULL` when the watermark now reaches the greatest `fill_seq` — and the block's `version` increments; exactly one settlement instruction per line is created in `PENDING` (§3.9); the plan's own `version` increments; and `PLAN_POSTED` lands."
    PRD §3.6: "One subtler consequence matters for allocation: if the block's `allocation_status` had reached `FULL` and a new fill arrives, the dimension drops back `FULL → PARTIAL`, because the new fill is uncovered by any posted plan (§3.7), and the block's `version` increments again."

    Design: Corner/state_machines/block_parallel_dimensions_independent
    """
    scenario = setup_filled_block(order_qtys=(100, 300), fills=((300, 1000),))
    block_id = scenario["block"]["id"]
    plan = create_plan_for_block(block_id, method="PRO_RATA")
    propose_plan(plan["id"])
    approve_plan(plan["id"])
    post_plan(plan["id"])

    block = get_block(block_id)
    assert block["status"] == "PARTIALLY_FILLED", (
        f"300 of 400 filled must keep execution at PARTIALLY_FILLED, got {block['status']}"
    )
    assert block["allocation_status"] == "FULL", (
        f"Watermark reached the greatest fill_seq, got {block['allocation_status']}"
    )

    record_fill(block_id, 100, 1100, executed_at="2026-08-01T09:05:00Z")
    block = get_block(block_id)
    assert block["status"] == "FILLED"
    assert block["allocation_status"] == "PARTIAL", (
        f"The new uncovered fill must drop allocation FULL → PARTIAL, got {block['allocation_status']}"
    )


def test_order_cancel_from_allocated_returns_invalid_state(api):
    """PRD §3.4: "Cancellation is available to a `Trader` from `PENDING_COMPLIANCE`, `COMPLIANCE_REJECTED`, or `APPROVED` — exactly the three states the account-suspension cascade cancels — and lands the order in the terminal `CANCELLED` with `ORDER_CANCELLED`."
    PRD §3.4: "Cancelling an order in any later state, such as `BLOCKED` or `ALLOCATED`, is rejected `ERR_INVALID_STATE`."

    Design: Corner/state_machines/order_cancel_from_allocated_returns_invalid_state
    """
    scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
    order = scenario["orders"][0]
    assert get_order(order["id"])["status"] == "ALLOCATED"

    res = api.cancel_order(order["id"], TRADER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_order(order["id"])["status"] == "ALLOCATED", (
        "A rejected cancel must leave the order ALLOCATED"
    )


def test_desk_admin_cannot_approve_plan(api, desk_admin_headers):
    """PRD §2.1: "A recognized role that is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/trading/allocation-plans/{planId}/approve` | Approve a PROPOSED plan (segregation of duties plus fairness gate) | ComplianceOfficer |"

    Design: Corner/rbac/desk_admin_cannot_approve_plan
    """
    scenario = setup_filled_block(order_qtys=(100,), fills=((100, 1000),))
    plan = create_plan_for_block(scenario["block"]["id"], method="PRO_RATA")
    propose_plan(plan["id"])

    res = api.approve_plan(plan["id"], desk_admin_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert get_plan(plan["id"])["status"] == "PROPOSED"
