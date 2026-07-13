"""State machine transitions, invalid transitions, and terminal-state lockdown.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_flavor, make_size, make_batch, make_station, make_event_cart, make_booking,
    open_drawer, open_order, add_line, pay, make_pre_order, drive_preorder_to,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
SCOOP = TEST_USERS["scooper_headers"]
BAKER = TEST_USERS["baker_headers"]
LEAD = TEST_USERS["shift_lead_headers"]


def test_batch_initial_state_is_prep(api):
    """PRD 3.2: "A freshly produced batch enters the `PREP` state with
    `remaining_volume_ml` equal to `initial_volume_ml` and its `reserved_volume_ml`,
    `committed_volume_ml`, and `wasted_volume_ml` all zero."

    Design: Corner/state_machines/batch_initial_state_is_prep
    """
    flavor = make_flavor(par_level_ml=300)
    batch = make_batch(flavor["id"], initial_volume_ml=500, release=False)
    assert batch["status"] == "PREP"
    assert batch["remaining_volume_ml"] == 500
    assert batch["reserved_volume_ml"] == 0


def test_release_available_batch_returns_not_prep(api):
    """PRD 3.2: "Releasing a batch that is not in `PREP` is rejected with
    `ERR_BATCH_NOT_PREP`."

    Design: Corner/state_machines/release_available_batch_returns_not_prep
    """
    flavor = make_flavor(par_level_ml=300)
    batch = make_batch(flavor["id"], initial_volume_ml=500)  # already released to AVAILABLE
    validate_error(api.release_batch(batch["id"], BAKER), "ERR_BATCH_NOT_PREP")


def test_waste_on_depleted_batch_returns_not_available(api):
    """PRD 3.4: "any batch whose `remaining_volume_ml` reaches zero as a result
    auto-transitions from `AVAILABLE` to the terminal `DEPLETED` state and is
    excluded from future reservations."
    PRD 3.2: "Waste may only be logged against a batch that is in `PREP` or
    `AVAILABLE`; a waste attempt on any other batch is rejected with
    `ERR_BATCH_NOT_AVAILABLE`."

    Design: Corner/state_machines/waste_on_depleted_batch_returns_not_available
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch = make_batch(flavor["id"], initial_volume_ml=180)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    pay(order["id"], payment_method="CARD")  # depletes the batch
    res = api.create_waste_event({"batch_id": batch["id"], "waste_type": "MELT", "volume_ml": 10}, BAKER)
    validate_error(res, "ERR_BATCH_NOT_AVAILABLE")


def test_void_paid_order_returns_not_open(api):
    """PRD 3.5: "Voiding a ticket that is not `OPEN` is rejected with
    `ERR_ORDER_NOT_OPEN`."

    Design: Corner/state_machines/void_paid_order_returns_not_open
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    pay(order["id"], payment_method="CARD")
    validate_error(api.void_order(order["id"], LEAD), "ERR_ORDER_NOT_OPEN")


def test_refund_open_order_returns_not_open(api):
    """PRD 3.5: "a refund attempted on a ticket that is not `PAID` is rejected with
    `ERR_ORDER_NOT_OPEN`."

    Design: Corner/state_machines/refund_open_order_returns_not_open
    """
    drawer = open_drawer()
    order = open_order(drawer["id"])
    validate_error(api.refund_order(order["id"], LEAD), "ERR_ORDER_NOT_OPEN")


def test_confirm_confirmed_preorder_invalid_state(api):
    """PRD 3.6: "Confirming anything not in `QUOTED` is rejected with
    `ERR_PREORDER_INVALID_STATE`, as is any pre-order transition attempted from an
    illegal state."

    Design: Corner/state_machines/confirm_confirmed_preorder_invalid_state
    """
    flavor = make_flavor(par_level_ml=300)
    station = make_station()
    pre_order = make_pre_order(flavor["id"], station["id"])
    validate_success(api.confirm_pre_order(pre_order["id"], SCOOP), 200)
    validate_error(api.confirm_pre_order(pre_order["id"], SCOOP), "ERR_PREORDER_INVALID_STATE")


def test_startproduction_from_quoted_invalid_state(api):
    """PRD 3.6: "Starting production moves a `CONFIRMED` pre-order to
    `IN_PRODUCTION`".
    PRD 3.6: "Confirming anything not in `QUOTED` is rejected with
    `ERR_PREORDER_INVALID_STATE`, as is any pre-order transition attempted from an
    illegal state."

    Design: Corner/state_machines/startproduction_from_quoted_invalid_state
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=500)
    station = make_station()
    pre_order = make_pre_order(flavor["id"], station["id"])  # QUOTED, never confirmed
    validate_error(api.start_production(pre_order["id"], BAKER), "ERR_PREORDER_INVALID_STATE")


def test_cancel_fulfilled_preorder_terminal_lockdown(api):
    """PRD 3.6: "A `Manager` may **cancel** a pre-order from `QUOTED`, `CONFIRMED`,
    or `IN_PRODUCTION`, moving it to the terminal `CANCELLED` state; a cancel from
    any other state is rejected with `ERR_PREORDER_INVALID_STATE`."

    Design: Corner/state_machines/cancel_fulfilled_preorder_terminal_lockdown
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=500)
    station = make_station()
    pre_order = make_pre_order(flavor["id"], station["id"])
    drive_preorder_to(pre_order["id"], "FULFILLED")
    validate_error(api.cancel_pre_order(pre_order["id"], MGR), "ERR_PREORDER_INVALID_STATE")


def test_close_cancelled_catering_invalid_state(api):
    """PRD 3.7: "Any close or cancel attempted on a booking that is not `BOOKED` is
    rejected with `ERR_CATERING_INVALID_STATE`."

    Design: Corner/state_machines/close_cancelled_catering_invalid_state
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=1000, expiry_at="2026-05-30T00:00:00Z")
    cart = make_event_cart()
    booking = make_booking(cart["id"], [{"flavor_id": flavor["id"], "volume_ml": 200}])
    validate_success(api.cancel_catering_booking(booking["id"], MGR), 200)
    res = api.close_catering_booking(booking["id"], {"actual_items": [{"flavor_id": flavor["id"], "volume_ml": 100}]}, MGR)
    validate_error(res, "ERR_CATERING_INVALID_STATE")


def test_drawer_close_twice_already_closed(api):
    """PRD 3.8: "Closing an already-closed drawer is rejected with
    `ERR_DRAWER_ALREADY_CLOSED`."

    Design: Corner/state_machines/drawer_close_twice_already_closed
    """
    drawer = open_drawer()
    validate_success(api.close_drawer(drawer["id"], {"counted_cash_cents": 10000}, LEAD), 200)
    validate_error(api.close_drawer(drawer["id"], {"counted_cash_cents": 10000}, LEAD), "ERR_DRAWER_ALREADY_CLOSED")


def test_pay_empty_order_returns_empty_order(api):
    """PRD 3.4: "Payment is refused unless the order has at least one `ACTIVE` line
    (`ERR_EMPTY_ORDER`) and the owning drawer is still `OPEN`
    (`ERR_DRAWER_NOT_OPEN`)."

    Design: Corner/state_machines/pay_empty_order_returns_empty_order
    """
    drawer = open_drawer()
    order = open_order(drawer["id"])
    validate_error(api.pay_order(order["id"], {"payment_method": "CARD"}, SCOOP), "ERR_EMPTY_ORDER")


def test_drawer_close_variance_reconciliation_over(api):
    """PRD 3.8: "Closing computes `variance_cents` as `counted_cash_cents` minus
    `expected_cash_cents` and sets the `reconciliation_status`: `BALANCED` when the
    variance is exactly zero, `OVER` when it is positive, and `SHORT` when it is
    negative. The drawer then moves from `OPEN` to the terminal `CLOSED` state."

    Design: Corner/state_machines/drawer_close_variance_reconciliation_over
    """
    drawer = open_drawer(opening_float_cents=10000)
    closed = validate_success(api.close_drawer(drawer["id"], {"counted_cash_cents": 10500}, LEAD), 200)
    assert closed["variance_cents"] == 500
    assert closed["reconciliation_status"] == "OVER"
    assert closed["status"] == "CLOSED"
