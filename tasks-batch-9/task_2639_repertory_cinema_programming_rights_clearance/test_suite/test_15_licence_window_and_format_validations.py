"""Licence window, projection format and screening allowance validations.

Every test places (or fails to place) one screening against the canonical house
and asserts which rung of the validation ladder answered the request.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_screen_block,
    assert_screening_allowance_conserved,
    clearance_version,
    place_showtime,
    read_booking,
    read_clearance,
    setup_programming_baseline,
    showtime_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMMER = TEST_USERS["programmer_headers"]


def _showtime_body(world, start_at, expected_clearance_version, **overrides):
    """A complete manual-placement payload against the world's cleared licence."""
    return showtime_payload(
        world["venue"]["id"],
        world["title"]["id"],
        world["booking"]["id"],
        world["clearance"]["id"],
        world["asset"]["id"],
        start_at,
        expected_clearance_version,
        **overrides,
    )


def _showtimes_at_venue(api, venue_id):
    rows, _meta = validate_paginated(
        api.list_showtimes(PROGRAMMER, params={"venue_id": venue_id})
    )
    return rows


class TestFormatCompatibility:

    def test_showtime_format_not_supported_by_the_venue_is_refused(self, api):
        """PRD §3.5: "The screening's `format` must simultaneously be one of the
        auditorium's `supported_formats`, equal the package's `format`, and equal
        the licence's `source_format`, otherwise `ERR_FORMAT_INCOMPATIBLE`."

        PRD §2.7: "Format compatibility — formats agree the whole way down the
        chain (`ERR_FORMAT_INCOMPATIBLE`). Applies to both schedulers and to the
        creation of a print/package asset."

        Design: Corner/validations/format_not_supported_by_the_venue_is_refused
        """
        world = setup_programming_baseline()
        version_before = clearance_version(world["clearance"]["id"])

        response = api.create_showtime(
            _showtime_body(
                world, "2026-08-14T12:00:00Z", version_before, format="PRINT_35MM"
            ),
            PROGRAMMER,
        )

        # PRINT_35MM is a declared member of the five-format enumeration, so the
        # schema rung has nothing to say: this is a business rejection.
        validate_error(response, ApiErrorId.ERR_FORMAT_INCOMPATIBLE.value)

        assert _showtimes_at_venue(api, world["venue"]["id"]) == [], (
            "A refused placement must leave no screening behind"
        )
        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_remaining"] == 6, (
            f"Expected screenings_remaining 6, got {clearance['screenings_remaining']} "
            "after a refused placement"
        )
        assert clearance["version"] == version_before, (
            f"Expected clearance version {version_before}, got {clearance['version']} "
            "after a refused placement"
        )
        assert_screening_allowance_conserved(clearance)


class TestOperatingDayAndLicenceWindow:

    def test_showtime_on_the_last_licensed_date_at_the_last_minute_is_accepted(
        self, api
    ):
        """PRD §3.5: "The venue-local time of `start_at` must fall between
        `open_local_time` and `last_start_local_time` inclusive, the venue-local
        date of `start_at` must fall inside the engagement's inclusive
        `engagement_start_date` through `engagement_end_date` span, and `start_at`
        must not be earlier than the logical clock — any of the three failing
        yields `ERR_SHOWTIME_WINDOW_INVALID`."

        PRD §2.8: "A screening's advertised start must fall on or after the former
        and on or before the latter; the block is permitted to end after
        `last_start_local_time`, and it is permitted to run past midnight, in
        which case its occupancy still collides with the next day's first show,
        because occupancy is compared as instants and not as same-day clock
        readings."

        PRD §3.5: "The screening's on-screen content runs for the auditorium's
        `trailer_reel_minutes` plus the title's `runtime_minutes` plus the
        screening's own `extra_minutes`, which is 0 at creation; `end_at` is
        `start_at` advanced by that total number of minutes, and `blocked_until`
        is `end_at` advanced by the auditorium's `turnaround_minutes`."

        Design: Corner/validations/showtime_on_the_last_licensed_date_at_the_last_permitted_minute_is_accepted
        """
        world = setup_programming_baseline()
        version_before = clearance_version(world["clearance"]["id"])

        # 22:00 venue-local is exactly last_start_local_time and 2026-08-20 is
        # exactly window_end_date and engagement_end_date.
        response = api.create_showtime(
            _showtime_body(world, "2026-08-20T22:00:00Z", version_before), PROGRAMMER
        )
        showtime = validate_success(response, expected_status=201)

        assert showtime["start_at"] == "2026-08-20T22:00:00.000Z", (
            f"Expected start_at 2026-08-20T22:00:00.000Z, got {showtime['start_at']}"
        )
        # 12 trailer minutes + 104 runtime minutes = 116 on-screen minutes from
        # 22:00, then the 25-minute turnaround buffer on the tail.
        assert_screen_block(
            showtime, "2026-08-20T23:56:00.000Z", "2026-08-21T00:21:00.000Z"
        )
        assert showtime["status"] == "SCHEDULED", (
            f"Expected SCHEDULED, got {showtime['status']}"
        )

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 1, (
            f"Expected screenings_used 1, got {clearance['screenings_used']}"
        )
        assert clearance["screenings_remaining"] == 5, (
            f"Expected screenings_remaining 5, got {clearance['screenings_remaining']}"
        )
        booking = read_booking(world["booking"]["id"])
        assert booking["scheduled_showtime_count"] == 1, (
            "Expected scheduled_showtime_count 1, got "
            f"{booking['scheduled_showtime_count']}"
        )

    def test_showtime_starting_after_the_last_permitted_local_minute_is_refused(
        self, api
    ):
        """PRD §3.5: "The venue-local time of `start_at` must fall between
        `open_local_time` and `last_start_local_time` inclusive, the venue-local
        date of `start_at` must fall inside the engagement's inclusive
        `engagement_start_date` through `engagement_end_date` span, and `start_at`
        must not be earlier than the logical clock — any of the three failing
        yields `ERR_SHOWTIME_WINDOW_INVALID`."

        Design: Corner/validations/showtime_starting_after_the_last_permitted_local_minute_is_refused
        """
        world = setup_programming_baseline()
        version_before = clearance_version(world["clearance"]["id"])

        # 22:30 is thirty minutes past the inclusive 22:00 boundary; the date is
        # inside both the licence and the engagement window and the screen is empty.
        response = api.create_showtime(
            _showtime_body(world, "2026-08-14T22:30:00Z", version_before), PROGRAMMER
        )

        validate_error(response, ApiErrorId.ERR_SHOWTIME_WINDOW_INVALID.value)

        assert _showtimes_at_venue(api, world["venue"]["id"]) == [], (
            "A refused placement must leave no screening behind"
        )
        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 0, (
            f"Expected screenings_used 0, got {clearance['screenings_used']}"
        )
        assert clearance["version"] == version_before, (
            f"Expected clearance version {version_before}, got {clearance['version']}"
        )

    def test_showtime_outside_the_licence_window_is_refused_before_the_engagement_check(
        self, api
    ):
        """PRD §2.7: "Checks are evaluated in one strictly ascending order, and
        **the first violated check wins**: once a rule fails, the request is rejected
        with that rule's error and no later rule is evaluated."

        PRD §2.7: "Licence window — the screening's venue-local date lies inside
        the clearance's licensed window, both ends inclusive
        (`ERR_CLEARANCE_WINDOW_NOT_COVERED`). Applies to both schedulers."

        PRD §2.7: "Showtime window — the venue-local start time lies inside the
        venue's operating start window, the venue-local date lies inside the
        engagement's inclusive date range, and the start instant is not earlier
        than the clock (`ERR_SHOWTIME_WINDOW_INVALID`). Applies to both
        schedulers."

        Design: Corner/validations/showtime_outside_the_licence_window_is_refused_before_the_engagement_check
        """
        world = setup_programming_baseline()
        version_before = clearance_version(world["clearance"]["id"])

        # 2026-08-21 lies outside the licence window AND outside the engagement
        # window, while 12:00 is comfortably inside the operating day.
        response = api.create_showtime(
            _showtime_body(world, "2026-08-21T12:00:00Z", version_before), PROGRAMMER
        )

        validate_error(response, ApiErrorId.ERR_CLEARANCE_WINDOW_NOT_COVERED.value)

        clearance = read_clearance(world["clearance"]["id"])
        booking = read_booking(world["booking"]["id"])
        assert clearance["window_end_date"] == "2026-08-20", (
            f"Expected window_end_date 2026-08-20, got {clearance['window_end_date']}"
        )
        assert booking["engagement_end_date"] == "2026-08-20", (
            "Expected engagement_end_date 2026-08-20, got "
            f"{booking['engagement_end_date']} — both windows must be breached so "
            "that only the higher rung can be the one reported"
        )
        assert _showtimes_at_venue(api, world["venue"]["id"]) == [], (
            "A refused placement must leave no screening behind"
        )
        assert clearance["screenings_remaining"] == 6, (
            f"Expected screenings_remaining 6, got {clearance['screenings_remaining']}"
        )


class TestScreeningAllowance:

    def test_screening_allowance_exhausted_once_the_licence_is_used_up(self, api):
        """PRD §3.5: "The licence must have at least one screening remaining,
        otherwise `ERR_SCREENING_ALLOWANCE_EXHAUSTED` — a `screenings_remaining`
        of exactly 1 still admits one more screening, and only 0 refuses."

        PRD §2.10: "A clearance's `screenings_used` is the count of screenings
        referencing it whose status is scheduled or completed, and
        `screenings_remaining` is `max_screenings` less `screenings_used`, never
        negative; a cancelled screening releases its allowance."

        Design: Corner/validations/screening_allowance_exhausted_once_the_licence_is_used_up
        """
        world = setup_programming_baseline(
            clearance_overrides={"max_screenings": 1}
        )

        # max_screenings 1 is the smallest legal ceiling, so the first placement
        # consumes the whole allowance.
        first = place_showtime(world, "2026-08-14T12:00:00Z")
        drawn_down = read_clearance(world["clearance"]["id"])
        assert drawn_down["screenings_remaining"] == 0, (
            f"Expected screenings_remaining 0, got {drawn_down['screenings_remaining']}"
        )
        fresh_version = drawn_down["version"]

        # A different day, so no screen collision, and a fresh licence version.
        response = api.create_showtime(
            _showtime_body(world, "2026-08-15T12:00:00Z", fresh_version), PROGRAMMER
        )

        validate_error(response, ApiErrorId.ERR_SCREENING_ALLOWANCE_EXHAUSTED.value)

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["max_screenings"] == 1, (
            f"Expected max_screenings 1, got {clearance['max_screenings']}"
        )
        assert clearance["screenings_used"] == 1, (
            f"Expected screenings_used 1, got {clearance['screenings_used']}"
        )
        assert clearance["screenings_remaining"] == 0, (
            f"Expected screenings_remaining 0, got {clearance['screenings_remaining']}"
        )
        assert clearance["version"] == fresh_version, (
            f"Expected clearance version {fresh_version}, got {clearance['version']} "
            "after a refused placement"
        )

        rows = _showtimes_at_venue(api, world["venue"]["id"])
        assert [row["id"] for row in rows] == [first["id"]], (
            f"Expected exactly the one placed screening, got {[r['id'] for r in rows]}"
        )
        booking = read_booking(world["booking"]["id"])
        assert booking["scheduled_showtime_count"] == 1, (
            "Expected scheduled_showtime_count 1, got "
            f"{booking['scheduled_showtime_count']}"
        )
