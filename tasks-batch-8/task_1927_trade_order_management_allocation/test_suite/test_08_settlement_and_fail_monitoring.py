"""Settlement instruction lifecycle, fail/repair cycle, escalation cascade,
fail-monitor boundary, settlement RBAC (PRD §3.1, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_order,
    create_order,
    fail,
    get_account,
    get_instruction,
    get_order,
    instruct,
    repair,
    settle,
    setup_posted_plan,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
OPS = TEST_USERS["settlement_ops_headers"]


class TestFailRepairCycleRetainsFailCount:
    def test_fail_moves_to_failed_and_counts(self, api):
        """PRD §3.9: "An operator fails an `INSTRUCTED` instruction with a `fail_reason` of BROKER_NON_DELIVERY, CUSTODIAN_MISMATCH, INSUFFICIENT_POSITION, or OTHER and an optional `note`; the instruction — identified by `instruction_status` — moves `INSTRUCTED → FAILED`, its `fail_count` increments by one, and `INSTRUCTION_FAILED` is written."

        Design: Difficulty/non_linear_state_machine/settlement_fail_repair_cycle_retains_fail_count
        """
        scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
        instruction = scenario["instructions"][scenario["allocations"][0]["id"]]
        instruct(instruction["id"])

        failed = fail(instruction["id"], "BROKER_NON_DELIVERY")
        assert failed["instruction_status"] == "FAILED"
        assert failed["fail_count"] == 1

    def test_repair_returns_to_instructed_without_resetting_count(self, api):
        """PRD §3.9: "Repair moves `FAILED → INSTRUCTED` and writes `INSTRUCTION_REPAIRED`, and deliberately does not reset `fail_count`."

        Design: Difficulty/non_linear_state_machine/settlement_fail_repair_cycle_retains_fail_count
        """
        scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
        instruction = scenario["instructions"][scenario["allocations"][0]["id"]]
        instruct(instruction["id"])
        fail(instruction["id"], "BROKER_NON_DELIVERY")

        repaired = repair(instruction["id"])
        assert repaired["instruction_status"] == "INSTRUCTED", (
            f"FAILED → INSTRUCTED cycle via repair, got {repaired['instruction_status']}"
        )
        assert repaired["fail_count"] == 1, (
            f"Repair deliberately does not reset fail_count, got {repaired['fail_count']}"
        )


class TestSettlementFailEscalationCascade:
    def _setup_second_failure(self, api):
        """Posted plan; instruction failed once and repaired; a fresh APPROVED order
        on the same account; then the second failure fires the escalation."""
        scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
        instruction = scenario["instructions"][scenario["allocations"][0]["id"]]
        instruct(instruction["id"])
        fail(instruction["id"], "BROKER_NON_DELIVERY")
        repair(instruction["id"])
        account = scenario["accounts"][0]
        extra_order = create_order(account["id"], scenario["security"]["id"], order_qty=50)
        approve_order(extra_order["id"])
        return scenario, instruction, extra_order

    def test_second_failure_suspends_account(self, api):
        """PRD §3.9: "When `fail_count` reaches two, escalation fires automatically: the allocation's account is suspended by the system, which itself cascades the order cancellations of §3.1."

        Design: Difficulty/transitive_cascade/settlement_fail_escalation_cascade
        """
        scenario, instruction, _ = self._setup_second_failure(api)

        failed = fail(instruction["id"], "CUSTODIAN_MISMATCH")
        assert failed["instruction_status"] == "FAILED"
        assert failed["fail_count"] == 2, (
            f"Second failure crosses the escalation threshold, got {failed['fail_count']}"
        )
        account = get_account(scenario["accounts"][0]["id"])
        assert account["status"] == "SUSPENDED", (
            f"Escalation suspends the allocation's account, got {account['status']}"
        )

    def test_escalation_cancels_open_orders_but_not_allocated(self, api):
        """PRD §3.9: "When `fail_count` reaches two, escalation fires automatically: the allocation's account is suspended by the system, which itself cascades the order cancellations of §3.1."
        PRD §3.1: "Suspension is destructive by design: every order of the account sitting in `PENDING_COMPLIANCE`, `COMPLIANCE_REJECTED`, or `APPROVED` transitions to `CANCELLED` outright, while orders already `BLOCKED` in a block are deliberately left untouched — the desk must unwind blocks explicitly."

        Design: Difficulty/transitive_cascade/settlement_fail_escalation_cascade
        """
        scenario, instruction, extra_order = self._setup_second_failure(api)
        fail(instruction["id"], "CUSTODIAN_MISMATCH")

        assert get_order(extra_order["id"])["status"] == "CANCELLED", (
            "The account's APPROVED order is cancelled by the suspension cascade"
        )
        allocated_order = get_order(scenario["orders"][0]["id"])
        assert allocated_order["status"] == "ALLOCATED", (
            f"ALLOCATED orders are outside the cancellation set, got {allocated_order['status']}"
        )


def test_instruction_settle_terminal_lockdown(api):
    """PRD §3.9: "When every line of an order has reached `SETTLED`, the order bubbles up to the terminal `SETTLED` with an `ORDER_SETTLED` event — from `ALLOCATED` directly, or from `UNDER_CORRECTION` once no flagged lines remain."
    PRD §2.8: "State-machine legality — the target resource is in a valid from-state for the action. Generic mismatches surface as `ERR_INVALID_STATE` (HTTP 409) — examples include approving a DRAFT plan, settling a PENDING instruction, cancelling an ALLOCATED order, or setting an account to the status it already has."

    Design: Corner/state_machines/instruction_settle_terminal_lockdown
    """
    scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
    instruction = scenario["instructions"][scenario["allocations"][0]["id"]]
    instruct(instruction["id"])

    settled = settle(instruction["id"])
    assert settled["instruction_status"] == "SETTLED"
    order = get_order(scenario["orders"][0]["id"])
    assert order["status"] == "SETTLED", (
        f"All lines SETTLED must bubble the order up to SETTLED, got {order['status']}"
    )

    res = api.settle_settlement(instruction["id"], OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_order(scenario["orders"][0]["id"])["status"] == "SETTLED"


def test_fixed_income_settlement_lag_two_days(api):
    """PRD §3.9: "The instruction captures `custodian_name` copied from the account at creation, computes `trade_date` as the calendar date of the latest `executed_at` across the covered fills, and derives `settle_date` by adding the security's settlement lag in calendar days — one day for EQUITY, two days for FIXED_INCOME."

    Design: Corner/calculations/settlement_lag_by_asset_class
    """
    scenario = setup_posted_plan(
        order_qtys=(100,), fills=((100, 1000),), asset_class="FIXED_INCOME"
    )
    instruction = scenario["instructions"][scenario["allocations"][0]["id"]]
    assert instruction["trade_date"] == "2026-08-01"
    assert instruction["settle_date"] == "2026-08-03", (
        f"FIXED_INCOME lag is two calendar days, got {instruction['settle_date']}"
    )


def test_fail_monitor_boundary_is_strictly_greater(api):
    """PRD §3.9: "The fail monitor automates the same transition: a `SettlementOps`-driven sweep marks every `INSTRUCTED` instruction whose current logical date is strictly later than its `settle_date` plus one calendar day as FAILED with reason OTHER — an instruction exactly one day past its settle date is not yet failed — applies the escalation cascade per instruction, and reports `checked_count`, `failed_count`, and the `failed_instruction_ids`."
    PRD §2.5: "The clock is monotone: the supplied instant must be strictly later than the current value, otherwise the request is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/fail_monitor_boundary_strictly_greater
    """
    scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
    instruction = scenario["instructions"][scenario["allocations"][0]["id"]]
    instruct(instruction["id"])
    # EQUITY: trade_date 2026-08-01, settle_date 2026-08-02.

    validate_success(api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, ADMIN))
    sweep1 = validate_success(api.run_fail_monitor(OPS))
    assert sweep1["failed_count"] == 0, (
        "Exactly settle_date + 1 day (2026-08-03) is not yet overdue"
    )

    validate_success(api.set_clock({"to_iso8601": "2026-08-04T00:00:00Z"}, ADMIN))
    sweep2 = validate_success(api.run_fail_monitor(OPS))
    assert sweep2["failed_count"] == 1, "Strictly past settle_date + 1 fails the instruction"
    assert instruction["id"] in sweep2["failed_instruction_ids"]

    after = get_instruction(instruction["id"])
    assert after["instruction_status"] == "FAILED"
    assert after["fail_reason"] == "OTHER", "Automatic failures carry reason OTHER"
    assert after["fail_count"] == 1


def test_trader_cannot_instruct_settlement(api, trader_headers):
    """PRD §2.1: "A recognized role that is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/trading/settlement-instructions/{instructionId}/instruct` | Send a PENDING (or repaired) instruction to the custodian (INSTRUCTED) | SettlementOps |"

    Design: Corner/rbac/trader_cannot_instruct_settlement
    """
    scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
    instruction = scenario["instructions"][scenario["allocations"][0]["id"]]

    res = api.instruct_settlement(instruction["id"], trader_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert get_instruction(instruction["id"])["instruction_status"] == "PENDING"
