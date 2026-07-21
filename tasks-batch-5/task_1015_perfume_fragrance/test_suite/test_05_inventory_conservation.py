"""Inventory reservation, the placed-order cancel cascade, and the on-hand +
reserved conservation invariant."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_placed_order, setup_fulfilled_order,
    TEST_USERS,
)

FULFILL = TEST_USERS["fulfillment_headers"]


def _lines_by_id(api, order_id, headers):
    data, _ = validate_paginated(api.list_order_lines(order_id, headers))
    return {ln["id"]: ln for ln in data}


# ─── Difficulty/transitive_cascade/order_cancel_depth2_line_inventory_release ───
def test_cancel_placed_order_marks_line_cancelled(api):
    """PRD §3.4: "Each active line's `status` becomes `CANCELLED`, and that
    line-cancellation returns its units to inventory."

    Design: Difficulty/transitive_cascade/order_cancel_depth2_line_inventory_release
    """
    ctx = setup_placed_order(3500, quantity=3, on_hand_qty=10, variant_kind="DECANT")
    api.cancel_order(ctx["order_id"], ctx["cust_headers"])
    lines = _lines_by_id(api, ctx["order_id"], ctx["cust_headers"])
    assert lines[ctx["line_id"]]["status"] == "CANCELLED"


def test_cancel_placed_order_releases_reservation(api):
    """PRD §3.4: "that line-cancellation returns its units to inventory — the
    variant's `reserved_qty` is decreased by the line quantity and its
    `on_hand_qty` increased by the same amount."

    Design: Difficulty/transitive_cascade/order_cancel_depth2_line_inventory_release
    """
    ctx = setup_placed_order(3500, quantity=3, on_hand_qty=10, variant_kind="DECANT")
    api.cancel_order(ctx["order_id"], ctx["cust_headers"])
    var = validate_success(api.get_variant(ctx["var_id"], ctx["cust_headers"]), 200)
    assert var["reserved_qty"] == 0
    assert var["on_hand_qty"] == 10


# ─── Difficulty/compensating_invariant/inventory_units_conserved_place_then_cancel ───
def test_placement_reserves_while_conserving_total(api):
    """PRD §2.10: "reserving units for a placement moves them from on-hand to
    reserved without changing the total."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_place_then_cancel
    """
    ctx = setup_placed_order(3500, quantity=3, on_hand_qty=10, variant_kind="DECANT")
    var = validate_success(api.get_variant(ctx["var_id"], ctx["cust_headers"]), 200)
    assert var["on_hand_qty"] == 7
    assert var["reserved_qty"] == 3
    assert var["on_hand_qty"] + var["reserved_qty"] == 10


def test_cancel_restores_conserved_total(api):
    """PRD §2.10: "releasing a cancelled placement moves them back." — the
    on-hand-plus-reserved total is unchanged across the place/cancel pair.

    Design: Difficulty/compensating_invariant/inventory_units_conserved_place_then_cancel
    """
    ctx = setup_placed_order(3500, quantity=3, on_hand_qty=10, variant_kind="DECANT")
    api.cancel_order(ctx["order_id"], ctx["cust_headers"])
    var = validate_success(api.get_variant(ctx["var_id"], ctx["cust_headers"]), 200)
    assert var["on_hand_qty"] == 10
    assert var["reserved_qty"] == 0
    assert var["on_hand_qty"] + var["reserved_qty"] == 10


# ─── Corner instance ──────────────────────────────────
def test_cancel_fulfilled_order_rejected(api):
    """PRD §3.4: "Cancelling a placed order is a depth-two cascade: it is
    permitted only while the order is `PLACED`." — a FULFILLED order is out of
    range and rejected with `ERR_INVALID_STATE`.

    Design: Corner/state_machines/cancel_fulfilled_order_returns_409
    """
    ctx = setup_fulfilled_order(9000, quantity=1, on_hand_qty=5, concentration="EDT")
    resp = api.cancel_order(ctx["order_id"], ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
