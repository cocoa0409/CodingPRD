"""Preconditions on publishing a menu, taking an order and closing a period.

Each of these pairs the refusal with the nearby request that must still succeed,
so a rule that is implemented as a blanket rejection fails just as loudly as one
that is not implemented at all.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    OTHER_BRAND_CODE,
    ApiErrorId,
    add_hour_window,
    assert_order_money_identity,
    assert_instant,
    assert_remittance_statement,
    assert_store_counters,
    burger_item_payload,
    create_accepted_adjustment,
    create_aggregator_channel_payload,
    create_channel,
    create_finalized_menu_version,
    create_hour_window_payload,
    create_order_payload,
    create_statement_payload,
    create_store,
    inject_order,
    list_listings,
    listing_for,
    make_admin_headers,
    make_analyst_headers,
    make_store_operator_headers,
    open_statement,
    order_line,
    place_order,
    place_ready_order,
    platter_item_payload,
    publish_menu_payload,
    read_adjustment,
    read_menu_version,
    read_order,
    read_statement,
    read_store,
    recompute_throttle,
    record_availability_event,
    set_clock,
    setup_published_store,
    setup_two_channel_store,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
PICKUP_BURGER = {"fulfillment_mode": "PICKUP", "lines": BURGER_LINE, "tip_cents": 0}
SETTLEMENT_CLOCK = "2026-08-04T01:00:00Z"


def test_a_store_cannot_adopt_another_brand_s_menu(api):
    """The catalogue and the store are each valid; only their brands disagree.

    PRD: "Four preconditions must hold: the named version's `state` is `PUBLISHED`,
    its `brand_code` equals the store's `brand_code` (otherwise `ERR_BRAND_MISMATCH`),
    the declared store version matches, and the store has at least one operating-hours
    window".

    Design: Corner/validations/val_publish_brand_mismatch_rejected
    """
    set_clock()
    create_channel()
    menu_version, _items = create_finalized_menu_version(item_payloads=[burger_item_payload()])
    store = create_store(brand_code=OTHER_BRAND_CODE, name="Other Brand Store")
    add_hour_window(store["id"], day_of_week=0, opens_at_minute=600, closes_at_minute=1320)

    response = api.publish_menu(
        store["id"],
        publish_menu_payload(menu_version["id"], store["version"]),
        make_store_operator_headers(store["id"]),
    )

    validate_error(response, ApiErrorId.ERR_BRAND_MISMATCH, 422)
    unchanged = read_store(store["id"])
    assert unchanged["active_menu_version_id"] is None
    assert unchanged["throttle_state"] == "PAUSED"
    assert unchanged["version"] == store["version"], "the failed publish consumed no version"
    assert read_menu_version(menu_version["id"])["published_store_count"] == 0


def test_a_store_with_no_operating_hours_cannot_publish_yet(api):
    """Adding a single window is the only difference between the refusal and success.

    PRD: "and the store has at least one operating-hours window (otherwise
    `ERR_STORE_HOURS_MISSING`, because a store with no hours has no defined ordering
    window and no defined quote)." "The first successful publish also lifts the store's
    posture from `PAUSED` to `NORMAL`".

    Design: Corner/validations/val_first_publish_requires_hour_windows
    """
    set_clock()
    channel = create_channel()
    menu_version, _items = create_finalized_menu_version(item_payloads=[burger_item_payload()])
    store = create_store()
    declared_version = store["version"]

    refused = api.publish_menu(
        store["id"],
        publish_menu_payload(menu_version["id"], declared_version),
        make_store_operator_headers(store["id"]),
    )

    validate_error(refused, ApiErrorId.ERR_STORE_HOURS_MISSING, 409)
    assert list_listings(store_id=store["id"], limit=100) == [], "nothing was materialised"

    add_hour_window(store["id"], day_of_week=0, opens_at_minute=600, closes_at_minute=1320)
    published = validate_success(
        api.publish_menu(
            store["id"],
            publish_menu_payload(menu_version["id"], declared_version),
            make_store_operator_headers(store["id"]),
        )
    )

    assert published["throttle_state"] == "NORMAL"
    assert published["active_menu_version_id"] == menu_version["id"]
    assert published["version"] == declared_version + 1, (
        "the refused attempt left the declared version still current"
    )
    rows = list_listings(store_id=store["id"], channel_id=channel["id"], limit=100)
    assert len(rows) == 1
    assert rows[0]["price_cents"] == 1265


def test_a_channel_that_does_not_do_delivery_takes_the_same_basket_for_pickup(api):
    """The rule is about the channel's configuration, not about the basket.

    PRD: "A final optional `accepts_delivery` flag decides whether delivery orders may
    be placed on the channel at all; when omitted it is true." "A `DELIVERY` order
    additionally requires that the channel's `accepts_delivery` be true, or it is
    refused with `ERR_CHANNEL_DELIVERY_UNSUPPORTED`".

    Design: Corner/validations/val_channel_without_delivery_rejects_delivery_order
    """
    env = setup_published_store(
        channel_payloads=[
            create_aggregator_channel_payload(
                code="PICKONLY", name="Pickup Only", eighty_six_policy="HONOR_86",
                accepts_delivery=False,
            )
        ],
        **BURGER_ONLY,
    )
    partner = env["partner_headers"]["PICKONLY"]

    refused = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channel"]["id"], external_ref="PO-1001",
            fulfillment_mode="DELIVERY", lines=BURGER_LINE, tip_cents=0,
        ),
        partner,
    )

    validate_error(refused, ApiErrorId.ERR_CHANNEL_DELIVERY_UNSUPPORTED, 422)
    _rows, meta = validate_paginated(
        api.list_orders(make_admin_headers(), params={"store_id": env["store"]["id"]})
    )
    assert meta["total_count"] == 0, "the refused delivery order was never created"

    accepted = place_order(env, external_ref="PO-1002", **PICKUP_BURGER)

    assert accepted["fulfillment_mode"] == "PICKUP"
    assert accepted["subtotal_cents"] == 1187
    assert_instant(accepted["promised_ready_at"], "2026-08-03T16:12:00Z", "promised_ready_at")
    assert read_store(env["store"]["id"])["open_order_count"] == 1


def test_one_undeliverable_item_sinks_the_whole_delivery_basket(api):
    """Eligibility is a property of the item, so a mixed basket fails as a whole.

    PRD: "and that every line's underlying item have `is_delivery_eligible` true, or it
    is refused with `ERR_ITEM_NOT_DELIVERY_ELIGIBLE`." "The travel figure
    `travel_minutes` is 11 minutes when the `fulfillment_mode` is `DELIVERY` and 0 when
    it is `PICKUP`."

    Design: Corner/validations/val_delivery_order_with_ineligible_item_rejected
    """
    env = setup_published_store(
        item_payloads=[burger_item_payload(), platter_item_payload()]
    )
    mixed = [order_line("BURGER", 1), order_line("PLATTER", 1)]
    partner = env["partner_headers"]["MARKETMAX"]

    refused = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channel"]["id"], external_ref="MP-1001",
            fulfillment_mode="DELIVERY", lines=mixed, tip_cents=0,
        ),
        partner,
    )
    validate_error(refused, ApiErrorId.ERR_ITEM_NOT_DELIVERY_ELIGIBLE, 422)
    _rows, meta = validate_paginated(
        api.list_orders(make_admin_headers(), params={"store_id": env["store"]["id"]})
    )
    assert meta["total_count"] == 0

    pickup = place_order(
        env, external_ref="MP-1002", fulfillment_mode="PICKUP", lines=mixed, tip_cents=0
    )
    lines, line_meta = validate_paginated(
        api.list_order_lines(pickup["id"], make_admin_headers())
    )
    assert line_meta["total_count"] == 2
    assert {line["sku"] for line in lines} == {"BURGER", "PLATTER"}

    delivery = place_order(
        env, external_ref="MP-1003", fulfillment_mode="DELIVERY", lines=BURGER_LINE, tip_cents=0
    )
    assert_instant(delivery["promised_ready_at"], "2026-08-03T16:25:00Z", "promised_ready_at")
    assert read_store(env["store"]["id"])["open_order_count"] == 2


def test_an_item_that_ran_out_is_unorderable_until_the_kitchen_restores_it(api):
    """Intake reads the derived availability, and a restore is enough to reopen it.

    PRD: "Every resolved listing must have `availability_state` equal to `AVAILABLE`,
    or the order is refused with `ERR_ITEM_NOT_AVAILABLE` — suppressed, 86-ed and
    throttle-suppressed items are all unorderable, and this is the check that makes the
    fan-out of §3.4 commercially meaningful."

    Design: Corner/validations/val_eighty_sixed_item_blocks_new_order
    """
    env = setup_published_store(**BURGER_ONLY)
    record_availability_event(env, "BURGER")
    assert listing_for(env, "BURGER")["availability_state"] == "EIGHTY_SIXED"

    refused = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channel"]["id"], external_ref="MP-1001",
            fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0,
        ),
        env["partner_headers"]["MARKETMAX"],
    )
    validate_error(refused, ApiErrorId.ERR_ITEM_NOT_AVAILABLE, 409)

    record_availability_event(env, "BURGER", event_type="RESTORE")

    restored = listing_for(env, "BURGER")
    assert restored["eighty_sixed"] is False
    assert restored["availability_state"] == "AVAILABLE"
    assert read_menu_version(env["menu_version"]["id"])["state"] == "PUBLISHED"

    order = place_order(env, external_ref="MP-1002", **PICKUP_BURGER)
    assert order["subtotal_cents"] == 1265
    assert order["bucket_index"] == 44

    events, meta = validate_paginated(
        api.list_availability_events(make_admin_headers(), params={"store_id": env["store"]["id"]})
    )
    assert meta["total_count"] == 2
    assert [event["event_type"] for event in events] == ["EIGHTY_SIX", "RESTORE"]


def test_a_paused_store_refuses_an_order_even_into_an_empty_bucket(api):
    """The posture gate is about the store, not about the bucket the order would land in.

    PRD: "and the store's `throttle_state` must not be `PAUSED`, or the request is
    refused with `ERR_STORE_PAUSED`." "Recomputing the posture cascades to the shelf."

    Design: Corner/validations/val_paused_store_rejects_new_order
    """
    env = setup_published_store(store_overrides={"prep_capacity_per_bucket": 1}, **BURGER_ONLY)
    place_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    set_clock("2026-08-03T16:15:00Z")
    place_order(env, external_ref="MP-1002", **PICKUP_BURGER)
    paused = recompute_throttle(env)
    assert paused["throttle_state"] == "PAUSED"
    assert paused["reserved_prep_slots"] == 2

    set_clock("2026-08-03T16:30:00Z")
    refused = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channel"]["id"], external_ref="MP-1003",
            fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0,
        ),
        env["partner_headers"]["MARKETMAX"],
    )

    validate_error(refused, ApiErrorId.ERR_STORE_PAUSED, 409)
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=2, reserved_prep_slots=2)
    assert listing_for(env, "BURGER")["availability_state"] == "THROTTLE_SUPPRESSED", (
        "the shelf agrees with the paused posture"
    )


def test_a_channel_reference_is_only_unique_within_its_own_channel(api):
    """The same reference collides on one channel and is a fresh order on the other.

    PRD: "a channel-side `external_ref` that must be unique within that channel — a
    repeat is `ERR_DUPLICATE_EXTERNAL_REF`".

    Design: Corner/validations/val_duplicate_external_ref_is_scoped_per_channel
    """
    env = setup_two_channel_store(
        store_overrides={"prep_capacity_per_bucket": 3}, **BURGER_ONLY
    )
    first = place_order(env, channel_code="MARKETMAX", external_ref="MP-DUP", **PICKUP_BURGER)

    duplicate = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channels"]["MARKETMAX"]["id"], external_ref="MP-DUP",
            fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0,
        ),
        env["partner_headers"]["MARKETMAX"],
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_EXTERNAL_REF, 409)

    sibling = place_order(env, channel_code="AGGRPLUS", external_ref="MP-DUP", **PICKUP_BURGER)

    assert sibling["subtotal_cents"] == 1187
    assert first["subtotal_cents"] == 1265, "each channel sells at its own shelf price"
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=2, reserved_prep_slots=2)
    _rows, meta = validate_paginated(
        api.list_orders(make_admin_headers(), params={"store_id": env["store"]["id"]})
    )
    assert meta["total_count"] == 2


def test_a_settlement_period_must_be_ordered_and_already_finished(api):
    """A future end and a reversed pair are both refused; the closed period is taken.

    PRD: "The period must be real and finished: `period_start` must be strictly
    earlier than `period_end`, and `period_end` must not be later than the current
    logical clock, so an inverted period or a period reaching into the future is
    refused with `ERR_INVALID_PERIOD`."

    Design: Corner/validations/val_statement_period_must_end_at_or_before_now
    """
    set_clock(SETTLEMENT_CLOCK)
    channel = create_channel()
    analyst = make_analyst_headers()

    future = api.create_statement(
        create_statement_payload(
            channel["id"], period_start="2026-08-04T00:00:00Z", period_end="2026-08-05T00:00:00Z"
        ),
        analyst,
    )
    validate_error(future, ApiErrorId.ERR_INVALID_PERIOD, 422)

    reversed_period = api.create_statement(
        create_statement_payload(
            channel["id"], period_start="2026-08-04T00:00:00Z", period_end="2026-08-03T00:00:00Z"
        ),
        analyst,
    )
    validate_error(reversed_period, ApiErrorId.ERR_INVALID_PERIOD, 422)

    statement = open_statement(channel["id"])

    assert_remittance_statement(statement)
    assert statement["state"] == "OPEN"
    assert statement["order_count"] == 0
    assert statement["gross_sales_cents"] == 0
    assert statement["adjustment_total_cents"] == 0
    assert statement["tier_base_cents"] == 0
    assert statement["commission_cents"] == 0
    assert statement["rebate_cents"] == 0
    assert statement["net_payable_cents"] == 0
    assert statement["tier"] == "TIER_1"
    _rows, meta = validate_paginated(
        api.list_statements(analyst, params={"channel_id": channel["id"]})
    )
    assert meta["total_count"] == 1


def test_an_empty_statement_cannot_be_frozen_until_it_holds_an_order(api):
    """The same reconcile call is a refusal and then a success, and the money follows.

    PRD: "it requires two things: the statement must hold at least one order, or it is
    refused with `ERR_STATEMENT_EMPTY`". "Reconciliation recomputes the aggregates
    through the pipeline and records the acting `X-User-ID` as `reconciled_by_user_id`".

    Design: Corner/validations/val_empty_statement_cannot_reconcile_then_passes
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_ready_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    set_clock(SETTLEMENT_CLOCK)
    statement = open_statement(env["channel"]["id"])
    analyst = make_analyst_headers()

    empty = api.reconcile_statement(statement["id"], analyst)
    validate_error(empty, ApiErrorId.ERR_STATEMENT_EMPTY, 409)
    still_open = read_statement(statement["id"])
    assert still_open["state"] == "OPEN"
    assert still_open["order_count"] == 0

    assigned = validate_success(
        api.assign_orders(statement["id"], {"order_ids": [order["id"]]}, analyst)
    )
    assert assigned["order_count"] == 1
    assert assigned["gross_sales_cents"] == 1564
    assert assigned["tier"] == "TIER_1"
    assert assigned["commission_cents"] == 391
    assert assigned["net_payable_cents"] == 1173

    reconciled = validate_success(api.reconcile_statement(statement["id"], analyst))

    assert reconciled["state"] == "RECONCILED"
    assert reconciled["reconciled_by_user_id"] == ANALYST_ONE_USER_ID
    settled_order = read_order(order["id"])
    assert settled_order["settlement_status"] == "STATEMENT_ASSIGNED"
    assert settled_order["remittance_statement_id"] == statement["id"]


def test_an_order_already_on_a_statement_reports_assignment_not_ineligibility(api):
    """The order still satisfies every eligibility term, so the lower-ranked rule fires.

    PRD: "That eligibility test deliberately says nothing about settlement status;
    that is a separate, lower-ranked check, so an order that already sits on some
    statement — whose `settlement_status` is therefore `STATEMENT_ASSIGNED` or
    `SETTLED` rather than `SETTLEABLE` — surfaces as `ERR_ORDER_ALREADY_ASSIGNED` and
    not as an eligibility failure. An order may belong to at most one statement at a
    time."

    Design: Corner/validations/val_assign_same_order_twice_hits_priority_41
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_ready_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    set_clock(SETTLEMENT_CLOCK)
    analyst = make_analyst_headers()
    first = open_statement(env["channel"]["id"])
    validate_success(api.assign_orders(first["id"], {"order_ids": [order["id"]]}, analyst))
    second = open_statement(env["channel"]["id"])

    same = api.assign_orders(first["id"], {"order_ids": [order["id"]]}, analyst)
    other = api.assign_orders(second["id"], {"order_ids": [order["id"]]}, analyst)

    validate_error(same, ApiErrorId.ERR_ORDER_ALREADY_ASSIGNED, 409)
    validate_error(other, ApiErrorId.ERR_ORDER_ALREADY_ASSIGNED, 409)

    holder = read_statement(first["id"])
    assert holder["order_count"] == 1, "no double counting"
    assert holder["gross_sales_cents"] == 1564
    empty = read_statement(second["id"])
    assert empty["order_count"] == 0
    assert empty["gross_sales_cents"] == 0
    assert read_order(order["id"])["remittance_statement_id"] == first["id"]


def test_an_order_carrying_an_accepted_refund_can_no_longer_be_cancelled(api):
    """The gate reads the order's refunded total, not any individual adjustment row.

    PRD: "Two money conditions guard it: the order's `settlement_status` must still be
    `SETTLEABLE`, and its `refunded_total_cents` must be exactly 0. An order carrying
    accepted refunds cannot be cancelled and is refused with
    `ERR_ORDER_HAS_ACCEPTED_ADJUSTMENTS`; the refunds must be reversed first so that
    the money identity of §3.5 stays intact."

    Design: Corner/validations/val_cancel_blocked_by_accepted_refund
    """
    env = setup_published_store(
        channel_payloads=[create_aggregator_channel_payload()], **BURGER_ONLY
    )
    order = place_order(env, external_ref="AG-1001", **PICKUP_BURGER)
    inject_order(env, order["id"])
    injected = read_order(order["id"])
    assert injected["channel_collected_cents"] == 1440

    adjustment = create_accepted_adjustment(injected, amount_cents=500)
    assert read_adjustment(adjustment["id"])["state"] == "ACCEPTED", (
        "an auto-accepting channel takes the refund on submission"
    )

    refunded = read_order(order["id"])
    assert refunded["refunded_total_cents"] == 500
    assert refunded["commission_cents"] == 150, "240 of commission less 90 of relief"
    assert refunded["brand_net_cents"] == 641
    assert_order_money_identity(refunded)

    response = api.cancel_order(
        order["id"], {"reason_code": "GUEST_CANCELLED"}, env["store_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ORDER_HAS_ACCEPTED_ADJUSTMENTS, 409)
    assert read_order(order["id"])["fulfillment_status"] == "PREPARING"
    assert read_store(env["store"]["id"])["open_order_count"] == 1


def test_an_out_of_range_hour_window_fails_the_shape_check_not_the_overlap_check(api):
    """A day of seven and a closing minute of 1441 are both malformed input.

    PRD: "a `day_of_week` from 0 (Monday) through 6 (Sunday)". "`ERR_INVALID_REQUEST`
    (400) — body and query shape: a required input is missing, a value has the wrong
    type, an enum value is not recognized, an integer falls outside its declared
    range".

    Design: Corner/validations/val_hour_window_day_of_week_out_of_range_rejected
    """
    set_clock()
    store = create_store()
    window = add_hour_window(store["id"], day_of_week=0, opens_at_minute=600, closes_at_minute=1320)
    headers = make_store_operator_headers(store["id"])

    bad_day = api.create_hour_window(
        store["id"],
        create_hour_window_payload(day_of_week=7, opens_at_minute=600, closes_at_minute=1320),
        headers,
    )
    validate_error(bad_day, ApiErrorId.ERR_INVALID_REQUEST, 400)

    bad_close = api.create_hour_window(
        store["id"],
        create_hour_window_payload(day_of_week=1, opens_at_minute=600, closes_at_minute=1441),
        headers,
    )
    validate_error(bad_close, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_hour_windows(store["id"], headers))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [window["id"]]
