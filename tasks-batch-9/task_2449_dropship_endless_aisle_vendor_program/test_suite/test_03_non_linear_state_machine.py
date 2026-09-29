"""Non-linear lifecycles: the backorder/re-sourcing cycle that returns an order line to
a state it has already occupied, and the two independent status axes an order carries."""

from test_helpers import (
    TEST_USERS,
    acknowledge_payload,
    assert_item_conservation,
    create_active_item,
    create_active_vendor,
    feed_inventory,
    get_success_data,
    make_vendor_user_headers,
    open_return,
    order_line_input,
    place_and_transmit_order,
    refresh_item,
    refresh_line,
    refresh_order,
    reset_clock,
    set_clock,
    setup_vendor_with_active_offer,
    ship_confirm,
    validate_success,
)

_MM = TEST_USERS["merchandise_manager_headers"]
_CARE = TEST_USERS["care_agent_headers"]

_CYCLE_SKU = "SKU-CYCLE-CHAIR"
_FEED_AT = "2026-08-03T09:00:00Z"
_TRANSMIT_AT = "2026-08-03T10:00:00Z"


def _setup_backordered_line_with_wholesale_fallback(api, suffix, order_ref):
    """A BACKORDERED line on a COMMISSION offer whose fallback sits at a WHOLESALE vendor.

    The fallback vendor discounts 1000 bps off a 19000-cent wholesale list, ships in two
    transit days under a 500-cent surcharge and carries a five-day lead time, so every
    commercial figure differs from the offer that is being re-sourced away from.
    """
    reset_clock(api)
    fallback_vendor = create_active_vendor(
        api,
        suffix=f"{suffix}FB",
        rules=[
            {
                "zone_code": "US-WEST",
                "ship_method": "GROUND",
                "transit_days": 2,
                "cutoff_hour_utc": 20,
                "surcharge_cents": 500,
            }
        ],
        cost_model="WHOLESALE",
        wholesale_discount_bps=1000,
        inventory_refresh_cadence_minutes=120,
        safety_buffer_units=2,
        oversell_grace_units=3,
        default_lead_time_days=5,
    )
    fallback_item = create_active_item(
        api,
        fallback_vendor["id"],
        sku=_CYCLE_SKU,
        unit_retail_cents=24999,
        unit_wholesale_cost_cents=19000,
        ship_method="GROUND",
        lead_time_days=5,
        reverse_freight_owner="VENDOR",
        restock_policy="RETAILER_RESTOCK",
        defect_window_days=30,
    )
    primary_vendor = create_active_vendor(
        api,
        suffix=f"{suffix}PR",
        rules=[
            {
                "zone_code": "US-WEST",
                "ship_method": "GROUND",
                "transit_days": 4,
                "cutoff_hour_utc": 18,
                "surcharge_cents": 0,
            }
        ],
    )
    primary_item = create_active_item(
        api,
        primary_vendor["id"],
        sku=_CYCLE_SKU,
        unit_retail_cents=24999,
        ship_method="GROUND",
        lead_time_days=3,
        reverse_freight_owner="RETAILER",
        restock_policy="VENDOR_RESTOCK",
        defect_window_days=30,
        fallback_item_id=fallback_item["id"],
    )
    set_clock(api, _FEED_AT)
    feed_inventory(
        api,
        primary_item["id"],
        primary_vendor["id"],
        on_hand_units=60,
        effective_from=_FEED_AT,
    )
    feed_inventory(
        api,
        fallback_item["id"],
        fallback_vendor["id"],
        on_hand_units=30,
        effective_from=_FEED_AT,
    )
    set_clock(api, _TRANSMIT_AT)
    placed = place_and_transmit_order(
        api, primary_item["id"], quantity=2, order_ref=order_ref
    )
    line = placed["lines"][0]
    get_success_data(
        api.acknowledge_line(
            line["id"],
            acknowledge_payload("BACKORDERED"),
            make_vendor_user_headers(primary_vendor["id"]),
        )
    )
    return {
        "primary_vendor_id": primary_vendor["id"],
        "fallback_vendor_id": fallback_vendor["id"],
        "primary_item_id": primary_item["id"],
        "fallback_item_id": fallback_item["id"],
        "order_id": placed["order_id"],
        "line_id": line["id"],
        "quantity": 2,
    }


def _setup_two_acknowledged_lines(api, suffix, order_ref):
    """One order with two accepted single-unit lines on the same offer.

    Both lines are transmitted and acknowledged, then the clock advances a day so a
    shipment lands inside the ship deadline and inside the defect window.
    """
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    placed = place_and_transmit_order(
        api,
        base["item_id"],
        quantity=1,
        order_ref=order_ref,
        extra_lines=[order_line_input(base["item_id"], 1)],
    )
    lines = placed["lines"]
    for line in lines:
        get_success_data(
            api.acknowledge_line(
                line["id"],
                acknowledge_payload("ACCEPTED"),
                make_vendor_user_headers(base["vendor_id"]),
            )
        )
    set_clock(api, "2026-08-04T10:00:00Z")
    return {
        **base,
        "order_id": placed["order_id"],
        "first_line_id": lines[0]["id"],
        "second_line_id": lines[1]["id"],
    }


# ─── The backorder → re-sourcing cycle ────────────────


def test_retransmit_returns_the_line_to_transmitted_on_a_second_attempt(api):
    """PRD §3.7: "Re-sourcing is a `MerchandiseManager` or administrator action, it is legal only from `BACKORDERED` — any other state raises `ERR_LINE_INVALID_STATE` — and it closes the line's cycle by returning it to `TRANSMITTED`, potentially at a completely different vendor."

    The line re-enters TRANSMITTED, a state it already occupied, and the second visit is
    marked as such: the attempt counter reads 2, the acknowledgment is wiped, and the
    line now points at the fallback offer rather than the offer it was placed against.

    Design: Difficulty/non_linear_state_machine/line_backorder_retransmit_cycle_returns_to_transmitted_on_fallback_vendor
    """
    state = _setup_backordered_line_with_wholesale_fallback(
        api, suffix="CYA", order_ref="ORD-CYCLE-A1"
    )
    assert refresh_line(api, state["line_id"])["status"] == "BACKORDERED"

    validate_success(api.retransmit_line(state["line_id"], _MM))

    line = refresh_line(api, state["line_id"])
    assert line["status"] == "TRANSMITTED"
    assert line["transmit_attempt_count"] == 2
    assert line["item_id"] == state["fallback_item_id"]


def test_retransmit_clears_the_previous_vendor_acknowledgment(api):
    """PRD §3.7: "The line's `acknowledged_at` is cleared back to null and `ack_sla_breached` back to false, because the new vendor has not been asked yet."

    The backorder disposition stamped an acknowledgment on the line; the re-sourcing hop
    must erase it, because the newly selected vendor has not answered yet.

    Design: Difficulty/non_linear_state_machine/line_backorder_retransmit_cycle_returns_to_transmitted_on_fallback_vendor
    """
    state = _setup_backordered_line_with_wholesale_fallback(
        api, suffix="CYB", order_ref="ORD-CYCLE-B1"
    )
    assert refresh_line(api, state["line_id"])["acknowledged_at"] is not None

    validate_success(api.retransmit_line(state["line_id"], _MM))

    line = refresh_line(api, state["line_id"])
    assert line["acknowledged_at"] is None
    assert line["ack_sla_breached"] is False


def test_retransmit_repins_cost_and_surcharge_but_never_the_customer_price(api):
    """PRD §3.7: "The line's `unit_retail_cents` is emphatically **not** changed — the customer's price was frozen at order capture and re-sourcing is invisible to the customer's bill — while `unit_cost_cents` and `surcharge_cents` are re-pinned against the new offer and against the coverage row that matched for the new vendor."

    The fallback vendor is WHOLESALE at 1000 bps off a 19000-cent list, so the line's
    cost flips from 21249 to 17100 and it picks up the new coverage row's 500-cent
    surcharge, while the 24999-cent retail the customer was quoted stands still.

    Design: Difficulty/non_linear_state_machine/line_backorder_retransmit_cycle_returns_to_transmitted_on_fallback_vendor
    """
    state = _setup_backordered_line_with_wholesale_fallback(
        api, suffix="CYC", order_ref="ORD-CYCLE-C1"
    )
    before = refresh_line(api, state["line_id"])
    assert before["unit_cost_cents"] == 21249
    assert before["surcharge_cents"] == 0

    validate_success(api.retransmit_line(state["line_id"], _MM))

    line = refresh_line(api, state["line_id"])
    assert line["unit_cost_cents"] == 17100
    assert line["surcharge_cents"] == 500
    assert line["unit_retail_cents"] == 24999

    order = refresh_order(api, state["order_id"])
    assert order["total_retail_cents"] == 49998
    assert order["total_cost_cents"] == 34700
    assert order["margin_cents"] == 15298


def test_retransmit_hands_the_reservation_from_the_old_offer_to_the_new_one(api):
    """PRD §3.7: "The previously sourcing offer gives it up: its `reserved_units` falls by the line's `quantity` and its `lifetime_released_units` rises by the same amount, and its `available_units` is recomputed."

    Two units leave the offer that could not serve the line and land on the fallback
    offer, with both offers' lifetime counters telling the story afterwards.

    Design: Difficulty/non_linear_state_machine/line_backorder_retransmit_cycle_returns_to_transmitted_on_fallback_vendor
    """
    state = _setup_backordered_line_with_wholesale_fallback(
        api, suffix="CYD", order_ref="ORD-CYCLE-D1"
    )
    assert refresh_item(api, state["primary_item_id"])["reserved_units"] == 2
    assert refresh_item(api, state["fallback_item_id"])["reserved_units"] == 0

    validate_success(api.retransmit_line(state["line_id"], _MM))

    previous = refresh_item(api, state["primary_item_id"])
    assert previous["reserved_units"] == 0
    assert previous["lifetime_reserved_units"] == 2
    assert previous["lifetime_released_units"] == 2
    assert previous["available_units"] == 55
    assert_item_conservation(previous)

    selected = refresh_item(api, state["fallback_item_id"])
    assert selected["reserved_units"] == 2
    assert selected["lifetime_reserved_units"] == 2
    assert selected["lifetime_released_units"] == 0
    assert selected["available_units"] == 29
    assert_item_conservation(selected)


def test_retransmit_repins_the_deadlines_and_promise_against_the_new_vendor(api):
    """PRD §3.7: "Both `ack_deadline_at` and `ship_deadline_at` are re-pinned from the fresh `transmitted_at` against the new vendor's `ack_sla_hours` and `ship_sla_grace_hours` and the new offer's `lead_time_days`, and `line_promise_date` is re-derived under the RECOMPUTED variant."

    Re-sourced at 2026-08-03T10:00:00Z onto a five-day-lead offer whose vendor grants 24
    acknowledgment hours and 12 grace hours, the line's deadlines move to 2026-08-04T10:00:00Z
    and 2026-08-08T22:00:00Z, and the promise becomes 2026-08-10 on two transit days with
    no padding.

    Design: Difficulty/non_linear_state_machine/line_backorder_retransmit_cycle_returns_to_transmitted_on_fallback_vendor
    """
    state = _setup_backordered_line_with_wholesale_fallback(
        api, suffix="CYE", order_ref="ORD-CYCLE-E1"
    )

    validate_success(api.retransmit_line(state["line_id"], _MM))

    line = refresh_line(api, state["line_id"])
    assert line["transmitted_at"].startswith("2026-08-03T10:00:00")
    assert line["ack_deadline_at"].startswith("2026-08-04T10:00:00")
    assert line["ship_deadline_at"].startswith("2026-08-08T22:00:00")
    assert line["line_promise_date"] == "2026-08-10"

    order = refresh_order(api, state["order_id"])
    assert order["recomputed_promise_date"] == "2026-08-10"
    assert order["promise_variant_in_effect"] == "RECOMPUTED"


# ─── Two independent status axes on one order ─────────


def test_shipment_moves_only_the_fulfillment_axis_of_a_two_line_order(api):
    """PRD §3.6: "Otherwise, if at least one line has shipped and at least one line is still open, it is `PARTIALLY_SHIPPED`."

    With one of two lines shipped the fulfillment axis reads PARTIALLY_SHIPPED, while
    the financial axis records only what a shipment triggers: a capture with nothing
    refunded yet.

    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_financial_axes_advance_independently
    """
    state = _setup_two_acknowledged_lines(api, suffix="PXA", order_ref="ORD-PARALLEL-A1")
    order_before = refresh_order(api, state["order_id"])
    assert order_before["fulfillment_status"] == "OPEN"
    assert order_before["financial_status"] == "PENDING"

    ship_confirm(api, state["first_line_id"], state["vendor_id"], 1)

    order = refresh_order(api, state["order_id"])
    assert order["fulfillment_status"] == "PARTIALLY_SHIPPED"
    assert order["financial_status"] == "CAPTURED"
    assert order["total_retail_cents"] == 49998
    assert order["refunded_cents"] == 0
    assert order["net_retail_cents"] == 49998


def test_return_authorization_moves_only_the_financial_axis(api):
    """PRD §3.6: "`CAPTURED → PARTIALLY_REFUNDED` fires when a return authorization leaves `refunded_cents` greater than 0 but still strictly below `total_retail_cents`."

    Authorizing a return of the one shipped unit refunds 24999 of the order's 49998
    cents, which moves the financial axis alone: the second line is still open, so the
    fulfillment axis stays exactly where the shipment left it.

    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_financial_axes_advance_independently
    """
    state = _setup_two_acknowledged_lines(api, suffix="PXB", order_ref="ORD-PARALLEL-B1")
    ship_confirm(api, state["first_line_id"], state["vendor_id"], 1)
    ra = open_return(api, state["first_line_id"], quantity_returned=1, reason_code="DEFECTIVE")

    validate_success(api.authorize_return(ra["id"], _CARE))

    order = refresh_order(api, state["order_id"])
    assert order["financial_status"] == "PARTIALLY_REFUNDED"
    assert order["fulfillment_status"] == "PARTIALLY_SHIPPED"
    assert order["refunded_cents"] == 24999
    assert order["net_retail_cents"] == 24999


def test_second_shipment_completes_fulfillment_without_disturbing_the_refund_state(api):
    """PRD §3.6: "The financial axis lives on the same order row and moves on its own triggers; neither axis constrains the other, so an order may perfectly well be `SHIPPED` on one axis and `PARTIALLY_REFUNDED` on the other, or `OPEN` and `PENDING` while a line waits in `BACKORDERED`."

    Shipping the remaining line empties the open set, so the fulfillment axis reaches
    SHIPPED, while the partial refund already posted against the order stands untouched
    on the financial axis.

    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_financial_axes_advance_independently
    """
    state = _setup_two_acknowledged_lines(api, suffix="PXC", order_ref="ORD-PARALLEL-C1")
    ship_confirm(api, state["first_line_id"], state["vendor_id"], 1)
    ra = open_return(api, state["first_line_id"], quantity_returned=1, reason_code="DEFECTIVE")
    get_success_data(api.authorize_return(ra["id"], _CARE))

    ship_confirm(api, state["second_line_id"], state["vendor_id"], 1)

    order = refresh_order(api, state["order_id"])
    assert order["fulfillment_status"] == "SHIPPED"
    assert order["financial_status"] == "PARTIALLY_REFUNDED"
    assert order["refunded_cents"] == 24999
    assert order["net_retail_cents"] == 24999
    assert refresh_line(api, state["first_line_id"])["status"] == "SHIPPED"
    assert refresh_line(api, state["second_line_id"])["status"] == "SHIPPED"
