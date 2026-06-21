"""Event/stand/order lifecycle: parallel order dimensions, stand revert cycle,
the peak-window depth-2 cascade, staffing side effects, and lifecycle guards.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade (peak window).
Queue B (Corner): state_machines/* and consistency_model/pickup.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_patron_headers,
    create_staff_shift_payload,
    create_venue, create_product, create_menu_item_payload,
)
from test_helpers.fixtures import (
    create_event, create_stand, create_event_doors_open, create_stand_opened_with_staff,
    setup_paid_order, setup_picked_up_order, setup_placed_order, setup_settled_empty_event,
    create_checked_in_shift,
)

MANAGER = TEST_USERS["manager_headers"]
OPERATOR = TEST_USERS["operator_headers"]
RUNNER = TEST_USERS["runner_headers"]


# ===========================================================================
# Queue A — order_parallel_payment_and_fulfillment_dimensions
# Paying a PLACED order flips payment UNPAID->PAID without touching fulfillment.
# ===========================================================================
def test_pay_advances_payment_without_touching_fulfillment(api):
    """PRD §3.8: "Paying a placed order moves its payment_status from UNPAID to
    PAID while leaving the fulfillment dimension untouched."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    state = setup_placed_order(line_qtys=(2,))
    ph = state["patron_headers"]
    order = validate_success(api.pay_order(state["order"]["id"], ph), 200)
    assert order["payment_status"] == "PAID"
    assert order["fulfillment_status"] == "PLACED"


def test_paid_order_fulfillment_still_placed_on_refetch(api):
    """PRD §3.8: "An order carries two independent status dimensions that evolve
    separately: fulfillment_status runs CART -> PLACED -> READY -> PICKED_UP with a
    branch to CANCELLED, while payment_status runs UNPAID -> PAID -> REFUNDED."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    state = setup_paid_order(line_qtys=(2,))
    order = validate_success(api.get_order(state["order"]["id"], state["patron_headers"]), 200)
    assert order["payment_status"] == "PAID"
    assert order["fulfillment_status"] == "PLACED"


# ===========================================================================
# Queue A — stand_open_suspend_open_revert_cycle
# OPEN -> SUSPENDED -> OPEN returns the stand to a previously visited state.
# ===========================================================================
def test_stand_reopens_from_suspended(api):
    """PRD §3.3: "Opening a stand moves it from CLOSED to OPEN (or reopens it from
    SUSPENDED to OPEN) and is the gate that makes its menu items sellable".
    PRD §3.3: "An operator may suspend an OPEN stand, moving it to SUSPENDED ...
    a stand may bounce between OPEN and SUSPENDED during a rush."

    Design: Difficulty/non_linear_state_machine/stand_open_suspend_open_revert_cycle
    """
    base = create_stand_opened_with_staff()
    stand_id = base["stand"]["id"]
    validate_success(api.suspend_stand(stand_id, OPERATOR), 200)
    reopened = validate_success(api.open_stand(stand_id, OPERATOR), 200)
    assert reopened["status"] == "OPEN"


def test_stand_suspend_sets_suspended_status(api):
    """PRD §3.3: "An operator may suspend an OPEN stand, moving it to SUSPENDED,
    which blocks new ordering though any already-READY orders may still be picked
    up".

    Design: Difficulty/non_linear_state_machine/stand_open_suspend_open_revert_cycle
    """
    base = create_stand_opened_with_staff()
    suspended = validate_success(api.suspend_stand(base["stand"]["id"], OPERATOR), 200)
    assert suspended["status"] == "SUSPENDED"


# ===========================================================================
# Queue A — peak_window_open_to_price_and_staff_recompute_depth2
# Opening the peak window recomputes menu price AND open stands' required_staff.
# HIGH base 850 mult 120: off-peak 1326 -> peak 1428; required_staff ceil(160/40)=4 -> +1 peak = 5.
# ===========================================================================
def test_peak_window_open_recomputes_menu_price(api):
    """PRD §3.3: "opening the peak window triggers a two-part cascade: the
    event-day price (price_cents) is recomputed for every menu item under every
    stand of the event, picking up the peak surge bonus".

    HIGH base 850 mult 120, peak surge 140 -> round(850*1.20*1.40)=1428.

    Design: Difficulty/transitive_cascade/peak_window_open_to_price_and_staff_recompute_depth2
    """
    venue = create_venue(venue_share_pct=10, service_fee_pct=0)
    product = create_product(venue["id"], sku="HOTDOG", name="Hot Dog", base_price_cents=850, unit_cost_cents=200)
    base = create_stand_opened_with_staff(
        venue_id=venue["id"], event_overrides={"event_multiplier_pct": 120},
        stand_overrides={"demand_tier": "HIGH", "expected_orders_per_hour": 160},
    )
    mi = validate_success(api.create_menu_item(create_menu_item_payload(base["stand"]["id"], product["id"]), MANAGER), 201)
    api.open_peak_window(base["event"]["id"], MANAGER)
    refreshed = validate_success(api.get_menu_item(mi["id"], MANAGER), 200)
    assert refreshed["price_cents"] == 1428


def test_peak_window_open_recomputes_required_staff(api):
    """PRD §3.3: "the required staffing (required_staff) is recomputed for every
    stand of the event currently in OPEN status, picking up the peak bump".
    PRD §3.7: "A peak bump of one additional worker is then added if and only if
    the event's peak window is currently open."

    ceil(160/40)=4 base; +1 peak bump -> required_staff 5; and event.peak_window true.

    Design: Difficulty/transitive_cascade/peak_window_open_to_price_and_staff_recompute_depth2
    """
    venue = create_venue(venue_share_pct=10, service_fee_pct=0)
    product = create_product(venue["id"], sku="HOTDOG", name="Hot Dog", base_price_cents=850, unit_cost_cents=200)
    base = create_stand_opened_with_staff(
        venue_id=venue["id"], event_overrides={"event_multiplier_pct": 120},
        stand_overrides={"demand_tier": "HIGH", "expected_orders_per_hour": 160},
    )
    validate_success(api.create_menu_item(create_menu_item_payload(base["stand"]["id"], product["id"]), MANAGER), 201)
    event = validate_success(api.open_peak_window(base["event"]["id"], MANAGER), 200)
    assert event["peak_window"] is True
    stand = validate_success(api.get_stand(base["stand"]["id"], MANAGER), 200)
    assert stand["required_staff"] == 5, f"expected 5, got {stand['required_staff']}"


# ===========================================================================
# Queue B — state_machines
# ===========================================================================
def test_settle_from_scheduled_returns_invalid_state(api):
    """PRD §3.3: "Settlement is permitted only while the event is IN_PROGRESS".
    PRD §2.8: "the state check: the target must be in a state from which the
    requested transition is defined, else ERR_INVALID_STATE."

    Design: Corner/state_machines/settle_from_scheduled_event_returns_invalid_state
    """
    venue = create_venue()
    event = create_event(venue["id"])
    resp = api.settle_event(event["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_peak_window_open_on_settled_event_returns_invalid_state(api):
    """PRD §3.3: "An event moves through SCHEDULED, DOORS_OPEN, IN_PROGRESS, and
    finally the terminal SETTLED."
    PRD §3.3: "Opening the peak window on a DOORS_OPEN event advances it to
    IN_PROGRESS ... the same open-peak action also applies while the event is
    already IN_PROGRESS with peak_window currently false".

    From terminal SETTLED no peak-window open is defined -> ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_settled_event_terminal_lockdown
    """
    s = setup_settled_empty_event()
    resp = api.open_peak_window(s["event"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_check_in_increments_assigned_staff_count(api):
    """PRD §3.7: "A worker checks in, moving the shift SCHEDULED -> CHECKED_IN and
    incrementing the stand's assigned_staff_count by one".

    Design: Corner/state_machines/check_in_increments_assigned_staff_count
    """
    venue = create_venue()
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    shift = validate_success(api.create_staff_shift(create_staff_shift_payload(stand["id"], worker_name="Ora"), MANAGER), 201)
    checked = validate_success(api.check_in_shift(shift["id"], OPERATOR), 200)
    assert checked["status"] == "CHECKED_IN"
    refreshed = validate_success(api.get_stand(stand["id"], OPERATOR), 200)
    assert refreshed["assigned_staff_count"] == 1


def test_double_check_in_returns_invalid_state(api):
    """PRD §3.7: "A worker checks in, moving the shift SCHEDULED -> CHECKED_IN".
    PRD §2.8: "the state check: the target must be in a state from which the
    requested transition is defined, else ERR_INVALID_STATE."

    A shift already CHECKED_IN is no longer SCHEDULED, so a second check-in fails.

    Design: Corner/state_machines/double_check_in_returns_invalid_state_idempotency
    """
    venue = create_venue()
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    shift = validate_success(api.create_staff_shift(create_staff_shift_payload(stand["id"], worker_name="Pia"), MANAGER), 201)
    validate_success(api.check_in_shift(shift["id"], OPERATOR), 200)
    resp = api.check_in_shift(shift["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_close_stand_with_placed_order_returns_invalid_state(api):
    """PRD §3.3: "Closing a stand moves it from OPEN or SUSPENDED to CLOSED and is
    permitted only when no order at that stand sits in fulfillment status PLACED or
    READY."

    Design: Corner/state_machines/close_stand_with_placed_order_returns_invalid_state
    """
    state = setup_placed_order(line_qtys=(1,))
    resp = api.close_stand(state["stand"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Queue B — consistency_model/pickup_reflects_gross_sales_immediately
# ===========================================================================
def test_pickup_reflects_gross_sales_immediately(api):
    """PRD §3.8: "Handing the order to the patron moves it from READY to PICKED_UP
    and increases the parent event's gross_sales_cents by the order's total_cents —
    this is the sale reaching the event ledger."

    LOW-tier, multiplier-100 stand so the menu price equals the 100c base: water
    100, qty 2, service_fee_pct 10 -> subtotal 200, fee 20, total 220 ->
    event.gross_sales_cents equals the order's total_cents (220) immediately on the
    same flow's GET.

    Design: Corner/consistency_model/pickup_reflects_gross_sales_immediately
    """
    state = setup_picked_up_order(
        line_qtys=(2,),
        venue_overrides={"venue_share_pct": 10, "service_fee_pct": 10},
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
        stand_overrides={"demand_tier": "LOW", "expected_orders_per_hour": 40},
        event_overrides={"event_multiplier_pct": 100},
    )
    assert state["order"]["fulfillment_status"] == "PICKED_UP"
    order_total = state["order"]["total_cents"]
    assert order_total == 220, f"expected order total 220, got {order_total}"
    event = validate_success(api.get_event(state["event"]["id"], MANAGER), 200)
    assert event["gross_sales_cents"] == order_total, f"expected gross {order_total}, got {event['gross_sales_cents']}"
