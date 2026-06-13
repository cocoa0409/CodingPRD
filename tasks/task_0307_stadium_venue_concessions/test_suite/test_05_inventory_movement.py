"""Inventory movement: replenishment delivery, FIFO depletion, transfers,
the expire-lots depth-3 cascade, and the transfer/refund compensating invariants.

Queue A (Difficulty): transitive_cascade (expire), compensating_invariant (transfer, refund).
Queue B (Corner): state_machines (replenishment, lot deplete), validations (expire),
                  cross_cutting (transfer complete derived on-hand).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_revenue_share_statement, ApiErrorId, TEST_USERS, make_patron_headers,
    create_venue, create_product, create_replenishment_payload, deliver_replenishment_payload,
    create_inventory_lot_payload, create_order_payload, create_order_line_payload,
    create_menu_item_payload,
)
from test_helpers.fixtures import (
    create_event, create_stand, create_event_doors_open, create_stand_opened_with_staff,
    create_lot, create_patron, setup_dispatched_transfer, setup_two_stands_one_event,
    setup_paid_order, stand_onhand, current_stand_version,
)

MANAGER = TEST_USERS["manager_headers"]
RUNNER = TEST_USERS["runner_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# ===========================================================================
# Queue A — expire_lot_to_waste_to_event_cost_to_net_statement_depth3
# expire -> EXPIRY WasteRecord (50*40=2000) -> event.waste_cost_cents bump ->
# NET-basis settled statement shrinks venue_share. gross 4922, waste 2000:
# NET base 2922, pct 20 -> round(584.4)=584; operator_net 4922-584=4338.
# ===========================================================================
def _depth3_cascade_settled():
    venue = create_venue(venue_share_pct=20, share_basis="NET", spoilage_valuation="FIFO", service_fee_pct=7)
    hotdog = create_product(venue["id"], sku="HOTDOG", name="Hot Dog", base_price_cents=1000, unit_cost_cents=200)
    bun = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=40, perishable=True)
    api_client.set_clock("2026-06-07T17:00:00.000Z", MANAGER)
    base = create_stand_opened_with_staff(
        venue_id=venue["id"], stand_overrides={"demand_tier": "MID", "expected_orders_per_hour": 80}
    )
    event, stand = base["event"], base["stand"]
    mi = validate_success(api_client.create_menu_item(create_menu_item_payload(stand["id"], hotdog["id"]), MANAGER), 201)
    create_lot(stand["id"], hotdog["id"], received_qty=50, unit_cost_cents=200, par_level=50, reorder_point=10)
    create_lot(stand["id"], bun["id"], received_qty=50, unit_cost_cents=40, par_level=60, reorder_point=10,
               expires_at="2026-06-07T19:00:00.000Z")
    patron = create_patron()
    ph = make_patron_headers(patron["id"])
    order = validate_success(api_client.create_order(create_order_payload(event["id"], stand["id"], patron["id"]), ph), 201)
    validate_success(api_client.add_order_line(order["id"], create_order_line_payload(mi["id"], 4), ph), 201)
    validate_success(api_client.place_order(order["id"], ph), 200)
    validate_success(api_client.pay_order(order["id"], ph), 200)
    sv = current_stand_version(stand["id"])
    validate_success(api_client.ready_order(order["id"], {"expected_stand_version": sv}, OPERATOR), 200)
    validate_success(api_client.pickup_order(order["id"], OPERATOR), 200)
    # Settlement requires the event be IN_PROGRESS (PRD §3.5). Advance via the
    # peak window after the sale is picked up — gross_sales_cents (4922) was
    # already snapshotted at pickup, so the peak price recompute does not touch it.
    validate_success(api_client.open_peak_window(event["id"], MANAGER), 200)
    api_client.set_clock("2026-06-07T20:00:00.000Z", MANAGER)
    validate_success(api_client.expire_lots(stand["id"], RUNNER), 200)
    validate_success(api_client.close_stand(stand["id"], OPERATOR), 200)
    stmt = validate_success(api_client.settle_event(event["id"], MANAGER), 201)
    event = validate_success(api_client.get_event(event["id"], MANAGER), 200)
    return event, stmt


def test_expire_lots_bumps_event_waste_cost(api):
    """PRD §3.5: "Expiring a lot is a depth-three cascade: a waste record with
    reason EXPIRY is created for the lot's remaining units (costed per the venue's
    spoilage policy, §3.6), the parent event's waste_cost_cents is increased by
    that waste record's cost_cents, and the lot's remaining_qty is set to zero and
    its status to EXPIRED."

    50 buns @ 40c expired -> waste 2000 -> event.waste_cost_cents 2000.

    Design: Difficulty/transitive_cascade/expire_lot_to_waste_to_event_cost_to_net_statement_depth3
    """
    event, _stmt = _depth3_cascade_settled()
    assert event["waste_cost_cents"] == 2000, f"expected 2000, got {event['waste_cost_cents']}"


def test_expire_cascade_shrinks_net_venue_share_at_settlement(api):
    """PRD §3.9: "Under the NET basis, the base is instead the greater of zero and
    the snapshot gross sales minus the snapshot waste cost, so venue_share_cents is
    that floored-at-zero net base multiplied by the venue's venue_share_pct divided
    by 100, rounded half-up to whole cents".

    gross 4922, waste 2000 -> NET base 2922, pct 20 -> round(584.4)=584;
    operator_net 4922-584=4338.

    Design: Difficulty/transitive_cascade/expire_lot_to_waste_to_event_cost_to_net_statement_depth3
    """
    _event, stmt = _depth3_cascade_settled()
    assert_revenue_share_statement(stmt)
    assert stmt["gross_sales_cents"] == 4922
    assert stmt["waste_cost_cents"] == 2000
    assert stmt["venue_share_cents"] == 584, f"expected 584, got {stmt['venue_share_cents']}"
    assert stmt["operator_net_cents"] == 4338, f"expected 4338, got {stmt['operator_net_cents']}"


# ===========================================================================
# Queue A — transfer_cancel_restores_total_on_hand_units
# Source 100; dispatch 30 (source 70); cancel re-credits 30 -> source back to 100,
# destination 0. Total conserved.
# ===========================================================================
def test_cancel_in_transit_transfer_restores_source_on_hand(api):
    """PRD §3.5: "Cancelling an IN_TRANSIT transfer is a compensating action that
    restores the units: it re-credits qty back to the source stand by creating a
    new ACTIVE inventory lot there whose received_qty and remaining_qty both equal
    qty and whose unit_cost_cents is the same weighted-average of the debited source
    lots, returning the global on-hand quantity to its pre-dispatch total."

    Source 100, dispatch 30, cancel -> source on-hand back to 100.

    Design: Difficulty/compensating_invariant/transfer_cancel_restores_total_on_hand_units
    """
    state = setup_dispatched_transfer(qty=30, source_lot_qty=100, lot_unit_cost=30)
    cancelled = validate_success(api.cancel_transfer(state["transfer"]["id"], RUNNER), 200)
    assert cancelled["status"] == "CANCELLED"
    assert stand_onhand(state["stand_a"]["id"], state["product"]["id"]) == 100


def test_cancel_in_transit_transfer_leaves_destination_empty(api):
    """PRD §3.5: "the units are now held in transit and not yet credited
    anywhere".
    PRD §3.5: "Cancelling an IN_TRANSIT transfer is a compensating action that
    restores the units ... returning the global on-hand quantity to its pre-dispatch
    total."

    Destination B never received the in-transit units -> remains 0 on-hand.

    Design: Difficulty/compensating_invariant/transfer_cancel_restores_total_on_hand_units
    """
    state = setup_dispatched_transfer(qty=30, source_lot_qty=100, lot_unit_cost=30)
    validate_success(api.cancel_transfer(state["transfer"]["id"], RUNNER), 200)
    assert stand_onhand(state["stand_b"]["id"], state["product"]["id"]) == 0


# ===========================================================================
# Queue A — order_cancel_refund_conserves_money_to_wallet
# PAID order total 220 cancelled refunds exactly 220 to the patron wallet.
# ===========================================================================
def _paid_order_for_refund():
    # LOW-tier, multiplier-100 stand so the menu price equals the 100c base; with
    # qty 2 and service_fee_pct 10 the order total is exactly 220.
    return setup_paid_order(
        line_qtys=(2,),
        venue_overrides={"venue_share_pct": 10, "service_fee_pct": 10},
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
        stand_overrides={"demand_tier": "LOW", "expected_orders_per_hour": 40},
        event_overrides={"event_multiplier_pct": 100},
    )


def test_cancel_paid_order_refunds_total_to_wallet(api):
    """PRD §3.8: "Cancelling sets the fulfillment_status to CANCELLED, and if the
    order had been paid it is a compensating refund: the payment_status is set to
    REFUNDED and the patron's wallet_credit_cents is credited by exactly the order's
    total_cents."

    total 220 (water 100, qty 2, fee 10%) -> wallet credited 220; payment REFUNDED.

    Design: Difficulty/compensating_invariant/order_cancel_refund_conserves_money_to_wallet
    """
    state = _paid_order_for_refund()
    ph = state["patron_headers"]
    order_total = state["order"]["total_cents"]
    assert order_total == 220, f"expected order total 220, got {order_total}"
    cancelled = validate_success(api.cancel_order(state["order"]["id"], ph), 200)
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["fulfillment_status"] == "CANCELLED"
    patron = validate_success(api.get_patron(state["patron"]["id"], ph), 200)
    assert patron["wallet_credit_cents"] == order_total, f"expected {order_total}, got {patron['wallet_credit_cents']}"


def test_cancel_paid_order_sets_cancelled_and_refunded(api):
    """PRD §3.8: "An order may be cancelled by the patron, but only while its
    fulfillment_status is still PLACED".
    PRD §3.8: "exactly the full total is returned so the patron's net charge is
    zero."

    Design: Difficulty/compensating_invariant/order_cancel_refund_conserves_money_to_wallet
    """
    state = _paid_order_for_refund()
    ph = state["patron_headers"]
    cancelled = validate_success(api.cancel_order(state["order"]["id"], ph), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"


# ===========================================================================
# Queue B — state_machines/replenishment_deliver_creates_active_lot_side_effect
# ===========================================================================
def test_replenishment_deliver_sets_fulfilled_and_creates_lot(api):
    """PRD §3.5: "On delivery the fulfilled_qty is set equal to requested_qty, and
    a new ACTIVE inventory lot is created on the destination stand whose
    received_qty and remaining_qty both equal the fulfilled quantity, taking its
    unit_cost_cents from the product default and its par_level and reorder_point
    from the delivery request."

    Design: Corner/state_machines/replenishment_deliver_creates_active_lot_side_effect
    """
    venue = create_venue()
    product = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=30, perishable=True)
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    repl = validate_success(api.create_replenishment(create_replenishment_payload(stand["id"], product["id"], requested_qty=40), RUNNER), 201)
    validate_success(api.pick_replenishment(repl["id"], RUNNER), 200)
    delivered = validate_success(api.deliver_replenishment(repl["id"], deliver_replenishment_payload(par_level=60, reorder_point=10), RUNNER), 200)
    assert delivered["fulfilled_qty"] == 40
    assert delivered["status"] == "DELIVERED"
    assert stand_onhand(stand["id"], product["id"]) == 40


def test_lot_depletes_to_depleted_on_ready(api):
    """PRD §3.8: "Readiness is where stock is actually consumed: on-hand for each
    line is decremented from the stand's ACTIVE lots of that product, oldest
    created_at first, with any lot hitting zero turning DEPLETED".
    PRD §3.5: "A lot becomes DEPLETED automatically the moment a decrementing
    operation drives its remaining_qty to zero".

    A 2-unit lot fully consumed by a qty-2 ready -> remaining 0, status DEPLETED.

    Design: Corner/state_machines/lot_depletes_to_depleted_on_pickup
    """
    state = setup_paid_order(
        line_qtys=(2,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
        lot_overrides={"received_qty": 2, "unit_cost_cents": 10, "par_level": 10, "reorder_point": 2},
    )
    sv = current_stand_version(state["stand"]["id"])
    validate_success(api.ready_order(state["order"]["id"], {"expected_stand_version": sv}, OPERATOR), 200)
    lot = validate_success(api.get_inventory_lot(state["lot"]["id"], OPERATOR), 200)
    assert lot["remaining_qty"] == 0
    assert lot["status"] == "DEPLETED"


# ===========================================================================
# Queue B — validations/expire_lot_not_yet_expired_returns_error
# ===========================================================================
def test_expire_sweep_leaves_future_dated_lot_active(api):
    """PRD §3.5: "each ACTIVE lot whose expires_at is non-null and at or before the
    server's current UTC clock, and which still has units on hand, is expired."
    PRD §3.5: "Expiring a lot whose expires_at is null or still in the future is
    rejected with ERR_LOT_NOT_EXPIRED."

    A lot expiring in the future is untouched by the sweep -> stays ACTIVE, qty 50.

    Design: Corner/validations/expire_lot_not_yet_expired_returns_error
    """
    venue = create_venue()
    product = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=30, perishable=True)
    api.set_clock("2026-07-23T17:00:00.000Z", MANAGER)
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    lot = create_lot(stand["id"], product["id"], received_qty=50, unit_cost_cents=30,
                     par_level=60, reorder_point=10, expires_at="2026-07-23T22:00:00.000Z")
    api.expire_lots(stand["id"], RUNNER)
    refreshed = validate_success(api.get_inventory_lot(lot["id"], RUNNER), 200)
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["remaining_qty"] == 50


# ===========================================================================
# Queue B — cross_cutting/transfer_complete_credits_destination_derived_onhand
# ===========================================================================
def test_transfer_complete_credits_destination_on_hand(api):
    """PRD §3.5: "Completing an IN_TRANSIT transfer credits the destination: a new
    ACTIVE inventory lot is created on the destination stand whose received_qty and
    remaining_qty both equal qty".

    After dispatch+complete of 30 A->B: A on-hand 70, B on-hand 30.

    Design: Corner/cross_cutting_complexity_layers/transfer_complete_credits_destination_derived_onhand
    """
    state = setup_dispatched_transfer(qty=30, source_lot_qty=100, lot_unit_cost=30)
    completed = validate_success(api.complete_transfer(state["transfer"]["id"], RUNNER), 200)
    assert completed["status"] == "COMPLETED"
    assert stand_onhand(state["stand_a"]["id"], state["product"]["id"]) == 70
    assert stand_onhand(state["stand_b"]["id"], state["product"]["id"]) == 30
