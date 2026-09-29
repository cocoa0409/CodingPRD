"""Conserved quantities across a forward operation and its compensation.

Units on an offer survive a reservation and the vendor cancellation that gives it
up, and cents across a vendor's two ledger buckets survive a return
authorization and the rejection that reverses it.
"""

from test_helpers import (
    TEST_USERS,
    assert_item_conservation,
    assert_vendor_ledger_conservation,
    cancel_line,
    order_lines_of,
    place_and_transmit_order,
    place_order,
    refresh_item,
    refresh_line,
    refresh_order,
    refresh_return,
    refresh_vendor,
    reject_return_payload,
    setup_authorized_return,
    setup_shipped_line,
    setup_vendor_with_active_offer,
    validate_success,
)

MM_HEADERS = TEST_USERS["merchandise_manager_headers"]

SHIPPED_LINE_TOTAL_CENTS = 42498


def _reserved_state(api, suffix, order_ref, quantity=4):
    """An ACTIVE offer of 60 on-hand carrying one open line of `quantity` units."""
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    order = place_order(api, base["item_id"], quantity=quantity, order_ref=order_ref)
    return base, order


def _cancelled_state(api, suffix, order_ref, quantity=4):
    """The same reservation, handed off and then cancelled by its vendor."""
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    placed = place_and_transmit_order(
        api, base["item_id"], quantity=quantity, order_ref=order_ref
    )
    line = placed["lines"][0]
    cancel_line(api, line["id"], base["vendor_id"])
    return base, placed, refresh_line(api, line["id"])


def _shipped_units_of(api, order_id):
    return [
        line for line in order_lines_of(api, order_id) if line["status"] == "SHIPPED"
    ]


# ─── Units conserved on the offer ─────────────────────


def test_placement_grows_the_reservation_and_both_live_counters(api):
    """PRD §3.5: "On the sourcing offer, `reserved_units` and `lifetime_reserved_units` each grow by the line's `quantity` and `available_units` is recomputed."

    Four units taken out of a trusted sixty, less the five-unit safety buffer,
    leave 51 orderable units behind.

    Design: Difficulty/compensating_invariant/unit_conservation_holds_across_reservation_and_vendor_cancellation
    """
    base, order = _reserved_state(api, "CU1", "ORD-UNITS-CU1")

    offer = refresh_item(api, base["item_id"])
    assert offer["reserved_units"] == 4
    assert offer["lifetime_reserved_units"] == 4
    assert offer["lifetime_released_units"] == 0
    assert offer["lifetime_shipped_units"] == 0
    assert offer["available_units"] == 51


def test_vendor_cancellation_releases_the_reservation_through_the_release_counter(api):
    """PRD §3.6: "**Hop one** sets the line's `status` to `CANCELLED_BY_VENDOR`, reduces the sourcing offer's `reserved_units` by the line's `quantity`, raises that offer's `lifetime_released_units` by the same amount, and recomputes its `available_units`."

    The compensation is expressed by growing the release counter, never by
    rewinding the reservation counter.

    Design: Difficulty/compensating_invariant/unit_conservation_holds_across_reservation_and_vendor_cancellation
    """
    base, placed, line = _cancelled_state(api, "CU2", "ORD-UNITS-CU2")
    assert line["status"] == "CANCELLED_BY_VENDOR"

    offer = refresh_item(api, base["item_id"])
    assert offer["reserved_units"] == 0
    assert offer["lifetime_released_units"] == 4
    assert offer["lifetime_shipped_units"] == 0


def test_unit_conservation_holds_before_and_after_the_cancellation(api):
    """PRD §2.10: "An offer's `reserved_units` must always equal its `lifetime_reserved_units` minus its `lifetime_released_units` minus its `lifetime_shipped_units`."

    The identity reads 4 == 4 - 0 - 0 while the line is open and 0 == 4 - 4 - 0
    once the vendor has walked away, with the reservation counter frozen at 4.

    Design: Difficulty/compensating_invariant/unit_conservation_holds_across_reservation_and_vendor_cancellation
    """
    base = setup_vendor_with_active_offer(api, suffix="CU3")
    placed = place_and_transmit_order(
        api, base["item_id"], quantity=4, order_ref="ORD-UNITS-CU3"
    )
    line = placed["lines"][0]

    open_view = refresh_item(api, base["item_id"])
    assert_item_conservation(open_view)
    assert open_view["reserved_units"] == 4
    assert open_view["lifetime_reserved_units"] == 4

    cancel_line(api, line["id"], base["vendor_id"])

    closed_view = refresh_item(api, base["item_id"])
    assert_item_conservation(closed_view)
    assert closed_view["reserved_units"] == 0
    assert closed_view["lifetime_reserved_units"] == 4


def test_availability_returns_to_its_exact_pre_order_value(api):
    """PRD §3.4: "For an `ACTIVE` offer it is the trusted on-hand figure reduced by the vendor's `safety_buffer_units`, increased by the vendor's `oversell_grace_units`, and reduced by the offer's `reserved_units`, with the whole result floored at 0 — the floor is applied once, after every other term."

    With nothing reserved again, sixty trusted units less the five-unit buffer put
    availability back on 55 — exactly where it stood before the order.

    Design: Difficulty/compensating_invariant/unit_conservation_holds_across_reservation_and_vendor_cancellation
    """
    base, placed, line = _cancelled_state(api, "CU4", "ORD-UNITS-CU4")

    offer = refresh_item(api, base["item_id"])
    assert offer["effective_on_hand_units"] == 60
    assert offer["reserved_units"] == 0
    assert offer["available_units"] == 55


# ─── Cents conserved across the vendor ledger ─────────


def test_shipment_credits_the_ledger_with_the_whole_shipped_line_total(api):
    """PRD §2.10: "A vendor's `settlement_balance_cents` plus its `chargeback_balance_cents` must always equal the total, summed over every `SHIPPED` order line whose current offer belongs to that vendor, of that line's `unit_cost_cents` multiplied by its `quantity` and increased by that line's `surcharge_cents`."

    Two units at 21249 cents of pinned cost with no surcharge put 42498 cents on
    the settlement side and nothing on the chargeback side.

    Design: Difficulty/compensating_invariant/cents_conservation_holds_across_return_authorization_and_rejection
    """
    state = setup_shipped_line(
        api,
        quantity=2,
        order_ref="ORD-CENTS-CC1",
        suffix="CC1",
        ship_at="2026-08-04T10:00:00Z",
    )

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["settlement_balance_cents"] == SHIPPED_LINE_TOTAL_CENTS
    assert vendor["chargeback_balance_cents"] == 0
    assert_vendor_ledger_conservation(vendor, _shipped_units_of(api, state["order_id"]))


def test_authorized_return_charges_the_vendor_its_cost_plus_reverse_freight(api):
    """PRD §3.8: "Step seven sets `vendor_chargeback_cents` to 0 when `routing_destination` is `RETAILER_DC`, and otherwise to `quantity_returned` multiplied by the line's frozen `unit_cost_cents`, increased by a further 1295 cents when `reverse_freight_owner` is `VENDOR`."

    A DEFECTIVE return routes to the sourcing vendor and puts reverse freight on
    it, so one unit of 21249 cents of cost becomes a 22544-cent chargeback.

    Design: Difficulty/compensating_invariant/cents_conservation_holds_across_return_authorization_and_rejection
    """
    state = setup_authorized_return(
        api,
        quantity=2,
        quantity_returned=1,
        reason_code="DEFECTIVE",
        order_ref="ORD-CENTS-CC2",
        suffix="CC2",
        ship_at="2026-08-04T10:00:00Z",
    )

    ra = refresh_return(api, state["return_id"])
    assert ra["routing_destination"] == "VENDOR"
    assert ra["reverse_freight_owner"] == "VENDOR"
    assert ra["restocking_fee_cents"] == 0
    assert ra["refund_cents"] == 24999
    assert ra["vendor_chargeback_cents"] == 22544


def test_authorization_moves_the_pair_of_balances_without_moving_their_sum(api):
    """PRD §3.8: "On the **VENDOR** branch, `routed_vendor_id` holds the selected vendor, that vendor's `chargeback_balance_cents` grows by the return's `vendor_chargeback_cents` while its `settlement_balance_cents` falls by the identical amount, and the order's `retailer_absorbed_cents` is left untouched."

    22544 cents cross from settlement to chargeback: 19954 plus 22544 is still the
    42498 cents the shipped line owes.

    Design: Difficulty/compensating_invariant/cents_conservation_holds_across_return_authorization_and_rejection
    """
    state = setup_authorized_return(
        api,
        quantity=2,
        quantity_returned=1,
        reason_code="DEFECTIVE",
        order_ref="ORD-CENTS-CC3",
        suffix="CC3",
        ship_at="2026-08-04T10:00:00Z",
    )

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["chargeback_balance_cents"] == 22544
    assert vendor["settlement_balance_cents"] == 19954
    assert (
        vendor["settlement_balance_cents"] + vendor["chargeback_balance_cents"]
        == SHIPPED_LINE_TOTAL_CENTS
    )
    assert_vendor_ledger_conservation(vendor, _shipped_units_of(api, state["order_id"]))
    assert refresh_order(api, state["order_id"])["retailer_absorbed_cents"] == 0


def test_authorization_partially_refunds_the_order(api):
    """PRD §3.6: "`CAPTURED → PARTIALLY_REFUNDED` fires when a return authorization leaves `refunded_cents` greater than 0 but still strictly below `total_retail_cents`."

    A 24999-cent refund against 49998 cents of captured retail is strictly partial,
    and the line now shows one returned unit.

    Design: Difficulty/compensating_invariant/cents_conservation_holds_across_return_authorization_and_rejection
    """
    state = setup_authorized_return(
        api,
        quantity=2,
        quantity_returned=1,
        reason_code="DEFECTIVE",
        order_ref="ORD-CENTS-CC4",
        suffix="CC4",
        ship_at="2026-08-04T10:00:00Z",
    )

    order = refresh_order(api, state["order_id"])
    assert order["total_retail_cents"] == 49998
    assert order["refunded_cents"] == 24999
    assert order["net_retail_cents"] == 24999
    assert order["financial_status"] == "PARTIALLY_REFUNDED"
    assert refresh_line(api, state["line_id"])["returned_units"] == 1


def test_rejecting_an_authorized_return_restores_both_vendor_balances(api):
    """PRD §3.8: "The pair of postings is exact, so a vendor's `settlement_balance_cents` and `chargeback_balance_cents` each return to precisely the value they held before the authorization, and their sum was never disturbed at all."

    Rejection reverses the 22544-cent chargeback in full, leaving 42498 cents of
    settlement and nothing charged back.

    Design: Difficulty/compensating_invariant/cents_conservation_holds_across_return_authorization_and_rejection
    """
    state = setup_authorized_return(
        api,
        quantity=2,
        quantity_returned=1,
        reason_code="DEFECTIVE",
        order_ref="ORD-CENTS-CC5",
        suffix="CC5",
        ship_at="2026-08-04T10:00:00Z",
    )

    rejected = validate_success(
        api.reject_return(
            state["return_id"], reject_return_payload("POLICY"), MM_HEADERS
        )
    )
    assert rejected["status"] == "REJECTED"

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["chargeback_balance_cents"] == 0
    assert vendor["settlement_balance_cents"] == SHIPPED_LINE_TOTAL_CENTS
    assert (
        vendor["settlement_balance_cents"] + vendor["chargeback_balance_cents"]
        == SHIPPED_LINE_TOTAL_CENTS
    )
    assert_vendor_ledger_conservation(vendor, _shipped_units_of(api, state["order_id"]))


def test_rejecting_an_authorized_return_walks_the_order_back_to_captured(api):
    """PRD §3.6: "And `PARTIALLY_REFUNDED → CAPTURED` is the compensating leg, fired when the rejection of an already-authorized return brings `refunded_cents` back to 0 — `PARTIALLY_REFUNDED` is emphatically not a terminal state."

    The refund is undone entirely: refunded cents back to 0, net retail back to
    the full 49998, and the line's returned units back to 0.

    Design: Difficulty/compensating_invariant/cents_conservation_holds_across_return_authorization_and_rejection
    """
    state = setup_authorized_return(
        api,
        quantity=2,
        quantity_returned=1,
        reason_code="DEFECTIVE",
        order_ref="ORD-CENTS-CC6",
        suffix="CC6",
        ship_at="2026-08-04T10:00:00Z",
    )
    validate_success(
        api.reject_return(
            state["return_id"], reject_return_payload("POLICY"), MM_HEADERS
        )
    )

    order = refresh_order(api, state["order_id"])
    assert order["refunded_cents"] == 0
    assert order["financial_status"] == "CAPTURED"
    assert order["net_retail_cents"] == 49998
    assert refresh_line(api, state["line_id"])["returned_units"] == 0
