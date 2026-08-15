"""Trade-error flagging, correction accounting, dismissal compensation (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_allocation,
    get_budget,
    get_instruction,
    get_order,
    get_trade_error,
    instruct,
    list_allocations,
    positions_for,
    setup_flagged_error,
    setup_posted_plan,
    settle,
    single_instruction_for_allocation,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["settlement_ops_headers"]


class TestWrongQtyCorrectionConservesBlockQuantity:
    """Original line 100@1000 (commission 500) flagged WRONG_QTY; corrected_qty 70."""

    def _correct(self, api):
        scenario = setup_flagged_error(error_type="WRONG_QTY", with_error_account=True)
        error_id = scenario["trade_error"]["id"]
        res = api.correct_trade_error(error_id, {"corrected_qty": 70}, ADMIN)
        return scenario, res

    def test_reversal_and_correction_lines_conserve_filled_quantity(self, api):
        """PRD §3.8: "A successful correction resolves the error, moving it `OPEN → RESOLVED`, and rewrites the books in a fixed sequence."
        PRD §3.8: "The original line moves `ERROR_FLAGGED → REVERSED`: its signed quantity comes out of the position, its `commission_cents` comes out of the budget accrual, and its settlement instruction — if still `PENDING`, `INSTRUCTED`, or `FAILED` — is `CANCELLED` with an `INSTRUCTION_CANCELLED` event."
        PRD §3.8: "Correction lines are then created directly in `POSTED`, each carrying `corrects_allocation_id` pointing at the reversed original and inheriting the original's `plan_id` and `order_id`; the primary corrected line is created first and, for WRONG_QTY, the ERROR-account residual line second."
        PRD §3.8: "For WRONG_QTY, `corrected_qty` is required and must be strictly greater than zero and strictly less than the original line's `alloc_qty` — anything else is `ERR_CORRECTION_QTY_EXCEEDS`; the residual quantity is absorbed by the desk's ERROR account, selected among ACTIVE accounts whose `account_type` is ERROR with ties broken by earliest `created_at`, and if no such account exists the correction is rejected `ERR_NO_ERROR_ACCOUNT`."

        Design: Difficulty/compensating_invariant/wrong_qty_correction_conserves_block_quantity
        """
        scenario, res = self._correct(api)
        resolved = validate_success(res)
        original = scenario["flagged_allocation"]

        assert resolved["status"] == "RESOLVED"
        assert get_allocation(original["id"])["status"] == "REVERSED"

        corrections, meta = list_allocations({"corrects_allocation_id": original["id"]})
        assert meta["total_count"] == 2, (
            f"WRONG_QTY correction posts a primary line plus an ERROR residual, got {meta['total_count']}"
        )
        by_account = {line["account_id"]: line for line in corrections}
        a1 = scenario["accounts"][0]
        err = scenario["error_account"]

        primary = by_account[a1["id"]]
        assert primary["status"] == "POSTED"
        assert primary["alloc_qty"] == 70
        assert primary["alloc_price_cents"] == 1000
        assert primary["plan_id"] == original["plan_id"]
        assert primary["order_id"] == original["order_id"]
        assert primary["corrects_allocation_id"] == original["id"]

        residual = by_account[err["id"]]
        assert residual["status"] == "POSTED"
        assert residual["alloc_qty"] == 30
        assert residual["corrects_allocation_id"] == original["id"]

        total = primary["alloc_qty"] + residual["alloc_qty"]
        assert total == 100 == scenario["block"]["filled_qty"], (
            f"Correction must conserve the block's filled quantity, got {total}"
        )

    def test_positions_budgets_and_order_recomputed(self, api):
        """PRD §3.8: "Commissions are recomputed line by line under the same pinned per-line rounding as §3.7 and accrued to the receiving accounts' budgets, positions are updated by the signed correction quantities, and one `PENDING` settlement instruction is created per correction line."
        PRD §3.8: "If no sibling line of the order remains `ERROR_FLAGGED`, the order returns `UNDER_CORRECTION → ALLOCATED` with its `allocated_qty` and `avg_executed_price_cents` recomputed and an `ORDER_CORRECTION_CLEARED` event."

        Design: Difficulty/compensating_invariant/wrong_qty_correction_conserves_block_quantity
        """
        scenario, res = self._correct(api)
        validate_success(res)
        a1 = scenario["accounts"][0]
        err = scenario["error_account"]
        sec_id = scenario["security"]["id"]

        pos_a1 = positions_for(a1["id"], sec_id)
        assert len(pos_a1) == 1 and pos_a1[0]["net_qty"] == 70, (
            f"A1 position must unwind 100 and re-post 70, got {pos_a1[0]['net_qty']}"
        )
        pos_err = positions_for(err["id"], sec_id)
        assert len(pos_err) == 1 and pos_err[0]["net_qty"] == 30

        # 500 reversed then 350 re-accrued (70*1000*50/10000); residual accrues 150.
        assert get_budget(scenario["budgets"][0]["id"])["accrued_commission_cents"] == 350
        assert get_budget(scenario["error_budget"]["id"])["accrued_commission_cents"] == 150

        order = get_order(scenario["orders"][0]["id"])
        assert order["status"] == "ALLOCATED"
        # Both correction lines inherit the original's order_id and land POSTED, so
        # both sit in the order's recompute input set: allocated_qty is 70 + 30 = 100.
        assert order["allocated_qty"] == 100
        assert order["avg_executed_price_cents"] == 1000


class TestWrongAccountCorrectionConservesFirmPosition:
    """A1 line 100@1000 (commission 500) flagged WRONG_ACCOUNT; corrected to A2."""

    def _correct(self, api):
        scenario = setup_flagged_error(
            error_type="WRONG_ACCOUNT", flag_role="compliance_officer", extra_accounts=1
        )
        error_id = scenario["trade_error"]["id"]
        target = scenario["extra_accounts"][0]
        res = api.correct_trade_error(error_id, {"target_account_id": target["id"]}, ADMIN)
        return scenario, res

    def test_correction_line_moves_to_target_account_inheriting_linkage(self, api):
        """PRD §3.8: "For WRONG_ACCOUNT, `target_account_id` is required; the target account must be ACTIVE (`ERR_ACCOUNT_SUSPENDED`) and different from the original account (`ERR_INVALID_REQUEST`)."
        PRD §3.8: "Correction lines are then created directly in `POSTED`, each carrying `corrects_allocation_id` pointing at the reversed original and inheriting the original's `plan_id` and `order_id`; the primary corrected line is created first and, for WRONG_QTY, the ERROR-account residual line second."

        Design: Difficulty/compensating_invariant/wrong_account_correction_conserves_firm_position
        """
        scenario, res = self._correct(api)
        resolved = validate_success(res)
        original = scenario["flagged_allocation"]
        a2 = scenario["extra_accounts"][0]

        assert resolved["status"] == "RESOLVED"
        assert get_allocation(original["id"])["status"] == "REVERSED"

        corrections, meta = list_allocations({"corrects_allocation_id": original["id"]})
        assert meta["total_count"] == 1
        correction = corrections[0]
        assert correction["status"] == "POSTED"
        assert correction["account_id"] == a2["id"]
        assert correction["alloc_qty"] == 100
        assert correction["order_id"] == original["order_id"], "Correction inherits the order linkage"
        assert correction["plan_id"] == original["plan_id"]
        assert correction["corrects_allocation_id"] == original["id"]

    def test_firm_position_conserved_across_accounts(self, api):
        """PRD §3.9: "Positions close the loop. A Position row per `account_id`-and-`security_id` pair accumulates `net_qty` as the sum of signed allocated quantities — positive for BUY, negative for SELL — over exactly the lines in `POSTED`, `SETTLED`, or `ERROR_FLAGGED`; `PROPOSED` and `REVERSED` lines contribute nothing."
        PRD §3.8: "Commissions are recomputed line by line under the same pinned per-line rounding as §3.7 and accrued to the receiving accounts' budgets, positions are updated by the signed correction quantities, and one `PENDING` settlement instruction is created per correction line."

        Design: Difficulty/compensating_invariant/wrong_account_correction_conserves_firm_position
        """
        scenario, res = self._correct(api)
        validate_success(res)
        a1 = scenario["accounts"][0]
        a2 = scenario["extra_accounts"][0]
        sec_id = scenario["security"]["id"]

        pos_a1 = positions_for(a1["id"], sec_id)
        pos_a2 = positions_for(a2["id"], sec_id)
        assert len(pos_a1) == 1 and pos_a1[0]["net_qty"] == 0
        assert len(pos_a2) == 1 and pos_a2[0]["net_qty"] == 100
        assert pos_a1[0]["net_qty"] + pos_a2[0]["net_qty"] == 100, (
            "Firm-wide net position for the security is conserved by the move"
        )

        # Commissions move with the line: 500 leaves A1 and lands on A2.
        assert get_budget(scenario["budgets"][0]["id"])["accrued_commission_cents"] == 0
        assert get_budget(scenario["extra_budgets"][0]["id"])["accrued_commission_cents"] == 500

        order = get_order(scenario["orders"][0]["id"])
        assert order["status"] == "ALLOCATED"
        assert order["allocated_qty"] == 100


def test_dismiss_restores_flagged_line_exactly(api):
    """PRD §3.8: "Dismissal is the false-alarm path, also `DeskAdmin`: the error moves `OPEN → DISMISSED`, the flagged line returns `ERROR_FLAGGED → POSTED` exactly as it was — compensation restores the line rather than rewriting it — the order's correction context clears if no flagged siblings remain, `ERROR_DISMISSED` is written, and the error's `version` increments."

    Design: Corner/state_machines/dismiss_restores_flagged_line_exactly
    """
    scenario = setup_flagged_error(error_type="WRONG_PRICE")
    original = scenario["flagged_allocation"]
    error_id = scenario["trade_error"]["id"]

    dismissed = validate_success(api.dismiss_trade_error(error_id, ADMIN))
    assert dismissed["status"] == "DISMISSED"

    assert get_allocation(original["id"])["status"] == "POSTED"
    assert get_order(scenario["orders"][0]["id"])["status"] == "ALLOCATED"

    # Zero drift: position, accrual, and the absence of correction lines.
    pos = positions_for(scenario["accounts"][0]["id"], scenario["security"]["id"])
    assert len(pos) == 1 and pos[0]["net_qty"] == 100
    assert get_budget(scenario["budgets"][0]["id"])["accrued_commission_cents"] == 500
    _, meta = list_allocations({"corrects_allocation_id": original["id"]})
    assert meta["total_count"] == 0


def test_wrong_price_correction_recomputes_commission(api):
    """PRD §3.8: "A WRONG_PRICE correction line carries the corrected price as its `alloc_price_cents`."
    PRD §3.8: "Commissions are recomputed line by line under the same pinned per-line rounding as §3.7 and accrued to the receiving accounts' budgets, positions are updated by the signed correction quantities, and one `PENDING` settlement instruction is created per correction line."
    PRD §3.8: "The original line moves `ERROR_FLAGGED → REVERSED`: its signed quantity comes out of the position, its `commission_cents` comes out of the budget accrual, and its settlement instruction — if still `PENDING`, `INSTRUCTED`, or `FAILED` — is `CANCELLED` with an `INSTRUCTION_CANCELLED` event."

    Design: Corner/state_machines/wrong_price_correction_recomputes_commission
    """
    scenario = setup_flagged_error(error_type="WRONG_PRICE")
    original = scenario["flagged_allocation"]
    original_instruction = scenario["instructions"][original["id"]]
    error_id = scenario["trade_error"]["id"]

    resolved = validate_success(
        api.correct_trade_error(error_id, {"corrected_price_cents": 1200}, ADMIN)
    )
    assert resolved["status"] == "RESOLVED"
    assert get_allocation(original["id"])["status"] == "REVERSED"

    corrections, meta = list_allocations({"corrects_allocation_id": original["id"]})
    assert meta["total_count"] == 1
    correction = corrections[0]
    assert correction["status"] == "POSTED"
    assert correction["alloc_price_cents"] == 1200
    # round_half_up(100 * 1200 * 50 / 10000) = 600
    assert correction["commission_cents"] == 600
    assert correction["alloc_qty"] == 100

    budget = get_budget(scenario["budgets"][0]["id"])
    assert budget["accrued_commission_cents"] == 600, (
        f"500 unwound then 600 re-accrued, got {budget['accrued_commission_cents']}"
    )
    pos = positions_for(scenario["accounts"][0]["id"], scenario["security"]["id"])
    assert pos[0]["net_qty"] == 100, "Price correction conserves quantity"

    assert get_instruction(original_instruction["id"])["instruction_status"] == "CANCELLED"
    fresh = single_instruction_for_allocation(correction["id"])
    assert fresh["instruction_status"] == "PENDING"


def test_error_flagged_line_still_counts_toward_position(api):
    """PRD §3.8: "A flagged line still counts toward positions, budget accruals, and order fill statistics — nothing is unwound until a correction actually lands."
    PRD §3.8: "Flagging creates a TradeError in `OPEN`, recording the flagged `allocation_id` and the operator's header as `flagged_by_user_id`, moves the allocation `POSTED → ERROR_FLAGGED`, bumps the line's `version`, tips the owning order `ALLOCATED → UNDER_CORRECTION` with an `ORDER_UNDER_CORRECTION` event, and writes `ERROR_FLAGGED`."

    Design: Corner/calculations/position_input_set_includes_error_flagged
    """
    scenario = setup_flagged_error(error_type="WRONG_PRICE")
    original = scenario["flagged_allocation"]

    assert get_allocation(original["id"])["status"] == "ERROR_FLAGGED"
    assert get_order(scenario["orders"][0]["id"])["status"] == "UNDER_CORRECTION"
    pos = positions_for(scenario["accounts"][0]["id"], scenario["security"]["id"])
    assert len(pos) == 1 and pos[0]["net_qty"] == 100, (
        f"ERROR_FLAGGED lines remain in the position input set, got {pos[0]['net_qty']}"
    )
    assert get_budget(scenario["budgets"][0]["id"])["accrued_commission_cents"] == 500


def test_correct_qty_equal_to_original_rejected(api):
    """PRD §3.8: "For WRONG_QTY, `corrected_qty` is required and must be strictly greater than zero and strictly less than the original line's `alloc_qty` — anything else is `ERR_CORRECTION_QTY_EXCEEDS`; the residual quantity is absorbed by the desk's ERROR account, selected among ACTIVE accounts whose `account_type` is ERROR with ties broken by earliest `created_at`, and if no such account exists the correction is rejected `ERR_NO_ERROR_ACCOUNT`."

    Design: Corner/validations/correct_qty_exceeds_rejected
    """
    scenario = setup_flagged_error(error_type="WRONG_QTY", with_error_account=True)
    error_id = scenario["trade_error"]["id"]

    res = api.correct_trade_error(error_id, {"corrected_qty": 100}, ADMIN)
    validate_error(res, ApiErrorId.ERR_CORRECTION_QTY_EXCEEDS)

    assert get_trade_error(error_id)["status"] == "OPEN"
    assert get_allocation(scenario["flagged_allocation"]["id"])["status"] == "ERROR_FLAGGED"


def test_correct_qty_without_error_account_rejected(api):
    """PRD §3.8: "For WRONG_QTY, `corrected_qty` is required and must be strictly greater than zero and strictly less than the original line's `alloc_qty` — anything else is `ERR_CORRECTION_QTY_EXCEEDS`; the residual quantity is absorbed by the desk's ERROR account, selected among ACTIVE accounts whose `account_type` is ERROR with ties broken by earliest `created_at`, and if no such account exists the correction is rejected `ERR_NO_ERROR_ACCOUNT`."

    Design: Corner/validations/correct_without_error_account_rejected
    """
    scenario = setup_flagged_error(error_type="WRONG_QTY")
    error_id = scenario["trade_error"]["id"]

    res = api.correct_trade_error(error_id, {"corrected_qty": 70}, ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_ERROR_ACCOUNT)
    assert get_trade_error(error_id)["status"] == "OPEN"


def test_correct_after_instruction_settled_rejected(api):
    """PRD §3.9: "Settlement is an economic fact and is allowed regardless of the owning allocation's state — but it only propagates when the allocation is currently `POSTED`, moving it `POSTED → SETTLED` with an `ALLOCATION_SETTLED` event."
    PRD §3.9: "Settling the instruction of an `ERROR_FLAGGED` line leaves the line untouched, and any later correction attempt on that line is rejected `ERR_ALLOCATION_ALREADY_SETTLED`."
    PRD §3.8: "In all cases the original line's settlement instruction must not already be `SETTLED` (`ERR_ALLOCATION_ALREADY_SETTLED`), and every account receiving a correction line must have an OPEN budget covering the trade date with room for the recomputed commissions (`ERR_NO_ACTIVE_BUDGET`, then `ERR_COMMISSION_BUDGET_EXCEEDED`)."

    Design: Corner/validations/correct_after_settlement_rejected
    """
    scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
    line = scenario["allocations"][0]
    instruction = scenario["instructions"][line["id"]]
    instruct(instruction["id"])

    trade_error = validate_success(
        api.flag_allocation_error(line["id"], {"error_type": "WRONG_PRICE"}, OPS), 201
    )
    settled = settle(instruction["id"])
    assert settled["instruction_status"] == "SETTLED", (
        "Settle is allowed even while the line is ERROR_FLAGGED"
    )
    assert get_allocation(line["id"])["status"] == "ERROR_FLAGGED", (
        "Settling the instruction of an ERROR_FLAGGED line leaves the line untouched"
    )

    res = api.correct_trade_error(trade_error["id"], {"corrected_price_cents": 1200}, ADMIN)
    validate_error(res, ApiErrorId.ERR_ALLOCATION_ALREADY_SETTLED)
    assert get_trade_error(trade_error["id"])["status"] == "OPEN"
    assert get_allocation(line["id"])["status"] == "ERROR_FLAGGED"


def test_second_flag_on_open_error_rejected(api):
    """PRD §3.8: "The line must be `POSTED` — flagging in any other state is `ERR_INVALID_STATE` — and must not already have an OPEN trade error (`ERR_ERROR_ALREADY_OPEN`)."
    PRD §3.8: "Trade errors are listed with optional `allocation_id` and `status` filters, and fetched individually by id."

    A line carrying an OPEN trade error is always in `ERROR_FLAGGED`, so the second
    flag trips both PRD-named 409s at once; the PRD names both rules for flag but
    does not pin which check fires first, so either error id satisfies the prose.

    Design: Corner/validations/error_already_open_rejected
    """
    scenario = setup_flagged_error(error_type="WRONG_QTY")
    line = scenario["flagged_allocation"]

    res = api.flag_allocation_error(line["id"], {"error_type": "WRONG_PRICE"}, COMPLIANCE)
    validate_error_is_one_of(res, [ApiErrorId.ERR_ERROR_ALREADY_OPEN, ApiErrorId.ERR_INVALID_STATE])

    _, meta = validate_paginated(api.list_trade_errors(OPS, params={"allocation_id": line["id"]}))
    assert meta["total_count"] == 1, (
        f"The rejected second flag must not create another error, got {meta['total_count']}"
    )
