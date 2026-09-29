"""Corner cases of individual endpoint behaviour.

Offer amendment and the suppress/reactivate round trip, the logical-clock endpoint
seen through the orders it dates, the all-or-nothing transmission of a multi-line
order, and the linkage a return carries when it is opened, authorized and received.
"""

from test_helpers import (
    DEFAULT_CLOCK_UTC,
    TEST_USERS,
    ApiErrorId,
    add_blackout,
    create_active_item,
    create_active_vendor,
    create_draft_item,
    create_order_payload,
    create_return_payload,
    feed_inventory,
    open_return,
    order_line_input,
    order_lines_of,
    place_order,
    refresh_item,
    refresh_line,
    refresh_order,
    refresh_return,
    set_clock,
    setup_shipped_line,
    setup_vendor_with_active_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MM = TEST_USERS["merchandise_manager_headers"]
CARE = TEST_USERS["care_agent_headers"]


def test_item_patch_amends_a_draft_offer_and_rederives_unit_cost(api):
    """PRD §3.3: "A successful amendment re-derives `unit_cost_cents` and increments the offer's `version`."

    A partial amendment touches only the fields it names: retail drops to 19999 and
    lead time to six days, the commission-derived cost falls to 16999, the untouched
    defect window is preserved and the offer stays DRAFT at version two.

    Design: Corner/endpoints/corner_item_patch_amends_a_draft_offer_and_rederives_unit_cost
    """
    vendor = create_active_vendor(api, suffix="PATCH")
    item = create_draft_item(api, vendor["id"], sku="SKU-PATCH-1")
    assert item["version"] == 1
    assert item["unit_cost_cents"] == 21249

    amended = validate_success(
        api.update_item(
            item["id"], {"unit_retail_cents": 19999, "lead_time_days": 6}, MM
        )
    )
    assert amended["unit_retail_cents"] == 19999
    assert amended["lead_time_days"] == 6
    assert amended["unit_cost_cents"] == 16999
    assert amended["defect_window_days"] == 30
    assert amended["status"] == "DRAFT"
    assert amended["version"] == 2

    read_back = refresh_item(api, item["id"])
    assert read_back["unit_retail_cents"] == 19999
    assert read_back["unit_cost_cents"] == 16999
    assert read_back["version"] == 2


def test_item_suppress_and_reactivate_round_trip(api):
    """PRD §3.3: "A manager taking an `ACTIVE` offer off the endless aisle moves it `ACTIVE → SUPPRESSED`, stamps `suppression_reason` as `MANUAL`, forces `available_units` to 0 and increments the offer's `version`."

    Suppression only masks orderability: the trusted on-hand figure behind the offer
    is untouched at sixty units, so reactivating the offer restores the same
    fifty-five available units and clears the suppression reason.

    Design: Corner/endpoints/corner_item_suppress_and_reactivate_round_trip
    """
    state = setup_vendor_with_active_offer(api, suffix="SUPP")
    assert state["item"]["available_units"] == 55
    assert state["item"]["version"] == 3

    suppressed = validate_success(api.suppress_item(state["item_id"], MM))
    assert suppressed["status"] == "SUPPRESSED"
    assert suppressed["suppression_reason"] == "MANUAL"
    assert suppressed["available_units"] == 0
    assert suppressed["version"] == 4

    masked = refresh_item(api, state["item_id"])
    assert masked["effective_on_hand_units"] == 60
    assert masked["available_units"] == 0

    reactivated = validate_success(api.activate_item(state["item_id"], MM))
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["suppression_reason"] is None
    assert reactivated["available_units"] == 55
    assert reactivated["version"] == 5


def test_clock_endpoint_advances_the_logical_clock_from_its_declared_default(api):
    """PRD §2.4: "Before any administrator has moved it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

    An order placed before the clock is ever moved is dated at the declared default
    and promised for 2026-08-10; after the clock is advanced to 2026-08-03T10:00:00Z
    the next order is dated there and promised for 2026-08-12.

    Design: Corner/endpoints/corner_clock_endpoint_advances_the_logical_clock_from_its_declared_default
    """
    vendor = create_active_vendor(api, suffix="CLK")
    item = create_active_item(api, vendor["id"], sku="SKU-CLOCK-1")
    feed_inventory(
        api,
        item["id"],
        vendor["id"],
        on_hand_units=60,
        effective_from=DEFAULT_CLOCK_UTC,
        feed_sequence=1,
    )

    at_default = validate_success(
        api.create_order(
            create_order_payload(
                "ORD-CLOCK-1",
                [order_line_input(item["id"], 1)],
                customer_zone_code="US-WEST",
            ),
            CARE,
        ),
        201,
    )
    assert at_default["placed_at"] == "2026-08-01T00:00:00.000Z"
    assert at_default["quoted_promise_date"] == "2026-08-10"

    set_clock(api, "2026-08-03T10:00:00Z")
    feed_inventory(
        api,
        item["id"],
        vendor["id"],
        on_hand_units=60,
        effective_from="2026-08-03T09:00:00Z",
        feed_sequence=2,
    )

    after_move = validate_success(
        api.create_order(
            create_order_payload(
                "ORD-CLOCK-2",
                [order_line_input(item["id"], 1)],
                customer_zone_code="US-WEST",
            ),
            CARE,
        ),
        201,
    )
    assert after_move["placed_at"] == "2026-08-03T10:00:00.000Z"
    assert after_move["quoted_promise_date"] == "2026-08-12"


def test_order_transmit_is_all_or_nothing_across_its_lines(api):
    """PRD §2.6: "No row is mutated when a request fails."

    An order spanning two vendors is transmitted as one unit: a blackout opened
    against the second vendor after capture defeats the whole call, so even the
    first line — whose own vendor is perfectly available — stays PENDING_TRANSMIT
    with no transmission stamp.

    Design: Corner/endpoints/corner_order_transmit_is_all_or_nothing_across_its_lines
    """
    set_clock(api, DEFAULT_CLOCK_UTC)
    open_vendor = create_active_vendor(api, suffix="BKA")
    open_item = create_active_item(api, open_vendor["id"], sku="SKU-BULK-A")
    blacked_vendor = create_active_vendor(
        api,
        suffix="BKB",
        cost_model="WHOLESALE",
        wholesale_discount_bps=1000,
        inventory_refresh_cadence_minutes=120,
        safety_buffer_units=2,
        oversell_grace_units=3,
        default_lead_time_days=5,
    )
    blacked_item = create_active_item(
        api,
        blacked_vendor["id"],
        sku="SKU-BULK-B",
        unit_wholesale_cost_cents=19000,
        lead_time_days=5,
        reverse_freight_owner="VENDOR",
        restock_policy="RETAILER_RESTOCK",
    )

    set_clock(api, "2026-08-03T09:00:00Z")
    feed_inventory(
        api,
        open_item["id"],
        open_vendor["id"],
        on_hand_units=60,
        effective_from="2026-08-03T09:00:00Z",
    )
    feed_inventory(
        api,
        blacked_item["id"],
        blacked_vendor["id"],
        on_hand_units=30,
        effective_from="2026-08-03T09:00:00Z",
    )
    set_clock(api, "2026-08-03T10:00:00Z")

    order = place_order(
        api,
        open_item["id"],
        quantity=1,
        order_ref="ORD-BULK-1",
        extra_lines=[order_line_input(blacked_item["id"], 1)],
    )
    lines = order_lines_of(api, order["id"])
    assert len(lines) == 2

    add_blackout(
        api,
        blacked_vendor["id"],
        start_date="2026-08-03",
        end_date="2026-08-04",
        reason="SYSTEM_CUTOVER",
        reopen_buffer_days=0,
    )

    blocked = api.transmit_order(order["id"], MM)
    validate_error(blocked, ApiErrorId.ERR_VENDOR_BLACKOUT.value)

    for line in lines:
        held = refresh_line(api, line["id"])
        assert held["status"] == "PENDING_TRANSMIT"
        assert held["transmitted_at"] is None

    untouched = refresh_order(api, order["id"])
    assert untouched["fulfillment_status"] == "OPEN"
    assert untouched["recomputed_promise_date"] is None
    assert untouched["promise_variant_in_effect"] == "QUOTED"


def test_return_create_links_its_line_and_authorize_links_the_routed_vendor(api):
    """PRD §3.8: "If any candidate is eligible, `routing_destination` becomes `VENDOR`, `routed_vendor_id` becomes the winning candidate's vendor, and `restock_disposition` is copied from that candidate's `restock_policy` — which may be `VENDOR_RESTOCK`, `RETAILER_RESTOCK` or `DESTROY`."

    A freshly opened return carries only its line; the routing fields are filled in at
    authorization, which names the sourcing vendor and makes the return discoverable
    by that vendor id.

    Design: Corner/endpoints/corner_return_create_links_its_line_and_authorize_links_the_routed_vendor
    """
    state = setup_shipped_line(
        api,
        quantity=1,
        order_ref="ORD-LINK-1",
        suffix="LINK",
        ship_at="2026-08-04T10:00:00Z",
    )

    opened = validate_success(
        api.create_return(
            create_return_payload(
                state["line_id"], quantity_returned=1, reason_code="NOT_AS_DESCRIBED"
            ),
            CARE,
        ),
        201,
    )
    assert opened["line_id"] == state["line_id"]
    assert opened["status"] == "REQUESTED"
    assert opened["routed_vendor_id"] is None

    authorized = validate_success(api.authorize_return(opened["id"], CARE))
    assert authorized["routing_destination"] == "VENDOR"
    assert authorized["routed_vendor_id"] == state["vendor_id"]
    assert authorized["restock_disposition"] == "VENDOR_RESTOCK"
    assert authorized["restocking_fee_cents"] == 0
    assert authorized["vendor_chargeback_cents"] == 22544

    rows, meta = validate_paginated(
        api.list_returns(ADMIN, params={"routed_vendor_id": state["vendor_id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [opened["id"]]


def test_return_receive_before_authorization_is_rejected(api):
    """PRD §2.6: "The return's `status` permits the requested transition: authorization from `REQUESTED`, receipt from `AUTHORIZED`, rejection from either `REQUESTED` or `AUTHORIZED`."

    Receipt is only reachable from AUTHORIZED, so receiving a return that is still
    merely REQUESTED is refused and neither the return's routing and restock fields
    nor the order's refunded total move.

    Design: Corner/endpoints/corner_return_receive_before_authorization_is_rejected
    """
    state = setup_shipped_line(
        api,
        quantity=1,
        order_ref="ORD-COND-1",
        suffix="COND",
        ship_at="2026-08-04T10:00:00Z",
    )
    opened = open_return(
        api, state["line_id"], quantity_returned=1, reason_code="LATE_DELIVERY"
    )
    assert opened["status"] == "REQUESTED"

    premature = api.receive_return(opened["id"], ADMIN, {"restocked_units": 1})
    validate_error(premature, ApiErrorId.ERR_RETURN_INVALID_STATE.value)

    held = refresh_return(api, opened["id"])
    assert held["status"] == "REQUESTED"
    assert held["routing_destination"] is None
    assert held["restocked_units"] == 0

    order = refresh_order(api, state["order_id"])
    assert order["refunded_cents"] == 0
