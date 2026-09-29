"""The coaching requirement, the staffing status it drives, and station rotation."""
import pytest

from test_helpers import (
    advance_clock,
    assert_staffing_status_consistent,
    assign_coach_to_session,
    create_compliant_coach,
    create_two_compliant_coaches,
    enroll_athlete,
    fetch_enrollment,
    fetch_group_session,
    fetch_staff_member,
    find_assigned_staff_ids,
    lock_session_roster,
    register_athlete,
    run_movement_screen,
    schedule_group_session,
    setup_session_with_coach,
    validate_error,
    validate_success,
)


def test_01_six_stations_demand_two_coaches_before_any_athlete_enrols(api):
    """The station term alone sets the requirement to two on a nearly empty session.

    "The **station requirement** divides `station_count` by 3, the number of
    equipment stations one coach can supervise, and likewise rounds up."

    Design: Difficulty/combinatorial_formula/coach_requirement_two_reached_by_station_term_and_by_ratio_term
    """
    (coach_a, headers_a), (coach_b, _headers_b) = create_two_compliant_coaches(
        "Ana Cruz", "Ben Oyelaran")
    athlete = register_athlete(full_name="Xena Ford", date_of_birth="2010-01-15")
    run_movement_screen(athlete["id"], headers_a)

    session = schedule_group_session(start_at="2026-08-10T10:00:00Z",
                                    end_at="2026-08-10T11:00:00Z",
                                    site_code="ONSITE", station_count=6, max_athletes=10)
    assert session["required_coach_count"] == 2, \
        "the requirement is computed from station_count alone at creation time"
    assign_coach_to_session(session["id"], coach_a["id"])
    staffed = assign_coach_to_session(session["id"], coach_b["id"], coach_role="ASSISTANT")
    assert staffed["staffing_status"] == "STAFFED"

    enrollment = enroll_athlete(athlete["id"], session["id"])

    reread = fetch_group_session(session["id"])
    assert reread["station_count"] == 6
    assert reread["athlete_units"] == pytest.approx(1.0, abs=0.05)
    assert reread["required_coach_count"] == 2
    assert reread["compliant_coach_count"] == 2
    assert reread["staffing_status"] == "STAFFED"
    assert_staffing_status_consistent(reread)
    assert enrollment["charge_cents"] == 4500


def test_02_four_and_a_half_offsite_units_demand_two_coaches_over_three_stations(api):
    """The same requirement of two arrives from the ratio term on an offsite session.

    "The **ratio requirement** divides `athlete_units` by the base ratio for the
    site — one coach per 8 athlete-units `ONSITE`, but only one coach per 4
    athlete-units `OFFSITE`, since travel training halves the tolerable span of
    control — and rounds the quotient up to a whole coach."

    Design: Difficulty/combinatorial_formula/coach_requirement_two_reached_by_station_term_and_by_ratio_term
    """
    (coach_a, headers_a), (coach_b, _headers_b) = create_two_compliant_coaches(
        "Ana Cruz", "Ben Oyelaran")
    juniors = []
    for name in ("Uma One", "Uma Two", "Uma Three"):
        junior = register_athlete(full_name=name, date_of_birth="2015-01-15")
        run_movement_screen(junior["id"], headers_a)
        juniors.append(junior)

    session = schedule_group_session(start_at="2026-08-11T10:00:00Z",
                                    end_at="2026-08-11T11:00:00Z",
                                    site_code="OFFSITE",
                                    offsite_location="Northside HS Gym",
                                    station_count=3, max_athletes=10)
    assert session["required_coach_count"] == 1
    assign_coach_to_session(session["id"], coach_a["id"])
    assign_coach_to_session(session["id"], coach_b["id"], coach_role="ASSISTANT")

    enrollments = [enroll_athlete(junior["id"], session["id"]) for junior in juniors]

    reread = fetch_group_session(session["id"])
    assert reread["station_count"] == 3, "three stations only ever demand one coach"
    # three athletes aged 11 contribute 1.5 units each
    assert reread["athlete_units"] == pytest.approx(4.5, abs=0.05)
    assert reread["required_coach_count"] == 2
    assert reread["compliant_coach_count"] == 2
    assert reread["staffing_status"] == "STAFFED"
    assert enrollments[-1]["status"] == "RESERVED"
    assert enrollments[-1]["funding_source"] == "DROP_IN"
    assert enrollments[-1]["charge_cents"] == 6000


def test_03_the_roster_lock_is_refused_while_the_only_coach_is_lapsed(
        api, performance_director_headers):
    """The lock's admissibility is decided by the assigned coach's credential state.

    "Locking while `staffing_status` is anything other than `STAFFED` is refused with
    `ERR_COACH_RATIO_EXCEEDED`, and locking after the session's `start_at` has been
    reached is refused with `ERR_ENROLLMENT_WINDOW_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/roster_lock_blocked_until_staffing_recovers_from_staff_credential_state
    """
    lapsing, _cert, lapsing_headers = create_compliant_coach(
        full_name="Ravi Chetty", cert_code="CSCS", issued_on="2023-08-15",
        cert_expires_on="2026-08-15")
    athlete = register_athlete(full_name="Nia Osei", date_of_birth="2010-01-15")
    run_movement_screen(athlete["id"], lapsing_headers)
    session = setup_session_with_coach(
        lapsing["id"], start_at="2026-09-20T10:00:00Z", end_at="2026-09-20T11:00:00Z",
        station_count=3, max_athletes=10)
    enrollment = enroll_athlete(athlete["id"], session["id"])
    assert session["staffing_status"] == "STAFFED"

    advance_clock("2026-09-01T00:00:00Z")
    validate_success(api.credential_review(lapsing["id"], performance_director_headers))

    validate_error(api.lock_roster(session["id"], performance_director_headers),
                   "ERR_COACH_RATIO_EXCEEDED", expected_status=422)

    assert fetch_staff_member(lapsing["id"])["credential_status"] == "LAPSED"
    reread = fetch_group_session(session["id"])
    assert reread["session_status"] == "SCHEDULED"
    assert reread["staffing_status"] == "UNDERSTAFFED"
    assert reread["compliant_coach_count"] == 0
    assert fetch_enrollment(enrollment["id"])["station_number"] is None


def test_04_the_same_lock_succeeds_once_a_compliant_coach_is_attached(
        api, performance_director_headers):
    """No field of the session changed between the refusal and the acceptance.

    "Three preconditions apply: the session must be `SCHEDULED`, its
    `staffing_status` must be `STAFFED`, and it must hold at least one `RESERVED`
    enrollment."

    Design: Difficulty/cross_entity_state_dependency/roster_lock_blocked_until_staffing_recovers_from_staff_credential_state
    """
    lapsing, _cert, lapsing_headers = create_compliant_coach(
        full_name="Ravi Chetty", cert_code="CSCS", issued_on="2023-08-15",
        cert_expires_on="2026-08-15")
    replacement, _cert_b, _headers_b = create_compliant_coach(
        full_name="Elin Krogh", role_title="PERFORMANCE_COACH",
        cert_expires_on="2027-12-31")
    athlete = register_athlete(full_name="Nia Osei", date_of_birth="2010-01-15")
    run_movement_screen(athlete["id"], lapsing_headers)
    session = setup_session_with_coach(
        lapsing["id"], start_at="2026-09-20T10:00:00Z", end_at="2026-09-20T11:00:00Z",
        station_count=3, max_athletes=10)
    enrollment = enroll_athlete(athlete["id"], session["id"])

    advance_clock("2026-09-01T00:00:00Z")
    validate_success(api.credential_review(lapsing["id"], performance_director_headers))
    validate_error(api.lock_roster(session["id"], performance_director_headers),
                   "ERR_COACH_RATIO_EXCEEDED", expected_status=422)

    recovered = assign_coach_to_session(session["id"], replacement["id"])
    assert recovered["staffing_status"] == "STAFFED"
    assert recovered["compliant_coach_count"] == 1
    assert find_assigned_staff_ids(recovered) == [replacement["id"]]

    locked = validate_success(api.lock_roster(session["id"],
                                             performance_director_headers))
    assert locked["session_status"] == "ROSTER_LOCKED"
    assert fetch_staff_member(replacement["id"])["credential_status"] == "COMPLIANT"
    reread_enrollment = fetch_enrollment(enrollment["id"])
    assert reread_enrollment["status"] == "RESERVED"
    assert reread_enrollment["station_number"] == 1


def test_05_the_lock_wraps_station_numbers_round_the_available_stations(api):
    """Three reserved athletes over two stations run 1, 2 and back to 1.

    "Each enrollment's `station_number` is one plus the remainder of dividing its
    counter position by the session's `station_count`, so the first athlete takes
    station 1, the athlete after the last station wraps back to station 1, and every
    station index falls between 1 and `station_count`."

    Design: Corner/calculations/station_rotation_wraps_modulo_station_count_in_created_at_order
    """
    coach, _cert, coach_headers = create_compliant_coach(
        full_name="Coach Rotation", role_title="PERFORMANCE_COACH")
    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=2, max_athletes=8)

    enrollments = []
    for name, dob in (("Rotation One", "2009-02-02"), ("Rotation Two", "2009-03-03"),
                      ("Rotation Three", "2009-04-04")):
        athlete = register_athlete(full_name=name, date_of_birth=dob)
        run_movement_screen(athlete["id"], coach_headers)
        enrollments.append(enroll_athlete(athlete["id"], session["id"]))

    locked = validate_success(api.lock_roster(session["id"], coach_headers))

    assert locked["session_status"] == "ROSTER_LOCKED"
    stations = [fetch_enrollment(row["id"])["station_number"] for row in enrollments]
    assert stations == [1, 2, 1]


def test_06_only_reserved_and_attended_rows_feed_the_weighted_athlete_count(
        api, front_desk_headers):
    """A canceled row and a waitlisted row contribute no supervision units.

    "For each enrollment on the session whose `status` is `RESERVED` or `ATTENDED` —
    `WAITLISTED`, `NO_SHOW`, `LATE_CANCEL` and `CANCELED` rows are excluded — the
    athlete contributes units by the **first matching** of these three branches: 2.5
    units if the athlete holds a return-to-sport plan in `STAGE_ACTIVE`,
    `STAGE_TESTING` or `MEDICAL_REVIEW`; otherwise 1.5 units if their `age_years` is
    12 or under; otherwise 1.0 unit."

    Design: Corner/calculations/athlete_units_exclude_waitlisted_and_canceled_rows
    """
    coach, _cert, coach_headers = create_compliant_coach(full_name="Coach Units")
    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, max_athletes=2)

    def screened(name, dob):
        athlete = register_athlete(full_name=name, date_of_birth=dob)
        run_movement_screen(athlete["id"], coach_headers)
        return athlete

    standard = screened("Units Standard", "2009-02-02")
    canceled_athlete = screened("Units Canceled", "2009-03-03")
    under_twelve = screened("Units Under Twelve", "2015-06-01")
    waitlisted_athlete = screened("Units Waitlisted", "2009-05-05")

    enroll_athlete(standard["id"], session["id"])
    doomed = enroll_athlete(canceled_athlete["id"], session["id"])
    canceled = validate_success(api.cancel_enrollment(doomed["id"], front_desk_headers))
    assert canceled["status"] == "CANCELED", "the cancel is more than 24 hours out"

    enroll_athlete(under_twelve["id"], session["id"])
    waitlisted = enroll_athlete(waitlisted_athlete["id"], session["id"],
                                request_waitlist=True)
    assert waitlisted["status"] == "WAITLISTED"

    reread = fetch_group_session(session["id"])
    # 1.0 for the senior athlete plus 1.5 for the eleven-year-old
    assert reread["athlete_units"] == pytest.approx(2.5, abs=0.05)
    assert reread["reserved_count"] == 2
    assert reread["waitlisted_count"] == 1
    assert reread["required_coach_count"] == 1
    assert reread["staffing_status"] == "STAFFED"


def test_07_the_assignment_response_already_carries_every_recomputed_field(api):
    """Derived staffing values are correct in the write's own body, with no re-read.

    "`staffing_status` follows mechanically: `STAFF_PENDING` while `assigned_staff`
    is empty and `compliant_coach_count` is 0; `UNDERSTAFFED` when
    `compliant_coach_count` is below `required_coach_count`; and `STAFFED` otherwise."

    Design: Corner/consistency_model/coach_assignment_response_reflects_recomputed_staffing_in_the_same_response
    """
    coach, _cert, coach_headers = create_compliant_coach(
        full_name="Coach Immediate", role_title="PERFORMANCE_COACH")
    athlete = register_athlete(full_name="Immediate Athlete", date_of_birth="2009-02-02")
    screen = run_movement_screen(athlete["id"], coach_headers)
    assert screen["risk_score"] == pytest.approx(0.00, abs=0.01), \
        "the finalize response already carries the computed risk score"

    session = schedule_group_session(start_at="2026-08-25T16:00:00Z",
                                    end_at="2026-08-25T17:00:00Z",
                                    station_count=3, max_athletes=8)
    assert session["staffing_status"] == "STAFF_PENDING"
    assert session["compliant_coach_count"] == 0
    first = assign_coach_to_session(session["id"], coach["id"])
    assert first["staffing_status"] == "STAFFED"
    enroll_athlete(athlete["id"], session["id"])

    second_coach, _cert_b, _headers_b = create_compliant_coach(
        full_name="Coach Immediate Two", role_title="PERFORMANCE_COACH")
    assigned = assign_coach_to_session(session["id"], second_coach["id"],
                                      coach_role="ASSISTANT")

    assert assigned["compliant_coach_count"] == 2
    assert assigned["required_coach_count"] == 1
    assert assigned["staffing_status"] == "STAFFED"
    assert assigned["athlete_units"] == pytest.approx(1.0, abs=0.05)
    assert assigned["reserved_count"] == 1
    assert assigned["version"] > first["version"]

    reread = fetch_group_session(session["id"])
    for field in ("staffing_status", "compliant_coach_count", "required_coach_count",
                  "athlete_units", "reserved_count", "version"):
        assert reread[field] == assigned[field], \
            "no derived field may lag behind the write that computed it"
