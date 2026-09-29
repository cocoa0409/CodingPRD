"""Version tokens, page windows, derived counters and read-your-writes.

The three optimistic-concurrency tests each replay a token an unrelated writer
has already consumed; the pagination test proves the window is applied after the
filter; the counter test drives three parents up and back down; the last one
insists the write response is already the truth.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ApiErrorId,
    add_hour_window,
    assert_channel_listing,
    assert_instant,
    assert_store,
    assert_store_counters,
    burger_item_payload,
    cancel_order_payload,
    create_adjustment_payload,
    create_aggregator_channel_payload,
    create_channel,
    create_finalized_menu_version,
    create_order_payload,
    create_store,
    fries_item_payload,
    inject_payload,
    list_listings,
    make_admin_headers,
    make_analyst_headers,
    make_channel_partner_headers,
    make_store_operator_headers,
    order_line,
    patch_channel_payload,
    patch_store_payload,
    place_order,
    publish_menu,
    publish_menu_payload,
    read_channel,
    read_menu_version,
    read_order,
    read_store,
    set_clock,
    setup_published_store,
    submit_adjustment,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
PICKUP_BURGER = {"fulfillment_mode": "PICKUP", "lines": BURGER_LINE, "tip_cents": 0}


def test_a_capacity_edit_invalidates_the_token_a_publisher_was_holding(api):
    """The unrelated writer moved the store, so the publisher must re-read it.

    PRD: "`POST /stores/{id}/publish-menu` requires `expected_store_version`,
    carrying the client's last observed `version` of the target `Store`. If it does
    not equal the store's current `version`, the publish is rejected with
    `ERR_STALE_STORE_VERSION` and HTTP 412." "`version` (integer): starts at 1 on
    creation and increments by exactly 1 on every mutation of that record".

    Design: Corner/complexity_layers/occ_publish_menu_with_stale_store_version_returns_412
    """
    set_clock()
    channel = create_channel()
    version, _items = create_finalized_menu_version(item_payloads=[burger_item_payload()])
    store = create_store(name="Store Twentysix")
    add_hour_window(store["id"])
    operator = make_store_operator_headers(store["id"])
    assert store["version"] == 1
    assert read_store(store["id"])["version"] == 1, (
        "an operating-hours window is its own record, so it is not a write to the store"
    )

    patched = validate_success(
        api.patch_store(store["id"], patch_store_payload(base_prep_minutes=20),
                        make_admin_headers())
    )
    assert_store(patched)
    assert patched["version"] == 2

    stale = api.publish_menu(store["id"], publish_menu_payload(version["id"], 1), operator)

    validate_error(stale, ApiErrorId.ERR_STALE_STORE_VERSION, 412)
    refused = read_store(store["id"])
    assert refused["active_menu_version_id"] is None
    assert refused["throttle_state"] == "PAUSED"
    assert refused["version"] == 2, "the rejected publish wrote nothing at all"

    published = validate_success(
        api.publish_menu(store["id"], publish_menu_payload(version["id"], 2), operator)
    )

    assert published["version"] == 3
    assert published["active_menu_version_id"] == version["id"]
    assert published["throttle_state"] == "NORMAL"

    quote = validate_success(
        api.get_quote(store["id"], operator,
                      params={"channel_id": channel["id"], "fulfillment_mode": "PICKUP"})
    )
    assert quote["prep_minutes"] == 20, "the capacity edit that caused the conflict took effect"
    assert_instant(quote["quoted_ready_at"], "2026-08-03T16:20:00Z", "quoted_ready_at")


def test_proposing_a_refund_consumes_the_order_token_it_was_given(api):
    """The token that just worked is exactly the token that must now fail.

    PRD: "`POST /adjustments` requires `expected_order_version`, carrying the client's
    last observed `version` of the `Order` named by `order_id`. If it does not equal the
    order's current `version`, the create is rejected with `ERR_STALE_ORDER_VERSION` and
    HTTP 412." "Creating the adjustment increments the order's `version` by 1".

    Design: Corner/complexity_layers/occ_adjustment_with_consumed_order_version_returns_412
    """
    env = setup_published_store(
        channel_payloads=[create_aggregator_channel_payload()], **BURGER_ONLY
    )
    order = place_order(env, external_ref="AG-3501", **PICKUP_BURGER)
    assert order["channel_collected_cents"] == 1440
    first_token = read_order(order["id"])["version"]
    analyst = make_analyst_headers(ANALYST_ONE_USER_ID)

    first = validate_success(
        api.create_adjustment(
            create_adjustment_payload(order["id"], first_token, amount_cents=100), analyst
        ),
        expected_status=201,
    )
    assert first["state"] == "DRAFT"

    replay = api.create_adjustment(
        create_adjustment_payload(
            order["id"], first_token, amount_cents=200, reason_code="LATE_DELIVERY"
        ),
        analyst,
    )

    validate_error(replay, ApiErrorId.ERR_STALE_ORDER_VERSION, 412)
    second_token = read_order(order["id"])["version"]
    assert second_token == first_token + 1, "only the accepted create moved the order"

    second = validate_success(
        api.create_adjustment(
            create_adjustment_payload(
                order["id"], second_token, amount_cents=200, reason_code="LATE_DELIVERY"
            ),
            analyst,
        ),
        expected_status=201,
    )
    assert second["amount_cents"] == 200

    _rows, meta = validate_paginated(
        api.list_adjustments(analyst, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 2, "the refused replay persisted nothing"

    assert submit_adjustment(first)["state"] == "ACCEPTED", "this channel accepts on submission"
    assert read_order(order["id"])["refunded_total_cents"] == 100
    submit_adjustment(second)
    assert read_order(order["id"])["refunded_total_cents"] == 300


def test_two_roles_contend_for_one_channel_token_and_the_shelf_keeps_its_price(api):
    """The loser is refused, and even the winner does not reprice what already exists.

    PRD: "`PATCH /channels/{id}` requires `expected_channel_version`, carrying the
    client's last observed `version` of the `Channel`. If it does not equal the
    channel's current `version`, the update is rejected with
    `ERR_STALE_CHANNEL_VERSION` and HTTP 412." "Revising a channel does **not** reprice
    anything that already exists. Listings keep the `price_cents` they were built with;
    a new markup or rounding mode reaches the shelf only at the next publish of a menu
    to a store."

    Design: Corner/complexity_layers/occ_channel_patch_replay_returns_412
    """
    set_clock()
    channel = create_channel()
    version, _items = create_finalized_menu_version(item_payloads=[burger_item_payload()])
    store = create_store(name="Store Twentyeight")
    add_hour_window(store["id"])
    published = publish_menu(store["id"], version["id"])
    assert channel["version"] == 1
    # Materializing the listing recomputed the channel's `listing_count`, and a
    # derived-field write is a mutation like any other, so the token moved.
    token = read_channel(channel["id"])["version"]
    assert token == 2
    assert list_listings(store_id=store["id"], limit=10)[0]["price_cents"] == 1265

    by_partner = validate_success(
        api.patch_channel(channel["id"], patch_channel_payload(token, markup_bps=2000),
                          make_channel_partner_headers(channel["id"]))
    )
    assert by_partner["markup_bps"] == 2000
    assert by_partner["version"] == token + 1

    replay = api.patch_channel(
        channel["id"], patch_channel_payload(token, service_fee_cents=349), make_admin_headers()
    )

    validate_error(replay, ApiErrorId.ERR_STALE_CHANNEL_VERSION, 412)
    untouched = read_channel(channel["id"])
    assert untouched["service_fee_cents"] == 299
    assert untouched["version"] == token + 1

    retried = validate_success(
        api.patch_channel(channel["id"], patch_channel_payload(token + 1, service_fee_cents=349),
                          make_admin_headers())
    )
    assert retried["service_fee_cents"] == 349
    assert retried["markup_bps"] == 2000
    assert retried["version"] == token + 2

    assert list_listings(store_id=store["id"], limit=10)[0]["price_cents"] == 1265, (
        "the shelf still carries the price it was built with"
    )

    publish_menu(store["id"], version["id"], published["version"])

    repriced = list_listings(store_id=store["id"], limit=10)
    assert len(repriced) == 1
    assert repriced[0]["price_cents"] == 1320, (
        "1099 at 2000 basis points is 1318.8, rounded half up to 1319 and up to the nickel"
    )


def test_the_page_window_is_applied_after_the_filter_not_before_it(api):
    """The total follows the filter, and a mutation moves the filtered population.

    PRD: "`total_count` is the number of records matching the filters before
    pagination is applied, and `has_more` is true exactly when records remain beyond the
    current page." "`limit` caps the number of records returned; it defaults to 10 when
    omitted, may not be smaller than 1, and may not be larger than 100. `offset` is the
    number of records to skip before the page begins; it defaults to 0 and may not be
    negative. A `limit` outside the range of 1 through 100 inclusive, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/complexity_layers/pagination_orders_filter_offset_and_limit_interact
    """
    env = setup_published_store(store_overrides={"prep_capacity_per_bucket": 5}, **BURGER_ONLY)
    orders = [
        place_order(env, external_ref=f"MP-360{index + 1}", **PICKUP_BURGER)
        for index in range(5)
    ]
    for order in orders[:2]:
        validate_success(api.inject_order(order["id"], inject_payload(), env["store_headers"]))
    admin = make_admin_headers()
    scope = {"store_id": env["store"]["id"]}

    rows, meta = validate_paginated(
        api.list_orders(admin, params={**scope, "limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 5
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api.list_orders(admin, params={**scope, "limit": 2, "offset": 4})
    )
    assert len(rows) == 1, "the last page is short because the population ends there"
    assert meta["total_count"] == 5
    assert meta["has_more"] is False

    pending_query = {**scope, "injection_status": "PENDING", "limit": 2, "offset": 0}
    rows, meta = validate_paginated(api.list_orders(admin, params=pending_query))
    assert len(rows) == 2
    assert meta["total_count"] == 3, "the total counts the filtered set, not the table"
    assert meta["has_more"] is True

    validate_success(api.inject_order(orders[2]["id"], inject_payload(), env["store_headers"]))

    rows, meta = validate_paginated(api.list_orders(admin, params=pending_query))
    assert len(rows) == 2
    assert meta["total_count"] == 2, "one row left the filtered population under a stable offset"
    assert meta["has_more"] is False

    _rows, accepted_meta = validate_paginated(
        api.list_orders(
            admin, params={**scope, "injection_status": "ACCEPTED", "limit": 100, "offset": 0}
        )
    )
    assert accepted_meta["total_count"] == 3

    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_orders(admin, params={**scope, **bad}),
            ApiErrorId.ERR_INVALID_REQUEST, 400,
        )


def test_three_derived_counters_come_back_down_as_well_as_up(api):
    """A cancellation and a republish must undo what a create and a publish did.

    PRD: "`Channel.listing_count` always equals the number of listings currently
    published to that channel." "`Store.open_order_count` always equals the number of
    that store's orders whose `fulfillment_status` is `PREPARING` or `READY` — orders
    that have reached `HANDED_OFF`, `DELIVERED` or `CANCELLED` no longer count."
    "it deletes every listing this store held under the previously active version and
    recomputes each affected channel's `listing_count`; it increments the adopted
    version's `published_store_count`; it decrements the previously active version's
    `published_store_count`".

    Design: Corner/complexity_layers/derived_counts_reconcile_after_create_and_change
    """
    set_clock()
    channel = create_channel()
    first_version, _first_items = create_finalized_menu_version(
        version_label="2026-Q3-V1",
        item_payloads=[burger_item_payload(), fries_item_payload()],
    )
    second_version, second_items = create_finalized_menu_version(
        version_label="2026-Q4-V2", item_payloads=[burger_item_payload()]
    )
    store = create_store(name="Store Thirty", prep_capacity_per_bucket=3)
    add_hour_window(store["id"])
    admin = make_admin_headers()

    after_first = publish_menu(store["id"], first_version["id"])
    assert read_channel(channel["id"])["listing_count"] == 2
    _rows, meta = validate_paginated(
        api.list_channel_listings(admin, params={"channel_id": channel["id"], "limit": 100})
    )
    assert meta["total_count"] == 2, "the counter equals its own source rows"
    assert read_menu_version(first_version["id"])["published_store_count"] == 1

    order = validate_success(
        api.create_order(
            create_order_payload(
                store["id"], channel["id"], external_ref="MP-3701", **PICKUP_BURGER
            ),
            make_channel_partner_headers(channel["id"]),
        ),
        expected_status=201,
    )
    assert_store_counters(read_store(store["id"]), open_order_count=1, reserved_prep_slots=1)

    validate_success(
        api.cancel_order(order["id"], cancel_order_payload("CHANNEL_REQUEST"),
                         make_channel_partner_headers(channel["id"]))
    )
    assert_store_counters(read_store(store["id"]), open_order_count=0, reserved_prep_slots=0)
    assert read_order(order["id"])["fulfillment_status"] == "CANCELLED"

    # The order create and the cancellation each wrote the store's counters, so the
    # publisher has to re-read the version it declares.
    assert read_store(store["id"])["version"] > after_first["version"]
    publish_menu(store["id"], second_version["id"])

    assert read_channel(channel["id"])["listing_count"] == 1
    assert read_menu_version(second_version["id"])["published_store_count"] == 1
    assert read_menu_version(first_version["id"])["published_store_count"] == 0
    assert read_menu_version(first_version["id"])["state"] == "SUPERSEDED"

    rows, meta = validate_paginated(
        api.list_channel_listings(admin, params={"store_id": store["id"], "limit": 100})
    )
    assert meta["total_count"] == 1
    assert_channel_listing(rows[0])
    assert rows[0]["menu_item_id"] == second_items["BURGER"]["id"], (
        "the stale second listing was deleted rather than left orphaned"
    )


def test_the_publish_response_is_already_the_whole_truth(api):
    """No follow-up read is needed, and an order placed in the same instant proves it.

    PRD: "Every one of those secondary writes is part of the same request: the system
    is immediately consistent, and a client that reads any touched record after a 2xx
    response sees the fully reconciled value. There is no background job, no eventual
    convergence, and no partial application". "it materializes one **channel listing**
    for every combination of an item in that version and a registered channel".

    Design: Corner/consistency_model/consistency_publish_response_is_immediately_authoritative
    """
    set_clock()
    marketplace = create_channel()
    aggregator = validate_success(
        api.create_channel(create_aggregator_channel_payload(), make_admin_headers()),
        expected_status=201,
    )
    version, _items = create_finalized_menu_version(
        item_payloads=[burger_item_payload(), fries_item_payload()]
    )
    store = create_store(name="Store Thirtyone")
    add_hour_window(store["id"])
    operator = make_store_operator_headers(store["id"])

    published = validate_success(
        api.publish_menu(store["id"], publish_menu_payload(version["id"], store["version"]),
                         operator)
    )

    assert published["active_menu_version_id"] == version["id"]
    assert published["throttle_state"] == "NORMAL"
    assert published["version"] == store["version"] + 1
    assert_instant(published["last_published_at"], "2026-08-03T16:00:00Z", "last_published_at")

    rows, meta = validate_paginated(
        api.list_channel_listings(make_admin_headers(),
                                  params={"store_id": store["id"], "limit": 100})
    )
    assert meta["total_count"] == 4, "two items on two channels, all in that one request"
    priced = {(row["channel_id"], row["sku"]): row["price_cents"] for row in rows}
    assert priced[(marketplace["id"], "BURGER")] == 1265
    assert priced[(marketplace["id"], "FRIES")] == 460
    assert priced[(aggregator["id"], "BURGER")] == 1187
    assert priced[(aggregator["id"], "FRIES")] == 431

    order = validate_success(
        api.create_order(
            create_order_payload(
                store["id"], aggregator["id"], external_ref="AG-3801", **PICKUP_BURGER
            ),
            make_channel_partner_headers(aggregator["id"]),
        ),
        expected_status=201,
    )

    assert order["subtotal_cents"] == 1187, "the brand-new listing priced the line"
    assert order["tax_cents"] == 104
    assert order["service_fee_cents"] == 149
    assert order["channel_collected_cents"] == 1440

    quote = validate_success(
        api.get_quote(store["id"], operator,
                      params={"channel_id": aggregator["id"], "fulfillment_mode": "PICKUP"})
    )
    assert quote["load_count"] == 1, "the reservation the order just made is already visible"
    assert quote["prep_minutes"] == 14, "12 of base plus one load pad of 2"
    assert_instant(quote["quoted_ready_at"], "2026-08-03T16:14:00Z", "quoted_ready_at")
