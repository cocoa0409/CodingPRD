"""Clearing crews onto the water: launch coverage, driver capacity and the hull
reservation that clearance takes out.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_water_condition_reading,
    assert_water_session,
    validate_error,
)
from test_helpers.fixtures import (
    add_single,
    book_session,
    clear_session,
    enrol_athlete,
    enrol_launch_driver,
    launch_session,
    post_open_reading,
    post_reading,
    read_member,
    read_session,
    read_shell,
    return_session,
    set_clock_to,
)


@pytest.fixture
def cold_restricted_learn_to_row(cast):
    """A learn-to-row outing on a cold, restricted river with both launches crewed."""
    primary = enrol_launch_driver("Dave Driver", 2)
    secondary = enrol_launch_driver("Della Driver", 2)
    novice = enrol_athlete("Novice Nell", "LEARN_TO_ROW", 65.0)
    shell = add_single(hull_name="Cygnet")
    reading = post_reading(cast["officer_headers"], air_temp_c=12.0, water_temp_c=10.0)
    session = book_session(
        shell["id"],
        cast["coach_headers"],
        session_kind="LEARN_TO_ROW",
        planned_start_at="2026-08-01T06:00:00Z",
        planned_end_at="2026-08-01T07:00:00Z",
        athlete_member_ids=[novice["id"]],
        primary_launch_driver_member_id=primary["id"],
        secondary_launch_driver_member_id=secondary["id"],
    )
    return {"shell": shell, "reading": reading, "session": session}


@pytest.fixture
def one_driver_two_outings(cast):
    """One driver at a supervision limit of one, spread across two overlapping outings."""
    driver = enrol_launch_driver("Dave Driver", 1)
    novice = enrol_athlete("Novice Nell", "LEARN_TO_ROW", 65.0)
    first_hull = add_single(hull_name="Cygnet")
    second_hull = add_single(hull_name="Pintail")
    open_reading = post_open_reading(cast["officer_headers"], observed_at="2026-08-01T05:00:00Z")
    cold_reading = post_reading(
        cast["officer_headers"],
        observed_at="2026-08-01T05:30:00Z",
        air_temp_c=12.0,
        water_temp_c=10.0,
    )
    first = book_session(
        first_hull["id"],
        cast["coach_headers"],
        session_kind="PRACTICE",
        planned_start_at="2026-08-01T06:00:00Z",
        planned_end_at="2026-08-01T08:00:00Z",
        primary_launch_driver_member_id=driver["id"],
    )
    first = clear_session(first["id"], open_reading["id"], cast["officer_headers"])
    second = book_session(
        second_hull["id"],
        cast["coach_headers"],
        session_kind="LEARN_TO_ROW",
        planned_start_at="2026-08-01T07:00:00Z",
        planned_end_at="2026-08-01T09:00:00Z",
        athlete_member_ids=[novice["id"]],
        primary_launch_driver_member_id=driver["id"],
    )
    return {
        "first_hull": first_hull,
        "second_hull": second_hull,
        "cold_reading": cold_reading,
        "first": first,
        "second": second,
    }


@pytest.fixture
def two_outings_one_hull(cast):
    """Two outings queued on one hull, the earlier of them already cleared."""
    rower = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
    shell = add_single(hull_name="Kingfisher")
    reading = post_open_reading(cast["officer_headers"], observed_at="2026-08-01T05:00:00Z")
    first = book_session(
        shell["id"],
        cast["coach_headers"],
        planned_start_at="2026-08-01T06:00:00Z",
        planned_end_at="2026-08-01T07:00:00Z",
        athlete_member_ids=[rower["id"]],
    )
    first = clear_session(first["id"], reading["id"], cast["officer_headers"])
    second = book_session(
        shell["id"],
        cast["coach_headers"],
        planned_start_at="2026-08-01T08:00:00Z",
        planned_end_at="2026-08-01T09:00:00Z",
    )
    return {
        "shell": shell,
        "rower": rower,
        "reading": reading,
        "first": first,
        "second": second,
    }


class TestLaunchCoverageRequirement:
    def test_three_coverage_conditions_are_capped_at_two_launches(
        self, cast, cold_restricted_learn_to_row
    ):
        """A learn-to-row outing on a cold, restricted river still needs only two.

        PRD: "The total is then capped at 2, which is the club's maximum launch
        commitment per outing — so a learn-to-row outing on a cold, restricted
        river still requires only two launches."

        Design: Difficulty/combinatorial_formula/session_launch_requirement_nested_min_over_three_flags_mode_a
        """
        reading = assert_water_condition_reading(cold_restricted_learn_to_row["reading"])
        assert reading["cold_water_flag"] is True, (
            "water at 10.0 degrees is strictly below 12.8, so the cold-water flag "
            f"is raised, got {reading['cold_water_flag']}"
        )
        assert reading["posture"] == "RESTRICTED", (
            f"a raised cold-water flag restricts the river, got {reading['posture']}"
        )

        session = assert_water_session(
            clear_session(
                cold_restricted_learn_to_row["session"]["id"],
                reading["id"],
                cast["officer_headers"],
            )
        )
        assert session["required_launch_count"] == 2, (
            "learn-to-row plus cold water plus a restricted posture raises three "
            f"launches, capped at 2, got {session['required_launch_count']}"
        )
        assert session["assigned_launch_count"] == 2, (
            "both launch-driver fields are filled, so two launches are assigned, "
            f"got {session['assigned_launch_count']}"
        )
        assert session["status"] == "CLEARED", (
            f"the assigned count meets the requirement, got {session['status']}"
        )

    def test_clearance_records_the_named_reading_and_reserves_the_hull(
        self, cast, cold_restricted_learn_to_row
    ):
        """The reading named in the request is the one the decision hangs on.

        PRD: "A successful clearance moves the session `PLANNED → CLEARED` and
        drives the hull `AVAILABLE → ASSIGNED`."

        Design: Difficulty/combinatorial_formula/session_launch_requirement_nested_min_over_three_flags_mode_a
        """
        reading = cold_restricted_learn_to_row["reading"]
        session = clear_session(
            cold_restricted_learn_to_row["session"]["id"],
            reading["id"],
            cast["officer_headers"],
        )
        assert session["reading_id"] == reading["id"], (
            "the named reading is persisted on the session, expected "
            f"{reading['id']}, got {session['reading_id']}"
        )
        shell = read_shell(cold_restricted_learn_to_row["shell"]["id"])
        assert shell["status"] == "ASSIGNED", (
            f"clearance reserves the hull, got {shell['status']}"
        )


class TestCoveragePrecedenceOverDriverCapacity:
    def test_coverage_shortfall_outranks_driver_overbooking(self, cast, one_driver_two_outings):
        """Both the coverage rule and the capacity rule bite; coverage is reported.

        PRD: "Clearance is refused with `ERR_LAUNCH_COVERAGE_INSUFFICIENT` when
        the assigned count is below the required count."

        Design: Difficulty/priority_pair_validation_conflict/clear_launch_coverage_safety_outranks_driver_overbooking_temporal
        """
        response = api_client.clear_water_session(
            one_driver_two_outings["second"]["id"],
            {"reading_id": one_driver_two_outings["cold_reading"]["id"]},
            cast["officer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LAUNCH_COVERAGE_INSUFFICIENT.value)

    def test_refused_clearance_leaves_the_outing_and_hull_untouched(
        self, cast, one_driver_two_outings
    ):
        """A rejected clearance writes nothing at all.

        PRD: "Clearance names a single `reading_id`, and the reading it names is
        the one the decision is recorded against; on success `reading_id` is
        persisted on the session and `required_launch_count` is recomputed from
        that reading."

        Design: Difficulty/priority_pair_validation_conflict/clear_launch_coverage_safety_outranks_driver_overbooking_temporal
        """
        api_client.clear_water_session(
            one_driver_two_outings["second"]["id"],
            {"reading_id": one_driver_two_outings["cold_reading"]["id"]},
            cast["officer_headers"],
        )
        second = assert_water_session(read_session(one_driver_two_outings["second"]["id"]))
        assert second["status"] == "PLANNED", (
            f"the refused outing stays PLANNED, got {second['status']}"
        )
        assert second["reading_id"] is None, (
            f"no reading is recorded against a refusal, got {second['reading_id']}"
        )
        assert second["required_launch_count"] == 0, (
            "required_launch_count is only recomputed on success, expected the "
            f"booking value of 0, got {second['required_launch_count']}"
        )
        assert second["assigned_launch_count"] == 1, (
            "one launch driver was named at booking, got "
            f"{second['assigned_launch_count']}"
        )
        hull = read_shell(one_driver_two_outings["second_hull"]["id"])
        assert hull["status"] == "AVAILABLE", (
            f"the refused outing's hull is not reserved, got {hull['status']}"
        )
        first = read_session(one_driver_two_outings["first"]["id"])
        assert first["status"] == "CLEARED", (
            f"the earlier outing keeps its clearance, got {first['status']}"
        )


class TestHullAvailabilityGatesClearance:
    def test_clearance_refused_while_the_hull_is_out_with_another_crew(
        self, cast, two_outings_one_hull
    ):
        """A hull already reserved cannot be cleared to a second crew.

        PRD: "Clearance requires the hull to be `AVAILABLE`
        (`ERR_SHELL_NOT_AVAILABLE`) and the named reading's `posture` to be
        `OPEN` or `RESTRICTED` — a `CLOSED` river yields `ERR_WATER_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/session_clearance_gated_on_shell_availability_both_directions
        """
        response = api_client.clear_water_session(
            two_outings_one_hull["second"]["id"],
            {"reading_id": two_outings_one_hull["reading"]["id"]},
            cast["officer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_SHELL_NOT_AVAILABLE.value)

        second = read_session(two_outings_one_hull["second"]["id"])
        assert second["status"] == "PLANNED", (
            f"the refused outing stays PLANNED, got {second['status']}"
        )
        assert second["reading_id"] is None, (
            f"no reading is recorded against a refusal, got {second['reading_id']}"
        )

    def test_logging_the_first_crew_back_in_frees_the_hull_for_the_second(
        self, cast, two_outings_one_hull
    ):
        """The return releases the hull, and the same clearance then succeeds.

        PRD: "Logging the crew back in, again optionally with a `note`, requires
        status `LAUNCHED` (`ERR_SESSION_NOT_LAUNCHED`), moves the session
        `LAUNCHED → RETURNED`, stamps `actual_return_at` from the logical clock,
        releases the hull `ASSIGNED → AVAILABLE`, and recomputes
        `logged_session_count` for every member named in `athlete_member_ids`"

        Design: Difficulty/cross_entity_state_dependency/session_clearance_gated_on_shell_availability_both_directions
        """
        api_client.clear_water_session(
            two_outings_one_hull["second"]["id"],
            {"reading_id": two_outings_one_hull["reading"]["id"]},
            cast["officer_headers"],
        )
        set_clock_to("2026-08-01T06:00:00Z")
        launch_session(two_outings_one_hull["first"]["id"], cast["officer_headers"])
        first = return_session(two_outings_one_hull["first"]["id"], cast["officer_headers"])
        assert first["status"] == "RETURNED", (
            f"the crew is logged back in, got {first['status']}"
        )
        assert read_shell(two_outings_one_hull["shell"]["id"])["status"] == "AVAILABLE", (
            "the return releases the hull"
        )
        rower = read_member(two_outings_one_hull["rower"]["id"])
        assert rower["logged_session_count"] == 1, (
            "the seated athlete has one completed outing on record, got "
            f"{rower['logged_session_count']}"
        )

        second = assert_water_session(
            clear_session(
                two_outings_one_hull["second"]["id"],
                two_outings_one_hull["reading"]["id"],
                cast["officer_headers"],
            )
        )
        assert second["status"] == "CLEARED", (
            f"the freed hull admits the second clearance, got {second['status']}"
        )
        assert second["required_launch_count"] == 0, (
            "an open-water practice outing needs no safety launch, got "
            f"{second['required_launch_count']}"
        )
        assert read_shell(two_outings_one_hull["shell"]["id"])["status"] == "ASSIGNED", (
            "the second clearance reserves the hull again"
        )
