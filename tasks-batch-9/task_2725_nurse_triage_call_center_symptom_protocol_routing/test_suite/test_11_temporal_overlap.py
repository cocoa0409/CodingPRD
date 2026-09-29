"""Half-open shift adjacency and the thirty-minute coverage handoff buffer."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_whole_minutes


@pytest.fixture
def nurse_on_a_day_shift(world):
    """One nurse holding a single 12:00-to-20:00 shift with the clock inside it."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z", nurse_keys=("nurse_a",), with_shifts=False
    )
    existing = world.add_shift(
        "nurse_a", start_utc="2026-08-03T12:00:00Z", end_utc="2026-08-03T20:00:00Z"
    )
    return existing


class TestShiftHalfOpenOverlap:
    def test_a_shift_starting_at_the_exact_end_of_another_is_accepted(
        self, world, nurse_on_a_day_shift
    ):
        """PRD §3.2: "The interval is half-open — the shift includes its start
        instant and excludes its end instant — which means one shift may begin at
        the exact instant another ends."

        Design: Difficulty/resource_temporal_overlap/nurse_shift_half_open_overlap_rejects_a_one_minute_straddle_but_allows_exact_adjacency
        """
        response = world.api.create_shift(
            world.nurse_id("nurse_a"),
            f.shift_payload(
                start_utc="2026-08-03T20:00:00Z", end_utc="2026-08-03T23:00:00Z"
            ),
            world.admin,
        )

        assert response.status_code == 201, (
            f"exact adjacency must be accepted, got {response.status_code}: "
            f"{response.text}"
        )

    def test_a_one_minute_straddle_of_the_end_instant_is_rejected(
        self, world, nurse_on_a_day_shift
    ):
        """PRD §3.2: "Two shifts for the same nurse conflict when the existing shift
        starts before the new one ends and the new one starts before the existing
        one ends; such a request is rejected with `ERR_SHIFT_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/nurse_shift_half_open_overlap_rejects_a_one_minute_straddle_but_allows_exact_adjacency
        """
        world.add_shift(
            "nurse_a", start_utc="2026-08-03T20:00:00Z", end_utc="2026-08-03T23:00:00Z"
        )

        response = world.api.create_shift(
            world.nurse_id("nurse_a"),
            f.shift_payload(
                start_utc="2026-08-03T19:59:00Z", end_utc="2026-08-03T21:00:00Z"
            ),
            world.admin,
        )

        validate_error(response, ApiErrorId.ERR_SHIFT_OVERLAP, 409)

    def test_the_two_accepted_shifts_carry_their_computed_minutes_and_derived_status(
        self, world, nurse_on_a_day_shift
    ):
        """PRD §3.2: "`SCHEDULED` while the clock is strictly before `start_utc`,
        `ACTIVE` while the clock is at or after `start_utc` and strictly before
        `end_utc`, and `ENDED` once the clock reaches `end_utc`."

        Design: Difficulty/resource_temporal_overlap/nurse_shift_half_open_overlap_rejects_a_one_minute_straddle_but_allows_exact_adjacency
        """
        existing = nurse_on_a_day_shift
        adjacent = world.add_shift(
            "nurse_a", start_utc="2026-08-03T20:00:00Z", end_utc="2026-08-03T23:00:00Z"
        )

        assert_whole_minutes(existing["scheduled_minutes"], 480, "day scheduled_minutes")
        assert_whole_minutes(
            adjacent["scheduled_minutes"], 180, "evening scheduled_minutes"
        )
        rows, meta = validate_paginated(
            world.api.list_shifts(world.nurse_id("nurse_a"), world.admin)
        )
        statuses = {row["start_utc"][11:16]: row["status"] for row in rows}
        assert statuses["12:00"] == "ACTIVE"
        assert statuses["20:00"] == "SCHEDULED"

    def test_the_rejected_straddle_leaves_only_the_two_valid_shifts(
        self, world, nurse_on_a_day_shift
    ):
        """PRD §3.2: "while exact adjacency, where the new start equals an existing
        end, is accepted."

        Design: Difficulty/resource_temporal_overlap/nurse_shift_half_open_overlap_rejects_a_one_minute_straddle_but_allows_exact_adjacency
        """
        world.add_shift(
            "nurse_a", start_utc="2026-08-03T20:00:00Z", end_utc="2026-08-03T23:00:00Z"
        )
        world.api.create_shift(
            world.nurse_id("nurse_a"),
            f.shift_payload(
                start_utc="2026-08-03T19:59:00Z", end_utc="2026-08-03T21:00:00Z"
            ),
            world.admin,
        )

        _, meta = validate_paginated(
            world.api.list_shifts(world.nurse_id("nurse_a"), world.admin)
        )
        assert meta["total_count"] == 2


@pytest.fixture
def practice_with_an_active_week_long_window(world):
    """An ACTIVE window from 2026-08-01 to 2026-08-08, drafted by the liaison."""
    world.bootstrap(clock="2026-07-30T12:00:00Z", nurse_keys=())
    base = world.create_coverage_window(
        as_liaison=True,
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-08T00:00:00Z",
        coverage_kind="WEEKEND",
    )
    world.activate_coverage_window(base["id"], as_liaison_for=world.practice_id)
    return base


class TestCoverageWindowThirtyMinuteBuffer:
    def test_a_twenty_nine_minute_leading_gap_is_rejected(
        self, world, practice_with_an_active_week_long_window
    ):
        """PRD §3.2: "a new window for a practice is rejected with
        `ERR_COVERAGE_WINDOW_CONFLICT` when the existing window's start minus thirty
        minutes falls before the new window's end and the new window's start falls
        before the existing window's end plus thirty minutes."

        Design: Difficulty/resource_temporal_overlap/coverage_window_thirty_minute_buffer_accepts_an_exact_gap_and_rejects_twenty_nine_minutes_on_both_sides
        """
        response = world.api.create_coverage_window(
            f.coverage_window_payload(
                world.practice_id,
                start_utc="2026-07-31T20:00:00Z",
                end_utc="2026-07-31T23:31:00Z",
                coverage_kind="NIGHTS",
            ),
            world.liaison_headers(),
        )

        validate_error(response, ApiErrorId.ERR_COVERAGE_WINDOW_CONFLICT, 409)

    def test_an_exact_thirty_minute_leading_gap_is_accepted_as_a_draft(
        self, world, practice_with_an_active_week_long_window
    ):
        """PRD §3.2: "A gap of exactly thirty minutes between two windows is
        acceptable; a gap of twenty-nine minutes is not."

        Design: Difficulty/resource_temporal_overlap/coverage_window_thirty_minute_buffer_accepts_an_exact_gap_and_rejects_twenty_nine_minutes_on_both_sides
        """
        leading = world.create_coverage_window(
            as_liaison=True,
            start_utc="2026-07-31T20:00:00Z",
            end_utc="2026-07-31T23:30:00Z",
            coverage_kind="NIGHTS",
        )

        assert leading["status"] == "DRAFT"
        assert leading["suspend_reason"] is None
        assert leading["coverage_kind"] == "NIGHTS"

    def test_a_twenty_nine_minute_trailing_gap_is_rejected_too(
        self, world, practice_with_an_active_week_long_window
    ):
        """PRD §3.2: "Coverage windows carry a mandatory thirty-minute handoff buffer
        on **both** sides".

        Design: Difficulty/resource_temporal_overlap/coverage_window_thirty_minute_buffer_accepts_an_exact_gap_and_rejects_twenty_nine_minutes_on_both_sides
        """
        world.create_coverage_window(
            as_liaison=True,
            start_utc="2026-07-31T20:00:00Z",
            end_utc="2026-07-31T23:30:00Z",
            coverage_kind="NIGHTS",
        )

        response = world.api.create_coverage_window(
            f.coverage_window_payload(
                world.practice_id,
                start_utc="2026-08-08T00:29:00Z",
                end_utc="2026-08-08T08:00:00Z",
                coverage_kind="OVERFLOW",
            ),
            world.liaison_headers(),
        )

        validate_error(response, ApiErrorId.ERR_COVERAGE_WINDOW_CONFLICT, 409)

    def test_the_practice_ends_with_exactly_three_windows_on_both_exact_gaps(
        self, world, practice_with_an_active_week_long_window
    ):
        """PRD §3.2: "Comparison is against every existing window of that practice
        whose `status` is `DRAFT` or `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/coverage_window_thirty_minute_buffer_accepts_an_exact_gap_and_rejects_twenty_nine_minutes_on_both_sides
        """
        world.create_coverage_window(
            as_liaison=True,
            start_utc="2026-07-31T20:00:00Z",
            end_utc="2026-07-31T23:30:00Z",
            coverage_kind="NIGHTS",
        )

        trailing = world.create_coverage_window(
            as_liaison=True,
            start_utc="2026-08-08T00:30:00Z",
            end_utc="2026-08-08T08:00:00Z",
            coverage_kind="OVERFLOW",
        )

        assert trailing["status"] == "DRAFT"
        _, meta = validate_paginated(
            world.api.list_practice_coverage_windows(
                world.practice_id, world.liaison_headers()
            )
        )
        assert meta["total_count"] == 3
