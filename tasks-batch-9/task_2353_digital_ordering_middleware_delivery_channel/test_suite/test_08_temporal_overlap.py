"""Two resources booked over intervals, with opposite endpoint conventions.

An operating-hours window is half-open, so a window may start at the minute
another one ends. A courier network's occupancy interval is closed at both ends, so
the network is still busy at the very instant its occupancy expires.
"""
from test_helpers import (
    ApiErrorId,
    accept_assignment,
    add_hour_window,
    assert_instant,
    assert_store_hour_window,
    burger_item_payload,
    create_courier_network,
    create_hour_window_payload,
    create_store,
    dispatch_order,
    make_store_operator_headers,
    order_line,
    place_injected_order,
    read_network,
    set_clock,
    setup_published_store,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_LINE = [order_line("BURGER", 1)]


def _store_with_monday_window():
    set_clock()
    store = create_store()
    window = add_hour_window(store["id"], day_of_week=0, opens_at_minute=600, closes_at_minute=1320)
    return store, window


def test_a_window_may_open_at_the_minute_another_one_closes(api):
    """Exact adjacency is not a collision because the closing minute is excluded.

    PRD: "an `opens_at_minute` from 0 through 1439 which is included in the window,
    and a `closes_at_minute` from 1 through 1440 which is excluded from it".
    "Exact adjacency — a new window opening at the very minute an existing window
    closes — is not a collision and is accepted." "The stored window also exposes
    `window_minutes`, the number of minutes it spans, obtained by subtracting
    `opens_at_minute` from `closes_at_minute`."

    Design: Difficulty/resource_temporal_overlap/store_hour_window_half_open_adjacency_allowed
    """
    store, first = _store_with_monday_window()
    assert_store_hour_window(first)
    assert first["window_minutes"] == 720

    adjacent = add_hour_window(
        store["id"], day_of_week=0, opens_at_minute=1320, closes_at_minute=1400
    )

    assert adjacent["opens_at_minute"] == 1320
    assert adjacent["window_minutes"] == 80
    assert adjacent["store_id"] == store["id"]

    _rows, meta = validate_paginated(
        api.list_hour_windows(
            store["id"], make_store_operator_headers(store["id"]), params={"day_of_week": 0}
        )
    )
    assert meta["total_count"] == 2, f"both Monday windows stand, got {meta['total_count']}"


def test_a_window_overlapping_by_a_single_minute_is_refused(api):
    """Opening one minute before the existing window closes is a genuine collision.

    PRD: "a proposed window collides with an existing window on that day when the
    new window's `opens_at_minute` is strictly less than the existing window's
    `closes_at_minute` **and** the existing window's `opens_at_minute` is strictly
    less than the new window's `closes_at_minute`." "Windows on different days never
    collide with each other."

    Design: Difficulty/resource_temporal_overlap/store_hour_window_half_open_adjacency_allowed
    """
    store, _first = _store_with_monday_window()
    headers = make_store_operator_headers(store["id"])

    response = api.create_hour_window(
        store["id"],
        create_hour_window_payload(day_of_week=0, opens_at_minute=1319, closes_at_minute=1400),
        headers,
    )

    validate_error(response, ApiErrorId.ERR_HOUR_WINDOW_OVERLAP, 409)

    other_day = validate_success(
        api.create_hour_window(
            store["id"],
            create_hour_window_payload(day_of_week=1, opens_at_minute=600, closes_at_minute=1320),
            headers,
        ),
        expected_status=201,
    )
    assert other_day["day_of_week"] == 1
    assert other_day["window_minutes"] == 720


def _three_injected_delivery_orders():
    env = setup_published_store(
        item_payloads=[burger_item_payload()], store_overrides={"prep_capacity_per_bucket": 3}
    )
    fast = create_courier_network(
        code="N_FAST", network_type="COURIER", priority_rank=1, per_delivery_fee_cents=650,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=1,
    )
    economy = create_courier_network(
        code="N_ECON", network_type="COURIER", priority_rank=2, per_delivery_fee_cents=450,
        handoff_sla_seconds=900, dispatch_buffer_seconds=180, max_concurrent_assignments=2,
    )
    orders = [
        place_injected_order(
            env, external_ref=ref, fulfillment_mode="DELIVERY", lines=BURGER_LINE, tip_cents=0
        )
        for ref in ("MP-2001", "MP-2002", "MP-2003")
    ]
    return env, fast, economy, orders


def test_acceptance_rebases_the_occupancy_window_on_the_handoff_deadline(api):
    """Accepting moves occupancy to the handoff deadline plus the dispatch buffer.

    PRD: "On success the assignment moves `OFFERED → ACCEPTED`, stamps `accepted_at`
    from the clock, sets `handoff_deadline_at` to `accepted_at` advanced by the
    network's `handoff_sla_seconds`, resets `occupancy_until` to that deadline
    advanced by the network's `dispatch_buffer_seconds`, and snapshots
    `delivery_fee_cents` from the network's `per_delivery_fee_cents` so a later fee
    change cannot rewrite history."

    Design: Difficulty/resource_temporal_overlap/courier_network_closed_occupancy_interval_with_buffer
    """
    env, fast, _economy, orders = _three_injected_delivery_orders()

    offered = dispatch_order(env, orders[0]["id"])
    assert offered["courier_network_id"] == fast["id"], "rank 1 wins while nothing is occupied"

    accepted = accept_assignment(offered)

    assert accepted["state"] == "ACCEPTED"
    assert_instant(accepted["accepted_at"], "2026-08-03T16:00:00Z", "accepted_at")
    assert_instant(accepted["handoff_deadline_at"], "2026-08-03T16:10:00Z", "handoff_deadline_at")
    assert_instant(accepted["occupancy_until"], "2026-08-03T16:12:00Z", "occupancy_until")
    assert accepted["delivery_fee_cents"] == 650
    assert accepted["handoff_penalty_cents"] == 0
    assert accepted["sla_breached"] is False


def test_a_network_is_still_occupied_at_the_closing_instant_of_its_interval(api):
    """At 16:12 the busy network is skipped; one minute later it wins again.

    PRD: "An assignment occupies its network from its `offered_at` through its
    `occupancy_until`, and that interval is **closed at both ends** — an instant
    exactly equal to either endpoint counts as inside it. A network's occupancy
    count at a given instant is the number of its assignments whose `state` is
    `OFFERED` or `ACCEPTED` and whose occupancy interval contains that instant."

    Design: Difficulty/resource_temporal_overlap/courier_network_closed_occupancy_interval_with_buffer
    """
    env, fast, economy, orders = _three_injected_delivery_orders()
    accept_assignment(dispatch_order(env, orders[0]["id"]))

    set_clock("2026-08-03T16:12:00Z")
    second = dispatch_order(env, orders[1]["id"])

    assert second["courier_network_id"] == economy["id"], (
        "the closing instant still counts as occupied, so the preferred network is full"
    )
    assert_instant(second["occupancy_until"], "2026-08-03T16:30:00Z", "occupancy_until")

    set_clock("2026-08-03T16:13:00Z")
    third = dispatch_order(env, orders[2]["id"])

    assert third["courier_network_id"] == fast["id"], (
        "one minute past the interval the preferred network is free and reclaims the offer"
    )
    assert_instant(third["occupancy_until"], "2026-08-03T16:25:00Z", "occupancy_until")

    assert read_network(fast["id"])["open_assignment_count"] == 2
    assert read_network(economy["id"])["open_assignment_count"] == 1
