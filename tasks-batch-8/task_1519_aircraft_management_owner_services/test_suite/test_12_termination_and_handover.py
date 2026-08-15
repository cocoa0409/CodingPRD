"""Management agreement termination: notice cascade, records release rules,
and the complete-termination obligation gates (PRD §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_active_agreement, setup_dispatch_ready, setup_termination_pending,
    create_event, create_filing, create_trip, approve_charter_trip,
    assign_duty, schedule_trip, setup_enrolled_program,
    file_accepted_insurance, give_notice, release_records,
    set_logical_clock, make_owner_headers, TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]
FO = TEST_USERS["flight_ops_headers"]
MP = TEST_USERS["maintenance_planner_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _setup_termination_notice_cascade(api):
    """ACTIVE agreement; QUALIFIED crew pair; ACCEPTED INSURANCE_COI (the only
    maintenance/compliance record); clock at 2026-08-13; one SCHEDULED CHARTER
    trip with PIC/SIC duty windows of 7.0h each ending 2026-08-12T13:00."""
    scenario = setup_dispatch_ready(tail_number="N900JX")
    aircraft_id = scenario["aircraft"]["id"]
    set_logical_clock("2026-08-13T00:00:00Z")

    trip = create_trip(
        aircraft_id, trip_use="CHARTER", departure_at="2026-08-12T08:00:00Z",
        block_hours_est=5.0, charter_quote_cents=900000, arrive_icao="KMIA",
    )
    approve_charter_trip(trip["id"], scenario["owner"]["id"])
    a1 = assign_duty(trip["id"], scenario["captain"]["id"], "PIC",
                     "2026-08-12T06:00:00Z", "2026-08-12T13:00:00Z")
    a2 = assign_duty(trip["id"], scenario["first_officer"]["id"], "SIC",
                     "2026-08-12T06:00:00Z", "2026-08-12T13:00:00Z")
    trip = schedule_trip(trip["id"])
    assert trip["status"] == "SCHEDULED"

    # Sanity: the 7.0h windows are inside the rolling 28-day window now.
    captain = validate_success(
        api.get_crew_member(scenario["captain"]["id"], FO), 200
    )
    assert captain["duty_hours_28d"] == pytest.approx(7.0)

    scenario["trip"] = trip
    scenario["assignment_ids"] = (a1["id"], a2["id"])
    return scenario


def test_termination_notice_snapshots_records_and_moves_state(api):
    """PRD §3.9: "Notice has three immediate side effects beyond the state
    change. The `notice_given_at` timestamp is set from the logical clock. A
    snapshot is taken: `records_total` becomes the count of all
    `MaintenanceEvent` and `ComplianceFiling` records, of any status, belonging
    to the agreement's aircraft."

    Design: Difficulty/transitive_cascade/termination_notice_cascades_trip_cancel_and_assignment_release
    """
    scenario = _setup_termination_notice_cascade(api)
    agreement_id = scenario["agreement"]["id"]

    noticed = give_notice(agreement_id, owner_id=scenario["owner"]["id"])
    assert noticed["status"] == "TERMINATION_PENDING"
    assert noticed["records_total"] == 1, (
        f"one INSURANCE_COI filing exists and no maintenance events, got "
        f"{noticed['records_total']}"
    )
    assert noticed.get("notice_given_at"), "notice_given_at must be set"
    assert noticed["notice_given_at"].startswith("2026-08-13T00:00:00")


def test_termination_notice_cancels_trips_and_releases_assignments(api):
    """PRD §3.9: "And every trip of the aircraft still in `REQUESTED`,
    `APPROVED`, or `SCHEDULED` is cascade-cancelled to `CANCELLED` — each such
    cancellation in turn releases that trip's `ASSIGNED` duty assignments to
    `RELEASED`, exactly as a manual cancellation would."
    PRD §3.3: "Releasing an assignment (performed by the `FlightOpsManager`, or by the system during trip cancellation or crew deactivation) moves it from `ASSIGNED` to `RELEASED`; the crew member's `duty_hours_7d` and `duty_hours_28d` decrease by the released assignment's `duty_hours` while window membership is otherwise unchanged."

    Design: Difficulty/transitive_cascade/termination_notice_cascades_trip_cancel_and_assignment_release
    """
    scenario = _setup_termination_notice_cascade(api)
    trip = scenario["trip"]
    a1_id, a2_id = scenario["assignment_ids"]

    give_notice(scenario["agreement"]["id"], owner_id=scenario["owner"]["id"])

    cancelled = validate_success(api.get_trip(trip["id"], FO), 200)
    assert cancelled["status"] == "CANCELLED"

    for assignment_id in (a1_id, a2_id):
        assignment = validate_success(api.get_assignment(assignment_id, FO), 200)
        assert assignment["status"] == "RELEASED", (
            f"assignment {assignment_id} must be released, got {assignment['status']}"
        )

    captain = validate_success(
        api.get_crew_member(scenario["captain"]["id"], FO), 200
    )
    assert captain["duty_hours_28d"] == pytest.approx(0.0), (
        f"released duty leaves the accumulator, got {captain['duty_hours_28d']}"
    )


def test_records_release_scope_and_double_release_rejected(api):
    """PRD §3.9: "Every entry must identify a `MaintenanceEvent` or
    `ComplianceFiling` belonging to the agreement's aircraft — anything else is
    `ERR_RECORD_NOT_IN_SCOPE` — and no named record may already have its
    `handed_over_at` set, which is `ERR_RECORD_ALREADY_RELEASED`."
    PRD §3.9: "A successful release sets `handed_over_at` on each named record,
    increases the agreement's `records_released` by the number of records in
    the batch, and increments the agreement's `version`. Release requires the
    agreement to be in `TERMINATION_PENDING` or `HANDOVER_IN_PROGRESS`
    (`ERR_AGREEMENT_INVALID_STATE` otherwise), and the first successful release
    moves the agreement from `TERMINATION_PENDING` to `HANDOVER_IN_PROGRESS`."

    Design: Corner/validations/records_release_scope_and_double_release_rejected
    """
    scenario = setup_active_agreement(tail_number="N430JX")
    aircraft_id = scenario["aircraft"]["id"]
    filing = file_accepted_insurance(aircraft_id, reference_no="COI-4301")
    trip = create_trip(aircraft_id, departure_at="2026-08-06T08:00:00Z",
                       block_hours_est=3.0)
    give_notice(scenario["agreement"]["id"], owner_id=scenario["owner"]["id"])

    # A TripRequest id is not a handover record.
    out_of_scope = api.release_records(
        scenario["agreement"]["id"], {"record_ids": [trip["id"]]}, AE
    )
    validate_error(out_of_scope, "ERR_RECORD_NOT_IN_SCOPE", expected_status=422)

    released_agreement = release_records(scenario["agreement"]["id"], [filing["id"]])
    assert released_agreement["records_released"] == 1
    assert released_agreement["status"] == "HANDOVER_IN_PROGRESS", (
        "first successful release moves the agreement to HANDOVER_IN_PROGRESS"
    )

    duplicate = api.release_records(
        scenario["agreement"]["id"], {"record_ids": [filing["id"]]}, AE
    )
    validate_error(duplicate, "ERR_RECORD_ALREADY_RELEASED", expected_status=409)


def test_complete_termination_handover_incomplete_rejected(api):
    """PRD §3.9: "Completion of the termination — again an `AccountExecutive`
    action — requires the agreement to be in `HANDOVER_IN_PROGRESS` and is
    guarded by two obligation checks: `records_released` must equal
    `records_total`, else `ERR_HANDOVER_INCOMPLETE`; and the aircraft must hold
    no trip in `REQUESTED`, `APPROVED`, or `SCHEDULED` and no maintenance
    program in `ENROLLED`, else `ERR_OPEN_OBLIGATIONS`."

    Design: Corner/validations/complete_termination_handover_incomplete_rejected
    """
    scenario = setup_termination_pending(
        tail_number="N440JX", with_filing=True, with_event=True
    )
    agreement_id = scenario["agreement"]["id"]
    assert scenario["agreement"]["records_total"] == 2, (
        "one MaintenanceEvent + one ComplianceFiling snapshot at notice"
    )

    release_records(agreement_id, [scenario["event"]["id"]])

    res = api.complete_termination(agreement_id, AE)
    validate_error(res, "ERR_HANDOVER_INCOMPLETE", expected_status=409)

    current = validate_success(api.get_agreement(agreement_id, AE), 200)
    assert current["status"] == "HANDOVER_IN_PROGRESS"
    assert current["records_released"] == 1
    assert current["records_total"] == 2


def test_complete_termination_open_obligations_rejected(api):
    """PRD §3.9: "Completion of the termination — again an `AccountExecutive`
    action — requires the agreement to be in `HANDOVER_IN_PROGRESS` and is
    guarded by two obligation checks: `records_released` must equal
    `records_total`, else `ERR_HANDOVER_INCOMPLETE`; and the aircraft must hold
    no trip in `REQUESTED`, `APPROVED`, or `SCHEDULED` and no maintenance
    program in `ENROLLED`, else `ERR_OPEN_OBLIGATIONS`."

    Design: Corner/validations/complete_termination_open_obligations_rejected
    """
    scenario = setup_active_agreement(tail_number="N450JX")
    aircraft_id = scenario["aircraft"]["id"]
    program = setup_enrolled_program(aircraft_id, rate_per_hour_cents=15000)
    assert program["status"] == "ENROLLED"
    filing = file_accepted_insurance(aircraft_id, reference_no="COI-4501")

    give_notice(scenario["agreement"]["id"], owner_id=scenario["owner"]["id"])
    released = release_records(scenario["agreement"]["id"], [filing["id"]])
    assert released["records_released"] == 1
    assert released["records_total"] == 1

    res = api.complete_termination(scenario["agreement"]["id"], AE)
    validate_error(res, "ERR_OPEN_OBLIGATIONS", expected_status=409)

    current = validate_success(
        api.get_agreement(scenario["agreement"]["id"], AE), 200
    )
    assert current["status"] == "HANDOVER_IN_PROGRESS"
