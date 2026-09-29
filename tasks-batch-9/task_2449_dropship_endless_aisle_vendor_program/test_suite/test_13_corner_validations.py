"""Corner cases of the validation rules that guard writes.

Uniqueness of vendor codes and order references, the availability and reservation
limits on order placement, geographic coverage, the return defect window and the
cumulative return-quantity ceiling, cost-model field agreement on an offer, and the
precedence of the feed-freshness check over the availability check.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    acknowledge_payload,
    create_active_vendor,
    create_item_payload,
    create_order_payload,
    create_return_payload,
    create_vendor_payload,
    make_vendor_user_headers,
    order_line_input,
    place_and_transmit_order,
    place_order,
    refresh_item,
    refresh_line,
    refresh_vendor,
    set_clock,
    setup_authorized_return,
    setup_vendor_with_active_offer,
    ship_confirm,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MM = TEST_USERS["merchandise_manager_headers"]
CARE = TEST_USERS["care_agent_headers"]


def test_duplicate_vendor_code_is_rejected(api):
    """PRD §3.1: "A `PlatformAdmin` or a `VendorOpsAnalyst` registers a prospective partner with its `vendor_code` — the trading-partner code that will appear on every catalog, inventory and order message, between 1 and 32 characters of uppercase alphanumerics and hyphens, and globally unique across the platform, with a collision answered by `ERR_DUPLICATE_VENDOR_CODE` — together with its `legal_name` of between 1 and 200 characters and its `cost_model`."

    The code is unique across every vendor row whatever its onboarding status, so a
    second registration under a code held by a merely DRAFT vendor collides, and the
    first vendor's own fields are left exactly as they were.

    Design: Corner/validations/corner_duplicate_vendor_code_is_rejected
    """
    first = validate_success(
        api.create_vendor(
            create_vendor_payload(
                vendor_code="V-DUP",
                legal_name="First Claimant LLC",
                cost_model="COMMISSION",
                commission_rate_bps=1500,
            ),
            ADMIN,
        ),
        201,
    )
    assert first["onboarding_status"] == "DRAFT"

    clash = api.create_vendor(
        create_vendor_payload(
            vendor_code="V-DUP",
            legal_name="Second Claimant LLC",
            cost_model="WHOLESALE",
            wholesale_discount_bps=1000,
        ),
        ADMIN,
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_VENDOR_CODE.value)

    held = refresh_vendor(api, first["id"])
    assert held["legal_name"] == "First Claimant LLC"
    assert held["cost_model"] == "COMMISSION"


def test_duplicate_order_ref_is_rejected(api):
    """PRD §3.5: "A `CareAgent` places a customer order by supplying an `order_ref`, the retailer's own order reference of 1 to 40 characters and globally unique across orders — a repeat is refused with `ERR_DUPLICATE_ORDER_REF` — a `customer_zone_code` of 1 to 16 characters of uppercase alphanumerics and hyphens describing the destination zone of the shipping address, and a `lines` array."

    The refused repeat reserves nothing: the offer still holds only the single unit
    the accepted order took, and only one order line exists against it.

    Design: Corner/validations/corner_duplicate_order_ref_is_rejected
    """
    state = setup_vendor_with_active_offer(api, suffix="DUPREF")
    place_order(api, state["item_id"], quantity=1, order_ref="ORD-UNIQ-1")

    repeat = api.create_order(
        create_order_payload(
            "ORD-UNIQ-1", [order_line_input(state["item_id"], 1)], customer_zone_code="US-WEST"
        ),
        CARE,
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_ORDER_REF.value)

    item = refresh_item(api, state["item_id"])
    assert item["reserved_units"] == 1
    assert item["available_units"] == 54

    rows, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"item_id": state["item_id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_return_quantity_beyond_shipped_units_is_rejected(api):
    """PRD §3.8: "And `quantity_returned` added to the line's existing `returned_units` must not exceed the line's shipped `quantity`, since a customer cannot return more than arrived; the overrun is refused with `ERR_RETURN_QUANTITY_EXCEEDS_SHIPPED`."

    The ceiling is cumulative rather than per request: with one of two shipped units
    already returned, a second request for two units overruns and is refused, leaving
    the line's returned_units untouched at one.

    Design: Corner/validations/corner_return_quantity_beyond_shipped_units_is_rejected
    """
    state = setup_authorized_return(
        api,
        quantity=2,
        quantity_returned=1,
        reason_code="DEFECTIVE",
        order_ref="ORD-QTY-1",
        suffix="RQTY",
        ship_at="2026-08-04T10:00:00Z",
    )
    assert refresh_line(api, state["line_id"])["returned_units"] == 1

    overrun = api.create_return(
        create_return_payload(
            state["line_id"], quantity_returned=2, reason_code="DEFECTIVE"
        ),
        CARE,
    )
    validate_error(overrun, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDS_SHIPPED.value)

    assert refresh_line(api, state["line_id"])["returned_units"] == 1
    rows, meta = validate_paginated(
        api.list_returns(ADMIN, params={"line_id": state["line_id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_order_for_exactly_the_available_units_succeeds(api):
    """PRD §3.5: "And the requested `quantity` must be at most the offer's `available_units`: a request for exactly `available_units` units is accepted, and one unit more is refused with `ERR_INSUFFICIENT_AVAILABILITY`."

    Ten on hand less a five-unit safety buffer leaves exactly five available, and a
    request for all five is the satisfied edge of the rule: it is accepted and drains
    availability to zero.

    Design: Corner/validations/corner_order_for_exactly_the_available_units_succeeds
    """
    state = setup_vendor_with_active_offer(api, suffix="EXACT", on_hand_units=10)
    assert state["item"]["available_units"] == 5

    order = validate_success(
        api.create_order(
            create_order_payload(
                "ORD-EXACT-1",
                [order_line_input(state["item_id"], 5)],
                customer_zone_code="US-WEST",
            ),
            CARE,
        ),
        201,
    )
    assert order["fulfillment_status"] == "OPEN"
    assert order["financial_status"] == "PENDING"
    assert order["total_retail_cents"] == 124995

    item = refresh_item(api, state["item_id"])
    assert item["reserved_units"] == 5
    assert item["available_units"] == 0


def test_order_line_zone_outside_vendor_coverage_is_rejected(api):
    """PRD §3.5: "An `ACTIVE` serviceability rule of the offer's vendor must match the order's `customer_zone_code` together with the offer's `ship_method`, or the request fails with `ERR_ZONE_NOT_SERVICEABLE`."

    The vendor's only live coverage row serves US-WEST, so a US-EAST order is refused
    and reserves nothing; the same offer ordered into US-WEST is accepted, which shows
    the offer itself was never the obstacle.

    Design: Corner/validations/corner_order_line_zone_outside_vendor_coverage_is_rejected
    """
    state = setup_vendor_with_active_offer(api, suffix="ZONE")

    uncovered = api.create_order(
        create_order_payload(
            "ORD-ZONE-1",
            [order_line_input(state["item_id"], 1)],
            customer_zone_code="US-EAST",
        ),
        CARE,
    )
    validate_error(uncovered, ApiErrorId.ERR_ZONE_NOT_SERVICEABLE.value)
    assert refresh_item(api, state["item_id"])["reserved_units"] == 0

    covered = validate_success(
        api.create_order(
            create_order_payload(
                "ORD-ZONE-2",
                [order_line_input(state["item_id"], 1)],
                customer_zone_code="US-WEST",
            ),
            CARE,
        ),
        201,
    )
    assert covered["customer_zone_code"] == "US-WEST"
    assert refresh_item(api, state["item_id"])["reserved_units"] == 1


def test_return_requested_after_the_defect_window_closes_is_rejected(api):
    """PRD §3.8: "The request must fall inside the defect window: the current logical date must be on or before the line's ship date advanced by the sourcing offer's `defect_window_days`, with the final day of the window still inside it, and a later request is refused with `ERR_OUTSIDE_DEFECT_WINDOW`."

    Two identical shipped lines dated 2026-08-04 under a thirty-day window: a request
    on the last day inside the window, 2026-09-03, is accepted, and the very next day
    is refused with nothing recorded against the second line.

    Design: Corner/validations/corner_return_requested_after_the_defect_window_closes_is_rejected
    """
    state = setup_vendor_with_active_offer(api, suffix="WIN")
    placed = place_and_transmit_order(
        api,
        state["item_id"],
        quantity=1,
        order_ref="ORD-WIN-1",
        extra_lines=[order_line_input(state["item_id"], 1)],
    )
    first_line, second_line = placed["lines"][0], placed["lines"][1]
    vendor_headers = make_vendor_user_headers(state["vendor_id"])
    for line in (first_line, second_line):
        validate_success(
            api.acknowledge_line(line["id"], acknowledge_payload("ACCEPTED"), vendor_headers)
        )
    set_clock(api, "2026-08-04T10:00:00Z")
    ship_confirm(
        api, first_line["id"], state["vendor_id"], 1, tracking_number="1Z-WN-001"
    )
    ship_confirm(
        api, second_line["id"], state["vendor_id"], 1, tracking_number="1Z-WN-002"
    )

    set_clock(api, "2026-09-03T23:00:00Z")
    last_day = validate_success(
        api.create_return(
            create_return_payload(
                first_line["id"], quantity_returned=1, reason_code="DEFECTIVE"
            ),
            CARE,
        ),
        201,
    )
    assert last_day["status"] == "REQUESTED"

    set_clock(api, "2026-09-04T00:00:00Z")
    too_late = api.create_return(
        create_return_payload(
            second_line["id"], quantity_returned=1, reason_code="DEFECTIVE"
        ),
        CARE,
    )
    validate_error(too_late, ApiErrorId.ERR_OUTSIDE_DEFECT_WINDOW.value)

    assert refresh_line(api, second_line["id"])["returned_units"] == 0
    rows, meta = validate_paginated(
        api.list_returns(ADMIN, params={"line_id": second_line["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_cumulative_reservations_across_orders_exhaust_availability(api):
    """PRD §3.4: "For an `ACTIVE` offer it is the trusted on-hand figure reduced by the vendor's `safety_buffer_units`, increased by the vendor's `oversell_grace_units`, and reduced by the offer's `reserved_units`, with the whole result floored at 0 — the floor is applied once, after every other term."

    Each of two three-unit requests would fit the original five available units, but
    the first order's reservation is subtracted before the second is judged, so the
    second is refused and adds no reservation of its own.

    Design: Corner/validations/corner_cumulative_reservations_across_orders_exhaust_availability
    """
    state = setup_vendor_with_active_offer(api, suffix="AGGR", on_hand_units=10)
    assert state["item"]["available_units"] == 5

    validate_success(
        api.create_order(
            create_order_payload(
                "ORD-AGGR-1",
                [order_line_input(state["item_id"], 3)],
                customer_zone_code="US-WEST",
            ),
            CARE,
        ),
        201,
    )
    item = refresh_item(api, state["item_id"])
    assert item["reserved_units"] == 3
    assert item["available_units"] == 2

    second = api.create_order(
        create_order_payload(
            "ORD-AGGR-2",
            [order_line_input(state["item_id"], 3)],
            customer_zone_code="US-WEST",
        ),
        CARE,
    )
    validate_error(second, ApiErrorId.ERR_INSUFFICIENT_AVAILABILITY.value)

    item = refresh_item(api, state["item_id"])
    assert item["reserved_units"] == 3
    assert item["available_units"] == 2
    rows, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"item_id": state["item_id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_wholesale_vendor_offer_without_a_wholesale_cost_is_rejected(api):
    """PRD §2.7: "The same discipline propagates to the offer level: an offer belonging to a `WHOLESALE` vendor must carry `unit_wholesale_cost_cents` of at least 1, both when it is created and when it is activated, whereas an offer belonging to a `COMMISSION` vendor must not carry `unit_wholesale_cost_cents` at all and is priced from `unit_retail_cents` alone."

    The very same body fails on a WHOLESALE vendor and succeeds on a COMMISSION one,
    where cost is derived from retail alone: 24999 at 1500 basis points retained
    yields 21249 cents per unit.

    Design: Corner/validations/corner_wholesale_vendor_offer_without_a_wholesale_cost_is_rejected
    """
    wholesale = create_active_vendor(
        api, suffix="WHS", cost_model="WHOLESALE", wholesale_discount_bps=1000
    )
    commission = create_active_vendor(api, suffix="CMS")

    missing_cost = api.create_item(
        create_item_payload(
            wholesale["id"],
            sku="SKU-COST-1",
            lead_time_days=5,
            reverse_freight_owner=None,
            restock_policy=None,
            defect_window_days=None,
        ),
        MM,
    )
    validate_error(missing_cost, ApiErrorId.ERR_COST_MODEL_FIELD_MISMATCH.value)
    rows, meta = validate_paginated(
        api.list_items(ADMIN, params={"vendor_id": wholesale["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    accepted = validate_success(
        api.create_item(
            create_item_payload(
                commission["id"],
                sku="SKU-COST-1",
                lead_time_days=3,
                reverse_freight_owner=None,
                restock_policy=None,
                defect_window_days=None,
            ),
            MM,
        ),
        201,
    )
    assert accepted["unit_cost_cents"] == 21249
    assert accepted.get("unit_wholesale_cost_cents") is None


def test_stale_feed_check_runs_before_the_availability_check(api):
    """PRD §2.6: "Because feed freshness at rank 37 precedes availability sufficiency at rank 38, an order line against an offer whose feed has gone stale surfaces as `ERR_INVENTORY_STALE` and never as `ERR_INSUFFICIENT_AVAILABILITY`, even though a stale offer's `available_units` is necessarily zero."

    A sixty-minute cadence trusts the feed for 180 minutes; at 300 minutes of age the
    offer reports itself stale with zero trusted on hand, and the order is refused on
    freshness rather than on the availability that staleness caused.

    Design: Corner/validations/corner_stale_feed_check_runs_before_the_availability_check
    """
    state = setup_vendor_with_active_offer(
        api, suffix="STALE", now_at="2026-08-03T14:00:00Z"
    )

    order = api.create_order(
        create_order_payload(
            "ORD-CASCV-1",
            [order_line_input(state["item_id"], 1)],
            customer_zone_code="US-WEST",
        ),
        CARE,
    )
    validate_error(order, ApiErrorId.ERR_INVENTORY_STALE.value)

    item = refresh_item(api, state["item_id"])
    assert item["inventory_is_stale"] is True
    assert item["effective_on_hand_units"] == 0
    assert item["available_units"] == 0
    assert item["reserved_units"] == 0
