"""DeliveryOrder state machine: the reschedule cycle and invalid/terminal transitions.

Queue A: non_linear_state_machine (order reschedule loop).
Queue B: deliver-from-SCHEDULED invalid, cancel-DELIVERED terminal lockdown.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_member_headers, make_driver_headers,
    setup_order_unable_to_access, get_order,
    post_fuel_price, new_customer, new_vehicle, new_order,
    new_truck, new_compartment, new_route, drive_order_to_arrived,
)


# ─── Queue A: non_linear_state_machine / order reschedule cycle ──────────────

def test_reschedule_returns_unable_order_to_scheduled(api):
    """PRD §3.6: "A `Member` or `FleetManager` may then reschedule an `UNABLE_TO_ACCESS`
    order back to `SCHEDULED`, supplying a fresh `delivery_window_start` and
    `delivery_window_end`."

    Design: Difficulty/non_linear_state_machine/delivery_order_reschedule_cycle_returns_to_scheduled
    """
    ctx = setup_order_unable_to_access()
    res = api.reschedule_order(
        ctx["order_id"],
        {"delivery_window_start": "2026-05-03T09:00:00Z",
         "delivery_window_end": "2026-05-03T11:00:00Z"},
        make_member_headers(ctx["customer_id"]))
    order = validate_success(res, 200)
    assert order["status"] == "SCHEDULED", "reschedule re-enters the already-left SCHEDULED state"


def test_reschedule_leaves_order_off_any_route(api):
    """PRD §3.6: "That removal takes the order off the route: the route's `stop_count`
    decreases by 1, the order's `route_id` is cleared to null, and the compartment
    reservation is released by decreasing `gallons_reserved` by the order's
    `requested_gallons`."
    PRD §3.6: "A `Member` or `FleetManager` may then reschedule an `UNABLE_TO_ACCESS` order
    back to `SCHEDULED`, supplying a fresh `delivery_window_start` and
    `delivery_window_end`."

    Design: Difficulty/non_linear_state_machine/delivery_order_reschedule_cycle_returns_to_scheduled
    """
    ctx = setup_order_unable_to_access()
    api.reschedule_order(
        ctx["order_id"],
        {"delivery_window_start": "2026-05-03T09:00:00Z",
         "delivery_window_end": "2026-05-03T11:00:00Z"},
        make_member_headers(ctx["customer_id"]))
    order = get_order(ctx["order_id"])
    assert order["status"] == "SCHEDULED"
    assert order["route_id"] is None, "rescheduled order carries no route"


# ─── Queue B: order state transitions ───────────────────────────────────────

def test_cancel_delivered_order_terminal_lockdown(api):
    """PRD §3.6: "A `Member`, `FleetManager`, or `Dispatcher` cancels an order in
    `SCHEDULED`, `ROUTED`, or `UNABLE_TO_ACCESS`, moving it to the terminal `CANCELLED`
    state."
    PRD §3.6: "An arrive, deliver, report-inaccessible, reschedule, or cancel attempted from
    a state the transition does not allow is rejected as an invalid order state."

    Design: Corner/state_machines/cancel_delivered_order_terminal_lockdown
    """
    post_fuel_price()
    cust = new_customer(name="Tia", email="tia@x.com")
    veh = new_vehicle(cust["id"], make_model="Ibiza")
    truck = new_truck(plate="TRK-T")
    new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id="driver-t")
    order = new_order(cust["id"], veh["id"], requested_gallons=5, delivery_address="Term St",
                      delivery_window_start="2026-05-02T09:00:00Z",
                      delivery_window_end="2026-05-02T10:00:00Z")
    drive_order_to_arrived(order["id"], route["id"], "driver-t")
    get_success_data(api.deliver_order(order["id"], {"dispensed_gallons": 5},
                                       make_driver_headers("driver-t")))
    res = api.cancel_order(order["id"], make_member_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_ORDER_STATE", expected_status=409)
    assert get_order(order["id"])["status"] == "DELIVERED"
