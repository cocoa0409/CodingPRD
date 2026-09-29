"""Two overlap rules whose endpoints behave differently. Shift occupancy is
half-open, so touching shifts at one worksite are fine while a cross-worksite
hand-over needs half an hour of clear air. Placement capacity intervals are
closed, so two placements that merely touch at one date do overlap.
"""

from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    add_second_student_placement,
    api_client,
    create_timesheet_entry_payload,
    get_success_data,
    log_shift,
    make_employer_supervisor_headers,
    read_placement,
    read_student,
    read_worksite,
    set_clock,
    setup_proposed_placement,
    setup_two_worksite_scenarios,
    validate_error,
)

TALIA_BRANDT = {"full_name": "Talia Brandt", "birth_date": "2008-02-11"}
TERRACE_HILL = {
    "legal_name": "Terrace Hill Garden Center",
    "naics_code": "444220",
    "industry_sector": "HOSPITALITY",
}
BRAM_OSTROW = {"full_name": "Bram Ostrow", "birth_date": "2009-05-05"}
INES_KAPLAN = {"full_name": "Ines Kaplan", "birth_date": "2009-08-08"}

FIRST_PLACEMENT = {
    "pay_classification": "PAID",
    "hourly_wage_cents": 1500,
    "stipend_total_cents": 0,
    "scheduled_weekly_hours": 12.00,
    "start_on": "2026-09-07",
    "end_on": "2026-10-31",
    "credit_target_credits": 0.50,
    "credit_award_mode": "HOURS_BASED",
    "required_evaluation_cycles": 1,
    "transportation_mode": "DISTRICT_BUS",
    "commute_round_trip_miles": 0.00,
}


def _read_supervisor(worksite_id, supervisor_id):
    rows = get_success_data(api_client.list_worksite_supervisors(worksite_id, COORDINATOR))
    return next(row for row in rows if row["id"] == supervisor_id)


def _one_student_at_two_worksites_with_adjacent_shifts():
    """One adult student holds a placement at each of two worksites, and works two
    back-to-back shifts at the first of them on 2026-09-14."""
    scenario_a, scenario_b = setup_two_worksite_scenarios(
        clock="2026-09-07T08:00:00Z",
        student_overrides=TALIA_BRANDT,
        permit_class="ADULT_18_PLUS",
    )
    set_clock("2026-09-15T08:00:00Z")
    first = log_shift(scenario_a, "2026-09-14", "09:00", "12:00")
    second = log_shift(scenario_a, "2026-09-14", "12:00", "14:00")
    return scenario_a, scenario_b, first, second


def _second_placement_touching_the_first_at_one_date():
    scenario = setup_proposed_placement(
        clock="2026-09-07T08:00:00Z",
        partner_overrides=TERRACE_HILL,
        worksite_overrides={"max_concurrent_students": 1},
        supervisor_overrides={"max_student_load": 2},
        student_overrides=BRAM_OSTROW,
        permit_class="MINOR_16_17",
        placement_overrides=dict(FIRST_PLACEMENT),
    )
    second_student, response = add_second_student_placement(
        scenario,
        student_overrides=INES_KAPLAN,
        permit_class="MINOR_16_17",
        placement_overrides={
            **FIRST_PLACEMENT,
            "start_on": "2026-10-31",
            "end_on": "2026-12-18",
        },
    )
    return scenario, second_student, response


class TestShiftOccupancyIsHalfOpen:
    def test_a_shift_starting_when_another_ends_at_the_same_worksite_is_accepted(self):
        """Shift occupancy is treated as a **half-open interval** running from `start_time`
        up to but not including `end_time`, so a shift ending at 12:00 and another starting
        at 12:00 on the same `work_date` do not collide. The comparison spans every `LOGGED`
        entry of the same student on that `work_date` across all of their placements.

        Design: Difficulty/resource_temporal_overlap/student_shift_half_open_adjacency_allowed_then_cross_worksite_travel_buffer_violated
        """
        scenario_a, _scenario_b, first, second = (
            _one_student_at_two_worksites_with_adjacent_shifts()
        )

        assert first["status"] == "LOGGED"
        assert second["status"] == "LOGGED"
        assert float(first["hours_worked"]) == 3.00
        assert float(second["hours_worked"]) == 2.00
        assert float(read_placement(scenario_a.placement_id)["total_verified_hours"]) == 5.00

    def test_a_cross_worksite_shift_fifteen_minutes_later_violates_the_travel_buffer(self):
        """When the colliding entry belongs to a placement at a *different* worksite, a
        30-minute travel buffer is added to the comparison, so the student must have half an
        hour of clear time between leaving one site and starting at the other. Any collision
        is refused with `ERR_STUDENT_SCHEDULE_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/student_shift_half_open_adjacency_allowed_then_cross_worksite_travel_buffer_violated
        """
        scenario_a, scenario_b, _first, _second = (
            _one_student_at_two_worksites_with_adjacent_shifts()
        )

        response = api_client.create_timesheet_entry(
            create_timesheet_entry_payload(
                scenario_b.placement_id, "2026-09-14", "14:15", "16:00"
            ),
            make_employer_supervisor_headers(scenario_b.supervisor_id),
        )

        validate_error(response, ApiErrorId.ERR_STUDENT_SCHEDULE_OVERLAP.value)
        assert response.status_code == 422

        assert float(read_placement(scenario_b.placement_id)["total_verified_hours"]) == 0.00
        assert float(read_placement(scenario_a.placement_id)["total_verified_hours"]) == 5.00
        assert float(read_student(scenario_a.student_id)["ytd_wbl_hours"]) == 5.00


class TestCapacityIntervalsAreClosed:
    def test_a_placement_starting_on_the_end_date_of_another_exceeds_capacity(self):
        """And the worksite's aggregate capacity must hold: consider the closed interval
        from `start_on` through `end_on`, take every existing placement on the same worksite
        whose `lifecycle_status` is `PROPOSED` or `ACTIVE` whose own closed interval shares
        at least one day with it — two intervals that merely touch at an endpoint do share
        that day and therefore do overlap — and count those placements together with the
        candidate. If that count exceeds the worksite's `max_concurrent_students`, the
        creation is refused with `ERR_WORKSITE_CAPACITY_EXCEEDED`.

        Design: Difficulty/resource_temporal_overlap/worksite_capacity_closed_date_interval_rejects_touching_placement
        """
        _scenario, _second_student, response = _second_placement_touching_the_first_at_one_date()

        validate_error(response, ApiErrorId.ERR_WORKSITE_CAPACITY_EXCEEDED.value)
        assert response.status_code == 422

    def test_the_supervisor_had_room_so_only_capacity_could_have_refused_it(self):
        """Capacity is declared as `max_concurrent_students`, at least 1, and is interpreted
        as an aggregate ceiling over any overlapping date range rather than a headcount at an
        instant. The supervisor must have room, meaning `active_student_load` plus 1 is at
        most `max_student_load`, or `ERR_SUPERVISOR_LOAD_EXCEEDED`.

        Design: Difficulty/resource_temporal_overlap/worksite_capacity_closed_date_interval_rejects_touching_placement
        """
        scenario, second_student, _response = _second_placement_touching_the_first_at_one_date()

        assert read_worksite(scenario.worksite_id)["slots_committed"] == 1

        supervisor = _read_supervisor(scenario.worksite_id, scenario.supervisor_id)
        assert supervisor["max_student_load"] == 2
        assert supervisor["active_student_load"] == 1

        assert read_student(second_student["id"])["active_placement_count"] == 0
