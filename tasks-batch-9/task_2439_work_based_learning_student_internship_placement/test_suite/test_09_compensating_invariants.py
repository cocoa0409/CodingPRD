"""Two compensating actions that have to leave the books exactly as they were:
voiding a shift must unwind every hour-derived figure, and terminating a
placement must hand back all three committed-capacity counters so the released
slot is immediately reusable.
"""

from test_helpers import (
    COORDINATOR,
    add_second_student_placement,
    api_client,
    get_success_data,
    list_entries,
    log_shifts,
    read_placement,
    read_student,
    read_worksite,
    set_clock,
    setup_active_placement,
    terminate_placement_payload,
    validate_success,
    void_timesheet_entry_payload,
)

COPPERFIELD = {
    "legal_name": "Copperfield Auto Care",
    "naics_code": "811111",
    "industry_sector": "MANUFACTURING",
}
OTIS_VERLAINE = {
    "full_name": "Otis Verlaine",
    "birth_date": "2009-03-03",
    "student_learner_certificate": True,
}
HALCYON_RADIO = {
    "legal_name": "Halcyon Community Radio",
    "naics_code": "515112",
    "industry_sector": "PUBLIC_ADMINISTRATION",
}
WREN_KOVACS = {"full_name": "Wren Kovacs", "birth_date": "2009-06-06"}
DOV_ASHKENAZI = {"full_name": "Dov Ashkenazi", "birth_date": "2009-09-19"}

ONE_CYCLE_PLACEMENT = {
    "pay_classification": "PAID",
    "hourly_wage_cents": 1500,
    "stipend_total_cents": 0,
    "scheduled_weekly_hours": 12.00,
    "start_on": "2026-09-07",
    "end_on": "2026-12-18",
    "credit_target_credits": 0.50,
    "credit_award_mode": "HOURS_BASED",
    "required_evaluation_cycles": 1,
    "transportation_mode": "DISTRICT_BUS",
    "commute_round_trip_miles": 0.00,
}


def _read_supervisor(worksite_id, supervisor_id):
    rows = get_success_data(api_client.list_worksite_supervisors(worksite_id, COORDINATOR))
    return next(row for row in rows if row["id"] == supervisor_id)


def _three_shifts_with_the_middle_one_voided():
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="AUT-220",
        credit_hours_target=60.00,
        partner_overrides=COPPERFIELD,
        student_overrides=OTIS_VERLAINE,
        permit_class="MINOR_16_17",
        placement_overrides={
            **ONE_CYCLE_PLACEMENT,
            "hourly_wage_cents": 1275,
            "transportation_mode": "PUBLIC_TRANSIT",
        },
    )
    set_clock("2026-09-14T08:00:00Z")
    entries = log_shifts(
        scenario,
        [
            ("2026-09-08", "08:00", "11:20"),
            ("2026-09-09", "08:00", "11:20"),
            ("2026-09-10", "08:00", "11:20"),
        ],
    )
    # The full ledger is observed before the compensating action.
    validate_success(api_client.get_wage_preview(scenario.placement_id, COORDINATOR))
    validate_success(
        api_client.void_timesheet_entry(
            entries[1]["id"],
            void_timesheet_entry_payload("Shift was cancelled by the employer after the fact"),
            COORDINATOR,
        )
    )
    return scenario, entries


def _terminated_placement_at_a_single_slot_worksite():
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="BRD-140",
        credit_hours_target=60.00,
        partner_overrides=HALCYON_RADIO,
        worksite_overrides={"max_concurrent_students": 1},
        supervisor_overrides={"max_student_load": 1},
        student_overrides=WREN_KOVACS,
        permit_class="MINOR_16_17",
        placement_overrides=dict(ONE_CYCLE_PLACEMENT),
    )
    set_clock("2026-09-14T08:00:00Z")
    validate_success(
        api_client.terminate_placement(
            scenario.placement_id,
            terminate_placement_payload("Student transferred out of the district"),
            COORDINATOR,
        )
    )
    return scenario


class TestVoidRestoresTheHourLedger:
    def test_voiding_the_middle_shift_recomputes_every_hour_derived_figure(self):
        """Voiding is a compensating action and must restore every hour-derived ledger
        exactly: the placement's `total_verified_hours`, `provisional_wage_cents` and
        `final_wage_cents` and the student's `ytd_wbl_hours` are all recomputed, and the
        voided entry is removed from the daily and weekly child-labor totals as well, so
        hours freed by a void become available for a subsequent shift.

        Design: Difficulty/compensating_invariant/voiding_a_timesheet_entry_restores_the_verified_hour_ledger
        """
        scenario, _entries = _three_shifts_with_the_middle_one_voided()

        placement = read_placement(scenario.placement_id)
        assert float(placement["total_verified_hours"]) == 6.66
        assert placement["provisional_wage_cents"] == 8492
        assert placement["final_wage_cents"] == 8492

    def test_only_the_voided_entry_changes_state_and_the_student_ledger_follows(self):
        """A new entry has `status` of `LOGGED` with `voided_reason` and
        `voided_by_user_id` null. `Student.ytd_wbl_hours` sums the same quantity across every
        placement of the student.

        Design: Difficulty/compensating_invariant/voiding_a_timesheet_entry_restores_the_verified_hour_ledger
        """
        scenario, entries = _three_shifts_with_the_middle_one_voided()

        stored = {row["id"]: row for row in list_entries(scenario.placement_id)}
        assert stored[entries[0]["id"]]["status"] == "LOGGED"
        assert stored[entries[1]["id"]]["status"] == "VOIDED"
        assert stored[entries[2]["id"]]["status"] == "LOGGED"

        assert float(read_student(scenario.student_id)["ytd_wbl_hours"]) == 6.66


class TestTerminationReleasesCommittedCapacity:
    def test_termination_hands_back_all_three_committed_counters(self):
        """Terminating a `PROPOSED` placement stores the supplied `termination_reason` and
        decrements the worksite's `slots_committed`, the supervisor's `active_student_load`
        and the student's `active_placement_count` each by 1. Terminating an `ACTIVE`
        placement does the same and additionally moves every evaluation cycle of that
        placement whose `cycle_status` is `OPEN`, `PARTIAL` or `SUSPENDED` to `CANCELLED` —
        note that a suspended cycle is swept up here, which is not the case when an agreement
        termination cancels cycles.

        Design: Difficulty/compensating_invariant/terminating_a_placement_releases_every_committed_slot_counter
        """
        scenario = _terminated_placement_at_a_single_slot_worksite()

        assert read_placement(scenario.placement_id)["lifecycle_status"] == "TERMINATED"
        assert read_worksite(scenario.worksite_id)["slots_committed"] == 0
        assert _read_supervisor(scenario.worksite_id, scenario.supervisor_id)[
            "active_student_load"
        ] == 0
        assert read_student(scenario.student_id)["active_placement_count"] == 0

    def test_the_released_slot_can_immediately_carry_another_student(self):
        """Creation also increments the host worksite's `slots_committed` by 1, the
        supervisor's `active_student_load` by 1 and the student's `active_placement_count` by
        1, and increments the worksite's `version` by 1. If that count exceeds the worksite's
        `max_concurrent_students`, the creation is refused with
        `ERR_WORKSITE_CAPACITY_EXCEEDED`.

        Design: Difficulty/compensating_invariant/terminating_a_placement_releases_every_committed_slot_counter
        """
        scenario = _terminated_placement_at_a_single_slot_worksite()

        _second_student, response = add_second_student_placement(
            scenario,
            student_overrides=DOV_ASHKENAZI,
            permit_class="MINOR_16_17",
            placement_overrides={
                **ONE_CYCLE_PLACEMENT,
                "start_on": "2026-09-14",
                "end_on": "2026-12-18",
            },
        )

        second_placement = validate_success(response, expected_status=201)
        assert second_placement["lifecycle_status"] == "PROPOSED"

        assert read_worksite(scenario.worksite_id)["slots_committed"] == 1
        assert _read_supervisor(scenario.worksite_id, scenario.supervisor_id)[
            "active_student_load"
        ] == 1
