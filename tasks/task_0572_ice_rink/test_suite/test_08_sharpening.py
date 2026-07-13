"""The skate-sharpening queue: lifecycle advancement and live-queue repositioning."""
from test_helpers import (
    validate_success, TEST_USERS, setup_sharpening_orders,
)

RM = TEST_USERS["rink_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Corner/state_machines/sharpening_order_advances_to_picked_up
# ---------------------------------------------------------------------------
def test_sharpening_order_advances_through_to_picked_up(api):
    """PRD §3.7: "Advancing an order is exclusively a `FrontDesk` action that moves
    it one step along the chain: `RECEIVED` to `IN_PROGRESS`, then to `READY`, then
    to `PICKED_UP`, incrementing `version` each time."

    Design: Corner/state_machines/sharpening_order_advances_to_picked_up
    """
    setup = setup_sharpening_orders(api, skate_types=("HOCKEY",))
    order_id = setup["orders"][0]["id"]
    validate_success(api.advance_sharpening_order(order_id, FD))
    validate_success(api.advance_sharpening_order(order_id, FD))
    data = validate_success(api.advance_sharpening_order(order_id, FD))
    assert data["status"] == "PICKED_UP", f"expected PICKED_UP, got {data['status']}"


# ---------------------------------------------------------------------------
# Corner/calculations/sharpening_queue_positions_and_repositioning
# ---------------------------------------------------------------------------
def test_queue_positions_close_up_after_first_reaches_ready(api):
    """PRD §3.7: "The `queue_position` is a one-based rank among the orders that are
    still live — those in `RECEIVED` or `IN_PROGRESS` status — ordered strictly by
    `created_at` ascending, with ties broken by `created_at` alone and never by
    `id`. Orders that are `READY` or `PICKED_UP` are excluded and occupy no
    position."
    PRD §3.7: "The step that matters for the queue is the move to `READY`: at that
    point the order leaves the live queue, and the `queue_position` of every later
    `RECEIVED` or `IN_PROGRESS` order is recomputed so the line closes up behind it."

    Design: Corner/calculations/sharpening_queue_positions_and_repositioning
    """
    setup = setup_sharpening_orders(api, skate_types=("HOCKEY", "FIGURE", "GOALIE"))
    o1, o2, o3 = (o["id"] for o in setup["orders"])
    # Initial live ranks by created_at: 1, 2, 3.
    assert validate_success(api.get_sharpening_order(o1, RM))["queue_position"] == 1
    assert validate_success(api.get_sharpening_order(o2, RM))["queue_position"] == 2
    assert validate_success(api.get_sharpening_order(o3, RM))["queue_position"] == 3
    # Advance o1 twice: RECEIVED -> IN_PROGRESS -> READY (leaves the queue).
    validate_success(api.advance_sharpening_order(o1, FD))
    validate_success(api.advance_sharpening_order(o1, FD))
    assert validate_success(api.get_sharpening_order(o2, RM))["queue_position"] == 1, (
        "second order should close up to position 1")
    assert validate_success(api.get_sharpening_order(o3, RM))["queue_position"] == 2, (
        "third order should close up to position 2")
