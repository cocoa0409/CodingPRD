"""Inclusive boundaries and declared precision: the inventory staleness limit at
exactly three refresh cadences, and the shipment deadline instant together with
the two-decimal rounding of the hours a shipment took.
"""

from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    acknowledge_payload,
    create_order_payload,
    make_care_agent_headers,
    make_platform_admin_headers,
    make_vendor_user_headers,
    order_line_input,
    place_and_transmit_order,
    refresh_item,
    refresh_line,
    set_clock,
    ship_confirm_payload,
    setup_acknowledged_line,
    setup_vendor_with_active_offer,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)

FEED_AT = "2026-08-03T09:00:00Z"
# A cadence of 60 minutes is trusted for 60 * 3 = 180 minutes.
AGE_AT_LIMIT = "2026-08-03T12:00:00Z"
AGE_ONE_MINUTE_PAST_LIMIT = "2026-08-03T12:01:00Z"

# A line transmitted at 10:00 with a 3 day lead time and 12 hours of grace.
TRANSMIT_AT = "2026-08-03T10:00:00Z"
SHIP_DEADLINE = "2026-08-06T22:00:00Z"
ONE_MINUTE_LATE = "2026-08-06T22:01:00Z"


def _instant(value):
    """Parse an API instant into an aware UTC datetime."""
    assert isinstance(value, str) and value, f"expected an instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_two_decimals(actual, expected):
    """A decimal figure declared to two places must match to the cent of an hour."""
    assert actual is not None, "the figure must be present"
    value = float(actual)
    assert abs(value - expected) < 1e-9, f"expected {expected:.2f}, got {actual!r}"


def _fed_offer(api, suffix, now_at):
    """An ACTIVE offer with 60 on hand fed at 09:00 and the clock at `now_at`."""
    return setup_vendor_with_active_offer(
        api,
        suffix=suffix,
        on_hand_units=60,
        feed_at=FEED_AT,
        now_at=now_at,
    )


def test_feed_age_exactly_at_three_cadence_periods_is_still_fresh(api):
    """PRD §3.4: "An age precisely equal to the limit is still fresh; one minute beyond it is stale."

    The feed was refreshed at 09:00 and the clock reads 12:00, so its age is
    exactly the 180 minute limit of a 60 minute cadence. Placement must succeed.

    Design: Difficulty/boundary_precision_check/inventory_staleness_boundary_at_exactly_three_cadence_periods
    """
    state = _fed_offer(api, suffix="BPA", now_at=AGE_AT_LIMIT)
    item_id = state["item_id"]

    at_limit = refresh_item(api, item_id)
    assert at_limit["inventory_is_stale"] is False
    assert at_limit["effective_on_hand_units"] == 60
    assert at_limit["available_units"] == 55, (
        "60 on hand less a 5 unit safety buffer and no reservations"
    )

    order = validate_success(
        api.create_order(
            create_order_payload("ORD-BPA-FRESH", [order_line_input(item_id, 1)]),
            make_care_agent_headers("care-bpa"),
        ),
        201,
    )
    assert order["fulfillment_status"] == "OPEN"

    after = refresh_item(api, item_id)
    assert after["reserved_units"] == 1
    assert after["available_units"] == 54


def test_feed_age_one_minute_past_the_limit_blocks_order_placement(api):
    """PRD §3.5: "The offer's feed must be fresh, or the request fails with `ERR_INVENTORY_STALE`."

    One minute beyond the 180 minute limit the same offer reports itself stale
    and the identical placement is refused.

    Design: Difficulty/boundary_precision_check/inventory_staleness_boundary_at_exactly_three_cadence_periods
    """
    state = _fed_offer(api, suffix="BPB", now_at=AGE_ONE_MINUTE_PAST_LIMIT)
    item_id = state["item_id"]

    past_limit = refresh_item(api, item_id)
    assert past_limit["inventory_is_stale"] is True

    response = api.create_order(
        create_order_payload("ORD-BPB-STALE", [order_line_input(item_id, 1)]),
        make_care_agent_headers("care-bpb"),
    )
    validate_error(response, ApiErrorId.ERR_INVENTORY_STALE.value)

    untouched = refresh_item(api, item_id)
    assert untouched["reserved_units"] == 0
    assert untouched["lifetime_reserved_units"] == 0


def test_stale_feed_zeroes_trusted_on_hand_without_withdrawing_the_offer(api):
    """PRD §3.4: "`effective_on_hand_units` is 0 when there is no governing snapshot or when `inventory_is_stale` is true, and is otherwise the governing snapshot's `on_hand_units`."

    Crossing the limit by a minute drops the trusted on-hand figure to 0 on read,
    even though the governing feed message still says 60 and is still ACTIVE.

    Design: Difficulty/boundary_precision_check/inventory_staleness_boundary_at_exactly_three_cadence_periods
    """
    state = _fed_offer(api, suffix="BPC", now_at=AGE_AT_LIMIT)
    item_id = state["item_id"]
    assert refresh_item(api, item_id)["effective_on_hand_units"] == 60

    set_clock(api, AGE_ONE_MINUTE_PAST_LIMIT)
    stale = refresh_item(api, item_id)
    assert stale["inventory_is_stale"] is True
    assert stale["effective_on_hand_units"] == 0
    assert stale["available_units"] == 0
    assert stale["status"] == "ACTIVE", (
        "only a feed message can auto-suppress an offer, and none was posted"
    )
    assert stale["suppression_reason"] is None

    admin = make_platform_admin_headers("admin-bpc")
    snapshots, _ = validate_paginated(
        api.list_inventory_snapshots(item_id, admin)
    )
    assert len(snapshots) == 1
    assert snapshots[0]["on_hand_units"] == 60
    assert snapshots[0]["status"] == "ACTIVE"


def test_ship_confirm_exactly_at_the_ship_deadline_counts_as_on_time(api):
    """PRD §3.6: "Two figures are computed onto it: `ship_hours`, the hours from the line's `transmitted_at` to the confirming clock instant rounded half up to two decimal places, and `on_time`, which is true exactly when the confirming clock instant is at or before the line's `ship_deadline_at`, so a confirmation landing precisely on the deadline counts as on time."

    A line transmitted at 10:00 with a 3 day lead time and 12 hours of grace is
    due at 22:00 three days later; confirming on that instant is on time at
    exactly 84 hours.

    Design: Difficulty/boundary_precision_check/ship_confirm_exactly_at_ship_deadline_counts_as_on_time
    """
    state = setup_acknowledged_line(
        api,
        quantity=1,
        order_ref="ORD-BPD-ONTIME",
        suffix="BPD",
        on_hand_units=60,
        feed_at=FEED_AT,
        now_at=TRANSMIT_AT,
    )
    line = refresh_line(api, state["line_id"])
    assert _instant(line["transmitted_at"]) == _instant(TRANSMIT_AT)
    assert _instant(line["ship_deadline_at"]) == _instant(SHIP_DEADLINE)

    set_clock(api, SHIP_DEADLINE)
    shipment = validate_success(
        api.ship_confirm_line(
            state["line_id"],
            ship_confirm_payload(1, tracking_number="1Z-BPD-ONTIME"),
            make_vendor_user_headers(state["vendor_id"]),
        ),
        201,
    )
    assert shipment["on_time"] is True
    _assert_two_decimals(shipment["ship_hours"], 84.00)
    assert refresh_line(api, state["line_id"])["status"] == "SHIPPED"


def test_ship_hours_one_minute_past_the_deadline_rounds_half_up_to_two_decimals(api):
    """PRD §2.7: "`ship_hours` on a shipment confirmation and `avg_ship_hours` and `composite_score` on a scorecard are all decimal numbers rounded half up to two decimal places."

    Confirming 84 hours and 1 minute after transmission yields 84.0166... hours,
    which must be reported as 84.02, and the confirmation is no longer on time.

    Design: Difficulty/boundary_precision_check/ship_confirm_exactly_at_ship_deadline_counts_as_on_time
    """
    state = setup_acknowledged_line(
        api,
        quantity=1,
        order_ref="ORD-BPE-LATE",
        suffix="BPE",
        on_hand_units=60,
        feed_at=FEED_AT,
        now_at=TRANSMIT_AT,
    )
    line = refresh_line(api, state["line_id"])
    assert _instant(line["ship_deadline_at"]) == _instant(SHIP_DEADLINE)

    set_clock(api, ONE_MINUTE_LATE)
    shipment = validate_success(
        api.ship_confirm_line(
            state["line_id"],
            ship_confirm_payload(1, tracking_number="1Z-BPE-LATE"),
            make_vendor_user_headers(state["vendor_id"]),
        ),
        201,
    )
    _assert_two_decimals(shipment["ship_hours"], 84.02)
    assert shipment["on_time"] is False


def test_ship_sla_breach_flag_separates_the_deadline_instant_from_one_minute_later(api):
    """PRD §3.6: "The shipping counterpart is narrower: `ship_sla_breached` is true only when a recorded `shipped_at` is later than `ship_deadline_at`."

    Two lines of one order share a deadline of 22:00. The line confirmed on that
    instant is unbreached; the line confirmed a minute later is breached.

    Design: Difficulty/boundary_precision_check/ship_confirm_exactly_at_ship_deadline_counts_as_on_time
    """
    state = _fed_offer(api, suffix="BPF", now_at=TRANSMIT_AT)
    item_id = state["item_id"]
    vendor_headers = make_vendor_user_headers(state["vendor_id"])

    placed = place_and_transmit_order(
        api,
        item_id,
        quantity=1,
        order_ref="ORD-BPF-SLA",
        extra_lines=[order_line_input(item_id, 1)],
    )
    first, second = placed["lines"][0], placed["lines"][1]
    for line in (first, second):
        assert _instant(line["ship_deadline_at"]) == _instant(SHIP_DEADLINE)
        get_success_data(
            api.acknowledge_line(
                line["id"], acknowledge_payload("ACCEPTED"), vendor_headers
            )
        )

    set_clock(api, SHIP_DEADLINE)
    on_deadline = validate_success(
        api.ship_confirm_line(
            first["id"],
            ship_confirm_payload(1, tracking_number="1Z-BPF-0001"),
            vendor_headers,
        ),
        201,
    )
    set_clock(api, ONE_MINUTE_LATE)
    late = validate_success(
        api.ship_confirm_line(
            second["id"],
            ship_confirm_payload(1, tracking_number="1Z-BPF-0002"),
            vendor_headers,
        ),
        201,
    )

    assert on_deadline["on_time"] is True
    assert late["on_time"] is False
    assert refresh_line(api, first["id"])["ship_sla_breached"] is False
    assert refresh_line(api, second["id"])["ship_sla_breached"] is True
