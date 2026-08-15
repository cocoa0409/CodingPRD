"""Composite setup helpers for the trading-desk test suites.

Every helper builds its preconditions from scratch against PRD-declared
endpoints (each pytest test runs against a freshly restarted server with an
empty database). Setup calls use get_success_data() so a broken precondition
surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import build_user_headers, get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_account_payload,
    create_block_payload,
    create_broker_payload,
    create_budget_payload,
    create_fail_payload,
    create_fill_payload,
    create_flag_payload,
    create_order_payload,
    create_plan_payload,
    create_restriction_payload,
    create_security_payload,
    create_status_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
EXEC = TEST_USERS["execution_desk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["settlement_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

TRADER_USER_ID = TEST_DEFAULTS["TRADER_USER_ID"]
APPROVER_USER_ID = TEST_DEFAULTS["APPROVER_USER_ID"]
DEFAULT_BUDGET_CENTS = TEST_DEFAULTS["BUDGET_AMOUNT_CENTS"]


def _fill_time(index: int) -> str:
    """Broker execution timestamps spaced five minutes apart from 09:00."""
    return f"2026-08-01T09:{5 * index:02d}:00Z"


# ─── Tier 1: reference data ───────────────────────────


def create_account(account_code="A1", account_type="DISCRETIONARY", **overrides):
    res = api_client.create_account(
        create_account_payload(account_code=account_code, account_type=account_type, **overrides),
        ADMIN,
    )
    return get_success_data(res, 201)


def create_security(ticker="ACME", asset_class="EQUITY", lot_size=1, **overrides):
    res = api_client.create_security(
        create_security_payload(ticker=ticker, asset_class=asset_class, lot_size=lot_size, **overrides),
        ADMIN,
    )
    return get_success_data(res, 201)


def create_broker(broker_code="BRK1", commission_rate_bp=50, supported_asset_classes=None, **overrides):
    res = api_client.create_broker(
        create_broker_payload(
            broker_code=broker_code,
            commission_rate_bp=commission_rate_bp,
            supported_asset_classes=supported_asset_classes or ["EQUITY", "FIXED_INCOME"],
            **overrides,
        ),
        ADMIN,
    )
    return get_success_data(res, 201)


def create_commission_budget(account_id, budget_amount_cents=DEFAULT_BUDGET_CENTS, **overrides):
    res = api_client.create_commission_budget(
        account_id,
        create_budget_payload(budget_amount_cents=budget_amount_cents, **overrides),
        ADMIN,
    )
    return get_success_data(res, 201)


def create_restriction(**overrides):
    """Create a restriction (lands DRAFT)."""
    res = api_client.create_restriction(create_restriction_payload(**overrides), COMPLIANCE)
    return get_success_data(res, 201)


def activate_restriction(restriction_id):
    return get_success_data(api_client.activate_restriction(restriction_id, COMPLIANCE))


def create_active_restriction(**overrides):
    """Create + activate a restriction. Returns the ACTIVE restriction."""
    restriction = create_restriction(**overrides)
    return activate_restriction(restriction["id"])


# ─── Tier 2: order pipeline ───────────────────────────


def create_order(account_id, security_id, side="BUY", order_qty=100, order_type="MARKET", **overrides):
    res = api_client.create_order(
        create_order_payload(account_id, security_id, side=side, order_qty=order_qty, order_type=order_type, **overrides),
        TRADER,
    )
    return get_success_data(res, 201)


def run_compliance_check(order_id):
    """Run the compliance check; returns the order whatever the outcome."""
    return get_success_data(api_client.compliance_check_order(order_id, COMPLIANCE))


def approve_order(order_id):
    """Run the compliance check and require APPROVED."""
    order = run_compliance_check(order_id)
    assert order["status"] == "APPROVED", (
        f"Setup expected compliance APPROVED, got {order['status']} "
        f"(note: {order.get('compliance_note')})"
    )
    return order


def create_approved_order(account_id, security_id, **overrides):
    order = create_order(account_id, security_id, **overrides)
    return approve_order(order["id"])


# ─── Tier 2/3: block pipeline ─────────────────────────


def create_block(security_id, side="BUY"):
    return get_success_data(api_client.create_block(create_block_payload(security_id, side=side), TRADER), 201)


def attach_order(block_id, order_id):
    return get_success_data(api_client.attach_order_to_block(block_id, {"order_id": order_id}, TRADER))


def route_block(block_id, broker_id):
    return get_success_data(api_client.route_block(block_id, {"broker_id": broker_id}, TRADER))


def record_fill(block_id, fill_qty, fill_price_cents, executed_at=None):
    payload = create_fill_payload(fill_qty=fill_qty, fill_price_cents=fill_price_cents)
    if executed_at is not None:
        payload["executed_at"] = executed_at
    return get_success_data(api_client.record_fill(block_id, payload, EXEC), 201)


def get_block(block_id):
    return get_success_data(api_client.get_block(block_id, TRADER))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, TRADER))


def get_budget(budget_id):
    return get_success_data(api_client.get_commission_budget(budget_id, TRADER))


def get_plan(plan_id):
    return get_success_data(api_client.get_allocation_plan(plan_id, TRADER))


def get_allocation(allocation_id):
    return get_success_data(api_client.get_allocation(allocation_id, TRADER))


def get_instruction(instruction_id):
    return get_success_data(api_client.get_settlement_instruction(instruction_id, OPS))


def get_trade_error(error_id):
    return get_success_data(api_client.get_trade_error(error_id, ADMIN))


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, ADMIN))


# ─── Tier 3: allocation plan pipeline ─────────────────


def create_plan_for_block(block_id, method="PRO_RATA", creator_user_id=TRADER_USER_ID):
    """Read the block's current version and create an OCC-guarded plan (DRAFT)."""
    version = get_block(block_id)["version"]
    headers = build_user_headers(creator_user_id, "Trader")
    res = api_client.create_allocation_plan(
        block_id, create_plan_payload(method, version), headers
    )
    return get_success_data(res, 201)


def propose_plan(plan_id, trader_user_id=TRADER_USER_ID):
    return get_success_data(api_client.propose_plan(plan_id, build_user_headers(trader_user_id, "Trader")))


def approve_plan(plan_id, approver_user_id=APPROVER_USER_ID):
    return get_success_data(
        api_client.approve_plan(plan_id, build_user_headers(approver_user_id, "ComplianceOfficer"))
    )


def post_plan(plan_id):
    return get_success_data(api_client.post_plan(plan_id, TRADER))


# ─── Listing helpers ──────────────────────────────────


def list_allocations(params=None):
    data, meta = validate_paginated(api_client.list_allocations(TRADER, params=params))
    return data, meta


def list_allocations_for_plan(plan_id):
    data, _ = list_allocations({"plan_id": plan_id})
    return data


def list_instructions(params=None):
    data, meta = validate_paginated(api_client.list_settlement_instructions(OPS, params=params))
    return data, meta


def list_instructions_for_allocation(allocation_id):
    data, _ = list_instructions({"allocation_id": allocation_id})
    return data


def single_instruction_for_allocation(allocation_id):
    instructions = list_instructions_for_allocation(allocation_id)
    assert len(instructions) == 1, (
        f"Expected exactly one settlement instruction for allocation {allocation_id}, "
        f"got {len(instructions)}"
    )
    return instructions[0]


def list_positions(params=None):
    data, meta = validate_paginated(api_client.list_positions(TRADER, params=params))
    return data, meta


def positions_for(account_id, security_id=None):
    params = {"account_id": account_id}
    if security_id is not None:
        params["security_id"] = security_id
    data, _ = list_positions(params)
    return data


def list_orders(params=None):
    data, meta = validate_paginated(api_client.list_orders(TRADER, params=params))
    return data, meta


# ─── Settlement instruction lifecycle ─────────────────


def instruct(instruction_id):
    return get_success_data(api_client.instruct_settlement(instruction_id, OPS))


def settle(instruction_id):
    return get_success_data(api_client.settle_settlement(instruction_id, OPS))


def fail(instruction_id, fail_reason):
    return get_success_data(api_client.fail_settlement(instruction_id, create_fail_payload(fail_reason), OPS))


def repair(instruction_id):
    return get_success_data(api_client.repair_settlement(instruction_id, OPS))


# ─── Tier 3 mega-fixtures: scenario composition ───────


def setup_routed_block(
    order_qtys=(100,),
    side="BUY",
    asset_class="EQUITY",
    lot_size=1,
    commission_rate_bp=50,
    supported_asset_classes=None,
    budget_amount_cents=DEFAULT_BUDGET_CENTS,
    with_budgets=True,
    extra_accounts=0,
    extra_account_budget_cents=DEFAULT_BUDGET_CENTS,
    with_error_account=False,
    error_budget_cents=DEFAULT_BUDGET_CENTS,
):
    """Accounts (one per order quantity, each with an OPEN budget unless disabled),
    one security, one broker, APPROVED orders attached to a routed (WORKING) block.

    ``budget_amount_cents`` may be a single int (same for every order account) or a
    sequence aligned with ``order_qtys``. ``extra_accounts`` adds DISCRETIONARY
    accounts (with budgets) that own no orders; ``with_error_account`` adds an
    ERROR-type account (with budget) for quantity-correction residual absorption.

    Returns a scenario dict.
    """
    n = len(order_qtys)
    if isinstance(budget_amount_cents, (list, tuple)):
        budget_amounts = list(budget_amount_cents)
        assert len(budget_amounts) == n
    else:
        budget_amounts = [budget_amount_cents] * n

    accounts, budgets = [], []
    for i, qty in enumerate(order_qtys):
        account = create_account(account_code=f"A{i + 1}")
        accounts.append(account)
        if with_budgets:
            budgets.append(create_commission_budget(account["id"], budget_amount_cents=budget_amounts[i]))
        else:
            budgets.append(None)

    extras, extra_budgets = [], []
    for j in range(extra_accounts):
        account = create_account(account_code=f"X{j + 1}")
        extras.append(account)
        extra_budgets.append(
            create_commission_budget(account["id"], budget_amount_cents=extra_account_budget_cents)
        )

    error_account = error_budget = None
    if with_error_account:
        error_account = create_account(account_code="ERRACCT", account_type="ERROR")
        error_budget = create_commission_budget(error_account["id"], budget_amount_cents=error_budget_cents)

    security = create_security(asset_class=asset_class, lot_size=lot_size)
    broker = create_broker(
        commission_rate_bp=commission_rate_bp,
        supported_asset_classes=supported_asset_classes or [asset_class],
    )

    orders = [
        create_approved_order(accounts[i]["id"], security["id"], side=side, order_qty=qty)
        for i, qty in enumerate(order_qtys)
    ]
    block = create_block(security["id"], side=side)
    for order in orders:
        attach_order(block["id"], order["id"])
    block = route_block(block["id"], broker["id"])

    return {
        "accounts": accounts,
        "budgets": budgets,
        "extra_accounts": extras,
        "extra_budgets": extra_budgets,
        "error_account": error_account,
        "error_budget": error_budget,
        "security": security,
        "broker": broker,
        "orders": orders,
        "block": block,
    }


def setup_filled_block(fills=((100, 1000),), **kwargs):
    """Routed block plus the given (fill_qty, fill_price_cents) fills recorded in order."""
    scenario = setup_routed_block(**kwargs)
    recorded = []
    for i, fill_spec in enumerate(fills):
        qty, price = fill_spec[0], fill_spec[1]
        executed_at = fill_spec[2] if len(fill_spec) > 2 else _fill_time(i)
        recorded.append(record_fill(scenario["block"]["id"], qty, price, executed_at=executed_at))
    scenario["fills"] = recorded
    scenario["block"] = get_block(scenario["block"]["id"])
    return scenario


def setup_posted_plan(fills=((100, 1000),), method="PRO_RATA", **kwargs):
    """Full chain through a POSTED allocation plan.

    Returns the scenario dict augmented with:
      plan         — the POSTED AllocationPlan
      allocations  — the plan's POSTED allocation lines
      instructions — {allocation_id: its single PENDING SettlementInstruction}
      block        — refreshed block state after the post
    """
    scenario = setup_filled_block(fills=fills, **kwargs)
    plan = create_plan_for_block(scenario["block"]["id"], method=method)
    propose_plan(plan["id"])
    approve_plan(plan["id"])
    plan = post_plan(plan["id"])
    scenario["plan"] = plan
    scenario["allocations"] = list_allocations_for_plan(plan["id"])
    scenario["instructions"] = {
        line["id"]: single_instruction_for_allocation(line["id"]) for line in scenario["allocations"]
    }
    scenario["block"] = get_block(scenario["block"]["id"])
    return scenario


def setup_flagged_error(error_type="WRONG_PRICE", flag_role="settlement_ops", **kwargs):
    """Posted single-order scenario with its one allocation line flagged.

    Returns the posted scenario augmented with:
      flagged_allocation — the ERROR_FLAGGED line
      trade_error        — the OPEN TradeError
    """
    scenario = setup_posted_plan(**kwargs)
    assert len(scenario["allocations"]) == 1, "flag fixture expects a single-line plan"
    line = scenario["allocations"][0]
    headers = OPS if flag_role == "settlement_ops" else COMPLIANCE
    trade_error = get_success_data(
        api_client.flag_allocation_error(line["id"], create_flag_payload(error_type), headers), 201
    )
    scenario["flagged_allocation"] = line
    scenario["trade_error"] = trade_error
    return scenario
