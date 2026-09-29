"""Three requests that each break two rules at once. The global ladder decides
which failure is reported, and in every case the earlier rung wins even though
the later one is just as true of the same request.
"""

from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    add_second_student_placement,
    api_client,
    block_placement_with_critical_incident,
    create_placement_payload,
    create_timesheet_entry_payload,
    enrol_student_with_issued_permit,
    get_success_data,
    list_entries,
    make_employer_supervisor_headers,
    read_placement,
    read_student,
    read_worksite,
    set_clock,
    setup_agreement_ready,
    setup_active_placement,
    setup_proposed_placement,
    validate_error,
)

QUARRY_BEND = {
    "legal_name": "Quarry Bend Supply",
    "naics_code": "423320",
    "industry_sector": "CONSTRUCTION",
}
SAM_TEAGUE = {"full_name": "Sam Teague", "birth_date": "2009-09-12"}
BEACON_ROOFING = {
    "legal_name": "Beacon Roofing Systems",
    "naics_code": "238160",
    "industry_sector": "CONSTRUCTION",
}
PIPER_NOLEN = {"full_name": "Piper Nolen", "birth_date": "2009-04-04"}
WILLOW_PARK = {
    "legal_name": "Willow Park Veterinary",
    "naics_code": "541940",
    "industry_sector": "HEALTHCARE",
}
OMAR_REDDICK = {"full_name": "Omar Reddick", "birth_date": "2009-02-08"}
ELLE_BAPTISTE = {"full_name": "Elle Baptiste", "birth_date": "2009-07-21"}

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


def _blocked_placement_then_overlong_shift():
    """A blocked placement, and a six-hour instructional-day shift that would also
    breach the 4.00-hour daily ceiling of the `MINOR_16_17` band."""
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="CON-115",
        credit_hours_target=60.00,
        partner_overrides=QUARRY_BEND,
        student_overrides=SAM_TEAGUE,
        permit_class="MINOR_16_17",
        placement_overrides=dict(ONE_CYCLE_PLACEMENT),
    )
    set_clock("2026-09-15T08:00:00Z")
    block_placement_with_critical_incident(
        scenario, "2026-09-14T10:05:00Z", injury_type="FRACTURE"
    )
    response = api_client.create_timesheet_entry(
        create_timesheet_entry_payload(scenario.placement_id, "2026-09-14", "08:00", "14:00"),
        make_employer_supervisor_headers(scenario.supervisor_id),
    )
    return scenario, response


def _minor_at_a_prohibited_hazard_site_on_a_sub_floor_wage():
    """A minor placed at a `PROHIBITED_HAZARD` worksite, on an hourly wage that is
    also below the applicable minimum."""
    set_clock("2026-09-07T08:00:00Z")
    scenario = setup_agreement_ready(
        partner_overrides=BEACON_ROOFING,
        worksite_overrides={"hazard_class": "PROHIBITED_HAZARD"},
    )
    scenario.student, scenario.permit = enrol_student_with_issued_permit(
        permit_class="MINOR_16_17",
        hazardous_endorsement=True,
        **PIPER_NOLEN,
    )
    worksite = read_worksite(scenario.worksite_id)
    response = api_client.create_placement(
        create_placement_payload(
            scenario.student_id,
            scenario.worksite_id,
            scenario.agreement_id,
            scenario.supervisor_id,
            worksite["version"],
            **{**ONE_CYCLE_PLACEMENT, "hourly_wage_cents": 900},
        ),
        COORDINATOR,
    )
    return scenario, response


def _second_placement_over_both_worksite_capacity_and_supervisor_load():
    """A worksite with room for one student and a supervisor with room for one
    student, then a second overlapping placement that breaches both ceilings."""
    scenario = setup_proposed_placement(
        clock="2026-09-07T08:00:00Z",
        partner_overrides=WILLOW_PARK,
        worksite_overrides={"max_concurrent_students": 1},
        supervisor_overrides={"max_student_load": 1},
        student_overrides=OMAR_REDDICK,
        permit_class="MINOR_16_17",
        placement_overrides=dict(ONE_CYCLE_PLACEMENT),
    )
    second_student, response = add_second_student_placement(
        scenario,
        student_overrides=ELLE_BAPTISTE,
        permit_class="MINOR_16_17",
        placement_overrides={
            **ONE_CYCLE_PLACEMENT,
            "start_on": "2026-10-01",
            "end_on": "2026-12-18",
        },
    )
    return scenario, second_student, response


class TestBlockedStateOutranksHourCap:
    def test_the_compliance_block_is_reported_rather_than_the_daily_cap(self):
        """When several rules could reject the same request, the outcome is
        deterministic: the checks below are evaluated in this order and the **first**
        failure is the one reported. 18. Placement's compliance dimension is not blocked —
        `ERR_PLACEMENT_COMPLIANCE_BLOCKED` (409). 33. Daily hour ledger stays within cap —
        `ERR_DAILY_HOUR_CAP_EXCEEDED` (422).

        Design: Difficulty/priority_pair_validation_conflict/blocked_placement_state_error_precedes_daily_hour_cap_on_timesheet
        """
        _scenario, response = _blocked_placement_then_overlong_shift()

        validate_error(response, ApiErrorId.ERR_PLACEMENT_COMPLIANCE_BLOCKED.value)
        assert response.status_code == 409

    def test_the_rejected_shift_leaves_the_hour_ledger_empty(self):
        """While a placement's `compliance_status` is `BLOCKED`, six operations are barred
        and each reports `ERR_PLACEMENT_COMPLIANCE_BLOCKED`: logging a timesheet entry,
        submitting an evaluation, submitting a reflection, completing the placement,
        settling its wages, and awarding its credit.

        Design: Difficulty/priority_pair_validation_conflict/blocked_placement_state_error_precedes_daily_hour_cap_on_timesheet
        """
        scenario, _response = _blocked_placement_then_overlong_shift()

        assert float(read_placement(scenario.placement_id)["total_verified_hours"]) == 0.00
        assert list_entries(scenario.placement_id) == []


class TestHazardCheckOutranksWageFloor:
    def test_the_hazard_prohibition_is_reported_rather_than_the_wage_floor(self):
        """A minor may never be placed at a worksite whose `hazard_class` is
        `PROHIBITED_HAZARD`, and such an attempt is refused with
        `ERR_HAZARDOUS_OCCUPATION_PROHIBITED`. 29. Prohibited hazardous occupation is not
        being assigned to a minor — `ERR_HAZARDOUS_OCCUPATION_PROHIBITED` (422). 50. Paid
        wage meets the applicable floor — `ERR_WAGE_BELOW_MINIMUM` (422).

        Design: Difficulty/priority_pair_validation_conflict/hazardous_occupation_error_precedes_wage_floor_on_placement_create
        """
        _scenario, response = _minor_at_a_prohibited_hazard_site_on_a_sub_floor_wage()

        validate_error(response, ApiErrorId.ERR_HAZARDOUS_OCCUPATION_PROHIBITED.value)
        assert response.status_code == 422

    def test_the_refused_creation_commits_no_slot(self):
        """A `PAID` placement must pay at least 1500 cents per hour, or at least 1275
        cents per hour when the student's `student_learner_certificate` is true — that
        certificate is exactly what buys the reduced learner floor — and a wage below the
        applicable floor is refused with `ERR_WAGE_BELOW_MINIMUM`. Creation also increments
        the host worksite's `slots_committed` by 1, the supervisor's `active_student_load`
        by 1 and the student's `active_placement_count` by 1, and increments the worksite's
        `version` by 1.

        Design: Difficulty/priority_pair_validation_conflict/hazardous_occupation_error_precedes_wage_floor_on_placement_create
        """
        scenario, _response = _minor_at_a_prohibited_hazard_site_on_a_sub_floor_wage()

        assert read_worksite(scenario.worksite_id)["slots_committed"] == 0
        assert read_student(scenario.student_id)["active_placement_count"] == 0


class TestWorksiteCapacityOutranksSupervisorLoad:
    def test_the_worksite_capacity_ceiling_is_reported_rather_than_the_supervisor_load(self):
        """If that count exceeds the worksite's `max_concurrent_students`, the creation is
        refused with `ERR_WORKSITE_CAPACITY_EXCEEDED`. 40. Worksite concurrent capacity is
        respected — `ERR_WORKSITE_CAPACITY_EXCEEDED` (422). 44. Supervisor student load is
        respected — `ERR_SUPERVISOR_LOAD_EXCEEDED` (422).

        Design: Difficulty/priority_pair_validation_conflict/worksite_capacity_error_precedes_supervisor_load_on_placement_create
        """
        _scenario, _second_student, response = (
            _second_placement_over_both_worksite_capacity_and_supervisor_load()
        )

        validate_error(response, ApiErrorId.ERR_WORKSITE_CAPACITY_EXCEEDED.value)
        assert response.status_code == 422

    def test_the_first_placement_keeps_the_only_slot_and_the_only_load_unit(self):
        """The supervisor must have room, meaning `active_student_load` plus 1 is at most
        `max_student_load`, or `ERR_SUPERVISOR_LOAD_EXCEEDED`. `Worksite.slots_committed`
        counts the worksite's placements whose `lifecycle_status` is `PROPOSED` or
        `ACTIVE`.

        Design: Difficulty/priority_pair_validation_conflict/worksite_capacity_error_precedes_supervisor_load_on_placement_create
        """
        scenario, second_student, _response = (
            _second_placement_over_both_worksite_capacity_and_supervisor_load()
        )

        assert read_worksite(scenario.worksite_id)["slots_committed"] == 1
        assert _read_supervisor(scenario.worksite_id, scenario.supervisor_id)[
            "active_student_load"
        ] == 1
        assert read_student(second_student["id"])["active_placement_count"] == 0
