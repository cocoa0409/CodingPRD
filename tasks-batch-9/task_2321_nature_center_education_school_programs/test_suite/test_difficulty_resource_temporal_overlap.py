"""Depth tests: the two opposite interval conventions this system uses.

A trail segment is occupied over a half-open window buffered only at its
trailing edge and is shared up to a person capacity; an educator is blocked over
a closed window buffered symmetrically and is exclusive. Each family probes both
sides of the boundary instant.
"""

from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    assign_resources,
    confirm_booking,
    create_booking,
    create_cleared_educator,
    create_published_offering,
    create_school,
    create_trail_segment,
    refresh_booking,
    refresh_educator,
    refresh_trail_segment,
    set_clock,
    validate_error,
    validate_success,
)

# A 40-person segment with the default 30-minute trailing recovery buffer and a
# weekly budget wide enough that only the instantaneous ceiling can bite.
_TRAIL_OVERRIDES = {
    "name": "Oxbow Loop",
    "capacity_persons": 40,
    "habitat_sensitivity": "LOW",
    "weekly_visitor_budget_persons": 200,
    "recovery_buffer_minutes": 30,
}

# Each party is 20 students plus 3 chaperones.
_STUDENT_COUNT = 20
_CHAPERONE_COUNT = 3

_TRAIL_WINDOWS = {
    # Occupies 09:00 through 11:30 (end plus the 30-minute buffer).
    "earlier": ("2026-09-29T09:00:00Z", "2026-09-29T11:00:00Z"),
    # Starts exactly at the instant the earlier window ends.
    "adjacent": ("2026-09-29T11:30:00Z", "2026-09-29T13:30:00Z"),
    # Genuinely straddles both of the other two windows.
    "straddling": ("2026-09-29T11:00:00Z", "2026-09-29T13:00:00Z"),
}


def _setup_trail_bookings_around_the_boundary() -> dict:
    """One trail segment plus three REQUESTED bookings, each carrying its own
    CLEARED educator so no staffing conflict interferes, all on that segment."""
    set_clock(DEFAULT_CLOCK)
    trail = create_trail_segment(**_TRAIL_OVERRIDES)
    offering = create_published_offering(
        title="Wetland Transect Walk",
        requires_trail_segment=True,
        slug_prefix="wetland",
    )
    school = create_school()
    bookings = {}
    for label, (start_utc, end_utc) in _TRAIL_WINDOWS.items():
        staffing = create_cleared_educator()
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc=start_utc,
            end_utc=end_utc,
            student_count=_STUDENT_COUNT,
            chaperone_count=_CHAPERONE_COUNT,
        )
        bookings[label] = assign_resources(
            booking["id"],
            lead_educator_id=staffing["educator"]["id"],
            trail_segment_id=trail["id"],
        )
    return {
        "trail_segment": refresh_trail_segment(trail["id"]),
        "offering": offering,
        "school": school,
        "bookings": bookings,
    }


def _setup_educator_bookings_around_the_boundary() -> dict:
    """One CLEARED educator already leading a 09:00-11:00 onsite booking, plus two
    unassigned candidates: one whose buffered window touches at 11:45 and one a
    single minute clear of it."""
    set_clock(DEFAULT_CLOCK)
    offering = create_published_offering()
    school = create_school()
    staffing = create_cleared_educator()

    def _booking(start_utc: str, end_utc: str) -> dict:
        return create_booking(
            school["id"],
            offering["id"],
            start_utc=start_utc,
            end_utc=end_utc,
            student_count=_STUDENT_COUNT,
            chaperone_count=_CHAPERONE_COUNT,
        )

    led = _booking("2026-09-29T09:00:00Z", "2026-09-29T11:00:00Z")
    led = assign_resources(led["id"], lead_educator_id=staffing["educator"]["id"])
    touching = _booking("2026-09-29T12:30:00Z", "2026-09-29T14:30:00Z")
    one_minute_clear = _booking("2026-09-29T12:31:00Z", "2026-09-29T14:31:00Z")
    return {
        "offering": offering,
        "school": school,
        "educator": refresh_educator(staffing["educator"]["id"]),
        "led_booking": led,
        "touching_booking": touching,
        "one_minute_clear_booking": one_minute_clear,
    }


class TestTrailHalfOpenOccupancyWindow:
    def test_booking_starting_when_the_buffered_window_ends_confirms(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.5: "Note the two consequences of half-open windows: a group starting exactly at the instant another group's window ends — that is, at the earlier booking's `end_utc` plus `recovery_buffer_minutes` — does **not** overlap it, and the check aggregates across all overlappers rather than rejecting on the first one it finds."

        Design: Difficulty/resource_temporal_overlap/trail_half_open_occupancy_allows_exact_adjacency_but_aggregate_capacity_rejects
        """
        scenario = _setup_trail_bookings_around_the_boundary()
        trail_id = scenario["trail_segment"]["id"]

        earlier = confirm_booking(scenario["bookings"]["earlier"]["id"])
        assert earlier["delivery_status"] == "CONFIRMED"

        adjacent = validate_success(
            api.confirm_booking(
                scenario["bookings"]["adjacent"]["id"], booking_coordinator_headers
            )
        )
        assert adjacent["delivery_status"] == "CONFIRMED"

        trail_after = refresh_trail_segment(trail_id)
        assert trail_after["visitors_this_week"] == 46
        assert trail_after["capacity_persons"] == 40

    def test_straddling_booking_rejected_once_aggregate_persons_exceed_capacity(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.5: "To evaluate a candidate, the server collects every other booking on the same segment in one of those three occupying states whose window intersects the candidate's window, adds the candidate's own persons to the sum of those overlappers' persons, and refuses confirmation with `ERR_TRAIL_CAPACITY_EXCEEDED` when that aggregate exceeds `capacity_persons`."

        Design: Difficulty/resource_temporal_overlap/trail_half_open_occupancy_allows_exact_adjacency_but_aggregate_capacity_rejects
        """
        scenario = _setup_trail_bookings_around_the_boundary()
        trail_id = scenario["trail_segment"]["id"]
        confirm_booking(scenario["bookings"]["earlier"]["id"])
        confirm_booking(scenario["bookings"]["adjacent"]["id"])

        straddling_id = scenario["bookings"]["straddling"]["id"]
        response = api.confirm_booking(straddling_id, booking_coordinator_headers)
        validate_error(response, ApiErrorId.ERR_TRAIL_CAPACITY_EXCEEDED.value)

        straddling_after = refresh_booking(straddling_id)
        assert straddling_after["delivery_status"] == "REQUESTED"
        assert straddling_after["trail_segment_id"] == trail_id

        trail_after = refresh_trail_segment(trail_id)
        assert trail_after["visitors_this_week"] == 46


class TestEducatorClosedBufferedInterval:
    def test_touching_buffered_educator_intervals_collide(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.6: "A conflict exists when any other booking — a different booking led by the same educator, in `REQUESTED`, `CONFIRMED`, `RAIN_DIVERTED` or `DELIVERED` — has a blocked interval that intersects the candidate's, and because these intervals are closed, two intervals that merely touch at an endpoint **do** collide."

        Design: Difficulty/resource_temporal_overlap/educator_closed_buffered_interval_rejects_touching_endpoints
        """
        scenario = _setup_educator_bookings_around_the_boundary()
        educator_id = scenario["educator"]["id"]
        touching = scenario["touching_booking"]

        response = api.assign_booking_resources(
            touching["id"],
            {
                "expected_booking_version": touching["version"],
                "lead_educator_id": educator_id,
            },
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_EDUCATOR_TIME_CONFLICT.value)

        touching_after = refresh_booking(touching["id"])
        assert touching_after["lead_educator_id"] is None
        assert touching_after["version"] == touching["version"]

        educator_after = refresh_educator(educator_id)
        assert educator_after["delivery_load_minutes_this_week"] == 120

    def test_educator_interval_one_minute_clear_of_the_buffer_assigns(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.6: "Educator double-booking is prevented over a **closed, symmetrically buffered** interval: each booking blocks its educator from the booking's `start_utc` minus a travel buffer through its `end_utc` plus the same buffer, inclusive at both ends, where the buffer is 45 minutes for an `ONSITE_FIELD_TRIP` or `VIRTUAL` programme and 60 minutes for an `OUTREACH_AT_SCHOOL` programme because the educator has to drive there and back."

        Design: Difficulty/resource_temporal_overlap/educator_closed_buffered_interval_rejects_touching_endpoints
        """
        scenario = _setup_educator_bookings_around_the_boundary()
        educator_id = scenario["educator"]["id"]
        candidate = scenario["one_minute_clear_booking"]

        assigned = validate_success(
            api.assign_booking_resources(
                candidate["id"],
                {
                    "expected_booking_version": candidate["version"],
                    "lead_educator_id": educator_id,
                },
                booking_coordinator_headers,
            )
        )
        assert assigned["lead_educator_id"] == educator_id
        assert assigned["version"] == candidate["version"] + 1

        educator_after = refresh_educator(educator_id)
        assert educator_after["delivery_load_minutes_this_week"] == 240
