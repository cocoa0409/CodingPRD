"""Volunteers, qualifications, session crewing and the service-hours ledger."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assign_crew,
    book_session,
    confirm_session,
    complete_session,
    crew_assignment_payload,
    make_leader,
    make_qualified_volunteer,
    make_sidewalker,
    make_volunteer,
    read_crew_assignment,
    read_qualification,
    read_session,
    read_volunteer,
    session_version,
    set_clock,
    setup_active_rider,
    setup_crewed_session,
    setup_level_3_rider,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORD


def _crewed_pair_for_service_hours():
    """LEVEL_3 rider with two crewed sessions: 2026-05-11 completed, 2026-05-12 confirmed."""
    scenario = setup_level_3_rider()
    leader = make_leader()
    sidewalker = make_sidewalker()

    first = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:00:00Z",
        duration_minutes=60,
    )
    assign_crew(first["id"], leader["volunteer_id"], "LEADER")
    assign_crew(
        first["id"], sidewalker["volunteer_id"], "SIDEWALKER", hold_type="ARM_OVER_THIGH"
    )
    confirm_session(first["id"], scenario["instructor_id"])
    complete_session(first["id"], scenario["instructor_id"], 45)

    second = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-12T10:00:00Z",
        duration_minutes=60,
    )
    assign_crew(second["id"], leader["volunteer_id"], "LEADER")
    assign_crew(
        second["id"], sidewalker["volunteer_id"], "SIDEWALKER", hold_type="ARM_OVER_THIGH"
    )
    confirm_session(second["id"], scenario["instructor_id"])

    scenario.update({"leader": leader, "sidewalker": sidewalker})
    return scenario


def test_service_hours_scheduled_variant_counts_booked_minutes(api):
    """PRD 3.4: "The `scheduled` reading counts the volunteer's `ASSIGNED`
    assignments on sessions in `CREW_PENDING`, `CONFIRMED` or `COMPLETED` and
    takes each session's `duration_minutes`; the `delivered` reading counts only
    `COMPLETED` sessions and takes each session's `mounted_minutes`."
    PRD 3.4: "The answer carries the `volunteer_id`, the echoed `period_start`,
    `period_end` and `variant`, the resulting `service_hours`, and a
    `session_count` giving the number of qualifying assignments."

    Design: Difficulty/dual_variant_calc/volunteer_service_hours_scheduled_vs_delivered_diverge
    """
    scenario = _crewed_pair_for_service_hours()

    scheduled = validate_success(
        api.get_service_hours(
            scenario["sidewalker"]["volunteer_id"],
            COORD,
            params={
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
                "variant": "scheduled",
            },
        )
    )
    assert scheduled["service_hours"] == pytest.approx(2.0, abs=0.001)
    assert scheduled["session_count"] == 2
    assert scheduled["variant"] == "scheduled"
    assert scheduled["period_start"] == "2026-05-01"
    assert scheduled["period_end"] == "2026-05-31"


def test_service_hours_delivered_variant_counts_only_ridden_minutes(api):
    """PRD 3.4: "The `scheduled` reading counts the volunteer's `ASSIGNED`
    assignments on sessions in `CREW_PENDING`, `CONFIRMED` or `COMPLETED` and
    takes each session's `duration_minutes`; the `delivered` reading counts only
    `COMPLETED` sessions and takes each session's `mounted_minutes`."
    PRD 3.4: "Each qualifying session's minutes are converted to hours and
    rounded to 2 decimal places **first**, the rounded figures are then summed,
    and the sum is rounded to 2 decimal places again."

    Design: Difficulty/dual_variant_calc/volunteer_service_hours_scheduled_vs_delivered_diverge
    """
    scenario = _crewed_pair_for_service_hours()

    delivered = validate_success(
        api.get_service_hours(
            scenario["sidewalker"]["volunteer_id"],
            COORD,
            params={
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
                "variant": "delivered",
            },
        )
    )
    assert delivered["service_hours"] == pytest.approx(0.75, abs=0.001)
    assert delivered["session_count"] == 1
    assert delivered["variant"] == "delivered"


def _inactive_volunteer_scenario():
    """LEVEL_3 rider plus a volunteer whose annual re-training clock has lapsed."""
    scenario = setup_level_3_rider()
    sidewalker = make_qualified_volunteer(
        crew_role="SIDEWALKER",
        full_name="Sam Sidewalker",
        date_of_birth="2000-02-02",
        last_retraining_on="2025-04-01",
        signed_off_on="2026-04-15",
    )
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    scenario.update(
        {"sidewalker": sidewalker, "session": session, "session_id": session["id"]}
    )
    return scenario


def test_crew_assignment_refused_while_the_volunteer_is_inactive(api):
    """PRD 2.7 rung 36: "The volunteer's `status` is `ACTIVE`; `SUSPENDED` and
    `INACTIVE` are both rejected — otherwise `ERR_VOLUNTEER_SUSPENDED` (409).
    Applies to crew assignment creation."
    PRD 2.11: "A volunteer's `status` is `SUSPENDED` if `suspended_until` is set
    and the logical clock is before it; otherwise `INACTIVE` if the logical clock
    has reached `retraining_due_at`; otherwise `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/crew_assignment_depends_on_volunteer_retraining_status
    """
    scenario = _inactive_volunteer_scenario()
    sidewalker = scenario["sidewalker"]

    assert read_volunteer(sidewalker["volunteer_id"])["status"] == "INACTIVE"
    assert read_qualification(sidewalker["qualification_id"])["status"] == "QUALIFIED"

    response = api.create_crew_assignment(
        scenario["session_id"],
        {
            "volunteer_id": sidewalker["volunteer_id"],
            "crew_role": "SIDEWALKER",
            "hold_type": "ARM_OVER_THIGH",
            "expected_session_version": scenario["session"]["version"],
        },
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_VOLUNTEER_SUSPENDED.value)

    _, meta = validate_paginated(
        api.list_crew_assignments(COORD, params={"session_id": scenario["session_id"]})
    )
    assert meta["total_count"] == 0


def test_retraining_the_volunteer_unblocks_the_same_crew_assignment(api):
    """PRD 3.4: "Recording the annual re-training with a `completed_on` date
    writes that date into `last_retraining_on`, re-derives `retraining_due_at`,
    increments the volunteer's `version`, and returns them `INACTIVE → ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/crew_assignment_depends_on_volunteer_retraining_status
    """
    scenario = _inactive_volunteer_scenario()
    sidewalker = scenario["sidewalker"]
    original_session_version = scenario["session"]["version"]

    refused = api.create_crew_assignment(
        scenario["session_id"],
        {
            "volunteer_id": sidewalker["volunteer_id"],
            "crew_role": "SIDEWALKER",
            "hold_type": "ARM_OVER_THIGH",
            "expected_session_version": original_session_version,
        },
        COORD,
    )
    validate_error(refused, ApiErrorId.ERR_VOLUNTEER_SUSPENDED.value)
    assert session_version(scenario["session_id"]) == original_session_version, (
        "The rejected call performed no mutation on the session"
    )

    retrained = validate_success(
        api.record_retraining(
            sidewalker["volunteer_id"], {"completed_on": "2026-05-01"}, COORD
        )
    )
    assert retrained["status"] == "ACTIVE"

    accepted = validate_success(
        api.create_crew_assignment(
            scenario["session_id"],
            {
                "volunteer_id": sidewalker["volunteer_id"],
                "crew_role": "SIDEWALKER",
                "hold_type": "ARM_OVER_THIGH",
                "expected_session_version": original_session_version,
            },
            COORD,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ASSIGNED"


def test_volunteer_closed_intervals_conflict_when_endpoints_touch(api):
    """PRD 3.4: "A volunteer's occupancy of a session is a **closed** interval
    from `scheduled_start` through `scheduled_end` inclusive, with no buffer, and
    two closed intervals conflict when each begins at or before the other ends."
    PRD 2.7 rung 35: "The volunteer's closed session interval neither touches nor
    overlaps the closed interval of another live session they are already
    assigned to — otherwise `ERR_VOLUNTEER_SCHEDULE_CONFLICT` (409). Applies to
    crew assignment creation."

    Design: Difficulty/resource_temporal_overlap/volunteer_closed_intervals_conflict_when_endpoints_touch
    """
    scenario = setup_level_3_rider(
        horses=[
            {"name": "Comet", "body_weight_lb": 1100, "tack_weight_lb": 30},
            {"name": "Blaze", "body_weight_lb": 1100, "tack_weight_lb": 30},
        ]
    )
    sidewalker = make_sidewalker()
    first = book_session(
        scenario["rider_id"],
        scenario["horse_ids"][0],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:00:00Z",
        duration_minutes=60,
    )
    second = book_session(
        scenario["rider_id"],
        scenario["horse_ids"][1],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T11:00:00Z",
        duration_minutes=60,
    )
    first_assignment = assign_crew(
        first["id"], sidewalker["volunteer_id"], "SIDEWALKER", hold_type="ARM_OVER_THIGH"
    )

    response = api.create_crew_assignment(
        second["id"],
        crew_assignment_payload(
            sidewalker["volunteer_id"], "SIDEWALKER", second["version"], hold_type="ARM_OVER_THIGH"
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_VOLUNTEER_SCHEDULE_CONFLICT.value)

    assert read_crew_assignment(first_assignment["id"])["status"] == "ASSIGNED"
    _, meta = validate_paginated(
        api.list_crew_assignments(COORD, params={"session_id": second["id"]})
    )
    assert meta["total_count"] == 0
    assert read_volunteer(sidewalker["volunteer_id"])["open_assignment_count"] == 1


def test_the_instructor_accepted_the_same_touching_boundary(api):
    """PRD 3.4: "A volunteer whose eleven o'clock session ends exactly as another
    begins therefore *does* conflict, where the same pair of sessions would be
    perfectly legal for the horse or the instructor."
    PRD 2.7 rung 32: "The new session's half-open interval does not intersect the
    half-open interval of another live session naming the same instructor in
    either the `instructor_id` or the `supervising_instructor_id` slot —
    otherwise `ERR_INSTRUCTOR_SCHEDULE_CONFLICT` (409). Applies to session
    creation."

    Design: Difficulty/resource_temporal_overlap/volunteer_closed_intervals_conflict_when_endpoints_touch
    """
    scenario = setup_level_3_rider(
        horses=[
            {"name": "Comet", "body_weight_lb": 1100, "tack_weight_lb": 30},
            {"name": "Blaze", "body_weight_lb": 1100, "tack_weight_lb": 30},
        ]
    )
    first = book_session(
        scenario["rider_id"],
        scenario["horse_ids"][0],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:00:00Z",
        duration_minutes=60,
    )
    second_response = api.create_session(
        {
            "rider_id": scenario["rider_id"],
            "horse_id": scenario["horse_ids"][1],
            "instructor_id": scenario["instructor_id"],
            "activity_type": "THERAPEUTIC_RIDING",
            "scheduled_start": "2026-05-11T11:00:00Z",
            "duration_minutes": 60,
        },
        scenario["instructor_headers"],
    )
    second = validate_success(second_response, expected_status=201)
    assert second["schedule_status"] == "CREW_PENDING", (
        "The instructor rule is half-open, so the 11:00 boundary is legal"
    )

    sidewalker = make_sidewalker()
    assign_crew(
        first["id"], sidewalker["volunteer_id"], "SIDEWALKER", hold_type="ARM_OVER_THIGH"
    )
    conflict = api.create_crew_assignment(
        second["id"],
        crew_assignment_payload(
            sidewalker["volunteer_id"],
            "SIDEWALKER",
            second["version"],
            hold_type="ARM_OVER_THIGH",
        ),
        COORD,
    )
    validate_error(conflict, ApiErrorId.ERR_VOLUNTEER_SCHEDULE_CONFLICT.value)


def test_expired_qualification_is_requalified_by_the_retraining(api):
    """PRD 3.4: "A `VolunteerCoordinator` signs it off by supplying
    `signed_off_on`, which moves it `IN_TRAINING → QUALIFIED` and sets
    `expires_at` to 365 days after `signed_off_on` promoted to midnight UTC,
    incrementing the qualification's `version`."
    PRD 3.4: "re-training re-signs **every** expired qualification of that
    volunteer with `signed_off_on` set to the re-training's `completed_on` and
    `expires_at` 365 days after it, incrementing each affected qualification's
    `version`."

    Design: Corner/state_machines/expired_qualification_is_requalified_by_the_annual_retraining
    """
    set_clock("2026-05-01T00:00:00Z")
    volunteer = make_volunteer(
        full_name="Sam Sidewalker",
        date_of_birth="2000-02-02",
        last_retraining_on="2026-04-01",
    )
    assert_same_instant(volunteer["retraining_due_at"], "2027-04-01T00:00:00.000Z")

    qualification = validate_success(
        api.create_qualification(
            volunteer["id"], {"crew_role": "SIDEWALKER", "training_hours": 6}, COORD
        ),
        expected_status=201,
    )
    signed = validate_success(
        api.sign_off_qualification(
            qualification["id"], {"signed_off_on": "2026-04-01"}, COORD
        )
    )
    assert_same_instant(signed["expires_at"], "2027-04-01T00:00:00.000Z")

    set_clock("2027-04-02T00:00:00Z")
    assert read_qualification(qualification["id"])["status"] == "EXPIRED"
    assert read_volunteer(volunteer["id"])["status"] == "INACTIVE"

    retrained = validate_success(
        api.record_retraining(volunteer["id"], {"completed_on": "2027-04-02"}, COORD)
    )
    assert retrained["status"] == "ACTIVE"

    requalified = read_qualification(qualification["id"])
    assert requalified["status"] == "QUALIFIED"
    assert_same_instant(requalified["expires_at"], "2028-04-01T00:00:00.000Z")


def test_leader_assignment_to_a_level_4_rider_is_not_required(api):
    """PRD 2.7 rung 33: "The requested `crew_role` is one the rider actually
    needs and is not already filled — otherwise `ERR_CREW_ROLE_NOT_REQUIRED`
    (422). Applies to crew assignment creation."
    PRD 3.1: "A `LEVEL_4` rider needs no sidewalkers and no leader, and their
    nominal hold is `NO_CONTACT`."

    Design: Corner/validations/assigning_a_leader_to_a_level_4_rider_returns_crew_role_not_required
    """
    scenario = setup_active_rider()
    volunteer = make_volunteer(
        full_name="Lee Leader",
        date_of_birth="2000-01-01",
        last_retraining_on="2026-04-01",
    )
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )

    response = api.create_crew_assignment(
        session["id"],
        crew_assignment_payload(volunteer["id"], "LEADER", session["version"]),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_CREW_ROLE_NOT_REQUIRED.value)

    _, meta = validate_paginated(
        api.list_crew_assignments(COORD, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0


def test_assigning_the_same_volunteer_twice_is_a_duplicate(api):
    """PRD 2.7 rung 34: "The same volunteer is not already assigned to this
    session in any role — otherwise `ERR_DUPLICATE_CREW_ASSIGNMENT` (409).
    Applies to crew assignment creation."
    PRD 3.1: "A `LEVEL_1` rider needs 2 sidewalkers and a leader, with the
    sidewalkers using the `OVER_THE_THIGH` hold."

    Design: Corner/validations/assigning_the_same_volunteer_twice_returns_duplicate_crew_assignment
    """
    scenario = setup_active_rider(
        assessment={"balance_score": 3, "trunk_control_score": 3}
    )
    assert scenario["assessment"]["independence_level"] == "LEVEL_1"

    sidewalker = make_sidewalker()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    assign_crew(
        session["id"],
        sidewalker["volunteer_id"],
        "SIDEWALKER",
        hold_type="OVER_THE_THIGH",
        expected_session_version=session["version"],
    )

    duplicate = api.create_crew_assignment(
        session["id"],
        crew_assignment_payload(
            sidewalker["volunteer_id"],
            "SIDEWALKER",
            session_version(session["id"]),
            hold_type="OVER_THE_THIGH",
        ),
        COORD,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CREW_ASSIGNMENT.value)

    _, meta = validate_paginated(
        api.list_crew_assignments(COORD, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 1
    assert read_session(session["id"])["crew_satisfied"] is False


def test_fifteen_year_old_cannot_lead_but_may_sidewalk(api):
    """PRD 2.7 rung 37: "The volunteer's `age_years` is at least the minimum age
    for the requested `crew_role` — otherwise `ERR_VOLUNTEER_UNDER_AGE` (422).
    Applies to crew assignment creation and to qualification sign-off."
    PRD 3.4: "Those ages are 16 to lead, 14 to sidewalk and 12 for barn work, and
    the comparison is inclusive, so a volunteer may sidewalk on their fourteenth
    birthday."

    Design: Corner/validations/fifteen_year_old_cannot_lead_but_may_sidewalk
    """
    scenario = setup_level_3_rider()
    young = make_qualified_volunteer(
        crew_role="SIDEWALKER",
        full_name="Kit Young",
        date_of_birth="2011-01-01",
        last_retraining_on="2026-04-01",
        signed_off_on="2026-04-01",
    )
    assert young["volunteer"]["age_years"] == 15

    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    booked_version = session["version"]

    refused = api.create_crew_assignment(
        session["id"],
        crew_assignment_payload(young["volunteer_id"], "LEADER", booked_version),
        COORD,
    )
    validate_error(refused, ApiErrorId.ERR_VOLUNTEER_UNDER_AGE.value)

    accepted = validate_success(
        api.create_crew_assignment(
            session["id"],
            crew_assignment_payload(
                young["volunteer_id"],
                "SIDEWALKER",
                booked_version,
                hold_type="ARM_OVER_THIGH",
            ),
            COORD,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ASSIGNED"


def test_sidewalker_qualification_does_not_authorise_leading(api):
    """PRD 3.4: "the volunteer must hold a `QUALIFIED` qualification for
    **exactly** this role, otherwise `ERR_VOLUNTEER_NOT_QUALIFIED`; and the hold
    must match, otherwise `ERR_HOLD_TYPE_MISMATCH`. A sidewalker qualification
    never authorises leading."

    Design: Corner/validations/sidewalker_qualification_does_not_authorise_leading
    """
    scenario = setup_level_3_rider()
    sidewalker = make_sidewalker()
    assert read_volunteer(sidewalker["volunteer_id"])["age_years"] == 26

    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    response = api.create_crew_assignment(
        session["id"],
        crew_assignment_payload(sidewalker["volunteer_id"], "LEADER", session["version"]),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_VOLUNTEER_NOT_QUALIFIED.value)

    _, meta = validate_paginated(
        api.list_qualifications(
            COORD,
            params={
                "volunteer_id": sidewalker["volunteer_id"],
                "crew_role": "LEADER",
            },
        )
    )
    assert meta["total_count"] == 0


def test_sidewalker_hold_type_must_match_the_assessed_hold(api):
    """PRD 2.7 rung 39: "For a `SIDEWALKER` assignment, `hold_type` is present
    and equals the rider's `sidewalker_hold_type`; for a `LEADER` assignment,
    `hold_type` is omitted or null — otherwise `ERR_HOLD_TYPE_MISMATCH` (422).
    Applies to crew assignment creation."
    PRD 3.1: "A fifth hold value, `ANKLE_HOLD`, is a legal value for a crew
    assignment's `hold_type` but is never produced by this matrix."

    Design: Corner/validations/sidewalker_hold_type_must_match_the_riders_assessed_hold
    """
    scenario = setup_level_3_rider()
    assert scenario["assessment"]["sidewalker_hold_type"] == "ARM_OVER_THIGH"

    sidewalker = make_sidewalker()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )

    response = api.create_crew_assignment(
        session["id"],
        crew_assignment_payload(
            sidewalker["volunteer_id"],
            "SIDEWALKER",
            session["version"],
            hold_type="ANKLE_HOLD",
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_HOLD_TYPE_MISMATCH.value)

    _, meta = validate_paginated(
        api.list_crew_assignments(COORD, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0


def test_confirm_with_only_a_leader_returns_crew_incomplete(api):
    """PRD 2.7 rung 40: "The session's `crew_satisfied` is true, with exact counts
    on both limbs — otherwise `ERR_CREW_INCOMPLETE` (409). Applies to session
    confirmation."
    PRD 3.4: "Whether a session's crew is complete is the `crew_satisfied` flag,
    and it demands **exact** equality on both limbs: the count of `ASSIGNED`
    sidewalker assignments must equal the rider's `required_sidewalker_count`,
    and the count of `ASSIGNED` leader assignments must equal 1 when the rider's
    `requires_leader` is true and 0 when it is false."

    Design: Corner/validations/confirm_with_only_a_leader_assigned_returns_crew_incomplete
    """
    scenario = setup_level_3_rider()
    leader = make_leader()
    sidewalker = make_sidewalker()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    assign_crew(
        session["id"],
        leader["volunteer_id"],
        "LEADER",
        expected_session_version=session["version"],
    )

    incomplete = api.confirm_session(session["id"], scenario["instructor_headers"])
    validate_error(incomplete, ApiErrorId.ERR_CREW_INCOMPLETE.value)

    assign_crew(
        session["id"], sidewalker["volunteer_id"], "SIDEWALKER", hold_type="ARM_OVER_THIGH"
    )
    confirmed = validate_success(
        api.confirm_session(session["id"], scenario["instructor_headers"])
    )
    assert confirmed["schedule_status"] == "CONFIRMED"
    assert confirmed["crew_satisfied"] is True


def test_crew_assignment_with_a_stale_session_version_is_rejected(api):
    """PRD 2.4: "Adding a crew assignment to a session — the create under
    `POST /sessions/{session_id}/crew-assignments` — requires a non-optional
    `expected_session_version` field in the request body carrying the client's
    last observed `version` of the target `Session`."
    PRD 2.4: "In all three cases, if the supplied value does not equal the parent
    entity's current stored `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and nothing is persisted."

    Design: Corner/cross_cutting_complexity_layers/crew_assignment_with_a_stale_session_version_returns_412
    """
    scenario = setup_level_3_rider()
    leader = make_leader()
    sidewalker = make_sidewalker()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    stale_version = session["version"]
    assign_crew(
        session["id"],
        leader["volunteer_id"],
        "LEADER",
        expected_session_version=stale_version,
    )

    rejected = api.create_crew_assignment(
        session["id"],
        crew_assignment_payload(
            sidewalker["volunteer_id"],
            "SIDEWALKER",
            stale_version,
            hold_type="ARM_OVER_THIGH",
        ),
        COORD,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION.value)

    fresh_version = session_version(session["id"])
    assert fresh_version == stale_version + 1

    accepted = validate_success(
        api.create_crew_assignment(
            session["id"],
            crew_assignment_payload(
                sidewalker["volunteer_id"],
                "SIDEWALKER",
                fresh_version,
                hold_type="ARM_OVER_THIGH",
            ),
            COORD,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ASSIGNED"
    assert read_session(session["id"])["crew_satisfied"] is True


def test_releasing_a_sidewalker_reverts_the_confirmed_session(api):
    """PRD 3.4: "If the release drops a `CONFIRMED` session below its crew
    requirement, that session reverts `CONFIRMED → CREW_PENDING` and its own
    `version` increments — the reversible edge of the schedule axis, reached
    without any operator touching the session itself."

    Design: Difficulty/non_linear_state_machine/session_confirmed_reverts_to_crew_pending_on_crew_release
    """
    scenario = setup_crewed_session()
    assert scenario["session"]["schedule_status"] == "CONFIRMED"

    released = validate_success(
        api.release_crew_assignment(
            scenario["sidewalker_assignment"]["id"],
            {"reason": "Sidewalker called in sick"},
            COORD,
        )
    )
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "Sidewalker called in sick"

    assert read_crew_assignment(scenario["leader_assignment"]["id"])["status"] == "ASSIGNED"

    session_after = read_session(scenario["session_id"])
    assert session_after["schedule_status"] == "CREW_PENDING"
    assert session_after["crew_satisfied"] is False
    assert session_after["billing_status"] == "UNBILLED"


def test_released_assignment_drops_the_volunteers_open_count(api):
    """PRD 3.4: "The assignment moves `ASSIGNED → RELEASED`, `release_reason`
    records the supplied reason, the session's `crew_satisfied` is re-derived,
    the volunteer's `open_assignment_count` drops, and the assignment's `version`
    increments."
    PRD 3.4: "`open_assignment_count` starts at 0 and thereafter counts the
    volunteer's `ASSIGNED` crew assignments on sessions that are `CREW_PENDING`
    or `CONFIRMED`."

    Design: Difficulty/non_linear_state_machine/session_confirmed_reverts_to_crew_pending_on_crew_release
    """
    scenario = setup_crewed_session()
    sidewalker_id = scenario["sidewalker"]["volunteer_id"]
    assert read_volunteer(sidewalker_id)["open_assignment_count"] == 1

    validate_success(
        api.release_crew_assignment(
            scenario["sidewalker_assignment"]["id"],
            {"reason": "Sidewalker called in sick"},
            COORD,
        )
    )

    assert read_volunteer(sidewalker_id)["open_assignment_count"] == 0
    assert (
        read_volunteer(scenario["leader"]["volunteer_id"])["open_assignment_count"] == 1
    )


def test_level_4_rider_confirms_with_no_crew_assignments(api):
    """PRD 3.4: "For a `LEVEL_4` rider the requirement is zero on both limbs, so
    the **empty** crew satisfies it and such a session confirms with no crew
    assignments at all."

    Design: Difficulty/boundary_precision_check/level_4_rider_confirms_with_zero_crew_assignments
    """
    scenario = setup_active_rider()
    assert scenario["assessment"]["independence_level"] == "LEVEL_4"
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )

    rows, meta = validate_paginated(
        api.list_crew_assignments(COORD, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    confirmed = validate_success(
        api.confirm_session(session["id"], scenario["instructor_headers"])
    )
    assert confirmed["schedule_status"] == "CONFIRMED"


def test_level_4_rider_crew_requirement_is_zero_on_both_limbs(api):
    """PRD 3.1: "A `LEVEL_4` rider needs no sidewalkers and no leader, and their
    nominal hold is `NO_CONTACT`."
    PRD 3.4: "For a `LEVEL_4` rider the requirement is zero on both limbs, so the
    **empty** crew satisfies it and such a session confirms with no crew
    assignments at all."

    Design: Difficulty/boundary_precision_check/level_4_rider_confirms_with_zero_crew_assignments
    """
    scenario = setup_active_rider()
    rider = validate_success(api.get_rider(scenario["rider_id"], ADMIN))
    assert rider["independence_level"] == "LEVEL_4"
    assert rider["required_sidewalker_count"] == 0
    assert rider["requires_leader"] is False
    assert rider["sidewalker_hold_type"] == "NO_CONTACT"

    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    assert read_session(session["id"])["crew_satisfied"] is True
