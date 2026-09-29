"""The arithmetic itself: ladders, constants, precedence and candidate ordering.

Each of these pins a formula at the point where a naive implementation would be
off by one — an inclusive threshold, a grace band closed at its upper bound, a
first-match-wins precedence, or a filter that has to run before an ordering.
"""
from test_helpers import (
    ApiErrorId,
    accept_assignment,
    assert_delivery_assignment,
    assert_handoff_penalty,
    assert_instant,
    assert_order_line,
    assert_order_money_identity,
    assert_quote_shape,
    burger_item_payload,
    create_aggregator_channel_payload,
    create_courier_network,
    create_finalized_menu_version,
    create_order_payload,
    dispatch_order,
    handoff_assignment,
    inject_order,
    listing_for,
    make_admin_headers,
    mark_ready,
    order_line,
    place_injected_order,
    place_order,
    platter_item_payload,
    publish_menu,
    quote,
    read_menu_version,
    read_network,
    read_order,
    read_store,
    recompute_throttle,
    record_availability_event,
    set_clock,
    setup_published_store,
    setup_two_channel_store,
    suppress_listing,
    validate_error,
    validate_paginated,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
PICKUP_BURGER = {"fulfillment_mode": "PICKUP", "lines": BURGER_LINE, "tip_cents": 0}
DELIVERY_BURGER = {"fulfillment_mode": "DELIVERY", "lines": BURGER_LINE, "tip_cents": 0}


def test_the_posture_ladder_trips_exactly_at_capacity_and_at_double_capacity(api):
    """One slot is already throttled, two are already paused, and recovery reverses it.

    PRD: "if `reserved_prep_slots` is greater than or equal to twice
    `prep_capacity_per_bucket` the target is `PAUSED`; otherwise, if
    `reserved_prep_slots` is greater than or equal to `prep_capacity_per_bucket` the
    target is `THROTTLED`; otherwise the target is `NORMAL`. Both thresholds are
    inclusive, so a store whose reserved slots exactly equal its per-bucket capacity
    is `THROTTLED`, and one whose reserved slots exactly equal double that capacity is
    `PAUSED`."

    Design: Corner/calculations/calc_throttle_ladder_inclusive_at_both_thresholds
    """
    # An IGNORE_THROTTLE channel keeps the shelf orderable while the posture climbs,
    # so the ladder itself is what the second order exercises.
    env = setup_published_store(
        channel_payloads=[create_aggregator_channel_payload()],
        store_overrides={"prep_capacity_per_bucket": 1},
        **BURGER_ONLY,
    )
    first = place_order(env, external_ref="MP-1001", **PICKUP_BURGER)

    throttled = recompute_throttle(env)
    assert throttled["reserved_prep_slots"] == 1
    assert throttled["throttle_state"] == "THROTTLED", "one reserved slot already meets capacity 1"

    set_clock("2026-08-03T16:15:00Z")
    second = place_order(env, external_ref="MP-1002", **PICKUP_BURGER)
    assert second["bucket_index"] == 45, "a fresh quarter hour is a fresh bucket"
    assert_instant(second["promised_ready_at"], "2026-08-03T16:37:00Z", "promised_ready_at")

    paused = recompute_throttle(env)
    assert paused["reserved_prep_slots"] == 2
    assert paused["throttle_state"] == "PAUSED", "two reserved slots already meet double capacity"

    inject_order(env, first["id"])
    mark_ready(env, first["id"])
    recovered = recompute_throttle(env)

    assert recovered["reserved_prep_slots"] == 1
    assert recovered["throttle_state"] == "THROTTLED"
    assert read_order(second["id"])["injection_status"] == "PENDING"


def test_only_the_travel_allowance_pushes_the_quote_past_its_ceiling(api):
    """Eighty minutes of preparation is quotable; the same load plus travel is not.

    PRD: "The travel figure `travel_minutes` is 11 minutes when the
    `fulfillment_mode` is `DELIVERY` and 0 when it is `PICKUP`. `total_minutes` is the
    sum of the two figures. If `total_minutes` exceeds 90 the quote is refused with
    `ERR_QUOTE_WINDOW_EXCEEDED` — a store so loaded that it would have to promise more
    than an hour and a half must stop quoting rather than promise a time it cannot
    keep." "Nothing is persisted by a quote".

    Design: Corner/calculations/calc_quote_window_exceeded_only_for_delivery
    """
    env = setup_published_store(
        store_overrides={"base_prep_minutes": 60, "prep_capacity_per_bucket": 6}, **BURGER_ONLY
    )
    for index in range(6):
        place_order(env, external_ref=f"MP-100{index}", **PICKUP_BURGER)
    store = recompute_throttle(env)
    assert store["throttle_state"] == "THROTTLED"
    assert store["reserved_prep_slots"] == 6

    pickup = quote(env, fulfillment_mode="PICKUP")

    assert_quote_shape(pickup, expected_variant="PROVISIONAL")
    assert pickup["load_count"] == 6
    assert pickup["prep_minutes"] == 80, "60 base, 2 for each of six orders, 8 for the throttle"
    assert pickup["travel_minutes"] == 0
    assert pickup["total_minutes"] == 80
    assert_instant(pickup["quoted_ready_at"], "2026-08-03T17:20:00Z", "quoted_ready_at")

    delivery = api.get_quote(
        env["store"]["id"], env["store_headers"],
        params={"channel_id": env["channel"]["id"], "fulfillment_mode": "DELIVERY"},
    )
    validate_error(delivery, ApiErrorId.ERR_QUOTE_WINDOW_EXCEEDED, 422)

    again = quote(env, fulfillment_mode="PICKUP")
    assert again["total_minutes"] == 80, "the refused quote persisted nothing"


def test_lateness_of_exactly_the_grace_period_is_not_a_breach(api):
    """Five minutes late is forgiven, so the ladder stays in its first band.

    PRD: "`sla_breached` is true when `handoff_lateness_seconds` is **strictly
    greater** than 300 seconds — five minutes of grace are forgiven, and lateness of
    exactly 300 seconds is not a breach. `handoff_penalty_cents` follows a four-band
    ladder in which every band is closed at its upper bound: lateness of at most 300
    seconds carries no penalty".

    Design: Corner/calculations/calc_handoff_penalty_band_closed_at_grace_upper_bound
    """
    env = setup_published_store(**BURGER_ONLY)
    network = create_courier_network(
        code="N_MKT", name="MarketCouriers", network_type="MARKETPLACE", priority_rank=1,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=5,
    )
    order = place_injected_order(env, external_ref="MP-2001", **DELIVERY_BURGER)
    assignment = accept_assignment(dispatch_order(env, order["id"]))
    assert_instant(assignment["handoff_deadline_at"], "2026-08-03T16:10:00Z", "handoff_deadline_at")
    assert_instant(assignment["occupancy_until"], "2026-08-03T16:12:00Z", "occupancy_until")
    mark_ready(env, order["id"])

    set_clock("2026-08-03T16:15:00Z")
    handed_off = handoff_assignment(assignment)

    assert handed_off["state"] == "HANDED_OFF"
    assert_instant(handed_off["handoff_at"], "2026-08-03T16:15:00Z", "handoff_at")
    assert handed_off["handoff_lateness_seconds"] == 300
    assert handed_off["sla_breached"] is False
    assert handed_off["handoff_penalty_cents"] == 0
    assert_handoff_penalty(handed_off)
    assert read_network(network["id"])["penalty_accrued_cents"] == 0
    assert read_order(order["id"])["fulfillment_status"] == "HANDED_OFF"


def test_a_suppressed_listing_stays_suppressed_even_once_the_item_runs_out(api):
    """Both flags are true and the higher rung of the ladder is the one that shows.

    PRD: "It is always derived, and the four candidate values are resolved by a
    first-match-wins ladder: if the listing's `suppressed` flag is true the state is
    `SUPPRESSED`; otherwise, if its `eighty_sixed` flag is true the state is
    `EIGHTY_SIXED`". "Suppression therefore outranks an 86, and an 86 outranks
    throttle suppression — a partner-suppressed item that is also out of stock still
    reads `SUPPRESSED`, which is what lets the partner keep the item hidden after the
    kitchen restores it."

    Design: Corner/calculations/calc_suppression_outranks_eighty_six_in_precedence
    """
    env = setup_published_store(**BURGER_ONLY)

    suppressed = suppress_listing(env, "BURGER")
    assert suppressed["suppressed"] is True
    assert suppressed["availability_state"] == "SUPPRESSED"

    record_availability_event(env, "BURGER")

    both = listing_for(env, "BURGER")
    assert both["eighty_sixed"] is True, "the 86 flag was recorded on the listing"
    assert both["availability_state"] == "SUPPRESSED", (
        "suppression sits above the 86 on the ladder, so the state does not change"
    )
    assert read_menu_version(env["menu_version"]["id"])["state"] == "EXHAUSTED", (
        "the whole catalogue is dark even though the listing state reports suppression"
    )

    unsuppressed = suppress_listing(env, "BURGER", suppressed=False)
    assert unsuppressed["suppressed"] is False
    assert unsuppressed["availability_state"] == "EIGHTY_SIXED", (
        "lifting the higher rung reveals the 86 underneath it, so nothing was overwritten"
    )


def test_a_throttled_store_hides_items_only_on_the_channel_that_asked_for_it(api):
    """The same item on two channels diverges the moment the kitchen is throttled.

    PRD: "`throttle_policy` is either `SUPPRESS_ON_THROTTLE`, where this channel's
    listings are hidden while the store is throttled or paused, or `IGNORE_THROTTLE`,
    where they are not." "Listings on `IGNORE_THROTTLE` channels are unaffected in
    either direction — that is precisely what the policy buys the channel."

    Design: Corner/calculations/calc_throttle_suppression_applies_only_to_opted_in_channel
    """
    env = setup_two_channel_store(
        store_overrides={"prep_capacity_per_bucket": 1}, **BURGER_ONLY
    )
    place_order(env, channel_code="MARKETMAX", external_ref="MP-1001", **PICKUP_BURGER)

    store = recompute_throttle(env)
    assert store["throttle_state"] == "THROTTLED"

    opted_in = listing_for(env, "BURGER", channel_code="MARKETMAX")
    assert opted_in["suppressed"] is False
    assert opted_in["eighty_sixed"] is False
    assert opted_in["availability_state"] == "THROTTLE_SUPPRESSED"

    opted_out = listing_for(env, "BURGER", channel_code="AGGRPLUS")
    assert opted_out["availability_state"] == "AVAILABLE"
    assert opted_out["price_cents"] == 1187

    set_clock("2026-08-03T16:15:00Z")
    refused = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channels"]["MARKETMAX"]["id"], external_ref="MP-1002",
            fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0,
        ),
        env["partner_headers"]["MARKETMAX"],
    )
    validate_error(refused, ApiErrorId.ERR_ITEM_NOT_AVAILABLE, 409)

    accepted = place_order(env, channel_code="AGGRPLUS", external_ref="AG-1001", **PICKUP_BURGER)
    assert accepted["bucket_index"] == 45, "the ignoring channel still sells the same item"
    assert accepted["subtotal_cents"] == 1187, "and it sells it at its own cent-grid price"


def test_publishing_a_new_menu_wipes_the_eighty_six_slate_without_a_restore(api):
    """The flag is a replay from the last publish, so a republish clears it.

    PRD: "A listing's `eighty_sixed` is true exactly when the most recent honored
    event for its store-and-item pair — walking the event log for that pair in
    ascending `created_at` order, with ties broken by insertion order, and skipping the
    pair entirely on `IGNORE_86` channels — was an `EIGHTY_SIX`." "and the replay
    window begins at the store's `last_published_at`, so a publish wipes the slate as
    described in §3.2." "a version drops to `SUPERSEDED` — stamping `superseded_at`
    from the clock — at the moment the last store that was running it publishes a
    different version".

    Design: Corner/calculations/calc_republish_resets_eighty_six_replay_window
    """
    env = setup_published_store(**BURGER_ONLY)
    record_availability_event(env, "BURGER")
    first_version = env["menu_version"]
    assert read_menu_version(first_version["id"])["state"] == "EXHAUSTED"
    darkened = listing_for(env, "BURGER")
    assert darkened["eighty_sixed"] is True
    assert darkened["availability_state"] == "EIGHTY_SIXED"

    second_version, _items = create_finalized_menu_version(
        version_label="2026-Q3-CORE-B", item_payloads=[burger_item_payload()]
    )

    set_clock("2026-08-03T17:00:00Z")
    republished = publish_menu(env["store"]["id"], second_version["id"])

    assert read_menu_version(first_version["id"])["state"] == "SUPERSEDED"
    assert read_menu_version(second_version["id"])["state"] == "PUBLISHED"
    assert republished["active_menu_version_id"] == second_version["id"]
    assert_instant(republished["last_published_at"], "2026-08-03T17:00:00Z", "last_published_at")

    fresh = listing_for(env, "BURGER")
    assert fresh["eighty_sixed"] is False, "no RESTORE was ever posted; the window simply moved"
    assert fresh["availability_state"] == "AVAILABLE"

    _rows, meta = validate_paginated(api.list_availability_events(make_admin_headers()))
    assert meta["total_count"] == 1, "the event log keeps the row; only its effect was reset"


def test_a_zero_tax_line_with_no_tip_reduces_the_money_identity_to_three_terms(api):
    """The aggregation still balances exactly when two of its terms are zero.

    PRD: "`channel_collected_cents`, the amount the channel charged the guest, is
    `subtotal_cents` plus `tax_cents` plus `service_fee_cents` plus `tip_cents`.
    `commission_cents` is the sum of `subtotal_cents` and `service_fee_cents`,
    multiplied by the channel's `commission_bps`, divided by 10,000 and rounded half
    up. `brand_net_cents`, the amount owed to the brand, is `subtotal_cents` plus
    `tax_cents` plus `tip_cents` minus `commission_cents`."

    Design: Corner/calculations/calc_order_totals_with_zero_tax_and_zero_tip
    """
    env = setup_published_store(
        channel_payloads=[create_aggregator_channel_payload()],
        item_payloads=[platter_item_payload()],
    )

    order = place_order(
        env, external_ref="AG-1001", fulfillment_mode="PICKUP",
        lines=[order_line("PLATTER", 1)], tip_cents=0,
    )

    lines, meta = validate_paginated(api.list_order_lines(order["id"], make_admin_headers()))
    assert meta["total_count"] == 1
    line = lines[0]
    assert_order_line(line)
    assert line["unit_price_cents"] == 49851, (
        f"46158 at 800 basis points is 49850.64, rounded half up on a cent grid, "
        f"got {line['unit_price_cents']}"
    )
    assert line["base_price_cents"] == 46158
    assert line["tax_bps"] == 0
    assert line["line_tax_cents"] == 0

    assert order["subtotal_cents"] == 49851
    assert order["tax_cents"] == 0
    assert order["markup_cents"] == 3693, "49851 of shelf price less the 46158 the brand set"
    assert order["service_fee_cents"] == 149
    assert order["tip_cents"] == 0
    assert order["channel_collected_cents"] == 50000
    assert order["commission_cents"] == 9000, "1800 basis points of the 50000 commissionable base"
    assert order["brand_net_cents"] == 40851
    assert_order_money_identity(order)
    assert order["bucket_index"] == 44
    assert_instant(order["promised_ready_at"], "2026-08-03T16:12:00Z", "promised_ready_at")


def test_the_courier_ladder_discards_ineligible_networks_before_ranking_the_rest(api):
    """Two networks are filtered out entirely and the fee breaks the rank tie.

    PRD: "A network is eligible for a given order when all three of the following
    hold: its `is_active` is true; either its `network_type` is `COURIER` or the order's
    channel has a `channel_type` of `MARKETPLACE`; and its occupancy count at the
    current logical clock is strictly less than its `max_concurrent_assignments`."
    "Otherwise the eligible networks are ordered by `priority_rank` ascending; ties are
    broken by `per_delivery_fee_cents` ascending, then by `handoff_sla_seconds`
    ascending, and finally by the network's `created_at` ascending".

    Design: Corner/calculations/calc_courier_ladder_filters_then_orders_candidates
    """
    env = setup_published_store(
        channel_payloads=[create_aggregator_channel_payload()], **BURGER_ONLY
    )
    inactive = create_courier_network(
        code="N_OFF", name="Offline Courier", network_type="COURIER", priority_rank=1,
        per_delivery_fee_cents=100, is_active=False,
    )
    marketplace_only = create_courier_network(
        code="N_MP", name="Marketplace Only", network_type="MARKETPLACE", priority_rank=1,
        per_delivery_fee_cents=100,
    )
    slower_rank = create_courier_network(
        code="N_SLOW", name="Second Choice", network_type="COURIER", priority_rank=2,
        per_delivery_fee_cents=100,
    )
    dearer = create_courier_network(
        code="N_A", name="Dearer Courier", network_type="COURIER", priority_rank=1,
        per_delivery_fee_cents=900,
    )
    winner = create_courier_network(
        code="N_B", name="Cheaper Courier", network_type="COURIER", priority_rank=1,
        per_delivery_fee_cents=300,
    )
    order = place_injected_order(env, external_ref="AG-2001", **DELIVERY_BURGER)

    assignment = dispatch_order(env, order["id"])

    assert_delivery_assignment(assignment)
    assert assignment["courier_network_id"] == winner["id"], (
        "the inactive network and the marketplace-only network are not candidates at all, "
        "rank 2 loses to rank 1, and 300 beats 900 on the fee tie-break"
    )
    assert assignment["state"] == "OFFERED"
    assert_instant(assignment["offered_at"], "2026-08-03T16:00:00Z", "offered_at")
    assert_instant(assignment["occupancy_until"], "2026-08-03T16:12:00Z", "occupancy_until")
    assert assignment["handoff_deadline_at"] is None, "no deadline exists until the offer is taken"
    assert assignment["delivery_fee_cents"] == 0, "the fee is snapshotted at acceptance, not at offer"

    assert read_network(winner["id"])["open_assignment_count"] == 1
    for loser in (inactive, marketplace_only, slower_rank, dearer):
        assert read_network(loser["id"])["open_assignment_count"] == 0, (
            f"network {loser['code']} was not offered the order"
        )
    assert read_order(order["id"])["fulfillment_status"] == "PREPARING", (
        "dispatch does not advance the kitchen dimension"
    )
    assert read_store(env["store"]["id"])["open_order_count"] == 1
