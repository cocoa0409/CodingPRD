"""Parts inventory reservation, the completion/cancellation cascades, and the
inventory conservation invariant.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_technician_headers,
    setup_diagnosed_ticket, setup_ticket_in_repair,
    add_part_order, create_part,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / complete_cascade_finalize_install_decrement
# ---------------------------------------------------------------------------
def test_complete_installs_reserved_part_and_decrements_stock(api):
    """PRD §3.5: "Driven by this finalization, each part order on the ticket in
    `RESERVED` status transitions `RESERVED → INSTALLED`, and for each such order the
    part's `on_hand_qty` and `reserved_qty` are both decreased by the order's quantity
    with `available_qty` recomputed."

    Design: Difficulty/transitive_cascade/complete_cascade_finalize_install_decrement
    """
    scn = setup_ticket_in_repair(market_value_cents=60000, spend_cap_cents=100000,
                                 labor_hours=2, part_specs=[(6000, 10, 2)])
    order = scn["orders"][0]
    part = scn["parts"][0]
    validate_success(api.complete_ticket(
        scn["ticket"]["id"], {"actual_labor_hours": 2},
        make_technician_headers(scn["technician"]["id"])))
    po = validate_success(api.get_part_order(order["id"], SM))
    assert po["status"] == "INSTALLED"
    p = validate_success(api.get_part(part["id"], SM))
    assert p["on_hand_qty"] == 8
    assert p["reserved_qty"] == 0
    assert p["available_qty"] == 8


def test_complete_finalizes_estimate_and_completes_ticket(api):
    """PRD §3.5: "On success the ticket's `completed_at` is stamped with the current
    logical-clock instant and the ticket moves `IN_REPAIR → COMPLETED`. The approved
    estimate is finalized, moving `APPROVED → FINALIZED`".

    Design: Difficulty/transitive_cascade/complete_cascade_finalize_install_decrement
    """
    scn = setup_ticket_in_repair(market_value_cents=60000, spend_cap_cents=100000,
                                 labor_hours=2, part_specs=[(6000, 10, 2)])
    completed = validate_success(api.complete_ticket(
        scn["ticket"]["id"], {"actual_labor_hours": 2},
        make_technician_headers(scn["technician"]["id"])))
    assert completed["status"] == "COMPLETED"
    est = validate_success(api.get_estimate(scn["ticket"]["id"], scn["estimate"]["id"], SM))
    assert est["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / cancel_cascade_return_release_inventory
# ---------------------------------------------------------------------------
def test_cancel_returns_reserved_part_and_releases_stock(api):
    """PRD §3.6: "Cancellation moves the ticket to `CANCELLED` and unwinds its
    commitments: each part order on the ticket in `RESERVED` status transitions
    `RESERVED → RETURNED`, releasing its held stock by decreasing the part's
    `reserved_qty` by the order's quantity and recomputing `available_qty`".

    Design: Difficulty/transitive_cascade/cancel_cascade_return_release_inventory
    """
    scn = setup_diagnosed_ticket(market_value_cents=60000, spend_cap_cents=100000)
    part = create_part(unit_price_cents=6000, on_hand_qty=10)
    order = add_part_order(scn["ticket"]["id"], scn["technician"]["id"], part["id"], 2)
    validate_success(api.cancel_ticket(scn["ticket"]["id"], SA))
    po = validate_success(api.get_part_order(order["id"], SM))
    assert po["status"] == "RETURNED"
    p = validate_success(api.get_part(part["id"], SM))
    assert p["reserved_qty"] == 0
    assert p["on_hand_qty"] == 10
    assert p["available_qty"] == 10


def test_cancel_moves_ticket_to_cancelled(api):
    """PRD §3.6: "A `ServiceAdvisor` may cancel a ticket while it is still in `INTAKE`,
    `DIAGNOSING`, or `AWAITING_APPROVAL`".

    Design: Difficulty/transitive_cascade/cancel_cascade_return_release_inventory
    """
    scn = setup_diagnosed_ticket(market_value_cents=60000, spend_cap_cents=100000)
    part = create_part(unit_price_cents=6000, on_hand_qty=10)
    add_part_order(scn["ticket"]["id"], scn["technician"]["id"], part["id"], 2)
    cancelled = validate_success(api.cancel_ticket(scn["ticket"]["id"], SA))
    assert cancelled["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / inventory_conserved_reserve_then_return
# ---------------------------------------------------------------------------
def test_inventory_conserved_after_reserve_then_return(api):
    """PRD §2.10: "For every `Part`, the `available_qty` is defined as `on_hand_qty`
    minus `reserved_qty`, recomputed on every reservation, restock, install, or return".
    PRD §3.6: "releasing its held stock by decreasing the part's `reserved_qty` by the
    order's quantity and recomputing `available_qty`".

    Design: Difficulty/compensating_invariant/inventory_conserved_reserve_then_return
    """
    scn = setup_diagnosed_ticket(market_value_cents=60000, spend_cap_cents=100000)
    part = create_part(unit_price_cents=6000, on_hand_qty=10)
    order = add_part_order(scn["ticket"]["id"], scn["technician"]["id"], part["id"], 3)
    # Reserve took available to 7.
    reserved = validate_success(api.get_part(part["id"], SM))
    assert reserved["reserved_qty"] == 3
    assert reserved["available_qty"] == 7
    validate_success(api.cancel_ticket(scn["ticket"]["id"], SA))
    p = validate_success(api.get_part(part["id"], SM))
    assert p["reserved_qty"] == 0
    assert p["available_qty"] == 10
    assert p["on_hand_qty"] == 10


def test_returned_order_is_terminal_after_cancel(api):
    """PRD §3.6: "each part order on the ticket in `RESERVED` status transitions
    `RESERVED → RETURNED`".

    Design: Difficulty/compensating_invariant/inventory_conserved_reserve_then_return
    """
    scn = setup_diagnosed_ticket(market_value_cents=60000, spend_cap_cents=100000)
    part = create_part(unit_price_cents=6000, on_hand_qty=10)
    order = add_part_order(scn["ticket"]["id"], scn["technician"]["id"], part["id"], 3)
    validate_success(api.cancel_ticket(scn["ticket"]["id"], SA))
    po = validate_success(api.get_part_order(order["id"], SM))
    assert po["status"] == "RETURNED"


# ---------------------------------------------------------------------------
# Corner: validations / part_order_zero_quantity_rejected
# ---------------------------------------------------------------------------
def test_part_order_zero_quantity_rejected(api):
    """PRD §2.11: "the request body is checked for well-formedness — required fields
    present, enum values in range, quantities at least 1, and an interval whose end is
    after its start — surfacing `ERR_VALIDATION`, `ERR_INVALID_QUANTITY`, or
    `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/part_order_zero_quantity_rejected
    """
    scn = setup_diagnosed_ticket(market_value_cents=1000, spend_cap_cents=100000)
    part = create_part(unit_price_cents=6000, on_hand_qty=10)
    resp = api.create_part_order(
        scn["ticket"]["id"], {"part_id": part["id"], "quantity": 0},
        make_technician_headers(scn["technician"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY.value, 422)


# ---------------------------------------------------------------------------
# Corner: validations / restock_out_of_stock_returns_part_out_of_stock
# ---------------------------------------------------------------------------
def test_restock_backordered_out_of_stock_returns_part_out_of_stock(api):
    """PRD §3.4: "if `available_qty` is less than the quantity, the order is instead
    created in `BACKORDERED` status and no stock is held."
    PRD §3.4: "it requires that the part's `available_qty` now be at least the order's
    `quantity`, otherwise it is rejected with `ERR_PART_OUT_OF_STOCK`."

    Design: Corner/validations/restock_out_of_stock_returns_part_out_of_stock
    """
    scn = setup_diagnosed_ticket(market_value_cents=1000, spend_cap_cents=100000)
    part = create_part(unit_price_cents=6000, on_hand_qty=0)
    order = add_part_order(scn["ticket"]["id"], scn["technician"]["id"], part["id"], 1)
    assert order["status"] == "BACKORDERED"
    resp = api.restock_part_order(order["id"], SM)
    validate_error(resp, ApiErrorId.ERR_PART_OUT_OF_STOCK.value, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines / restock_reserved_part_order_returns_part_order_invalid_state
# ---------------------------------------------------------------------------
def test_restock_reserved_order_returns_part_order_invalid_state(api):
    """PRD §3.4: "if the part's `available_qty` is greater than or equal to the ordered
    `quantity`, the order is created directly in `RESERVED` status".
    PRD §3.4: "Restock is permitted only while the order is `BACKORDERED`, otherwise
    `ERR_PART_ORDER_INVALID_STATE`".

    Design: Corner/state_machines/restock_reserved_part_order_returns_part_order_invalid_state
    """
    scn = setup_diagnosed_ticket(market_value_cents=1000, spend_cap_cents=100000)
    part = create_part(unit_price_cents=6000, on_hand_qty=10)
    order = add_part_order(scn["ticket"]["id"], scn["technician"]["id"], part["id"], 1)
    assert order["status"] == "RESERVED"
    resp = api.restock_part_order(order["id"], SM)
    validate_error(resp, ApiErrorId.ERR_PART_ORDER_INVALID_STATE.value, 409)
