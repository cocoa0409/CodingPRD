"""The same clock arithmetic under two deliberately opposite conventions.

Zone capacity is a half-open interval compared strictly, so back-to-back windows
are two distinct slots. A courier's committed time is a closed interval padded a
quarter of an hour on each end, so that same pair is one conflict.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    ZONE_Z2,
    build_courier,
    build_network,
    build_patient,
    build_ready_order,
    build_window,
    build_zone,
    factories,
    make_courier_headers,
    read_courier,
    read_delivery,
    read_window,
    reserve_delivery,
    set_clock,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

SINGLE_LINE_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}


def _publish(api, zone_id, **overrides):
    return api.create_delivery_window(
        factories.delivery_window_payload(zone_id, **overrides), headers=OPS_HEADERS
    )


@pytest.fixture
def two_zones_and_an_afternoon_window(api):
    """Zones Z1 and Z2, and one scheduled Z1 window covering 14:00Z to 16:00Z."""
    set_clock(api, utc_ts(3, 9))
    zone_one = build_zone(api)
    zone_two = build_zone(api, **ZONE_Z2)
    first = build_window(api, zone_one["id"])
    return zone_one, zone_two, first


class TestZoneHalfOpenAdjacency:
    """"A capacity window is a **half-open** interval: `window_start` is
    inclusive, `window_end` is exclusive, so a window that begins exactly when
    another ends is a distinct slot rather than a clash."
    """

    def test_a_window_starting_exactly_when_another_ends_is_a_distinct_slot(
        self, api, two_zones_and_an_afternoon_window
    ):
        """Sharing an endpoint is not sharing time.

        "A capacity window is a **half-open** interval: `window_start` is
        inclusive, `window_end` is exclusive, so a window that begins exactly when
        another ends is a distinct slot rather than a clash."

        Design: Difficulty/resource_temporal_overlap/zone_window_half_open_adjacency_admits_abutting_window
        """
        zone_one, _zone_two, _first = two_zones_and_an_afternoon_window
        abutting = validate_success(
            _publish(
                api,
                zone_one["id"],
                window_start=utc_ts(3, 16),
                window_end=utc_ts(3, 18),
            ),
            201,
        )
        assert abutting["status"] == "OPEN"

    def test_one_second_of_real_overlap_is_rejected(
        self, api, two_zones_and_an_afternoon_window
    ):
        """Starting a second early is a genuine clash.

        "the candidate interval does not overlap a non-`CLOSED` window of the same
        `zone_id` and `courier_mode` under half-open comparison — otherwise
        `ERR_WINDOW_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/zone_window_half_open_adjacency_admits_abutting_window
        """
        zone_one, _zone_two, _first = two_zones_and_an_afternoon_window
        response = _publish(
            api,
            zone_one["id"],
            window_start="2026-08-03T15:59:59Z",
            window_end=utc_ts(3, 18, 30),
        )
        validate_error(response, "ERR_WINDOW_OVERLAP")

    def test_the_resource_is_scoped_to_one_zone_and_one_courier_mode(
        self, api, two_zones_and_an_afternoon_window
    ):
        """The identical interval is free again in another zone or another mode.

        "the candidate interval does not overlap a non-`CLOSED` window of the same
        `zone_id` and `courier_mode` under half-open comparison"

        Design: Difficulty/resource_temporal_overlap/zone_window_half_open_adjacency_admits_abutting_window
        """
        zone_one, zone_two, _first = two_zones_and_an_afternoon_window
        validate_success(
            _publish(
                api, zone_one["id"], window_start=utc_ts(3, 16), window_end=utc_ts(3, 18)
            ),
            201,
        )
        validate_success(_publish(api, zone_two["id"]), 201)
        validate_success(_publish(api, zone_one["id"], courier_mode="ON_DEMAND"), 201)

        _rows, meta = validate_paginated(
            api.list_delivery_windows(OPS_HEADERS, zone_id=zone_one["id"])
        )
        assert meta["total_count"] == 3

    def test_a_zero_length_interval_is_refused_before_any_overlap_test(
        self, api, two_zones_and_an_afternoon_window
    ):
        """An interval that contains no time at all is not an interval.

        "`window_start` is strictly earlier than `window_end` — otherwise
        `ERR_WINDOW_INTERVAL_INVALID` — and the candidate interval does not
        overlap a non-`CLOSED` window of the same `zone_id` and `courier_mode`
        under half-open comparison — otherwise `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/zone_window_half_open_adjacency_admits_abutting_window
        """
        zone_one, _zone_two, _first = two_zones_and_an_afternoon_window
        response = _publish(
            api, zone_one["id"], window_start=utc_ts(3, 20), window_end=utc_ts(3, 20)
        )
        validate_error(response, "ERR_WINDOW_INTERVAL_INVALID")

        _rows, meta = validate_paginated(
            api.list_delivery_windows(OPS_HEADERS, zone_id=zone_one["id"])
        )
        assert meta["total_count"] == 1


@pytest.fixture
def courier_committed_to_the_afternoon(api):
    """One courier serving Z1 and Z3, holding the 14:00Z to 16:00Z Z1 leg.

    Its buffered committed interval therefore runs from 13:45Z to 16:15Z. Two
    further bags wait: one on the abutting Z1 window and one on a Z3 window that
    starts a minute past the buffer edge.
    """
    net = build_network(api)
    zone_three = build_zone(api, zone_code="Z3")
    tom = build_patient(
        api,
        net.pharmacy["id"],
        full_name="Tom Reid",
        date_of_birth="1975-09-30",
        phone_last4="3390",
        address_line="44 Fir Ln",
        zone_code="Z3",
    )

    order_a = build_ready_order(api, net, **SINGLE_LINE_ORDER)
    order_b = build_ready_order(api, net, **SINGLE_LINE_ORDER)
    order_c = validate_success(
        api.create_pharmacy_order(
            factories.pharmacy_order_payload(
                net.pharmacy["id"],
                tom["id"],
                health_plan_id=net.plan["id"],
                **SINGLE_LINE_ORDER,
            ),
            headers=net.pharmacy_headers,
        ),
        201,
    )
    validate_success(api.mark_order_ready(order_c["id"], headers=net.pharmacy_headers))

    window_one = build_window(api, net.zone["id"])
    window_two = build_window(
        api, net.zone["id"], window_start=utc_ts(3, 16), window_end=utc_ts(3, 18)
    )
    window_three = build_window(
        api,
        zone_three["id"],
        window_start=utc_ts(3, 16, 16),
        window_end=utc_ts(3, 18, 16),
    )

    held = reserve_delivery(api, net, order_a["id"], window_one["id"])
    abutting = reserve_delivery(api, net, order_b["id"], window_two["id"])
    past_buffer = reserve_delivery(api, net, order_c["id"], window_three["id"])

    courier = build_courier(api, served_zone_codes=["Z1", "Z3"])
    set_clock(api, utc_ts(3, 13, 45))
    accepted = validate_success(
        api.dispatch_delivery(
            held["id"],
            headers=OPS_HEADERS,
            payload=factories.dispatch_payload(courier["id"]),
        ),
        201,
    )
    accepted = validate_success(
        api.accept_assignment(accepted["id"], headers=make_courier_headers(courier["id"]))
    )
    return courier, accepted, window_two, abutting, past_buffer


class TestCourierBufferedClosedInterval:
    """"Two windows that sit back to back are perfectly legal for a zone (§3.1
    uses strict comparison on half-open intervals) yet illegal for one courier"
    """

    def test_the_abutting_window_collides_with_the_padded_committed_interval(
        self, api, courier_committed_to_the_afternoon
    ):
        """The zone-legal pair is a conflict once the buffer is applied.

        "A candidate window conflicts when the candidate's `window_start` is at or
        before the padded upper bound **and** the padded lower bound is at or
        before the candidate's `window_end`. Because the comparisons are
        non-strict, sharing an endpoint with the padded interval *is* a conflict."

        Design: Difficulty/resource_temporal_overlap/courier_buffered_closed_interval_rejects_abutting_assignment
        """
        courier, _accepted, _window_two, abutting, _past_buffer = (
            courier_committed_to_the_afternoon
        )
        response = api.dispatch_delivery(
            abutting["id"],
            headers=OPS_HEADERS,
            payload=factories.dispatch_payload(courier["id"]),
        )
        validate_error(response, "ERR_COURIER_OVERLAP_CONFLICT", 409)

    def test_the_selector_drops_the_conflicted_courier_without_naming_the_conflict(
        self, api, courier_committed_to_the_afternoon
    ):
        """The only courier in the network silently leaves the candidate pool.

        "When this conflict is detected during selector filtering the courier is
        silently dropped from the pool with no error of its own; when it is
        detected at accept time it is reported as `ERR_COURIER_OVERLAP_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/courier_buffered_closed_interval_rejects_abutting_assignment
        """
        _courier, _accepted, window_two, abutting, _past_buffer = (
            courier_committed_to_the_afternoon
        )
        response = api.dispatch_delivery(
            abutting["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
        )
        validate_error(response, "ERR_NO_ELIGIBLE_COURIER", 409)

        delivery = read_delivery(api, abutting["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["courier_id"] is None
        assert read_window(api, window_two["id"])["reserved_slots"] == 1

    def test_one_minute_past_the_buffer_edge_clears_the_same_courier(
        self, api, courier_committed_to_the_afternoon
    ):
        """A 16:16Z start is outside a 16:15Z padded bound, so the offer stands.

        "For every `ACCEPTED` assignment the courier holds, take the window of
        that assignment's delivery and pad it by a quarter of an hour on each end
        — from `window_start` minus 15 minutes to `window_end` plus 15 minutes —
        treating the padded interval as *closed* at both ends."

        Design: Difficulty/resource_temporal_overlap/courier_buffered_closed_interval_rejects_abutting_assignment
        """
        courier, accepted, _window_two, _abutting, past_buffer = (
            courier_committed_to_the_afternoon
        )
        offer = validate_success(
            api.dispatch_delivery(
                past_buffer["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(courier["id"]),
            ),
            201,
        )
        assert offer["courier_id"] == courier["id"]
        assert offer["status"] == "OFFERED"

        on_route = read_courier(api, courier["id"])
        assert on_route["status"] == "ON_ROUTE"
        assert on_route["active_delivery_count"] == 1

        assert accepted["status"] == "ACCEPTED"
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, courier_id=courier["id"])
        )
        assert meta["total_count"] == 2
