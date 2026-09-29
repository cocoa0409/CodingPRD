"""Two writes that are refused because of the state of a neighbouring entity
rather than anything wrong with the request itself: a placement blocked by an
agreement that has not finished its negotiation, and a shift blocked by a permit
that was revoked after the placement had already gone active.
"""

from test_helpers import (
    COORDINATOR,
    DRAFTER,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_placement_payload,
    create_timesheet_entry_payload,
    enrol_student_with_issued_permit,
    get_success_data,
    list_entries,
    make_employer_supervisor_headers,
    read_agreement,
    read_permit,
    read_placement,
    read_student,
    read_worksite,
    revoke_work_permit,
    set_clock,
    setup_active_placement,
    setup_partner_worksite_supervisor,
    validate_error,
)

STONEBRIDGE = {
    "legal_name": "Stonebridge Dental Group",
    "naics_code": "621210",
    "industry_sector": "HEALTHCARE",
}
CYRUS_BEHN = {"full_name": "Cyrus Behn", "birth_date": "2009-10-09"}
GRAFTON_PRINT = {
    "legal_name": "Grafton Print Works",
    "naics_code": "323111",
    "industry_sector": "MANUFACTURING",
}
MARISOL_VEGA = {"full_name": "Marisol Vega", "birth_date": "2009-01-15"}

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


def _placement_attempted_under_a_countersigned_but_unexecuted_agreement():
    set_clock("2026-09-07T08:00:00Z")
    scenario = setup_partner_worksite_supervisor(partner_overrides=STONEBRIDGE)
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(
                scenario.partner_id, scenario.worksite_id, scenario.supervisor_id
            ),
            DRAFTER,
        )
    )
    get_success_data(
        api_client.employer_sign_agreement(
            agreement["id"], {}, make_employer_supervisor_headers(scenario.supervisor_id)
        )
    )
    scenario.agreement = read_agreement(agreement["id"])
    scenario.student, scenario.permit = enrol_student_with_issued_permit(
        permit_class="MINOR_16_17", **CYRUS_BEHN
    )
    worksite = read_worksite(scenario.worksite_id)
    response = api_client.create_placement(
        create_placement_payload(
            scenario.student_id,
            scenario.worksite_id,
            scenario.agreement_id,
            scenario.supervisor_id,
            worksite["version"],
            **ONE_CYCLE_PLACEMENT,
        ),
        COORDINATOR,
    )
    return scenario, response


def _shift_attempted_after_the_permit_was_revoked():
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="GRA-160",
        credit_hours_target=60.00,
        partner_overrides=GRAFTON_PRINT,
        student_overrides=MARISOL_VEGA,
        permit_class="MINOR_16_17",
        placement_overrides=dict(ONE_CYCLE_PLACEMENT),
    )
    set_clock("2026-09-14T08:00:00Z")
    revoke_work_permit(scenario.permit_id, "Guardian withdrew consent for the permit")
    response = api_client.create_timesheet_entry(
        create_timesheet_entry_payload(scenario.placement_id, "2026-09-11", "15:00", "18:00"),
        make_employer_supervisor_headers(scenario.supervisor_id),
    )
    return scenario, response


class TestPlacementDependsOnAgreementState:
    def test_a_placement_cannot_be_created_before_the_agreement_is_executed(self):
        """The referenced agreement must have reached `EXECUTED`, or the creation is
        refused with `ERR_AGREEMENT_NOT_EXECUTED`. Countersignature on the employer side
        moves the agreement `PENDING_EMPLOYER → PENDING_DISTRICT`.

        Design: Difficulty/cross_entity_state_dependency/placement_create_blocked_while_agreement_still_pending_district
        """
        scenario, response = _placement_attempted_under_a_countersigned_but_unexecuted_agreement()

        validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED.value)
        assert response.status_code == 409
        assert read_agreement(scenario.agreement_id)["status"] == "PENDING_DISTRICT"

    def test_the_refused_placement_commits_no_capacity_anywhere(self):
        """Creation also increments the host worksite's `slots_committed` by 1, the
        supervisor's `active_student_load` by 1 and the student's `active_placement_count`
        by 1, and increments the worksite's `version` by 1.

        Design: Difficulty/cross_entity_state_dependency/placement_create_blocked_while_agreement_still_pending_district
        """
        scenario, _response = _placement_attempted_under_a_countersigned_but_unexecuted_agreement()

        assert read_worksite(scenario.worksite_id)["slots_committed"] == 0
        assert read_student(scenario.student_id)["active_placement_count"] == 0


class TestTimesheetDependsOnPermitState:
    def test_a_shift_is_refused_once_the_students_permit_has_been_revoked(self):
        """The student must also hold a valid permit for the band at the moment of logging:
        an `ISSUED` permit, `expires_on` on or after the clock date, `permit_class` matching
        the placement's `permit_class_at_start`; otherwise `ERR_WORK_PERMIT_INVALID`. This
        is the check that catches a permit revoked or expired mid-placement, because
        revocation only flags the placement rather than blocking it.

        Design: Difficulty/cross_entity_state_dependency/timesheet_rejected_because_students_work_permit_was_revoked
        """
        _scenario, response = _shift_attempted_after_the_permit_was_revoked()

        validate_error(response, ApiErrorId.ERR_WORK_PERMIT_INVALID.value)
        assert response.status_code == 422

    def test_the_placement_stays_active_and_merely_flagged_with_an_empty_ledger(self):
        """Revocation flags but does not block: every `Placement` of that student whose
        `lifecycle_status` is `PROPOSED` or `ACTIVE` and whose `compliance_status` is
        `PENDING_REVIEW` or `CLEARED` moves to `FLAGGED`. `Placement.total_verified_hours`
        sums `hours_worked` over the placement's timesheet entries whose `status` is
        `LOGGED`, to two decimals.

        Design: Difficulty/cross_entity_state_dependency/timesheet_rejected_because_students_work_permit_was_revoked
        """
        scenario, _response = _shift_attempted_after_the_permit_was_revoked()

        assert read_permit(scenario.student_id, scenario.permit_id)["status"] == "REVOKED"

        placement = read_placement(scenario.placement_id)
        assert placement["lifecycle_status"] == "ACTIVE"
        assert placement["compliance_status"] == "FLAGGED"
        assert float(placement["total_verified_hours"]) == 0.00
        assert list_entries(scenario.placement_id) == []
