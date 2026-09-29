"""Acceptance inspections: the two car dimensions, the reinspection cascade and closeout."""
from test_helpers import (
    ApiErrorId,
    api_client,
    list_code_triggers,
    make_ahj_inspector_headers,
    read_car,
    read_code_trigger,
    read_group,
    read_inspection_appointment,
    read_outage_window,
    read_procurement_order,
    read_project,
    record_inspection_result,
    request_inspection,
    schedule_inspection,
    set_clock,
    setup_accepted_car,
    setup_car_in_testing,
    setup_scheduled_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PM

ASHFIELD = {
    "name": "City of Ashfield",
    "code_edition_year": 2019,
    "fire_service_required": True,
    "seismic_zone": 0,
    "door_protection_required": False,
    "inspection_lead_days": 10,
    "witness_test_required": False,
    "reinspection_extension_hours": 24,
    "permit_surcharge_pct": 0.0000,
}


def _ashfield_accepted_car(**kwargs) -> dict:
    """One Ashfield car carried to ACCEPTED with its fire trigger priced and satisfied."""
    return setup_accepted_car(
        jurisdiction_overrides=ASHFIELD,
        building_name="Ashfield Plaza",
        trigger_cost_cents=600_000,
        staging_area_sqft=1200,
        **kwargs,
    )


def _follow_up_appointment(ctx: dict) -> dict:
    """A second appointment on the already accepted car, scheduled for 2026-09-10."""
    appointment = request_inspection(ctx["car"]["id"], "2026-09-10")
    scheduled = schedule_inspection(
        ctx["jurisdiction"]["id"], appointment["id"], "2026-09-10T13:00:00Z"
    )
    set_clock("2026-09-10T13:00:00Z")
    return scheduled


def test_the_work_and_compliance_dimensions_advance_on_separate_tracks():
    """Every `ElevatorCar` advances along two status dimensions at once, and they never move
    each other. `work_status` is the physical delivery dimension: it runs `SURVEY_PENDING`,
    `SURVEYED`, `SCOPED`, `PROCURING`, `OUTAGE_ACTIVE`, `TESTING`, `ACCEPTED`,
    `IN_WARRANTY`, `UNDER_CONTRACT`, starting at `SURVEY_PENDING` and terminating at
    `UNDER_CONTRACT`. `compliance_status` is the code-compliance dimension: it takes the
    values `NOT_EVALUATED`, `TRIGGERS_OPEN`, `TRIGGERS_CLEARED` and `CODE_ACCEPTED`,
    starting at `NOT_EVALUATED`, and it is cyclic — a car can return to `TRIGGERS_OPEN` from
    `CODE_ACCEPTED` and can be reset all the way to `NOT_EVALUATED`.

    On the compliance dimension a car standing at `TRIGGERS_CLEARED` advances to
    `CODE_ACCEPTED`, and every code trigger of the car's live scope option in status
    `PRICED` or `WAIVED` becomes `SATISFIED`.

    Design: Difficulty/non_linear_state_machine/elevator_car_parallel_work_and_compliance_dimensions
    """
    ctx = setup_car_in_testing(
        jurisdiction_overrides=ASHFIELD,
        building_name="Ashfield Plaza",
        trigger_cost_cents=600_000,
        staging_area_sqft=1200,
    )
    trigger_id = ctx["code_triggers"][0]["id"]

    in_testing = read_car(ctx["car"]["id"])
    assert in_testing["work_status"] == "TESTING"
    assert in_testing["compliance_status"] == "TRIGGERS_CLEARED"
    assert read_code_trigger(trigger_id)["status"] == "PRICED"

    appointment = request_inspection(ctx["car"]["id"], "2026-08-25")
    schedule_inspection(
        ctx["jurisdiction"]["id"], appointment["id"], "2026-08-25T13:00:00Z"
    )
    set_clock("2026-08-25T13:00:00Z")
    ruled = record_inspection_result(
        ctx["jurisdiction"]["id"], appointment["id"], result="PASSED"
    )
    assert ruled["status"] == "PASSED"

    accepted = read_car(ctx["car"]["id"])
    assert accepted["work_status"] == "ACCEPTED"
    assert accepted["compliance_status"] == "CODE_ACCEPTED"
    assert read_code_trigger(trigger_id)["status"] == "SATISFIED"
    assert read_project(ctx["project"]["id"])["status"] == "CLOSEOUT"


def test_a_follow_up_failure_reverses_both_dimensions_without_touching_the_scope():
    """The second link, caused by the first, sends the car back into the hoistway: its
    `work_status` moves from `TESTING` — or from `ACCEPTED`, when the failure is a follow-up
    ruling on a car that had already been accepted — to `OUTAGE_ACTIVE`, its
    `compliance_status` moves to `TRIGGERS_OPEN` from either `TRIGGERS_CLEARED` or
    `CODE_ACCEPTED`, and every code trigger of the car's live option in status `PRICED` or
    `SATISFIED` reverts to `REQUIRED` while triggers in status `WAIVED` stay `WAIVED` — a
    waiver granted by the authority survives a failed test.

    Design: Difficulty/non_linear_state_machine/elevator_car_parallel_work_and_compliance_dimensions
    """
    ctx = _ashfield_accepted_car()
    trigger_id = ctx["code_triggers"][0]["id"]
    first_appointment = ctx["inspection_appointment"]["id"]
    option_id = ctx["scope_option"]["id"]
    assert read_car(ctx["car"]["id"])["compliance_status"] == "CODE_ACCEPTED"

    second = _follow_up_appointment(ctx)
    failed = record_inspection_result(
        ctx["jurisdiction"]["id"], second["id"], result="FAILED"
    )
    assert failed["status"] == "FAILED"

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "OUTAGE_ACTIVE"
    assert car["compliance_status"] == "TRIGGERS_OPEN"
    assert car["approved_scope_option_id"] == option_id
    assert read_code_trigger(trigger_id)["status"] == "REQUIRED"

    assert read_inspection_appointment(first_appointment)["status"] == "PASSED"
    assert list_code_triggers(option_id)[0]["status"] == "REQUIRED"


def test_a_failed_reinspection_reopens_the_window_and_extends_its_end():
    """The third link, caused by the second, reopens the car's outage window: the car's
    window in status `COMPLETED` with the greatest `completed_at`, ties broken by the
    earlier `created_at`, moves `COMPLETED → ACTIVE`, its `extension_hours` increases by the
    jurisdiction's `reinspection_extension_hours` and its `end_at` is pushed out by the same
    number of hours.

    This reopening bypasses the group buffer check entirely: the cascade is the consequence
    of a code failure rather than an operator's scheduling request, and a scheduling rule
    must never be able to block it.

    Design: Difficulty/transitive_cascade/failed_reinspection_reopens_window_freezes_project_and_reverts_closeout
    """
    ctx = _ashfield_accepted_car()
    window_id = ctx["outage_window"]["id"]
    trigger_id = ctx["code_triggers"][0]["id"]

    before = read_outage_window(window_id)
    assert before["status"] == "COMPLETED"
    assert before["extension_hours"] == 0
    assert before["end_at"].startswith("2026-08-12T18:00:00")

    second = _follow_up_appointment(ctx)
    record_inspection_result(ctx["jurisdiction"]["id"], second["id"], result="FAILED")

    reopened = read_outage_window(window_id)
    assert reopened["status"] == "ACTIVE"
    assert reopened["extension_hours"] == 24
    assert reopened["end_at"] == "2026-08-13T18:00:00.000Z"

    assert read_inspection_appointment(second["id"])["status"] == "FAILED"
    assert read_car(ctx["car"]["id"])["work_status"] == "OUTAGE_ACTIVE"
    assert read_code_trigger(trigger_id)["status"] == "REQUIRED"


def test_a_failed_reinspection_freezes_the_project_and_reverts_closeout():
    """The fourth link, caused by the third, refreshes the group's `cars_in_service`, which
    drops by one, and the project's `active_outage_count`, which rises by one. The fifth
    link, caused by the fourth, recomputes the project's `downtime_posture`, which reaches
    `FROZEN` whenever the group has now fallen below its `min_cars_in_service`. The sixth
    link, caused by the second, moves the project `CLOSEOUT → EXECUTION` when the project
    had already reached `CLOSEOUT`.

    Design: Difficulty/transitive_cascade/failed_reinspection_reopens_window_freezes_project_and_reverts_closeout
    """
    ctx = _ashfield_accepted_car()
    project_id = ctx["project"]["id"]
    group_id = ctx["group"]["id"]
    validate_success(
        api_client.patch_elevator_group(group_id, {"min_cars_in_service": 1}, PM)
    )

    quiet = read_project(project_id)
    assert quiet["status"] == "CLOSEOUT"
    assert quiet["downtime_posture"] == "OPEN"
    assert quiet["active_outage_count"] == 0
    assert quiet["approved_scope_value_cents"] == 5_600_000
    assert read_group(group_id)["cars_in_service"] == 1

    second = _follow_up_appointment(ctx)
    record_inspection_result(ctx["jurisdiction"]["id"], second["id"], result="FAILED")

    assert read_group(group_id)["cars_in_service"] == 0
    after = read_project(project_id)
    assert after["active_outage_count"] == 1
    assert after["downtime_posture"] == "FROZEN"
    assert after["status"] == "EXECUTION"
    assert after["approved_scope_value_cents"] == 5_600_000

    assert read_procurement_order(ctx["procurement_order"]["id"])["status"] == "INSTALLED"


def test_rescheduling_a_ruled_appointment_reports_the_state_not_the_lead():
    """An appointment that has already been ruled on — `PASSED`, `CONDITIONAL`, `FAILED` or
    `CANCELLED` — is not reschedulable at all, and the attempt is refused with the distinct
    `ERR_INSPECTION_NOT_RESCHEDULABLE` so the operator learns that the ruling, not the
    request shape, closed the appointment.

    Design: Difficulty/priority_pair_validation_conflict/ruled_appointment_reschedule_rejected_by_state_before_lead
    """
    ctx = setup_accepted_car(staging_area_sqft=1200)
    appointment_id = ctx["inspection_appointment"]["id"]
    assert read_inspection_appointment(appointment_id)["status"] == "PASSED"
    assert read_project(ctx["project"]["id"])["status"] == "CLOSEOUT"

    response = api_client.reschedule_inspection_appointment(
        appointment_id,
        {"scheduled_at": "2026-08-26T09:00:00Z"},
        make_ahj_inspector_headers(ctx["jurisdiction"]["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_INSPECTION_NOT_RESCHEDULABLE, expected_status=409
    )
    assert response.json()["data"]["error_id"] != "ERR_INSPECTION_LEAD_UNMET"

    stored = read_inspection_appointment(appointment_id)
    assert stored["status"] == "PASSED"
    assert stored["reschedule_count"] == 0
    assert stored["scheduled_at"] == "2026-08-25T13:00:00.000Z"
    assert read_car(ctx["car"]["id"])["work_status"] == "ACCEPTED"


def test_the_lead_check_only_surfaces_once_the_appointment_state_is_sound():
    """The new `scheduled_at` must clear the jurisdiction's lead exactly as at scheduling
    time, or `ERR_INSPECTION_LEAD_UNMET` applies.

    This is a self-loop: the appointment must be in status `SCHEDULED` and stays
    `SCHEDULED`.

    Design: Difficulty/priority_pair_validation_conflict/ruled_appointment_reschedule_rejected_by_state_before_lead
    """
    ctx = setup_scheduled_inspection(staging_area_sqft=1200)
    appointment_id = ctx["inspection_appointment"]["id"]
    jurisdiction_id = ctx["jurisdiction"]["id"]
    assert read_inspection_appointment(appointment_id)["status"] == "SCHEDULED"
    assert read_project(ctx["project"]["id"])["jurisdiction_id"] == jurisdiction_id

    headers = make_ahj_inspector_headers(jurisdiction_id)
    too_soon = api_client.reschedule_inspection_appointment(
        appointment_id, {"scheduled_at": "2026-08-11T13:00:00Z"}, headers
    )
    validate_error(too_soon, ApiErrorId.ERR_INSPECTION_LEAD_UNMET, expected_status=409)
    assert too_soon.json()["data"]["error_id"] != "ERR_INSPECTION_NOT_RESCHEDULABLE"

    unchanged = read_inspection_appointment(appointment_id)
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["reschedule_count"] == 0
    assert unchanged["scheduled_at"] == "2026-08-25T13:00:00.000Z"

    moved = validate_success(
        api_client.reschedule_inspection_appointment(
            appointment_id, {"scheduled_at": "2026-08-27T13:00:00Z"}, headers
        )
    )
    assert moved["status"] == "SCHEDULED"
    assert moved["reschedule_count"] == 1
    assert moved["scheduled_at"] == "2026-08-27T13:00:00.000Z"


def test_a_request_inside_the_jurisdictions_lead_window_is_refused():
    """The requested date must clear the jurisdiction's lead: the number of whole days from
    the logical clock to the `requested_date`, obtained by taking the elapsed seconds and
    discarding any remainder short of a full 86,400-second day, must be at or above the
    jurisdiction's `inspection_lead_days`, and a date that does not clear it is refused with
    `ERR_INSPECTION_LEAD_UNMET`. That same whole-day figure is snapshotted for audit as
    `lead_days_at_request`. A new appointment opens in status `REQUESTED` with
    `scheduled_at` null, `reschedule_count` at zero and `punch_list_count` at zero, and its
    `recorded_by_jurisdiction_id` is set to the governing project's `jurisdiction_id` —
    which is also, by construction, the `X-User-ID` any inspector who later rules on it will
    present.

    When `witness_requested` is omitted it takes the governing jurisdiction's
    `witness_test_required` as its value, so a jurisdiction that always witnesses gets a
    witnessed test without the contractor having to remember.

    Design: Corner/validations/inspection_requested_inside_the_jurisdiction_lead_window_is_rejected
    """
    ctx = setup_car_in_testing(staging_area_sqft=1200)
    car_id = ctx["car"]["id"]
    jurisdiction_id = ctx["jurisdiction"]["id"]
    assert read_car(car_id)["work_status"] == "TESTING"

    too_soon = api_client.create_inspection_appointment(
        {"car_id": car_id, "requested_date": "2026-08-15"}, PM
    )
    validate_error(too_soon, ApiErrorId.ERR_INSPECTION_LEAD_UNMET, expected_status=409)

    _, meta = validate_paginated(
        api_client.list_inspection_appointments(PM, params={"car_id": car_id})
    )
    assert meta["total_count"] == 0
    assert read_car(car_id)["work_status"] == "TESTING"

    accepted = validate_success(
        api_client.create_inspection_appointment(
            {"car_id": car_id, "requested_date": "2026-08-25"}, PM
        ),
        expected_status=201,
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["scheduled_at"] is None
    assert accepted["reschedule_count"] == 0
    assert accepted["punch_list_count"] == 0
    # The clock stands at 2026-08-10T09:00Z, so 2026-08-25T00:00Z is 14 whole days
    # away once the remainder short of a full 86,400-second day is discarded.
    assert accepted["lead_days_at_request"] == 14
    assert accepted["recorded_by_jurisdiction_id"] == jurisdiction_id
    assert accepted["witness_requested"] is False
    assert read_car(car_id)["work_status"] == "TESTING"


def test_a_conditional_ruling_without_a_punch_list_count_is_refused():
    """The `punch_list_count` must be at least 1; a conditional ruling with the count
    omitted or zero is refused with `ERR_PUNCH_LIST_REQUIRED`.

    A **conditional** ruling accepts the car with a snag list, and it is deliberately *not*
    the same as a pass.

    Design: Corner/errors/conditional_inspection_result_without_a_punch_list_is_rejected
    """
    ctx = setup_scheduled_inspection(staging_area_sqft=1200)
    appointment_id = ctx["inspection_appointment"]["id"]
    headers = make_ahj_inspector_headers(ctx["jurisdiction"]["id"])
    set_clock("2026-08-25T13:00:00Z")

    omitted = api_client.record_inspection_result(
        appointment_id, {"result": "CONDITIONAL"}, headers
    )
    validate_error(omitted, ApiErrorId.ERR_PUNCH_LIST_REQUIRED, expected_status=409)

    zero = api_client.record_inspection_result(
        appointment_id, {"result": "CONDITIONAL", "punch_list_count": 0}, headers
    )
    validate_error(zero, ApiErrorId.ERR_PUNCH_LIST_REQUIRED, expected_status=409)

    stored = read_inspection_appointment(appointment_id)
    assert stored["status"] == "SCHEDULED"
    assert stored["punch_list_count"] == 0

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "TESTING"
    assert car["compliance_status"] == "TRIGGERS_CLEARED"
    assert read_project(ctx["project"]["id"])["status"] == "EXECUTION"


def test_a_third_reschedule_of_one_appointment_is_refused():
    """The `reschedule_count` must be strictly below 2; a third move is refused with
    `ERR_RESCHEDULE_LIMIT`.

    On success the replacement `scheduled_at` is stored, `reschedule_count` increases by 1,
    and `lead_days_at_request` is recomputed against the new `scheduled_at`.

    Design: Corner/errors/a_fourth_reschedule_beyond_the_limit_is_rejected
    """
    ctx = setup_scheduled_inspection(staging_area_sqft=1200)
    appointment_id = ctx["inspection_appointment"]["id"]
    headers = make_ahj_inspector_headers(ctx["jurisdiction"]["id"])

    first = validate_success(
        api_client.reschedule_inspection_appointment(
            appointment_id, {"scheduled_at": "2026-08-26T13:00:00Z"}, headers
        )
    )
    assert first["scheduled_at"] == "2026-08-26T13:00:00.000Z"
    assert first["reschedule_count"] == 1

    second = validate_success(
        api_client.reschedule_inspection_appointment(
            appointment_id, {"scheduled_at": "2026-08-27T13:00:00Z"}, headers
        )
    )
    assert second["scheduled_at"] == "2026-08-27T13:00:00.000Z"
    assert second["reschedule_count"] == 2

    third = api_client.reschedule_inspection_appointment(
        appointment_id, {"scheduled_at": "2026-08-28T13:00:00Z"}, headers
    )
    validate_error(third, ApiErrorId.ERR_RESCHEDULE_LIMIT, expected_status=409)
    assert third.json()["data"]["error_id"] != "ERR_INSPECTION_LEAD_UNMET"

    stored = read_inspection_appointment(appointment_id)
    assert stored["scheduled_at"] == "2026-08-27T13:00:00.000Z"
    assert stored["reschedule_count"] == 2
    assert stored["status"] == "SCHEDULED"


def test_ruling_on_an_appointment_that_was_never_scheduled_is_refused():
    """The appointment must be in status `SCHEDULED`, or the ruling is refused with
    `ERR_INSPECTION_STATE_INVALID`, and the car must stand at `work_status` `TESTING` or
    `ACCEPTED`, the latter allowing a follow-up ruling on a car that was already accepted.

    Design: Corner/errors/recording_a_result_on_an_unscheduled_appointment_is_rejected
    """
    ctx = setup_car_in_testing(staging_area_sqft=1200)
    appointment = request_inspection(ctx["car"]["id"], "2026-08-25")
    assert appointment["status"] == "REQUESTED"

    response = api_client.record_inspection_result(
        appointment["id"],
        {"result": "PASSED"},
        make_ahj_inspector_headers(ctx["jurisdiction"]["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_INSPECTION_STATE_INVALID, expected_status=409
    )

    stored = read_inspection_appointment(appointment["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["scheduled_at"] is None

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "TESTING"
    assert car["compliance_status"] == "TRIGGERS_CLEARED"
    assert read_project(ctx["project"]["id"])["status"] == "EXECUTION"
