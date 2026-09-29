"""Who may act: universal reads, exclusive operations and segregation of duties."""

from test_helpers import (
    ASSIGN_COMPLETED,
    COMPLIANCE_HEADERS,
    DIRECTOR_HEADERS,
    ENROLLMENT_ACTIVE,
    FRONT_DESK_HEADERS,
    INSPECTION_PASS,
    LAUNDRY_LEAD_HEADERS,
    OCCUPANCY_DUE_OUT,
    OCCUPANCY_STAYOVER,
    ORDINANCE_NONE,
    PROGRAM_DAILY,
    PROGRAM_OPT_OUT,
    ROLE_COMPLIANCE,
    SERVICE_CHECKOUT,
    WAIVER_DECISION_GRANT,
    WAIVER_GRANTED,
    WAIVER_REQUESTED,
    ApiErrorId,
    assert_credits,
    assert_is_null,
    assert_score_pct,
    assignment_payload,
    build_scenario,
    decide_waiver,
    enrollment_payload,
    make_headers,
    make_supervisor_headers,
    read_assignment,
    read_room,
    read_roster,
    request_waiver,
    validate_error,
    validate_paginated,
    validate_success,
    waiver_decision_payload,
)

ONE_DEPARTURE_DAY = {
    "forecast_occupied_rooms": 1,
    "forecast_arrivals": 0,
    "forecast_departures": 1,
    "planned_deep_clean_rooms": 0,
}

FULL_MARKS = {
    "bathroom_points": 9,
    "linen_points": 9,
    "dust_points": 9,
    "amenity_points": 9,
    "floor_points": 9,
}


# --------------------------------------------------------------------------
# The universally readable computed capability
# --------------------------------------------------------------------------


def test_the_laundry_lead_may_read_the_sample_plan(api):
    """A role that may not otherwise touch a roster still receives the plan body.

    PRD 3.6: "Any role may call it against a roster, and it returns `roster_id`,
    `completed_count`, `sample_rate`, `required_samples`, `inspections_completed`,
    `remaining_samples` and `selected_assignment_ids`."

    Design: Corner/rbac/rbac_every_role_may_read_the_sample_plan
    """
    scenario = build_scenario(
        api, rooms=["101"], forecast=ONE_DEPARTURE_DAY, clocked_in=False
    )

    plan = validate_success(
        api.get_sample_plan(scenario.roster_id, LAUNDRY_LEAD_HEADERS), 200
    )

    assert plan["roster_id"] == scenario.roster_id
    assert plan["completed_count"] == 0
    assert plan["required_samples"] == 0
    assert plan["inspections_completed"] == 0
    assert plan["remaining_samples"] == 0
    assert plan["selected_assignment_ids"] == []
    for label, headers in (
        ("ComplianceOfficer", COMPLIANCE_HEADERS),
        ("FrontDeskAgent", FRONT_DESK_HEADERS),
        ("HousekeepingDirector", DIRECTOR_HEADERS),
        ("RoomAttendant", scenario.attendant_headers()),
        ("Supervisor", scenario.supervisor_headers()),
    ):
        also = validate_success(
            api.get_sample_plan(scenario.roster_id, headers), 200
        )
        assert also["roster_id"] == scenario.roster_id, (
            f"{label} must also be able to read the plan"
        )


# --------------------------------------------------------------------------
# An operation exclusive to the front desk
# --------------------------------------------------------------------------


def test_a_supervisor_may_not_enrol_a_guest_in_a_service_programme(api):
    """Enrolment creation belongs to the front desk, even though a supervisor may accrue.

    PRD 3.9: "A `FrontDeskAgent` creates one against a `room_id`, naming the
    `reservation_code` the incentive accrues to (1 to 32 characters), the `program`,
    and the `nights` of the stay the enrolment covers (1 to 60)."

    Design: Corner/rbac/rbac_supervisor_creating_a_service_enrollment_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_STAYOVER}],
        with_day=False,
        with_roster=False,
    )
    payload = enrollment_payload(
        scenario.room_id("101"), PROGRAM_OPT_OUT, 2, reservation_code="R-3001"
    )

    response = api.create_service_enrollment(payload, scenario.supervisor_headers())

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    _, meta = validate_paginated(
        api.list_service_enrollments(
            {"room_id": scenario.room_id("101")}, DIRECTOR_HEADERS
        )
    )
    assert meta["total_count"] == 0, "the refused create must leave no enrolment"
    assert read_room(api, scenario.room_id("101"))["service_program"] == PROGRAM_DAILY, (
        "the room's programme must be untouched by a refused enrolment"
    )
    enrolled = validate_success(
        api.create_service_enrollment(payload, FRONT_DESK_HEADERS), 201
    )
    assert enrolled["status"] == ENROLLMENT_ACTIVE
    assert enrolled["points_per_skip"] == 500


# --------------------------------------------------------------------------
# An operation the laundry lead has no part in
# --------------------------------------------------------------------------


def test_the_laundry_lead_may_not_hand_out_cleaning_work(api):
    """Assignment creation names two roles, and the laundry lead is neither.

    PRD 3.4: "A `HousekeepingDirector` or a `Supervisor` creates one by naming the
    `roster_id`, the `room_id`, a `service_type`, and the `expected_roster_version`
    demanded by §2.7."

    Design: Corner/rbac/rbac_laundry_lead_creating_a_room_assignment_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_DEPARTURE_DAY,
        clocked_in=False,
    )
    before = read_roster(api, scenario.roster_id)
    payload = assignment_payload(
        scenario.roster_id,
        scenario.room_id("101"),
        before["version"],
        SERVICE_CHECKOUT,
    )

    response = api.create_room_assignment(payload, LAUNDRY_LEAD_HEADERS)

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["assigned_credits"], 0.00, "assigned_credits")
    assert roster["version"] == before["version"], (
        "a refused assignment must not move the roster version"
    )
    _, meta = validate_paginated(
        api.list_room_assignments({"roster_id": scenario.roster_id}, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 0
    accepted = validate_success(
        api.create_room_assignment(payload, scenario.supervisor_headers()), 201
    )
    assert_credits(accepted["credits"], 1.00, "credits")


# --------------------------------------------------------------------------
# Nobody inspects their own work
# --------------------------------------------------------------------------


def test_a_qualified_attendant_may_not_inspect_their_own_clean(api):
    """The inspector holds the role and the qualification, and is still refused.

    PRD 3.6: "Segregation of duties then applies: the inspecting `X-User-ID` must
    differ from the `attendant_id` of the roster that owns the inspected assignment,
    because nobody inspects their own work, and a violation is
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/rbac_attendant_inspecting_their_own_room_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_DEPARTURE_DAY,
        worker_overrides={"can_inspect": True},
    )
    cleaned = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T09:00:00.000Z",
        "2026-08-03T09:30:00.000Z",
    )

    response = scenario.inspect_raw(
        cleaned["id"],
        headers=make_supervisor_headers(scenario.worker_id),
        **FULL_MARKS,
    )

    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
    _, meta = validate_paginated(
        api.list_inspections({"assignment_id": cleaned["id"]}, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 0, "the refused filing must leave no inspection"
    assert read_assignment(api, cleaned["id"])["status"] == ASSIGN_COMPLETED
    assert read_roster(api, scenario.roster_id)["inspections_completed"] == 0
    inspection = scenario.inspect(cleaned["id"], **FULL_MARKS)
    assert_score_pct(inspection["score_pct"], 90.0)
    assert inspection["result"] == INSPECTION_PASS, (
        "the identical scores filed by somebody else must be accepted"
    )


def test_the_operator_who_filed_a_waiver_may_not_grant_it(api):
    """The acting role is the only one permitted to decide, yet the identity collides.

    PRD 3.3: "Segregation of duties is absolute here: the deciding `X-User-ID` must
    differ from the roster's `waiver_requested_by_user_id`, and an operator deciding
    their own request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/rbac_waiver_requester_deciding_the_same_waiver_is_rejected
    """
    scenario = build_scenario(
        api,
        property_overrides={
            "name": "Lakeside Inn",
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 4.00,
        },
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_DEPARTURE_DAY,
        clocked_in=False,
    )
    requested = request_waiver(api, scenario.roster_id, 5.00, scenario.inspector_id)
    assert requested["waiver_state"] == WAIVER_REQUESTED
    assert_credits(requested["waiver_requested_credits"], 5.00, "waiver_requested_credits")
    assert requested["waiver_requested_by_user_id"] == scenario.inspector_id

    response = api.decide_waiver(
        scenario.roster_id,
        waiver_decision_payload(WAIVER_DECISION_GRANT),
        make_headers(ROLE_COMPLIANCE, scenario.inspector_id),
    )

    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
    roster = read_roster(api, scenario.roster_id)
    assert roster["waiver_state"] == WAIVER_REQUESTED
    assert_is_null(roster["waiver_decided_by_user_id"], "waiver_decided_by_user_id")
    assert roster["version"] == requested["version"], (
        "a refused decision must not move the roster version"
    )
    decided = decide_waiver(api, scenario.roster_id, WAIVER_DECISION_GRANT)
    assert decided["waiver_state"] == WAIVER_GRANTED, (
        "a second compliance identity decides the same request without objection"
    )
