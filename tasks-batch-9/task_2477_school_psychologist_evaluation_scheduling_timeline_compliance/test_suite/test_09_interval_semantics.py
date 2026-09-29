"""Two contended calendars with opposite interval semantics."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    MeetingStatus,
    SessionStatus,
    api_client,
    assert_interpreter_session,
    eligibility_meeting_payload,
    fixtures,
    interpreter_session_payload,
)
from test_helpers.test_users import TEST_USERS

INTAKE = TEST_USERS["intake_coordinator_headers"]


def _one_evaluator_across_two_buildings():
    """One psychologist holding an interpreter case in each of two buildings.

    Two sessions already sit back to back in the first building, which is legal
    because same-building intervals are compared without a travel buffer.
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    building_one = fixtures.create_school(
        name="Kingsbury Elementary",
        building_code="KB15",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=470,
    )
    building_two = fixtures.create_school(
        name="Larkspur Elementary",
        building_code="LK16",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=450,
    )
    psychologist = fixtures.create_psychologist(
        [building_one["id"], building_two["id"]],
        full_name="Nadia Roy",
        employee_number="E-1015",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    _, first_evaluation = fixtures.consented_referral(
        building_one["id"],
        student_local_id="STU-Q",
        primary_language="es",
        interpreter_required=True,
        requested_domains=["COGNITIVE"],
        intervention_team_summary="tier 3, newcomer",
    )
    fixtures.assign_evaluator(first_evaluation["id"], psychologist["id"])
    _, second_evaluation = fixtures.consented_referral(
        building_two["id"],
        student_local_id="STU-R",
        primary_language="es",
        interpreter_required=True,
        requested_domains=["ACADEMIC"],
        intervention_team_summary="tier 3, newcomer",
    )
    fixtures.assign_evaluator(second_evaluation["id"], psychologist["id"])

    first_session = fixtures.book_session(
        first_evaluation["id"],
        "2026-09-10T09:00:00Z",
        "2026-09-10T10:00:00Z",
        interpreter_name="O. Vega",
    )
    second_session = fixtures.book_session(
        first_evaluation["id"],
        "2026-09-10T10:00:00Z",
        "2026-09-10T11:00:00Z",
        interpreter_name="O. Vega",
    )
    return {
        "psychologist": psychologist,
        "first_evaluation": first_evaluation,
        "second_evaluation": second_evaluation,
        "first_session": first_session,
        "second_session": second_session,
    }


def _building_at_capacity_two():
    """A building whose two capacity slots are already taken over 15:00-16:30."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Oakhaven High",
        building_code="OH17",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=980,
    )
    _, first_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-S", requested_domains=["COGNITIVE"]
    )
    first_meeting = fixtures.create_meeting(
        first_evaluation["id"],
        school["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
    )
    _, second_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-T", requested_domains=["ACADEMIC"]
    )
    second_meeting = fixtures.create_meeting(
        second_evaluation["id"],
        school["id"],
        "2026-09-20T15:30:00Z",
        "2026-09-20T16:30:00Z",
    )
    _, third_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-U", requested_domains=["ADAPTIVE"]
    )
    return school, first_meeting, second_meeting, third_evaluation


def test_same_building_sessions_may_touch_at_an_instant():
    """A session starting exactly when the previous one ends is accepted.

    "Because the semantics are half-open, two sessions in the same building that merely touch — where the earlier session's end instant equals the later session's start instant — do **not** conflict; the same two intervals in different buildings do conflict, because the fifteen-minute travel buffer pushes them into overlap."

    Design: Difficulty/resource_temporal_overlap/psychologist_calendar_half_open_plus_travel_buffer
    """
    context = _one_evaluator_across_two_buildings()

    assert_interpreter_session(context["first_session"])
    assert context["first_session"]["status"] == SessionStatus.SCHEDULED.value
    assert context["first_session"]["duration_minutes"] == 60

    assert_interpreter_session(context["second_session"])
    assert context["second_session"]["status"] == SessionStatus.SCHEDULED.value
    assert context["second_session"]["duration_minutes"] == 60

    sessions = fixtures.evaluation_sessions(context["first_evaluation"]["id"])
    assert len(sessions) == 2


def test_a_cross_building_session_inside_the_travel_buffer_is_refused():
    """Eleven o'clock in another building is inside the fifteen-minute buffer.

    "For each such existing session, the buffer is zero minutes when that session's building is the same building as the new session's, and fifteen minutes when the buildings differ, reflecting travel time between sites."

    Design: Difficulty/resource_temporal_overlap/psychologist_calendar_half_open_plus_travel_buffer
    """
    context = _one_evaluator_across_two_buildings()

    response = api_client.book_interpreter_session(
        interpreter_session_payload(
            context["second_evaluation"]["id"],
            "2026-09-10T11:00:00Z",
            "2026-09-10T12:00:00Z",
            language_code="es",
            interpreter_name="P. Ruiz",
        ),
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_PSYCH_CALENDAR_CONFLICT.value, 409)
    assert fixtures.evaluation_sessions(context["second_evaluation"]["id"]) == []


def test_clearing_the_travel_buffer_by_fifteen_minutes_is_accepted():
    """Shifting the cross-building booking a quarter of an hour later succeeds.

    "The new booking conflicts when the interval running from fifteen minutes (or zero) before its `session_start_at` up to, but not including, fifteen minutes (or zero) after its `session_end_at` overlaps the existing session's own half-open interval from its `session_start_at` up to but not including its `session_end_at`."

    Design: Difficulty/resource_temporal_overlap/psychologist_calendar_half_open_plus_travel_buffer
    """
    context = _one_evaluator_across_two_buildings()

    response = api_client.book_interpreter_session(
        interpreter_session_payload(
            context["second_evaluation"]["id"],
            "2026-09-10T11:15:00Z",
            "2026-09-10T12:15:00Z",
            language_code="es",
            interpreter_name="P. Ruiz",
        ),
        INTAKE,
    )

    booked = validate_success(response, 201)
    assert booked["status"] == SessionStatus.SCHEDULED.value
    assert booked["duration_minutes"] == 60
    assert len(fixtures.evaluation_sessions(context["second_evaluation"]["id"])) == 1
    # Booking interpreter support never touches the caseload aggregates.
    assert fixtures.get_psychologist(context["psychologist"]["id"])[
        "open_case_points"
    ] == 14


def test_two_overlapping_meetings_fit_inside_a_capacity_of_two():
    """The building tolerates exactly as many intersecting meetings as it declares.

    "The server counts the meetings at the same `school_id`, other than the one being written, whose status is `PROPOSED`, `NOTICED`, `RESCHEDULE_REQUESTED` or `HELD` and whose closed interval intersects the requested closed interval."

    Design: Difficulty/resource_temporal_overlap/school_meeting_closed_interval_aggregate_capacity
    """
    _, first_meeting, second_meeting, _ = _building_at_capacity_two()

    assert first_meeting["status"] == MeetingStatus.PROPOSED.value
    assert second_meeting["status"] == MeetingStatus.PROPOSED.value


def test_a_third_meeting_touching_at_an_instant_fills_the_building():
    """Closed intervals make a touching endpoint count, so the third is refused.

    "Every building declares a `concurrent_meeting_capacity`, and meeting intervals at a building are compared under **closed interval semantics** — both endpoints included, so two meetings that merely touch at an instant **do** conflict, in deliberate contrast to the half-open interpreter calendar of §3.5."

    Design: Difficulty/resource_temporal_overlap/school_meeting_closed_interval_aggregate_capacity
    """
    school, _, _, third_evaluation = _building_at_capacity_two()
    guard_version = fixtures.evaluation_version(third_evaluation["id"])

    response = api_client.create_eligibility_meeting(
        eligibility_meeting_payload(
            third_evaluation["id"],
            school["id"],
            "2026-09-20T16:00:00Z",
            "2026-09-20T17:00:00Z",
            guard_version,
        ),
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_SCHOOL_MEETING_CAPACITY_FULL.value, 409)
    assert fixtures.meetings_for_evaluation(third_evaluation["id"]) == []
    assert fixtures.evaluation_version(third_evaluation["id"]) == guard_version


def test_a_third_meeting_clear_of_every_closed_interval_is_accepted():
    """One minute past the latest end instant leaves the intersecting count at zero.

    "If that count is greater than or equal to the building's `concurrent_meeting_capacity`, the request is rejected with `ERR_SCHOOL_MEETING_CAPACITY_FULL`."

    Design: Difficulty/resource_temporal_overlap/school_meeting_closed_interval_aggregate_capacity
    """
    school, _, _, third_evaluation = _building_at_capacity_two()
    guard_version = fixtures.evaluation_version(third_evaluation["id"])

    response = api_client.create_eligibility_meeting(
        eligibility_meeting_payload(
            third_evaluation["id"],
            school["id"],
            "2026-09-20T16:31:00Z",
            "2026-09-20T17:30:00Z",
            guard_version,
        ),
        INTAKE,
    )

    created = validate_success(response, 201)
    assert created["status"] == MeetingStatus.PROPOSED.value
    assert created["reschedule_count"] == 0
    assert len(fixtures.meetings_for_evaluation(third_evaluation["id"])) == 1
