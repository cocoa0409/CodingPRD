"""Corner cases in the platform's derived arithmetic.

Covers available-to-promise units and the buffer/grace/reservation terms, the
governing inventory snapshot, order money rollups after a line cancellation,
scorecard population windows, composite scoring and tier banding, the
empty-fallback outcome of re-sourcing, and the quoted delivery promise.
"""

from test_helpers import (
    ApiErrorId,
    assert_availability,
    assert_tier_for_score,
    create_active_item,
    create_active_vendor,
    create_inventory_snapshot_payload,
    create_order_payload,
    get_success_data,
    make_vendor_user_headers,
    order_line_input,
    order_lines_of,
    place_and_transmit_order,
    refresh_item,
    refresh_line,
    refresh_order,
    refresh_vendor,
    reset_clock,
    seeded_scorecard_payload,
    set_clock,
    setup_shipped_line,
    setup_vendor_with_active_offer,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
OPS_HEADERS = TEST_USERS["vendor_ops_analyst_headers"]
MM_HEADERS = TEST_USERS["merchandise_manager_headers"]
CARE_HEADERS = TEST_USERS["care_agent_headers"]


def _two_dp(value):
    """A decimal figure the PRD pins to two places, compared at that precision."""
    assert value is not None, "expected a decimal figure, got null"
    return round(float(value), 2)


def test_available_units_applies_buffer_and_grace_to_a_fresh_feed(api):
    """PRD §3.4: "For an `ACTIVE` offer it is the trusted on-hand figure reduced by the vendor's `safety_buffer_units`, increased by the vendor's `oversell_grace_units`, and reduced by the offer's `reserved_units`, with the whole result floored at 0 — the floor is applied once, after every other term."

    A vendor holding back 5 units with no oversell grace, an offer with no open
    lines and a fresh feed of 60 on hand must expose exactly 55 orderable units.

    Design: Corner/calculations/corner_available_to_promise_units_for_a_known_feed
    """
    state = setup_vendor_with_active_offer(
        api,
        suffix="ATP",
        vendor_overrides={
            "safety_buffer_units": 5,
            "oversell_grace_units": 0,
            "inventory_refresh_cadence_minutes": 60,
        },
        item_overrides={"sku": "SKU-ATP-CHAIR"},
        on_hand_units=60,
        feed_at="2026-08-03T09:00:00Z",
        now_at="2026-08-03T09:00:00Z",
    )

    item = validate_success(api.get_item(state["item_id"], ADMIN_HEADERS))

    assert item["effective_on_hand_units"] == 60, (
        "a fresh governing snapshot of 60 units is trusted in full"
    )
    assert item["reserved_units"] == 0, "no order line holds any unit yet"
    assert item["available_units"] == 55, "60 - 5 + 0 - 0 is 55"
    assert item["inventory_is_stale"] is False
    assert_availability(item, 60, 5, 0)


def test_availability_reads_buffer_and_grace_from_a_wholesale_vendor_row(api):
    """PRD §3.4: "For an `ACTIVE` offer it is the trusted on-hand figure reduced by the vendor's `safety_buffer_units`, increased by the vendor's `oversell_grace_units`, and reduced by the offer's `reserved_units`, with the whole result floored at 0 — the floor is applied once, after every other term."

    Both protection terms come off the vendor row, so a buffer of 2 and a grace of
    3 turn 30 trusted units into 31 orderable ones — more than are on hand. The
    same offer's cost is derived from the wholesale price at a 1000 bps discount.

    Design: Corner/calculations/corner_safety_buffer_and_oversell_grace_constants_applied_on_a_wholesale_vendor
    """
    state = setup_vendor_with_active_offer(
        api,
        suffix="WHL",
        vendor_overrides={
            "cost_model": "WHOLESALE",
            "wholesale_discount_bps": 1000,
            "inventory_refresh_cadence_minutes": 120,
            "safety_buffer_units": 2,
            "oversell_grace_units": 3,
            "default_lead_time_days": 5,
        },
        item_overrides={
            "sku": "SKU-WHL-DESK",
            "unit_wholesale_cost_cents": 19000,
            "lead_time_days": 5,
            "reverse_freight_owner": "VENDOR",
            "restock_policy": "RETAILER_RESTOCK",
        },
        rules=[{"transit_days": 2, "cutoff_hour_utc": 20, "surcharge_cents": 500}],
        on_hand_units=30,
        feed_at="2026-08-03T09:00:00Z",
        now_at="2026-08-03T09:00:00Z",
    )

    item = validate_success(api.get_item(state["item_id"], ADMIN_HEADERS))

    assert item["effective_on_hand_units"] == 30
    assert item["reserved_units"] == 0
    assert item["available_units"] == 31, "30 - 2 + 3 - 0 is 31"
    assert item["unit_cost_cents"] == 17100, "19000 at a 1000 bps discount is 17100"
    assert item["inventory_is_stale"] is False
    assert_availability(item, 30, 2, 3)


def test_scorecard_period_window_filters_the_line_population(api):
    """PRD §3.9: "A line belongs to the scorecard when the vendor of the offer named by its current `item_id` is the scored vendor, its `transmitted_at` is non-null, and the UTC calendar date of that `transmitted_at` falls on or after `period_start` and on or before `period_end`."

    One line is transmitted on 3 August and shipped two hours later. Scored over
    September the population is empty, so the seeded priors are honoured; scored
    over August the same seeds are ignored in favour of the measured figures.

    Design: Corner/calculations/corner_scorecard_period_window_filters_the_line_input_set
    """
    state = setup_shipped_line(
        api,
        quantity=1,
        order_ref="ORD-FILTER-1",
        suffix="SCF",
        item_overrides={"sku": "SKU-SCF-CHAIR"},
        ship_at="2026-08-03T12:00:00Z",
    )
    seeds = dict(
        avg_ship_hours=48.0, on_time_bps=8000, cancellation_bps=500, defect_bps=400
    )

    september = validate_success(
        api.create_scorecard(
            state["vendor_id"],
            seeded_scorecard_payload(
                period_start="2026-09-01", period_end="2026-09-30", **seeds
            ),
            OPS_HEADERS,
        ),
        201,
    )
    august = validate_success(
        api.create_scorecard(
            state["vendor_id"],
            seeded_scorecard_payload(
                period_start="2026-08-01", period_end="2026-08-31", **seeds
            ),
            OPS_HEADERS,
        ),
        201,
    )

    assert september["transmitted_line_count"] == 0, "nothing was transmitted in September"
    assert september["on_time_ship_rate_bps"] == 8000, "the seeded prior is honoured"
    assert _two_dp(september["avg_ship_hours"]) == 48.00

    assert august["transmitted_line_count"] == 1
    assert august["shipped_line_count"] == 1
    assert august["on_time_ship_rate_bps"] == 10000, "measured, so the seed is ignored"
    assert _two_dp(august["avg_ship_hours"]) == 2.00, "10:00 to 12:00 is two hours"
    assert august["cancellation_rate_bps"] == 0
    assert august["defect_rate_bps"] == 0


def test_composite_of_exactly_ninety_lands_gold_while_eighty_nine_ninety_nine_lands_silver(api):
    """PRD §3.9: "Banding follows in strict descending order: the `tier` is `UNRATED` when `composite_score` is null, `PLATINUM` when it is 95 or above, `GOLD` when it is 90 or above, `SILVER` when it is 80 or above, `WATCH` when it is 70 or above, and `PROBATION` in every remaining case."

    Two seeded periods straddle the GOLD cutoff: a composite of exactly 90.00 is
    GOLD with one padding day, while 89.99 drops to SILVER with two. Neither
    scorecard is published, so the vendor itself stays UNRATED.

    Design: Corner/calculations/corner_tier_threshold_at_exactly_ninety_composite_lands_gold
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="TIER")

    at_cutoff = validate_success(
        api.create_scorecard(
            vendor["id"],
            seeded_scorecard_payload(
                avg_ship_hours=24.0,
                on_time_bps=9000,
                cancellation_bps=1000,
                defect_bps=1000,
                period_start="2026-06-01",
                period_end="2026-06-30",
            ),
            OPS_HEADERS,
        ),
        201,
    )
    below_cutoff = validate_success(
        api.create_scorecard(
            vendor["id"],
            seeded_scorecard_payload(
                avg_ship_hours=24.0,
                on_time_bps=8998,
                cancellation_bps=1000,
                defect_bps=1000,
                period_start="2026-05-01",
                period_end="2026-05-31",
            ),
            OPS_HEADERS,
        ),
        201,
    )

    assert _two_dp(at_cutoff["composite_score"]) == 90.00
    assert at_cutoff["tier"] == "GOLD"
    assert at_cutoff["promise_padding_days"] == 1
    assert_tier_for_score(at_cutoff["tier"], _two_dp(at_cutoff["composite_score"]))

    assert _two_dp(below_cutoff["composite_score"]) == 89.99
    assert below_cutoff["tier"] == "SILVER"
    assert below_cutoff["promise_padding_days"] == 2
    assert_tier_for_score(
        below_cutoff["tier"], _two_dp(below_cutoff["composite_score"])
    )

    row = refresh_vendor(api, vendor["id"])
    assert row["performance_tier"] == "UNRATED", "a DRAFT scorecard never touches the vendor"


def test_composite_weights_span_the_full_range(api):
    """PRD §3.9: "The platform first forms a basis-point composite as one half of `on_time_ship_rate_bps`, plus three tenths of the quantity 10000 minus `cancellation_rate_bps`, plus two tenths of the quantity 10000 minus `defect_rate_bps`, that sum rounded half up to a whole basis point."

    A perfect seeded period scores 100.00, a worst-case one 0.00, and a mixed set
    that is perfect on time but wholly cancelled and defect-free lands on exactly
    70.00 — the 0.50 and 0.20 contributions with nothing left over.

    Design: Corner/calculations/corner_composite_weights_span_the_full_range_and_sum_to_one
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="WEIGHT")

    best = validate_success(
        api.create_scorecard(
            vendor["id"],
            seeded_scorecard_payload(
                avg_ship_hours=12.0,
                on_time_bps=10000,
                cancellation_bps=0,
                defect_bps=0,
                period_start="2026-04-01",
                period_end="2026-04-30",
            ),
            OPS_HEADERS,
        ),
        201,
    )
    worst = validate_success(
        api.create_scorecard(
            vendor["id"],
            seeded_scorecard_payload(
                avg_ship_hours=200.0,
                on_time_bps=0,
                cancellation_bps=10000,
                defect_bps=10000,
                period_start="2026-03-01",
                period_end="2026-03-31",
            ),
            OPS_HEADERS,
        ),
        201,
    )
    mixed = validate_success(
        api.create_scorecard(
            vendor["id"],
            seeded_scorecard_payload(
                avg_ship_hours=36.0,
                on_time_bps=10000,
                cancellation_bps=10000,
                defect_bps=0,
                period_start="2026-02-01",
                period_end="2026-02-28",
            ),
            OPS_HEADERS,
        ),
        201,
    )

    assert _two_dp(best["composite_score"]) == 100.00
    assert best["tier"] == "PLATINUM"
    assert best["promise_padding_days"] == 0

    assert _two_dp(worst["composite_score"]) == 0.00
    assert worst["tier"] == "PROBATION"
    assert worst["promise_padding_days"] == 5

    assert _two_dp(mixed["composite_score"]) == 70.00
    assert mixed["tier"] == "WATCH"
    assert mixed["promise_padding_days"] == 3


def test_order_totals_reaggregate_after_a_line_cancellation(api):
    """PRD §3.6: "**Hop two**, caused by hop one changing the line's status, re-derives the order's `total_retail_cents`, `total_cost_cents` and `margin_cents` over the remaining non-cancelled lines and re-derives the order's `fulfillment_status`."

    Two identical transmitted lines total 49998 retail and 42498 cost. Cancelling
    one re-derives the money from the survivor rather than decrementing blindly,
    leaving exactly one line's worth with no rounding residue.

    Design: Corner/calculations/corner_order_totals_reaggregate_after_a_line_cancellation
    """
    state = setup_vendor_with_active_offer(
        api, suffix="AGG", item_overrides={"sku": "SKU-AGG-CHAIR"}
    )
    placed = place_and_transmit_order(
        api,
        state["item_id"],
        quantity=1,
        order_ref="ORD-AGG-1",
        extra_lines=[order_line_input(state["item_id"], 1)],
    )
    before = placed["order"]
    assert before["total_retail_cents"] == 49998
    assert before["total_cost_cents"] == 42498
    assert before["margin_cents"] == 7500

    first_line = placed["lines"][0]
    validate_success(
        api.cancel_line(first_line["id"], make_vendor_user_headers(state["vendor_id"]))
    )

    line = refresh_line(api, first_line["id"])
    order = refresh_order(api, placed["order_id"])
    item = refresh_item(api, state["item_id"])

    assert line["status"] == "CANCELLED_BY_VENDOR"
    assert order["total_retail_cents"] == 24999, "only the surviving line counts"
    assert order["total_cost_cents"] == 21249
    assert order["margin_cents"] == 3750
    assert order["net_retail_cents"] == 24999, "nothing has been refunded"
    assert order["fulfillment_status"] == "OPEN", "one line is still open, none shipped"
    assert item["reserved_units"] == 1, "the cancelled line gave its reservation up"


def test_governing_snapshot_is_selected_by_window_not_by_insertion_order(api):
    """PRD §3.4: "The candidates are the offer's snapshots whose `status` is `ACTIVE` and whose window contains the logical clock, meaning `effective_from` is at or before the clock and either `effective_to` is null or the clock is strictly before `effective_to`."

    A future-dated open-ended feed of 15 units is posted first and a feed covering
    the current clock is posted second. Containment picks the second one, so the
    trusted on-hand figure is 60 rather than the newest or highest-sequenced row.

    Design: Corner/calculations/corner_effective_snapshot_is_chosen_by_window_not_by_insertion_order
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="SNAP")
    item = create_active_item(api, vendor["id"], sku="SKU-SNAP-CHAIR")
    vendor_headers = make_vendor_user_headers(vendor["id"])
    set_clock(api, "2026-08-03T09:00:00Z")

    future_row = validate_success(
        api.create_inventory_snapshot(
            item["id"],
            create_inventory_snapshot_payload(
                expected_item_version=refresh_item(api, item["id"])["version"],
                on_hand_units=15,
                effective_from="2026-08-04T00:00:00Z",
                feed_sequence=2,
            ),
            vendor_headers,
        ),
        201,
    )
    current_row = validate_success(
        api.create_inventory_snapshot(
            item["id"],
            create_inventory_snapshot_payload(
                expected_item_version=refresh_item(api, item["id"])["version"],
                on_hand_units=60,
                effective_from="2026-08-03T00:00:00Z",
                feed_sequence=1,
                effective_to="2026-08-04T00:00:00Z",
            ),
            vendor_headers,
        ),
        201,
    )
    assert future_row["id"] != current_row["id"]

    rows, _meta = validate_paginated(
        api.list_inventory_snapshots(item["id"], ADMIN_HEADERS)
    )
    assert len(rows) == 2, "the later window is not superseded by an earlier one"
    assert [row["status"] for row in rows] == ["ACTIVE", "ACTIVE"]

    live = refresh_item(api, item["id"])
    assert live["effective_on_hand_units"] == 60, "the containing window governs"
    assert live["effective_on_hand_units"] != 15
    assert live["inventory_is_stale"] is False
    assert live["status"] == "ACTIVE"
    assert live["available_units"] == 55, "60 - 5 + 0 - 0 is 55"


def test_pending_transmit_lines_already_reduce_available_units(api):
    """PRD §3.4: "`reserved_units` counts the units held by that offer's open order lines, which are precisely the lines in `PENDING_TRANSMIT`, `TRANSMITTED`, `ACKNOWLEDGED` or `BACKORDERED`; lines that have reached `SHIPPED` or `CANCELLED_BY_VENDOR` no longer reserve anything."

    A line no vendor has seen yet already holds its units, so availability falls
    from 55 to 51 the moment the order is placed, while the feed figure itself is
    untouched.

    Design: Corner/calculations/corner_reservations_from_untransmitted_lines_already_reduce_availability
    """
    state = setup_vendor_with_active_offer(
        api, suffix="FWD", item_overrides={"sku": "SKU-FWD-CHAIR"}
    )

    order = validate_success(
        api.create_order(
            create_order_payload(
                "ORD-FWD-1", [order_line_input(state["item_id"], 4)]
            ),
            CARE_HEADERS,
        ),
        201,
    )

    line = order_lines_of(api, order["id"])[0]
    assert line["status"] == "PENDING_TRANSMIT"
    assert line["transmitted_at"] is None

    item = refresh_item(api, state["item_id"])
    assert item["reserved_units"] == 4
    assert item["available_units"] == 51, "55 orderable units less the 4 just reserved"
    assert item["effective_on_hand_units"] == 60, "the feed itself is untouched"
    assert_availability(item, 60, 5, 0)


def test_retransmit_with_no_fallback_offer_is_rejected_without_side_effects(api):
    """PRD §3.7: "When the eligible set comes back empty the request is rejected with `ERR_NO_ELIGIBLE_FALLBACK_VENDOR` and HTTP 422, the line stays exactly where it was in `BACKORDERED`, and no side effect of any kind is applied."

    The offer declares no fallback, so the chain walk yields an empty candidate
    pool. The line keeps its state, its offer, its single transmit attempt and its
    reservation.

    Design: Corner/calculations/corner_retransmit_without_any_eligible_fallback_is_rejected
    """
    state = setup_vendor_with_active_offer(
        api, suffix="NOFB", item_overrides={"sku": "SKU-NOFB-CHAIR"}
    )
    placed = place_and_transmit_order(
        api, state["item_id"], quantity=2, order_ref="ORD-NOFB-1"
    )
    line_id = placed["lines"][0]["id"]
    get_success_data(
        api.acknowledge_line(
            line_id,
            {"ack_disposition": "BACKORDERED"},
            make_vendor_user_headers(state["vendor_id"]),
        )
    )
    assert refresh_line(api, line_id)["status"] == "BACKORDERED"

    response = api.retransmit_line(line_id, MM_HEADERS)

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_FALLBACK_VENDOR.value, 422)

    line = refresh_line(api, line_id)
    assert line["status"] == "BACKORDERED"
    assert line["transmit_attempt_count"] == 1, "the refused attempt does not count"
    assert line["item_id"] == state["item_id"], "the line was never re-sourced"
    assert refresh_item(api, state["item_id"])["reserved_units"] == 2


def test_promise_variant_stays_quoted_until_the_first_transmission(api):
    """PRD §3.5: "At placement `promise_variant_in_effect` reads `QUOTED` and `recomputed_promise_date` is still null."

    An order placed at 10:00 on 3 August against a three-day lead time, four
    transit days and two padding days is promised 12 August. Until a line is
    transmitted the RECOMPUTED variant is simply not in play, so divergence is 0.

    Design: Corner/calculations/corner_promise_variant_in_effect_is_quoted_until_the_first_transmission
    """
    state = setup_vendor_with_active_offer(
        api, suffix="VARSEL", item_overrides={"sku": "SKU-VARSEL-CHAIR"}
    )
    order = get_success_data(
        api.create_order(
            create_order_payload(
                "ORD-VARSEL-1", [order_line_input(state["item_id"], 1)]
            ),
            CARE_HEADERS,
        )
    )

    promise = validate_success(api.get_order_promise(order["id"], CARE_HEADERS))

    assert promise["order_id"] == order["id"]
    assert promise["promise_variant_in_effect"] == "QUOTED"
    assert promise["quoted_promise_date"] == "2026-08-12"
    assert promise["recomputed_promise_date"] is None
    assert promise["promise_divergence_days"] == 0

    row = refresh_order(api, order["id"])
    assert row["promise_variant_in_effect"] == "QUOTED"
    assert row["quoted_promise_date"] == "2026-08-12"
    assert row["recomputed_promise_date"] is None
    assert row["fulfillment_status"] == "OPEN"
