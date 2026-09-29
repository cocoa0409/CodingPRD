"""Half-open tarmac intervals against closed-inclusive reporting periods."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ERR_REPORT_PERIOD_OVERLAP,
    ERR_TARMAC_INTERVAL_OVERLAP,
    OPS_HEADERS,
    assert_instant,
    assert_segment_state,
    create_booking,
    create_passenger,
    create_policy_profile,
    factories as f,
    open_report,
    read_profile,
    read_segment,
    read_tarmac_event,
    set_clock,
)

# ─── Tarmac occupations that touch ────────────────────


def _first_occupation_closed_at_2140(api):
    """One leg whose first occupation ran 18:40 to 21:40 and is now closed."""
    set_clock(api, "2026-08-10T23:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "touch@example.com", "Tou Ching")
    booking = create_booking(
        api, passenger["id"], profile["id"], "TCH001", 30000, "CREDIT_CARD"
    )
    segment = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ202",
                origin_iata="DEN",
                destination_iata="ORD",
                scheduled_departure_utc="2026-08-10T18:30:00Z",
                scheduled_arrival_utc="2026-08-10T21:00:00Z",
                segment_fare_cents=30000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    first = validate_success(
        api.create_tarmac_delay_event(
            f.tarmac_event_payload(segment["id"], "2026-08-10T18:40:00Z", "DEPARTURE"),
            OPS_HEADERS,
        ),
        201,
    )
    validate_success(
        api.deplane_tarmac_event(
            first["id"], f.deplane_payload("2026-08-10T21:40:00Z"), OPS_HEADERS
        )
    )
    return segment, first


class TestTarmacIntervalsTouch:
    def test_a_new_occupation_may_start_at_the_exact_instant_the_last_one_ended(self, api):
        """21:40 is free the moment the 18:40 occupation closes there.

        PRD §3.5: "Because the interval end is exclusive, merely touching is permitted: a
        new event may start at the exact instant a previous one ended."

        Design: Difficulty/resource_temporal_overlap/tarmac_intervals_touch_allowed_overlap_rejected
        """
        segment, first = _first_occupation_closed_at_2140(api)

        second = validate_success(
            api.create_tarmac_delay_event(
                f.tarmac_event_payload(segment["id"], "2026-08-10T21:40:00Z", "ARRIVAL"),
                OPS_HEADERS,
            ),
            201,
        )
        validate_success(
            api.deplane_tarmac_event(
                second["id"], f.deplane_payload("2026-08-10T22:00:00Z"), OPS_HEADERS
            )
        )

        first_row = read_tarmac_event(api, first["id"], segment["id"])
        second_row = read_tarmac_event(api, second["id"], segment["id"])
        assert first_row["tarmac_minutes"] == 180
        assert_instant(first_row["interval_end_utc"], "2026-08-10T21:40:00Z")
        assert first_row["is_violation"] is False
        assert second_row["tarmac_minutes"] == 20
        assert_segment_state(
            read_segment(api, segment["id"]), cumulative_tarmac_minutes=200
        )

    def test_a_new_occupation_starting_inside_a_closed_interval_is_rejected(self, api):
        """21:50 lands inside the second occupation and is refused as an overlap.

        PRD §3.5: "A new event whose interval intersects any existing occupation is
        refused with `ERR_TARMAC_INTERVAL_OVERLAP`."

        PRD §3.5: "A closed event occupies the interval from its `tarmac_start_utc`
        inclusive to its `interval_end_utc` exclusive; an event still open occupies
        everything from its `tarmac_start_utc` onward without end, and therefore blocks
        every later event on the same leg until it is closed."

        Design: Difficulty/resource_temporal_overlap/tarmac_intervals_touch_allowed_overlap_rejected
        """
        segment, _ = _first_occupation_closed_at_2140(api)
        second = validate_success(
            api.create_tarmac_delay_event(
                f.tarmac_event_payload(segment["id"], "2026-08-10T21:40:00Z", "ARRIVAL"),
                OPS_HEADERS,
            ),
            201,
        )
        validate_success(
            api.deplane_tarmac_event(
                second["id"], f.deplane_payload("2026-08-10T22:00:00Z"), OPS_HEADERS
            )
        )

        refused = api.create_tarmac_delay_event(
            f.tarmac_event_payload(segment["id"], "2026-08-10T21:50:00Z", "ARRIVAL"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_TARMAC_INTERVAL_OVERLAP, 409)
        _, meta = validate_paginated(
            api.list_segment_tarmac_events(segment["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2, "the refused create must not persist a third row"
        assert_segment_state(
            read_segment(api, segment["id"]), cumulative_tarmac_minutes=200
        )


# ─── Reporting periods that share a boundary ──────────


def _profile_with_a_june_report(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    report = open_report(api, profile["id"], "2026-06-01T00:00:00Z", "2026-06-30T23:59:59Z")
    return profile, report


class TestReportPeriodBoundaryCollision:
    def test_two_periods_sharing_one_boundary_instant_intersect(self, api):
        """A period starting on June's last second collides with June itself.

        PRD §3.9: "Reporting periods for one profile may not intersect, and because both
        ends are **inclusive**, two periods that share a single boundary instant do
        intersect — an overlap is `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_inclusive_boundary_collision
        """
        profile, _ = _profile_with_a_june_report(api)
        before = read_profile(api, profile["id"])

        refused = api.create_regulator_report(
            f.report_payload(
                profile["id"],
                before["version"],
                "2026-06-30T23:59:59Z",
                "2026-07-31T23:59:59Z",
            ),
            ADMIN_HEADERS,
        )

        validate_error(refused, ERR_REPORT_PERIOD_OVERLAP, 409)
        after = read_profile(api, profile["id"])
        assert after["report_count"] == 1
        assert after["version"] == before["version"], "a refused open moves no version"

    def test_a_period_starting_one_second_later_opens_cleanly(self, api):
        """July opens beside June and the profile's report count reaches two.

        PRD §3.9: "A `ComplianceAdmin` opens a report by naming the
        `policy_profile_id`, a `period_start_utc`, a `period_end_utc` strictly later than
        the start, and the `expected_policy_profile_version` guard of §2.6; a start at or
        after the end is `ERR_PERIOD_BOUNDS_INVALID`."

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_inclusive_boundary_collision
        """
        profile, _ = _profile_with_a_june_report(api)

        july = open_report(
            api, profile["id"], "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z"
        )

        assert july["status"] == "DRAFT"
        assert read_profile(api, profile["id"])["report_count"] == 2
        _, meta = validate_paginated(
            api.list_policy_profile_reports(profile["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
