"""Inventory cascades: finalize -> deplete -> rollup -> reorder flag, the reorder
boundary, refund compensation, cycle-count variance/shrink, and the end-of-day
close.

Translates difficulty instances (queue A: transitive_cascade,
boundary_precision_check, compensating_invariant) and corner instances (queue B:
state_machines, calculations, errors, endpoints).
"""
from test_helpers import (
    validate_success, validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

SM = TEST_USERS["store_manager_headers"]
PM = TEST_USERS["price_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
CSH = TEST_USERS["cashier_headers"]
AUD = TEST_USERS["inventory_auditor_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / finalize_depletes_lot_rolls_up_sets_reorder_flag
# ---------------------------------------------------------------------------
def test_finalize_depletes_lot_and_lot_becomes_depleted(api):
    """PRD §3.8: "A lot whose remaining quantity reaches 0 transitions to `DEPLETED`."
    PRD §3.8: "depletion proceeds lot by lot in that FEFO order, taking from each lot the smaller of its remaining quantity and the outstanding demand, reducing the lot's `remaining_qty` ..."

    Design: Difficulty/transitive_cascade/finalize_depletes_lot_rolls_up_sets_reorder_flag
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Rice", unit_price_cents=99, reorder_point_qty=5)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    lot = fixtures.get_single_lot(product["id"])
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 5)
    fixtures.finalize_sale(sale["id"])
    lot_now = get_success_data(api.get_inventory_lot(lot["id"], AUD))
    assert lot_now["status"] == "DEPLETED"
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 0


def test_finalize_cascade_sets_reorder_flag(api):
    """PRD §3.8: "After depletion, each affected product gets its inventory rollup and the cascading reorder-flag recompute, so a product whose on-hand drops to or below its reorder point becomes `reorder_flagged`."
    PRD §3.4: "`reorder_flagged` is true exactly when `on_hand_qty` is less than or equal to `reorder_point_qty`."

    Design: Difficulty/transitive_cascade/finalize_depletes_lot_rolls_up_sets_reorder_flag
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Rice2", unit_price_cents=99, reorder_point_qty=5)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 5)
    fixtures.finalize_sale(sale["id"])
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["reorder_flagged"] is True


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / reorder_flag_at_exact_reorder_point
# ---------------------------------------------------------------------------
def test_reorder_flag_true_at_exact_reorder_point(api):
    """PRD §3.4: "The boundary is inclusive — an on-hand quantity exactly equal to
    the reorder point flags the product, while an on-hand quantity one unit above
    the reorder point does not."

    Design: Difficulty/boundary_precision_check/reorder_flag_at_exact_reorder_point
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Flour", unit_price_cents=99, reorder_point_qty=5)
    fixtures.receive_lot(product["id"], 6, unit_cost_cents=100, expected_total_cents=600)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 1)  # on-hand 6 -> 5
    fixtures.finalize_sale(sale["id"])
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 5
    assert prod["reorder_flagged"] is True


def test_reorder_flag_false_one_above_reorder_point(api):
    """PRD §3.4: "an on-hand quantity one unit above the reorder point does not"
    flag the product.
    PRD §3.2: "a lot that lifts on-hand above the reorder point clears `reorder_flagged`."

    Design: Difficulty/boundary_precision_check/reorder_flag_at_exact_reorder_point
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Flour2", unit_price_cents=99, reorder_point_qty=5)
    fixtures.receive_lot(product["id"], 6, unit_cost_cents=100, expected_total_cents=600)
    prod = get_success_data(api.get_product(product["id"], PM))  # on-hand 6, point 5
    assert prod["on_hand_qty"] == 6
    assert prod["reorder_flagged"] is False


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / pay_then_refund_conserves_on_hand_and_value
# ---------------------------------------------------------------------------
def test_refund_restores_tender_to_refunded(api):
    """PRD §3.9: "Refunding is a `StoreManager`-only compensation on the tender axis. It requires the tender status to be `PAID`, else `ERR_SALE_NOT_PAID`, and moves `tender_status` to `REFUNDED`."

    Design: Difficulty/compensating_invariant/pay_then_refund_conserves_on_hand_and_value
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Pasta", unit_price_cents=200, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100,
                         expected_total_cents=1000, override_variance=False)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 4)
    fixtures.finalize_sale(sale["id"])
    get_success_data(api.pay_sale(sale["id"], CSH))
    refunded = validate_success(api.refund_sale(sale["id"], SM))
    assert refunded["tender_status"] == "REFUNDED"


def test_refund_conserves_on_hand_qty_and_value(api):
    """PRD §3.9: "The compensation invariant is exact: after a pay followed by a refund, the product's `on_hand_qty` and `on_hand_value_cents` return to their pre-finalize values ..."

    Design: Difficulty/compensating_invariant/pay_then_refund_conserves_on_hand_and_value
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Pasta2", unit_price_cents=200, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100,
                         expected_total_cents=1000, override_variance=False)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 4)
    fixtures.finalize_sale(sale["id"])
    get_success_data(api.pay_sale(sale["id"], CSH))
    validate_success(api.refund_sale(sale["id"], SM))
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 10
    assert prod["on_hand_value_cents"] == 1000


# ---------------------------------------------------------------------------
# Corner: state_machines / reconcile_before_submit_returns_not_submitted
# ---------------------------------------------------------------------------
def test_reconcile_before_submit_returns_not_submitted(api):
    """PRD §3.10: "Reconciling moves a submitted count from `SUBMITTED` to `RECONCILED`, requiring `SUBMITTED` else `ERR_CYCLE_COUNT_NOT_SUBMITTED` ..."

    Design: Corner/state_machines/reconcile_before_submit_returns_not_submitted
    """
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="CC",
                                      unit_price_cents=99, reorder_point_qty=0)
    cc = fixtures.open_cycle_count(dept["id"], product["id"])  # DRAFT
    resp = api.reconcile_cycle_count(cc["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_CYCLE_COUNT_NOT_SUBMITTED.value)


# ---------------------------------------------------------------------------
# Corner: calculations / cycle_count_short_writes_off_shrink
# ---------------------------------------------------------------------------
def test_cycle_count_short_writes_off_shrink(api):
    """PRD §3.10: "When the count is short — `variance_qty` is below 0 — the absolute shortfall is depleted from the product's lots in FEFO order, the `shrink_value_cents` is set to the book value of those depleted units ..."
    PRD §3.10: "`variance_qty` is computed as the counted quantity minus that book snapshot, a signed figure."

    Design: Corner/calculations/cycle_count_short_writes_off_shrink
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Count",
                                      unit_price_cents=150, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=90,
                         expected_total_cents=900, override_variance=False)
    cc = fixtures.open_cycle_count(dept["id"], product["id"])
    submitted = fixtures.submit_cycle_count(cc["id"], 7)
    assert submitted["variance_qty"] == -3
    reconciled = validate_success(api.reconcile_cycle_count(cc["id"], AUD))
    assert reconciled["shrink_value_cents"] == 270
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 7


# ---------------------------------------------------------------------------
# Corner: calculations / cycle_count_over_creates_adjustment_lot
# ---------------------------------------------------------------------------
def test_cycle_count_over_creates_adjustment_lot(api):
    """PRD §3.10: "When the count is over — `variance_qty` is above 0 — one adjustment lot is created in `ACTIVE` with a null `shipment_id` and a `received_qty` equal to the variance, valued at the product's most recent active lot's `unit_cost_cents` ... and `shrink_value_cents` is 0."

    Design: Corner/calculations/cycle_count_over_creates_adjustment_lot
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Over",
                                      unit_price_cents=150, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100,
                         expected_total_cents=500, override_variance=False)
    cc = fixtures.open_cycle_count(dept["id"], product["id"])
    submitted = fixtures.submit_cycle_count(cc["id"], 8)
    assert submitted["variance_qty"] == 3
    reconciled = validate_success(api.reconcile_cycle_count(cc["id"], AUD))
    assert reconciled["shrink_value_cents"] == 0
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 8


# ---------------------------------------------------------------------------
# Corner: errors / eod_close_blocked_by_open_cycle_count
# ---------------------------------------------------------------------------
def test_eod_close_blocked_by_open_cycle_count(api):
    """PRD §3.10: "Closing moves it from `OPEN` to `CLOSED`, requiring `OPEN` else `ERR_EOD_NOT_OPEN`, and is blocked while the department still has any cycle count in `SUBMITTED` (unreconciled) state, in which case it is rejected with `ERR_EOD_OPEN_CYCLE_COUNTS`."

    Design: Corner/errors/eod_close_blocked_by_open_cycle_count
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="EOD",
                                      unit_price_cents=99, reorder_point_qty=0)
    cc = fixtures.open_cycle_count(dept["id"], product["id"])
    fixtures.submit_cycle_count(cc["id"], 0)  # SUBMITTED, not reconciled
    eod = fixtures.open_eod(dept["id"], business_date="2026-06-05T00:00:00Z")
    resp = api.close_eod(eod["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_EOD_OPEN_CYCLE_COUNTS.value)


# ---------------------------------------------------------------------------
# Corner: endpoints / eod_close_rolls_up_and_sets_shrink_alert
# opening 100000 (1000 units @ 100); pull a 20-unit lot -> shrink 2000;
# shrink_bps = floor(2000*10000/100000)=200; alert_bps 200 -> alert true.
# ---------------------------------------------------------------------------
def test_eod_close_rolls_up_and_sets_shrink_alert(api):
    """PRD §3.10: "when `opening_value_cents` is 0 the `shrink_bps` is 0, otherwise it is the shrink total multiplied by 10000 and divided by the opening value, floored to a whole number of basis points; `shrink_alert` is true exactly when `shrink_bps` is greater than or equal to the department's `shrink_alert_bps`, the boundary being inclusive so an equal value alerts."

    Design: Corner/endpoints/eod_close_rolls_up_and_sets_shrink_alert
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department(shrink_alert_bps=200)
    product = fixtures.create_product(department_id=dept["id"], name="EODP",
                                      unit_price_cents=100, reorder_point_qty=0)
    # Lot A: 980 units @ 100 (received within tolerance).
    fixtures.receive_lot(product["id"], 980, unit_cost_cents=100,
                         expected_total_cents=98000, override_variance=False)
    # Lot B: 20 units @ 100 -> total on-hand value 100000.
    ship_b, _ = fixtures.receive_lot(product["id"], 20, unit_cost_cents=100,
                                     expected_total_cents=2000, override_variance=False)
    eod = fixtures.open_eod(dept["id"], business_date="2026-06-05T00:00:00Z")
    # Pull lot B (20 units @ 100 = 2000 shrink) within the EOD window.
    lots_b = get_success_data(api.list_inventory_lots(
        AUD, params={"product_id": product["id"], "shipment_id": ship_b["id"]}))
    lot_b = (lots_b if isinstance(lots_b, list) else lots_b["data"])[0]
    get_success_data(api.pull_lot(lot_b["id"], AUD))
    closed = validate_success(api.close_eod(eod["id"], AUD))
    assert closed["opening_value_cents"] == 100000
    assert closed["shrink_total_cents"] == 2000
    assert closed["shrink_bps"] == 200
    assert closed["shrink_alert"] is True
    assert closed["status"] == "CLOSED"
