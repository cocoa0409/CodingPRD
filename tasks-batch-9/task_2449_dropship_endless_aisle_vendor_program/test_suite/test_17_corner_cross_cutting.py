"""Cross-cutting behaviour: the two optimistic-concurrency guards on offers and
vendors, and the platform's immediate-consistency contract in which every derived
money, availability and rollup figure is current the instant a write returns."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_payload,
    assert_item_conservation,
    assert_vendor_ledger_conservation,
    create_active_vendor,
    create_inventory_snapshot_payload,
    create_order_payload,
    create_seeded_scorecard,
    get_success_data,
    make_merchandise_manager_headers,
    make_vendor_user_headers,
    order_line_input,
    order_lines_of,
    place_and_transmit_order,
    refresh_item,
    refresh_line,
    refresh_order,
    refresh_vendor,
    reset_clock,
    set_clock,
    setup_vendor_with_active_offer,
    ship_confirm_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CARE = TEST_USERS["care_agent_headers"]


def _snapshot_rows(api, item_id):
    """Every feed message of one offer, read back through the list endpoint."""
    rows, _meta = validate_paginated(
        api.list_inventory_snapshots(item_id, ADMIN, params={"limit": 100})
    )
    return rows


def test_replayed_expected_item_version_on_a_feed_post_is_refused(api):
    """PRD §2.9: "If the value does not equal the offer's current `version`, the request is rejected with `ERR_STALE_ITEM_VERSION` and HTTP 412."

    The first feed message consumes the offer version the client observed and moves
    the offer on. Replaying that same now-outdated `expected_item_version` is refused
    with the 412, writes nothing at all, and re-reading the version makes the retry
    land.

    Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_item_version_on_a_feed_refresh_is_refused
    """
    base = setup_vendor_with_active_offer(
        api, suffix="OCCI", feed=False, now_at="2026-08-05T09:00:00Z"
    )
    item_id = base["item_id"]
    vendor_headers = make_vendor_user_headers(base["vendor_id"])
    observed_version = base["item"]["version"]

    first = validate_success(
        api.create_inventory_snapshot(
            item_id,
            create_inventory_snapshot_payload(
                expected_item_version=observed_version,
                on_hand_units=60,
                effective_from="2026-08-03T00:00:00Z",
                feed_sequence=1,
                effective_to="2026-08-04T00:00:00Z",
            ),
            vendor_headers,
        ),
        201,
    )
    assert first["on_hand_units"] == 60
    version_after_first = refresh_item(api, item_id)["version"]
    assert version_after_first > observed_version, (
        "posting a feed message must move the offer's version on"
    )
    assert len(_snapshot_rows(api, item_id)) == 1

    # The second post carries the pre-supersede version the client last saw. Its
    # window is disjoint from the first, so overlap cannot explain the refusal.
    stale = api.create_inventory_snapshot(
        item_id,
        create_inventory_snapshot_payload(
            expected_item_version=observed_version,
            on_hand_units=12,
            effective_from="2026-08-05T00:00:00Z",
            feed_sequence=2,
        ),
        vendor_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ITEM_VERSION.value)

    assert refresh_item(api, item_id)["version"] == version_after_first, (
        "a refused feed post must not mutate the offer"
    )
    assert len(_snapshot_rows(api, item_id)) == 1, (
        "a refused feed post must not create a feed message row"
    )

    fresh_version = refresh_item(api, item_id)["version"]
    retried = validate_success(
        api.create_inventory_snapshot(
            item_id,
            create_inventory_snapshot_payload(
                expected_item_version=fresh_version,
                on_hand_units=12,
                effective_from="2026-08-05T00:00:00Z",
                feed_sequence=2,
            ),
            vendor_headers,
        ),
        201,
    )
    assert retried["on_hand_units"] == 12
    assert len(_snapshot_rows(api, item_id)) == 2

    item = refresh_item(api, item_id)
    assert item["inventory_is_stale"] is False
    assert item["effective_on_hand_units"] == 12, (
        "the governing snapshot for the current clock reports 12 units on hand"
    )


def test_stale_expected_vendor_version_on_scorecard_publish_is_refused(api):
    """PRD §2.9: "A value that does not equal that vendor's current `version` is rejected with `ERR_STALE_VENDOR_VERSION` and HTTP 412."

    The vendor row moves for reasons that have nothing to do with scorecards: a
    suspension and a reinstatement both bump it while the draft sits untouched.
    Publishing with the version captured before those moves is refused, and the
    vendor keeps its old tier and padding until the corrected publish lands.

    Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_vendor_version_on_scorecard_publish_is_refused
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="OCCV")
    vendor_id = vendor["id"]
    stale_version = vendor["version"]

    set_clock(api, "2026-10-01T00:00:00Z")
    scorecard = create_seeded_scorecard(
        api,
        vendor_id,
        20.0,
        9500,
        300,
        400,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    # 0.5*9500 + 0.3*(10000-300) + 0.2*(10000-400) = 9580 bps -> 95.80 -> PLATINUM.
    assert scorecard["status"] == "DRAFT"
    assert abs(float(scorecard["composite_score"]) - 95.80) < 0.005
    assert scorecard["tier"] == "PLATINUM"
    assert scorecard["promise_padding_days"] == 0

    suspender = make_merchandise_manager_headers("mm-suspender-OCCV")
    get_success_data(api.suspend_vendor(vendor_id, suspender))
    fresh_version = get_success_data(api.reinstate_vendor(vendor_id, suspender))[
        "version"
    ]
    assert fresh_version == stale_version + 2, (
        "suspension and reinstatement each increment the vendor's version by 1"
    )

    refused = api.publish_scorecard(scorecard["id"], stale_version, ADMIN)
    validate_error(refused, ApiErrorId.ERR_STALE_VENDOR_VERSION.value)

    still_draft = get_success_data(api.list_scorecards(vendor_id, ADMIN))
    assert still_draft[0]["status"] == "DRAFT"
    assert still_draft[0]["published_at"] is None
    after_refusal = refresh_vendor(api, vendor_id)
    assert after_refusal["performance_tier"] == "UNRATED"
    assert after_refusal["promise_padding_days"] == 2
    assert after_refusal["version"] == fresh_version, (
        "a refused publish must not mutate the vendor"
    )

    published = validate_success(
        api.publish_scorecard(scorecard["id"], fresh_version, ADMIN)
    )
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None

    final_vendor = refresh_vendor(api, vendor_id)
    assert final_vendor["performance_tier"] == "PLATINUM"
    assert final_vendor["promise_padding_days"] == 0
    assert final_vendor["version"] == fresh_version + 1
    assert final_vendor["onboarding_status"] == "ACTIVE"


def test_order_placement_response_already_carries_money_and_promise(api):
    """PRD §3.5: "Because an untransmitted line's cost and surcharge are both 0 — no vendor and no coverage row have been pinned yet — a freshly placed order reports `total_cost_cents` of 0 and `margin_cents` equal to its `total_retail_cents`, and only transmission turns that into a real margin."

    Placement is immediately consistent: the creation response already reports the
    rolled-up money view and the quoted promise, a re-read of the order returns
    exactly the same values, and the reservation is already visible on the offer.

    Design: Corner/consistency_model/corner_every_derived_field_is_current_in_the_mutating_response
    """
    base = setup_vendor_with_active_offer(api, suffix="IMM1")
    item_id = base["item_id"]

    created = validate_success(
        api.create_order(
            create_order_payload(
                "ORD-IMM-1",
                [order_line_input(item_id, 2)],
                customer_zone_code="US-WEST",
            ),
            CARE,
        ),
        201,
    )

    # 2 x 24999 retail; no cost is pinned until transmission.
    assert created["total_retail_cents"] == 49998
    assert created["total_cost_cents"] == 0
    assert created["margin_cents"] == 49998
    assert created["net_retail_cents"] == 49998
    assert created["refunded_cents"] == 0
    assert created["retailer_absorbed_cents"] == 0
    assert created["fulfillment_status"] == "OPEN"
    assert created["financial_status"] == "PENDING"
    assert created["promise_variant_in_effect"] == "QUOTED"
    assert created["recomputed_promise_date"] is None
    # Placed 2026-08-03T10:00Z, hour 10 is before the cutoff hour 18, so no
    # rollover; 3 lead days + 4 transit days + 2 padding days land on 2026-08-12.
    assert created["quoted_promise_date"] == "2026-08-12"

    reread = refresh_order(api, created["id"])
    for field in (
        "total_retail_cents",
        "total_cost_cents",
        "margin_cents",
        "net_retail_cents",
        "fulfillment_status",
        "financial_status",
        "promise_variant_in_effect",
        "quoted_promise_date",
        "recomputed_promise_date",
    ):
        assert reread[field] == created[field], (
            f"{field} must read back exactly as the creation response reported it"
        )

    item = refresh_item(api, item_id)
    assert item["reserved_units"] == 2
    assert item["lifetime_reserved_units"] == 2
    # 60 on hand less the 5-unit safety buffer less the 2 reserved units.
    assert item["available_units"] == 53
    assert_item_conservation(item)

    line = order_lines_of(api, created["id"])[0]
    assert line["status"] == "PENDING_TRANSMIT"
    assert line["unit_retail_cents"] == 24999
    assert line["unit_cost_cents"] == 0
    assert line["surcharge_cents"] == 0


def test_shipment_confirmation_effects_are_visible_with_no_reread_delay(api):
    """PRD §3.6: "On the vendor's ledger, `settlement_balance_cents` grows by the line's `unit_cost_cents` multiplied by its `quantity` plus the line's `surcharge_cents` — the money the retailer now owes for goods that have physically moved."

    The shipment response already carries its own derived figures, and the order
    rollup, the vendor ledger and the offer's availability view are all current on
    the very next read — no settling time is ever needed.

    Design: Corner/consistency_model/corner_every_derived_field_is_current_in_the_mutating_response
    """
    base = setup_vendor_with_active_offer(api, suffix="IMM2")
    item_id = base["item_id"]
    vendor_id = base["vendor_id"]

    placed = place_and_transmit_order(
        api, item_id, quantity=2, order_ref="ORD-IMM-2"
    )
    order_id = placed["order_id"]
    line = placed["lines"][0]

    # Transmission pins cost from the offer: 24999 * 8500 / 10000 = 21249 per unit.
    assert line["status"] == "TRANSMITTED"
    assert line["unit_cost_cents"] == 21249
    assert line["surcharge_cents"] == 0
    assert placed["order"]["total_cost_cents"] == 42498
    assert placed["order"]["margin_cents"] == 7500
    assert placed["order"]["promise_variant_in_effect"] == "RECOMPUTED"

    promise = validate_success(api.get_order_promise(order_id, ADMIN))
    assert promise["quoted_promise_date"] == "2026-08-12"
    # RECOMPUTED drops the padding entirely: 3 lead days + 4 transit days from the
    # 2026-08-03T10:00Z transmission.
    assert promise["recomputed_promise_date"] == "2026-08-10"
    assert promise["promise_variant_in_effect"] == "RECOMPUTED"
    assert promise["promise_divergence_days"] == 2

    get_success_data(
        api.acknowledge_line(
            line["id"], acknowledge_payload("ACCEPTED"), make_vendor_user_headers(vendor_id)
        )
    )

    set_clock(api, "2026-08-04T10:00:00Z")
    shipment = validate_success(
        api.ship_confirm_line(
            line["id"], ship_confirm_payload(2), make_vendor_user_headers(vendor_id)
        ),
        201,
    )
    assert shipment["line_id"] == line["id"]
    assert shipment["shipped_units"] == 2
    assert shipment["package_count"] == 1
    assert shipment["ship_date"] == "2026-08-04"
    # Transmitted 2026-08-03T10:00Z, confirmed exactly 24 hours later, well inside
    # the 3-day lead plus 12-hour grace deadline.
    assert abs(float(shipment["ship_hours"]) - 24.00) < 0.005
    assert shipment["on_time"] is True

    order = refresh_order(api, order_id)
    assert order["fulfillment_status"] == "SHIPPED"
    assert order["financial_status"] == "CAPTURED"
    assert order["net_retail_cents"] == 49998
    assert order["refunded_cents"] == 0

    vendor = refresh_vendor(api, vendor_id)
    assert vendor["settlement_balance_cents"] == 42498
    assert vendor["chargeback_balance_cents"] == 0

    shipped_line = refresh_line(api, line["id"])
    assert shipped_line["status"] == "SHIPPED"
    assert shipped_line["ship_sla_breached"] is False
    assert_vendor_ledger_conservation(vendor, [shipped_line])

    item = refresh_item(api, item_id)
    assert item["reserved_units"] == 0
    assert item["lifetime_shipped_units"] == 2
    assert_item_conservation(item)
    # The feed was stamped at 2026-08-03T09:00Z and the cadence is 60 minutes, so a
    # clock at 2026-08-04T10:00Z is far past the 180-minute staleness limit.
    assert item["inventory_is_stale"] is True
    assert item["effective_on_hand_units"] == 0
    assert item["available_units"] == 0
