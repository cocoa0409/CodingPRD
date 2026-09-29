"""Boundary arithmetic: the two cold-water comparisons, the coxswain deadweight
ceiling, the half-open hull window with its turnaround buffer, and the launch
driver's aggregate capacity.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_lineup_seat,
    assert_water_condition_reading,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_coxed_four,
    add_single,
    book_session,
    clear_session,
    coxswain_seat_of_entry,
    declare_coxed_four_lineup,
    enrol_athlete,
    enrol_coxswain,
    enrol_launch_driver,
    open_entry,
    open_regatta,
    post_open_reading,
    post_reading,
    read_entry,
    read_regatta,
    read_session,
    read_shell,
    set_clock_to,
    submit_entry,
    weigh_in_seat,
)

WEIGH_IN_CLOCK = "2026-08-12T06:30:00Z"


@pytest.fixture
def two_coxed_fours_awaiting_weigh_in(cast):
    """Two submitted coxed fours whose coxswains straddle the deadweight ceiling."""
    regatta = open_regatta()
    rowers = [enrol_athlete(f"Rower {index}", "COMPETITIVE", 80.0) for index in range(1, 5)]
    rower_ids = [rower["id"] for rower in rowers]
    coxswains = [enrol_coxswain("Kip Cox", 40.0), enrol_coxswain("Pip Cox", 39.9)]
    entries = []
    for index, (hull_name, cox, seed) in enumerate(
        (("Osprey", coxswains[0], 400.0), ("Merlin", coxswains[1], 402.0))
    ):
        shell = add_coxed_four(hull_name=hull_name)
        entry = open_entry(
            regatta["id"],
            shell["id"],
            cast["coach_headers"],
            event_code="MIXED_4PLUS_OPEN",
            boat_class="4+",
            seed_time_seconds=seed,
        )
        entry = declare_coxed_four_lineup(entry, cox["id"], rower_ids, cast["coach_headers"])
        entries.append(submit_entry(entry["id"], cast["coach_headers"]))
    set_clock_to(WEIGH_IN_CLOCK)
    return {"regatta": regatta, "entries": entries, "coxswains": coxswains}


@pytest.fixture
def hull_with_one_booked_window(cast, single_shell):
    """One hull carrying a single PLANNED outing from 06:00 to 07:30."""
    session = book_session(
        single_shell["id"],
        cast["coach_headers"],
        planned_start_at="2026-08-01T06:00:00Z",
        planned_end_at="2026-08-01T07:30:00Z",
    )
    return {"shell": single_shell, "session": session}


@pytest.fixture
def driver_at_capacity(cast):
    """One driver limited to a single outing, named on three overlapping bookings."""
    driver = enrol_launch_driver("Dana Driver", 1)
    hulls = [add_single(hull_name=name) for name in ("Cygnet", "Pintail", "Teal")]
    reading = post_open_reading(cast["officer_headers"], observed_at="2026-08-01T05:00:00Z")
    windows = (
        ("2026-08-01T06:00:00Z", "2026-08-01T08:00:00Z"),
        ("2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z"),
        ("2026-08-01T07:00:00Z", "2026-08-01T09:00:00Z"),
    )
    sessions = [
        book_session(
            hull["id"],
            cast["coach_headers"],
            session_kind="LEARN_TO_ROW",
            planned_start_at=start_at,
            planned_end_at=end_at,
            primary_launch_driver_member_id=driver["id"],
        )
        for hull, (start_at, end_at) in zip(hulls, windows)
    ]
    sessions[0] = clear_session(sessions[0]["id"], reading["id"], cast["officer_headers"])
    return {"hulls": hulls, "reading": reading, "sessions": sessions}


class TestColdWaterComparisons:
    def test_water_of_exactly_twelve_point_eight_is_not_cold(self, cast):
        """The single-reading comparison is strictly below the threshold.

        PRD: "The `cold_water_flag` is raised when the water temperature is
        strictly below 12.8 degrees Celsius, or when the water and air
        temperatures added together come to 30.0 degrees or less; the two
        comparisons differ deliberately — strictly below on the single water
        reading, at-or-below on the combined sum."

        Design: Difficulty/boundary_precision_check/cold_water_strict_lt_vs_inclusive_combined_sum_lte
        """
        reading = assert_water_condition_reading(
            post_reading(cast["officer_headers"], air_temp_c=25.0, water_temp_c=12.8)
        )
        assert reading["cold_water_flag"] is False, (
            "water sitting exactly on 12.8 degrees with a combined sum of 37.8 is "
            f"not cold, got {reading['cold_water_flag']}"
        )
        assert reading["posture"] == "OPEN", (
            "no closing or restricting condition holds, so the river is OPEN, got "
            f"{reading['posture']}"
        )

    def test_combined_sum_of_exactly_thirty_degrees_is_cold(self, cast):
        """The combined-sum comparison is at-or-below the threshold.

        PRD: "Otherwise it is `RESTRICTED` when the wind is 12.0 knots or more,
        or the visibility is 800 metres or less, or the `cold_water_flag` is
        raised, or the `traffic_pattern` is `NARROW_CHANNEL`. Failing all of
        those, the posture is `OPEN`."

        Design: Difficulty/boundary_precision_check/cold_water_strict_lt_vs_inclusive_combined_sum_lte
        """
        reading = assert_water_condition_reading(
            post_reading(cast["officer_headers"], air_temp_c=17.1, water_temp_c=12.9)
        )
        assert reading["cold_water_flag"] is True, (
            "water at 12.9 is not cold on its own, but 12.9 + 17.1 = 30.0 is at the "
            f"combined threshold, got {reading['cold_water_flag']}"
        )
        assert reading["posture"] == "RESTRICTED", (
            f"a raised cold-water flag restricts the river, got {reading['posture']}"
        )
        assert "version" not in reading, (
            "a reading is an immutable observation and carries no version"
        )


class TestCoxswainDeadweightCeiling:
    def test_deadweight_of_exactly_fifteen_kilograms_passes(
        self, cast, two_coxed_fours_awaiting_weigh_in
    ):
        """The ceiling comparison is strictly greater-than.

        PRD: "For a `COXSWAIN` seat, `deadweight_kg` is the club's minimum
        coxswain weight of 55.0 kilograms less the recorded weight, floored at
        zero and rounded half up to one decimal place — the sandbag the crew must
        carry."

        Design: Difficulty/boundary_precision_check/coxswain_deadweight_strict_gt_boundary_pass_and_fail
        """
        scenario = two_coxed_fours_awaiting_weigh_in
        seat_id = coxswain_seat_of_entry(scenario["entries"][0]["id"])["id"]
        seat = assert_lineup_seat(weigh_in_seat(seat_id, 40.0, cast["official_headers"]))
        assert seat["deadweight_kg"] == pytest.approx(15.0, abs=0.01), (
            f"55.0 less 40.0 is 15.0 kilograms of sandbag, got {seat['deadweight_kg']}"
        )
        assert seat["weigh_in_status"] == "PASSED", (
            f"a total of exactly 15.0 kilograms passes, got {seat['weigh_in_status']}"
        )
        assert seat["weighed_kg"] == pytest.approx(40.0, abs=0.01), (
            f"the recorded weight is stamped on the seat, got {seat['weighed_kg']}"
        )
        assert seat["weighed_by_user_id"] == cast["official"]["id"], (
            "the acting official is stamped on the seat, expected "
            f"{cast['official']['id']}, got {seat['weighed_by_user_id']}"
        )
        entry = read_entry(scenario["entries"][0]["id"])
        assert entry["status"] == "SUBMITTED", (
            f"a passing weigh-in leaves the entry SUBMITTED, got {entry['status']}"
        )

    def test_one_hundred_grams_lighter_fails_and_demotes_only_that_entry(
        self, cast, two_coxed_fours_awaiting_weigh_in
    ):
        """A tenth of a kilogram over the ceiling fails the crew.

        PRD: "The comparison is strictly greater-than: a total of exactly 15.0
        kilograms passes. Concretely, a coxswain weighing 40.0 kilograms carries
        15.0 kilograms of deadweight and is recorded `PASSED`; one weighing 39.9
        kilograms carries 15.1 and is recorded `FAILED`."

        Design: Difficulty/boundary_precision_check/coxswain_deadweight_strict_gt_boundary_pass_and_fail
        """
        scenario = two_coxed_fours_awaiting_weigh_in
        passing_seat = coxswain_seat_of_entry(scenario["entries"][0]["id"])["id"]
        weigh_in_seat(passing_seat, 40.0, cast["official_headers"])

        failing_seat = coxswain_seat_of_entry(scenario["entries"][1]["id"])["id"]
        seat = assert_lineup_seat(weigh_in_seat(failing_seat, 39.9, cast["official_headers"]))
        assert seat["deadweight_kg"] == pytest.approx(15.1, abs=0.01), (
            f"55.0 less 39.9 is 15.1 kilograms of sandbag, got {seat['deadweight_kg']}"
        )
        assert seat["weigh_in_status"] == "FAILED", (
            f"15.1 kilograms is strictly over the ceiling, got {seat['weigh_in_status']}"
        )
        assert read_entry(scenario["entries"][0]["id"])["status"] == "SUBMITTED", (
            "the passing crew is untouched by the other entry's failure"
        )
        assert read_entry(scenario["entries"][1]["id"])["status"] == "LINEUP_DECLARED", (
            "a failed weigh-in demotes its own entry SUBMITTED -> LINEUP_DECLARED"
        )
        regatta = read_regatta(scenario["regatta"]["id"])
        assert regatta["net_fee_cents"] == 13500, (
            "only the still-submitted four contributes its 13500-cent fee, got "
            f"{regatta['net_fee_cents']}"
        )


class TestHullWindowTurnaroundBuffer:
    def test_booking_inside_the_turnaround_buffer_conflicts(
        self, cast, hull_with_one_booked_window
    ):
        """The buffer is appended to the earlier outing's end before comparison.

        PRD: "the requested half-open window must not intersect the window of
        any other session on the same hull in status `PLANNED`, `CLEARED` or
        `LAUNCHED` once a 30-minute turnaround buffer has been appended to the
        earlier session's end, and a collision is rejected with
        `ERR_SHELL_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/shell_window_half_open_plus_thirty_minute_turnaround_buffer
        """
        response = api_client.create_water_session(
            {
                "shell_id": hull_with_one_booked_window["shell"]["id"],
                "session_kind": "PRACTICE",
                "planned_start_at": "2026-08-01T07:45:00Z",
                "planned_end_at": "2026-08-01T09:00:00Z",
            },
            cast["coach_headers"],
        )
        validate_error(response, ApiErrorId.ERR_SHELL_WINDOW_CONFLICT.value)

        session = read_session(hull_with_one_booked_window["session"]["id"])
        assert session["planned_end_at"] == "2026-08-01T07:30:00Z", (
            "the incumbent outing's window is untouched, got "
            f"{session['planned_end_at']}"
        )

    def test_windows_touching_the_buffered_endpoints_are_accepted(
        self, cast, hull_with_one_booked_window
    ):
        """Touching endpoints do not intersect a half-open window.

        PRD: "A booked session is `PLANNED`, with `reading_id` and
        `actual_return_at` null, `required_launch_count` 0, and
        `assigned_launch_count` set to the count of non-null values among the two
        launch-driver fields — 0, 1 or 2."

        Design: Difficulty/resource_temporal_overlap/shell_window_half_open_plus_thirty_minute_turnaround_buffer
        """
        shell_id = hull_with_one_booked_window["shell"]["id"]
        for start_at, end_at, note in (
            ("2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z", "starts as the buffer expires"),
            ("2026-08-01T04:30:00Z", "2026-08-01T05:30:00Z", "its own buffer ends at 06:00"),
        ):
            created = validate_success(
                api_client.create_water_session(
                    {
                        "shell_id": shell_id,
                        "session_kind": "PRACTICE",
                        "planned_start_at": start_at,
                        "planned_end_at": end_at,
                    },
                    cast["coach_headers"],
                ),
                expected_status=201,
            )
            assert created["status"] == "PLANNED", (
                f"the outing that {note} is booked, got {created['status']}"
            )

        rows, meta = validate_paginated(
            api_client.list_water_sessions(cast["coach_headers"], {"shell_id": shell_id})
        )
        assert meta["total_count"] == 3, (
            f"the hull carries three booked outings, got {meta['total_count']}"
        )
        for row in rows:
            assert row["status"] == "PLANNED", (
                f"outing {row['id']} should still be PLANNED, got {row['status']}"
            )


class TestLaunchDriverAggregateCapacity:
    def test_strictly_overlapping_outing_exceeds_the_supervision_limit(
        self, cast, driver_at_capacity
    ):
        """A driver already covering an overlapping outing is at capacity.

        PRD: "That count must be strictly less than the driver's
        `launch_supervision_limit`, or clearance is refused with
        `ERR_LAUNCH_DRIVER_OVERBOOKED`."

        Design: Difficulty/resource_temporal_overlap/launch_driver_aggregate_capacity_touching_windows_do_not_conflict
        """
        response = api_client.clear_water_session(
            driver_at_capacity["sessions"][2]["id"],
            {"reading_id": driver_at_capacity["reading"]["id"]},
            cast["officer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LAUNCH_DRIVER_OVERBOOKED.value)

        refused = read_session(driver_at_capacity["sessions"][2]["id"])
        assert refused["status"] == "PLANNED", (
            f"the refused outing stays PLANNED, got {refused['status']}"
        )
        assert read_shell(driver_at_capacity["hulls"][2]["id"])["status"] == "AVAILABLE", (
            "the refused outing's hull is not reserved"
        )

    def test_touching_windows_do_not_count_against_the_limit(self, cast, driver_at_capacity):
        """No turnaround buffer applies to the driver-capacity rule.

        PRD: "For each non-null launch driver, the server counts the sessions in
        status `CLEARED` or `LAUNCHED` naming that driver whose half-open window
        strictly intersects this session's window — sessions that merely touch
        endpoints do not count, and no turnaround buffer applies here, unlike the
        hull-conflict rule."

        Design: Difficulty/resource_temporal_overlap/launch_driver_aggregate_capacity_touching_windows_do_not_conflict
        """
        cleared = clear_session(
            driver_at_capacity["sessions"][1]["id"],
            driver_at_capacity["reading"]["id"],
            cast["officer_headers"],
        )
        assert cleared["status"] == "CLEARED", (
            "an outing starting exactly as the earlier one ends is not an overlap, "
            f"got {cleared['status']}"
        )
        assert cleared["required_launch_count"] == 1, (
            "a learn-to-row outing on open water needs one launch, got "
            f"{cleared['required_launch_count']}"
        )
        assert cleared["assigned_launch_count"] == 1, (
            f"one driver is named, got {cleared['assigned_launch_count']}"
        )

        response = api_client.clear_water_session(
            driver_at_capacity["sessions"][2]["id"],
            {"reading_id": driver_at_capacity["reading"]["id"]},
            cast["officer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LAUNCH_DRIVER_OVERBOOKED.value)

        assert read_shell(driver_at_capacity["hulls"][0]["id"])["status"] == "ASSIGNED", (
            "the first cleared outing holds its hull"
        )
        assert read_shell(driver_at_capacity["hulls"][1]["id"])["status"] == "ASSIGNED", (
            "the second cleared outing holds its hull"
        )
        assert read_shell(driver_at_capacity["hulls"][2]["id"])["status"] == "AVAILABLE", (
            "the twice-refused outing never reserved its hull"
        )
