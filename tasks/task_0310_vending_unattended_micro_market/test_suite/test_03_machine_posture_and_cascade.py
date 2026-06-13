"""Machine three-dimensional posture: parallel stock/cash status evolution,
the inclusive cash-alert threshold boundary, and the depth-3 reconcile cascade
(lot -> slot.on_hand -> machine.stock_status).
"""
from test_helpers import validate_success, api_client, counted_line
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile, make_sale,
)
from test_helpers.test_users import TEST_USERS

FIELD_OPS = TEST_USERS["field_ops_headers"]


# ─── non_linear_state_machine / nlsm_machine_parallel_status_dimensions ────

def _posture_machine():
    """cash_capacity 50000, threshold 0.80 (=40000), par_fill 0.25; one slot
    capacity 8 par 8 price 20000 stocked with 4 units. Returns (machine, slot)."""
    set_clock("2026-06-02T00:00:00Z")
    host = make_host(name="Posture Host", contact_email="p@x.com")
    prod = make_product(sku="BIGITEM", name="Big", category="BEVERAGE", unit_cost_cents=5000)
    machine = make_machine(host["id"], asset_tag="M-5", machine_type="BEVERAGE_VENDOR",
                           cash_capacity_cents=50000, cash_alert_threshold_pct=0.80,
                           par_fill_threshold_pct=0.25)
    slot = make_slot(machine["id"], prod["id"], slot_code="C1",
                     capacity=8, par_level=8, price_cents=20000)
    driver = make_driver(full_name="Vic", employee_code="EMP5")
    route = make_route(driver["id"], "2026-06-02T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 4)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    return machine, slot


def test_cash_sale_flips_cash_status_to_full_warn():
    """PRD §3.2: "Let the alert level be the floor of cash_alert_threshold_pct
    multiplied by cash_capacity_cents. When a cash sale settles and pushes
    cash_on_hand_cents to at or above that alert level, the machine transitions
    CASH_OK -> CASH_FULL_WARN; the boundary is inclusive, so at exactly the alert
    level the machine warns."

    Design: Difficulty/non_linear_state_machine/nlsm_machine_parallel_status_dimensions
    """
    machine, slot = _posture_machine()
    # qty 2 * 20000 = 40000 == floor(0.80 * 50000) -> CASH_FULL_WARN.
    make_sale(machine["id"], slot["id"], 2, "CASH")
    after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after["cash_on_hand_cents"] == 40000, after
    assert after["cash_status"] == "CASH_FULL_WARN", after


def test_stock_dimension_evolves_independently_of_cash():
    """PRD §3.2: "A machine carries three independent status dimensions that
    evolve separately."
    PRD §3.2: "When a machine is STOCKED and an inventory mutation (a sale
    settling, a lot purge, or a visit reconciling) drops the aggregate fill ratio
    to at or below par_fill_threshold_pct while the total on-hand across active
    slots is still greater than zero, the machine transitions STOCKED ->
    LOW_STOCK."

    The same CASH sale that warns the cash dimension drives the stock dimension
    independently to LOW_STOCK (on_hand 2 of capacity 8 -> ratio 0.25 <= 0.25,
    still > 0).

    Design: Difficulty/non_linear_state_machine/nlsm_machine_parallel_status_dimensions
    """
    machine, slot = _posture_machine()
    make_sale(machine["id"], slot["id"], 2, "CASH")
    after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after["cash_status"] == "CASH_FULL_WARN", after
    assert after["stock_status"] == "LOW_STOCK", after


# ─── boundary_precision_check / bpc_cash_alert_at_exact_threshold_warns ────

def _cash_boundary_machine():
    set_clock("2026-06-06T00:00:00Z")
    host = make_host(name="BP Host", contact_email="bp@x.com")
    prod = make_product(sku="BPC", name="BPC Item", category="BEVERAGE", unit_cost_cents=4000)
    machine = make_machine(host["id"], asset_tag="M-10", machine_type="BEVERAGE_VENDOR",
                           cash_capacity_cents=50000, cash_alert_threshold_pct=0.80)
    slot = make_slot(machine["id"], prod["id"], slot_code="I1",
                     capacity=10, par_level=10, price_cents=20000)
    driver = make_driver(full_name="Bo", employee_code="EMP10")
    route = make_route(driver["id"], "2026-06-06T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 5)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    return machine, slot


def test_cash_at_exactly_alert_level_warns():
    """PRD §3.2: "the boundary is inclusive, so at exactly the alert level the
    machine warns."

    Design: Difficulty/boundary_precision_check/bpc_cash_alert_at_exact_threshold_warns
    """
    machine, slot = _cash_boundary_machine()
    # qty 2 * 20000 = 40000 == floor(0.80 * 50000).
    make_sale(machine["id"], slot["id"], 2, "CASH")
    after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after["cash_on_hand_cents"] == 40000, after
    assert after["cash_status"] == "CASH_FULL_WARN", after


def test_cash_just_below_alert_level_stays_ok():
    """PRD §3.2: "After any cash mutation the cash posture is recomputed: if
    cash_on_hand_cents is at or above the alert level the status is
    CASH_FULL_WARN, otherwise it is CASH_OK."

    A single qty-1 cash sale (20000) leaves the vault below the 40000 alert level,
    so cash_status stays CASH_OK — the boundary's strictly-below side.

    Design: Difficulty/boundary_precision_check/bpc_cash_alert_at_exact_threshold_warns
    """
    machine, slot = _cash_boundary_machine()
    make_sale(machine["id"], slot["id"], 1, "CASH")  # 20000 < 40000
    after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after["cash_on_hand_cents"] == 20000, after
    assert after["cash_status"] == "CASH_OK", after


# ─── transitive_cascade / tc_reconcile_lot_slot_machine_depth3 ─────────────

def _empty_stockout_machine():
    """Machine with one empty slot (cap 20 par 20 price 100c, on_hand 0 ->
    STOCKOUT); a dispatched route with one kitted stop; a DRAFT visit refilling
    20. Returns (machine, slot, visit, v0)."""
    set_clock("2026-06-03T00:00:00Z")
    host = make_host(name="Casc Host", contact_email="c@x.com")
    prod = make_product(sku="CAS", name="Cas Item", category="SNACK", unit_cost_cents=50)
    machine = make_machine(host["id"], asset_tag="M-7", machine_type="SNACK_VENDOR",
                           par_fill_threshold_pct=0.25)
    slot = make_slot(machine["id"], prod["id"], slot_code="D1",
                     capacity=20, par_level=20, price_cents=100)
    driver = make_driver(full_name="Cas", employee_code="EMP7")
    route = make_route(driver["id"], "2026-06-03T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 20)], v0, driver["id"])
    return machine, slot, visit, v0, driver["id"]


def test_reconcile_cascade_creates_lot_and_fills_slot():
    """PRD §3.5: "Then, for each line whose refill_units is greater than zero, the
    system creates an InventoryLot with filled_units equal to that line's
    refill_units, unit_cost_cents snapshotted from the slot's product's current
    unit_cost_cents, expiration_date computed from the current clock plus the
    product's shelf_life_days, and status AVAILABLE (cascade hop one). The system
    then recomputes each touched slot's on_hand from its lots (cascade hop two)".

    Design: Difficulty/transitive_cascade/tc_reconcile_lot_slot_machine_depth3
    """
    machine, slot, visit, v0, driver_id = _empty_stockout_machine()
    reconcile(visit["id"], v0, driver_id)
    # Hop 1: a new lot with remaining_units 20.
    lots = api_client.list_slot_lots(slot["id"], FIELD_OPS).json()["data"]
    assert len(lots) == 1, lots
    assert lots[0]["remaining_units"] == 20, lots[0]
    # Hop 2: slot.on_hand recomputed to 20.
    slot_after = validate_success(api_client.get_slot(slot["id"], FIELD_OPS), 200)
    assert slot_after["on_hand"] == 20, slot_after


def test_reconcile_cascade_rederives_machine_to_stocked():
    """PRD §3.5: "re-derives the machine's stock_status from aggregate fill
    (cascade hop three)".
    PRD §3.2: "When a reconcile raises the aggregate fill ratio strictly above
    par_fill_threshold_pct, the machine transitions STOCKOUT -> STOCKED."

    Design: Difficulty/transitive_cascade/tc_reconcile_lot_slot_machine_depth3
    """
    machine, slot, visit, v0, driver_id = _empty_stockout_machine()
    before = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert before["stock_status"] == "STOCKOUT", before
    reconcile(visit["id"], v0, driver_id)
    # Hop 3: full slot (ratio 1.0 > 0.25) -> STOCKED.
    after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after["stock_status"] == "STOCKED", after
