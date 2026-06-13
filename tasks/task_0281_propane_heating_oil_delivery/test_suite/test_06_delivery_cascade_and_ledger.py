"""Delivery cascades, the account ledger, budget settlement, and optimistic
concurrency on the account version.

Translates queue A (Difficulty) rules transitive_cascade (deliver cascade),
dual_variant_calc (budget PROVISIONAL vs FINAL ledger), compensating_invariant
(budget ledger conserved across deliver/reverse), and cross_entity_state_dependency
(deliver requires tank IN_SERVICE), plus queue B (Corner) OCC and route
auto-completion instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    reverse_order_payload,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
INSP = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade — deliver -> tank level -> reorder -> ledger/budget
# ---------------------------------------------------------------------------
def test_deliver_cascade_tank_reorder_then_budget_ledger(api):
    """PRD §3.6: "First, the tank's `current_gallons` rises by `delivered_gallons` and its `last_delivery_at` is set to the current clock. Second, that level change re-runs the reorder projection of §3.3, which may flip the tank's `reorder_status` from `DUE` back to `OK` now that it is full. Third, the account ledger is debited: `credit_balance_cents` decreases by `invoice_total_cents`; and if the account is on an `ACTIVE` `BudgetPlan`, that plan's `actual_cost_to_date_cents` increases by the same `invoice_total_cents`, its `settlement_balance_cents` is recomputed, and the order's `budget_plan_id` is stamped with that plan."

    Design: Difficulty/transitive_cascade/deliver_cascade_tank_reorder_then_budget_ledger
    """
    fx.set_clock("2026-01-10T00:00:00Z")
    base = fx.setup_account_plan_passed_tank(
        plan_type="FIXED", locked_price=300, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500,
                        "reorder_threshold_pct": 30, "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    before = fx.evaluate_reorder(tank["id"])
    assert before["reorder_status"] == "DUE"  # 100/500 = pct 20
    bp = fx.create_budget_plan(account["id"], estimated_annual_gallons=1200,
                               estimated_price_cents_per_gallon=300)
    fx.post_installments(account["id"], bp["id"], 2)
    truck = fx.create_truck(region_code="NE_01")
    route = fx.create_route(truck["id"])
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    fx.dispatch_route(truck["id"], route["id"])

    delivered = fx.deliver_order(account["id"], order["id"], 200)
    assert delivered["invoice_total_cents"] == 61500  # fuel 200*295 tier1 + 2500 off_route

    tank_after = validate_success(api.get_tank(tank["id"], DISP))
    assert tank_after["current_gallons"] == 300  # 100 + 200
    assert tank_after["reorder_status"] == "OK"  # 300/500 = pct 60 > 30
    bp_after = validate_success(api.get_budget_plan(bp["id"], AM))
    assert bp_after["actual_cost_to_date_cents"] == 61500


def test_deliver_cascade_debits_account_credit_ledger(api):
    """PRD §3.6: "Third, the account ledger is debited: `credit_balance_cents` decreases by `invoice_total_cents"

    Design: Difficulty/transitive_cascade/deliver_cascade_tank_reorder_then_budget_ledger
    """
    fx.set_clock("2026-01-10T00:00:00Z")
    base = fx.setup_account_plan_passed_tank(
        plan_type="FIXED", locked_price=300, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500,
                        "reorder_threshold_pct": 30, "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    bp = fx.create_budget_plan(account["id"], estimated_annual_gallons=1200,
                               estimated_price_cents_per_gallon=300)
    fx.post_installments(account["id"], bp["id"], 2)  # +60000 credit
    truck = fx.create_truck(region_code="NE_01")
    route = fx.create_route(truck["id"])
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    fx.dispatch_route(truck["id"], route["id"])
    fx.deliver_order(account["id"], order["id"], 200)  # invoice 61500 debit

    acct = validate_success(api.get_account(account["id"], AM))
    # running ledger: +60000 installments - 61500 debit = -1500.
    assert acct["credit_balance_cents"] == 60000 - 61500


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — budget PROVISIONAL vs FINAL ledger
# ---------------------------------------------------------------------------
def test_budget_reconcile_provisional_vs_final_ledger(api):
    """PRD §3.10: "While a plan is `ACTIVE`, its `settlement_balance_cents` is purely informational — a provisional view. The account's `credit_balance_cents` is not trued up to it; the running ledger carries only the posted installment credits and the delivery debits as they actually occur."
    PRD §3.10: "Reconciliation finalizes `settlement_balance_cents` as `installments_paid_count` multiplied by `monthly_installment_cents`, minus `actual_cost_to_date_cents`, and then refunds that finalized balance out of the running ledger: the account's `credit_balance_cents` is decreased by the finalized `settlement_balance_cents`."

    Design: Difficulty/dual_variant_calc/budget_reconcile_provisional_vs_final_ledger
    """
    base = fx.setup_account_plan_passed_tank(
        plan_type="FIXED", locked_price=300, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    bp = fx.create_budget_plan(account["id"], estimated_annual_gallons=1200,
                               estimated_price_cents_per_gallon=300)
    # monthly installment = 1200*300/12 = 30000.
    fx.post_installments(account["id"], bp["id"], 4)  # funded 120000
    truck = fx.create_truck(region_code="NE_01")
    route = fx.create_route(truck["id"], route_date="2026-02-01T00:00:00Z",
                            window_start="2026-02-01T09:00:00Z",
                            window_end="2026-02-01T12:00:00Z")
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    fx.dispatch_route(truck["id"], route["id"])
    fx.deliver_order(account["id"], order["id"], 200)  # invoice 61500

    acct_before = validate_success(api.get_account(account["id"], AM))
    # PROVISIONAL running ledger: +120000 installments - 61500 debit = 58500.
    assert acct_before["credit_balance_cents"] == 58500

    reconciled = validate_success(api.reconcile_budget_plan(account["id"], bp["id"], AM))
    assert reconciled["settlement_balance_cents"] == 58500  # 120000 - 61500
    assert reconciled["status"] == "RECONCILED"
    acct_after = validate_success(api.get_account(account["id"], AM))
    # FINAL refunds settlement out: 58500 - 58500 = 0.
    assert acct_after["credit_balance_cents"] == 0


def test_budget_provisional_installments_credit_running_ledger(api):
    """PRD §3.10: "Posting increments `installments_paid_count` by one, credits the account by adding `monthly_installment_cents` to its `credit_balance_cents` (the installment funds the account), and recomputes `settlement_balance_cents`."
    PRD §3.10: "While a plan is `ACTIVE`, its `settlement_balance_cents` is purely informational — a provisional view. The account's `credit_balance_cents` is not trued up to it"

    Design: Difficulty/dual_variant_calc/budget_reconcile_provisional_vs_final_ledger
    """
    account = fx.create_account(region_code="NE_01", fuel_type="PROPANE",
                                customer_name="Budget Bea")
    bp = fx.create_budget_plan(account["id"], estimated_annual_gallons=1200,
                               estimated_price_cents_per_gallon=300)
    # monthly installment 30000; post 4 with no delivery.
    fx.post_installments(account["id"], bp["id"], 4)
    acct = validate_success(api.get_account(account["id"], AM))
    # PROVISIONAL running ledger carries the posted installment credits as they occur.
    assert acct["credit_balance_cents"] == 120000  # 4 * 30000
    bp_now = validate_success(api.get_budget_plan(bp["id"], AM))
    # settlement = installments funded (120000) - actuals (0) = 120000, provisional.
    assert bp_now["settlement_balance_cents"] == 120000
    assert bp_now["installments_paid_count"] == 4


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant — ledger conserved across deliver/reverse
# ---------------------------------------------------------------------------
def test_budget_ledger_conserved_across_deliver_reverse(api):
    """PRD §3.6: "if the order has a `budget_plan_id`, that budget plan's `actual_cost_to_date_cents` decreases by `invoice_total_cents` and its `settlement_balance_cents` is recomputed, so that the ledger is conserved exactly across a deliver-then-reverse pair."
    PRD §3.6: "the account's `credit_balance_cents` increases by `invoice_total_cents"

    Design: Difficulty/compensating_invariant/budget_ledger_conserved_across_deliver_reverse
    """
    base = fx.setup_account_plan_passed_tank(
        plan_type="FIXED", locked_price=300, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    bp = fx.create_budget_plan(account["id"], estimated_annual_gallons=1200,
                               estimated_price_cents_per_gallon=300)
    truck = fx.create_truck(region_code="NE_01")
    route = fx.create_route(truck["id"], route_date="2026-02-13T00:00:00Z",
                            window_start="2026-02-13T09:00:00Z",
                            window_end="2026-02-13T12:00:00Z")
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    fx.dispatch_route(truck["id"], route["id"])

    acct_pre = validate_success(api.get_account(account["id"], AM))
    assert acct_pre["credit_balance_cents"] == 0  # no installments
    fx.deliver_order(account["id"], order["id"], 200)  # +61500 actuals, -61500 credit

    acct_v2 = fx.get_account_version(account["id"])
    validate_success(api.reverse_order(
        account["id"], order["id"], reverse_order_payload(acct_v2), AM))

    bp_final = validate_success(api.get_budget_plan(bp["id"], AM))
    assert bp_final["actual_cost_to_date_cents"] == 0  # deliver then reverse
    acct_final = validate_success(api.get_account(account["id"], AM))
    assert acct_final["credit_balance_cents"] == 0  # ledger conserved


def test_reverse_restores_order_cancelled_and_tank_level(api):
    """PRD §3.6: "A delivered order can be reversed by an account manager, a compensating transition `DELIVERED → CANCELLED`."
    PRD §3.6: "Reversal unwinds the delivery's effects: the tank's `current_gallons` decreases by `delivered_gallons` and its `reorder_status` is recomputed"

    Design: Difficulty/compensating_invariant/budget_ledger_conserved_across_deliver_reverse
    """
    base = fx.setup_account_plan_passed_tank(
        plan_type="FIXED", locked_price=300, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    fx.create_budget_plan(account["id"], estimated_annual_gallons=1200,
                          estimated_price_cents_per_gallon=300)
    truck = fx.create_truck(region_code="NE_01")
    route = fx.create_route(truck["id"], route_date="2026-02-14T00:00:00Z",
                            window_start="2026-02-14T09:00:00Z",
                            window_end="2026-02-14T12:00:00Z")
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    fx.dispatch_route(truck["id"], route["id"])
    fx.deliver_order(account["id"], order["id"], 200)  # tank now 300

    acct_v2 = fx.get_account_version(account["id"])
    reversed_order = validate_success(api.reverse_order(
        account["id"], order["id"], reverse_order_payload(acct_v2), AM))
    assert reversed_order["status"] == "CANCELLED"
    tank_after = validate_success(api.get_tank(tank["id"], DISP))
    assert tank_after["current_gallons"] == 100  # 300 - 200 restored


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency — deliver requires tank IN_SERVICE
# ---------------------------------------------------------------------------
def test_order_deliver_requires_tank_in_service(api):
    """PRD §3.6: "the tank must be `IN_SERVICE` (else `ERR_TANK_NOT_IN_SERVICE`)"
    PRD §3.8: "a `FAILED` result on a tank that is `IN_SERVICE` locks it out (`IN_SERVICE → LOCKED_OUT`)"

    Design: Difficulty/cross_entity_state_dependency/order_deliver_requires_tank_in_service
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=300, requested_gallons=200,
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    # FAILED inspection locks the tank out after the order is SCHEDULED on a
    # DISPATCHED route.
    validate_success(api.create_inspection(
        s["tank"]["id"], {"result": "FAILED", "inspected_at": "2026-01-02T00:00:00Z"}, INSP),
        expected_status=201)
    account_v = fx.get_account_version(s["account"]["id"])
    resp = api.deliver_order(
        s["account"]["id"], s["order"]["id"],
        {"delivered_gallons": 200, "expected_account_version": account_v}, DRIVER)
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_IN_SERVICE.value)


def test_order_deliver_requires_tank_in_service_after_manual_lockout(api):
    """PRD §3.6: "the tank must be `IN_SERVICE` (else `ERR_TANK_NOT_IN_SERVICE`)"
    PRD §3.3: "a tank goes `IN_SERVICE → LOCKED_OUT` either when an inspector files a failing safety check or when an operator manually locks it out"

    Design: Difficulty/cross_entity_state_dependency/order_deliver_requires_tank_in_service
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=300, requested_gallons=200,
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    # Manual lockout (distinct pathway from a FAILED inspection) takes the tank out
    # of service before deliver.
    validate_success(api.lockout_tank(s["tank"]["id"], INSP))
    account_v = fx.get_account_version(s["account"]["id"])
    resp = api.deliver_order(
        s["account"]["id"], s["order"]["id"],
        {"delivered_gallons": 200, "expected_account_version": account_v}, DRIVER)
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_IN_SERVICE.value)


# ---------------------------------------------------------------------------
# Corner: route auto-completion (bubble up)
# ---------------------------------------------------------------------------
def test_route_auto_completes_when_last_order_delivered(api):
    """PRD §3.5: "A route reaches `DISPATCHED → COMPLETED` by itself, with no explicit request: this is a system transition that fires when a `DISPATCHED` route has no `DeliveryOrder` left in `SCHEDULED` (every assigned order has reached `DELIVERED` or `CANCELLED`)."

    Design: Corner/state_machines/route_auto_completes_when_last_order_delivered
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=300, requested_gallons=200,
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    fx.deliver_order(s["account"]["id"], s["order"]["id"], 200)
    route = validate_success(api.get_route(s["route"]["id"], DISP))
    assert route["status"] == "COMPLETED"


def test_cancel_dispatched_route_with_delivery_rejected(api):
    """PRD §3.5: "Cancelling from `DISPATCHED` (`DISPATCHED → CANCELLED`) requires the route to be in `DISPATCHED` (else `ERR_INVALID_STATE`) and additionally that no order on the route has already reached `DELIVERED` (else `ERR_ROUTE_HAS_DELIVERIES`)"

    Design: Corner/errors/cancel_dispatched_route_with_delivery_rejected
    """
    base = fx.setup_account_plan_passed_tank(
        plan_type="FIXED", locked_price=300, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 2000, "k_factor": 1500, "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01")
    route = fx.create_route(truck["id"], route_date="2026-03-08T00:00:00Z",
                            window_start="2026-03-08T09:00:00Z",
                            window_end="2026-03-08T12:00:00Z")
    o1 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    o2 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], o1["id"], route["id"])
    fx.assign_order(account["id"], o2["id"], route["id"])
    fx.dispatch_route(truck["id"], route["id"])
    fx.deliver_order(account["id"], o1["id"], 200)  # one DELIVERED, one still SCHEDULED

    resp = api.cancel_route(truck["id"], route["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_DELIVERIES.value)


# ---------------------------------------------------------------------------
# Corner: optimistic concurrency on the account version
# ---------------------------------------------------------------------------
def test_occ_correct_version_deliver_succeeds_and_increments(api):
    """PRD §2.7: "When a driver completes a delivery, the request must carry `expected_account_version` equal to the account's current `version`."
    PRD §3.6: "Finally the account's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_deliver_succeeds_and_increments
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=300, requested_gallons=200,
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    acct_v = fx.get_account_version(s["account"]["id"])
    delivered = validate_success(api.deliver_order(
        s["account"]["id"], s["order"]["id"],
        {"delivered_gallons": 200, "expected_account_version": acct_v}, DRIVER))
    assert delivered["status"] == "DELIVERED"
    acct_after = validate_success(api.get_account(s["account"]["id"], AM))
    assert acct_after["version"] == acct_v + 1


def test_occ_stale_version_deliver_rejected(api):
    """PRD §2.7: "If another ledger-mutating operation — a prior delivery or a reversal — has advanced the account's `version` since the client last read it, the delivery is rejected with `ERR_STALE_VERSION` and an HTTP status of 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_deliver_rejected
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=300, requested_gallons=200,
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 100})
    acct_v = fx.get_account_version(s["account"]["id"])
    resp = api.deliver_order(
        s["account"]["id"], s["order"]["id"],
        {"delivered_gallons": 200, "expected_account_version": acct_v - 1}, DRIVER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
