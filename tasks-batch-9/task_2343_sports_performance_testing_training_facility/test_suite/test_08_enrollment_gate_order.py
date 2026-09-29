"""The order of the enrollment gates: state, safety, capacity, ratio and the clock."""
import pytest

from test_helpers import (
    advance_clock,
    create_compliant_coach,
    create_enrollment_payload,
    create_two_compliant_coaches,
    enroll_athlete,
    fetch_athlete,
    fetch_group_session,
    register_athlete,
    run_movement_screen,
    setup_cleared_athlete,
    setup_session_with_coach,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFSITE_VENUE = "Northside HS Gym"


def test_01_a_suspended_athlete_is_refused_before_any_funding_question(
        api, front_desk_headers, performance_director_headers):
    """Both the membership state and the funding rule are violated; state wins.

    "A `SUSPENDED` athlete is refused with `ERR_ATHLETE_SUSPENDED` before any
    funding, ratio, safety or temporal evaluation."

    Design: Difficulty/priority_pair_validation_conflict/suspension_state_error_outranks_missing_session_credit_on_enrollment
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Suspended Enroller",
                           "date_of_birth": "2010-01-15"},
        coach_name="Coach Priority")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        station_count=3, max_athletes=10)
    validate_success(api.suspend_athlete(athlete["id"], {"reason": "Unpaid balance"},
                                       performance_director_headers))

    error = validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], session["id"],
                                     funding_preference="PACKAGE_ONLY"),
            front_desk_headers),
        "ERR_ATHLETE_SUSPENDED", expected_status=409)
    assert error["error_id"] != "ERR_NO_SESSION_CREDIT", \
        "the fiscal refusal sits eight rungs below the membership state"

    assert fetch_athlete(athlete["id"])["membership_status"] == "SUSPENDED"
    reread = fetch_group_session(session["id"])
    assert reread["reserved_count"] == 0
    assert reread["waitlisted_count"] == 0
    _rows, meta = validate_paginated(api.list_enrollments(
        performance_director_headers, params={"athlete_id": athlete["id"]}))
    assert meta["total_count"] == 0


def test_02_the_same_request_from_an_active_athlete_reaches_the_fiscal_refusal(
        api, front_desk_headers):
    """With the suspension lifted the lower rung is the one that fires.

    "`ERR_NO_SESSION_CREDIT` is reserved for the athlete who owns **no** package at
    all and has no eligible contract slot, while asking for `PACKAGE_ONLY` funding."

    Design: Difficulty/priority_pair_validation_conflict/suspension_state_error_outranks_missing_session_credit_on_enrollment
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Unfunded Enroller",
                           "date_of_birth": "2010-01-15"},
        coach_name="Coach Priority")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        station_count=3, max_athletes=10)
    assert athlete["membership_status"] == "ACTIVE"
    assert athlete["team_contract_id"] is None

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], session["id"],
                                     funding_preference="PACKAGE_ONLY"),
            front_desk_headers),
        "ERR_NO_SESSION_CREDIT", expected_status=402)

    assert fetch_group_session(session["id"])["reserved_count"] == 0


def test_03_a_medical_hold_is_reported_ahead_of_the_coaching_ratio(
        api, front_desk_headers, medical_provider_headers):
    """The third booking would also breach the ratio, but safety is reported first.

    "While an athlete is on `MEDICAL_HOLD` no enrollment can be created for them
    regardless of funding, ratio or readiness, and the attempt returns
    `ERR_ATHLETE_MEDICAL_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/medical_hold_safety_error_outranks_coach_ratio_error_on_offsite_enrollment
    """
    coach, _cert, coach_headers = create_compliant_coach(full_name="Coach Travel")
    juniors = []
    for name in ("Junior One", "Junior Two", "Junior Hold"):
        junior = register_athlete(full_name=name, date_of_birth="2015-01-15")
        run_movement_screen(junior["id"], coach_headers)
        juniors.append(junior)
    held = juniors[-1]
    validate_success(api.medical_hold_athlete(
        held["id"], {"hold_reason": "Concussion protocol"}, medical_provider_headers))

    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        site_code="OFFSITE", offsite_location=OFFSITE_VENUE, station_count=3,
        max_athletes=10)
    booked = [enroll_athlete(junior["id"], session["id"]) for junior in juniors[:2]]

    error = validate_error(
        api.create_enrollment(
            create_enrollment_payload(held["id"], session["id"]), front_desk_headers),
        "ERR_ATHLETE_MEDICAL_HOLD", expected_status=422)
    assert error["error_id"] != "ERR_COACH_RATIO_EXCEEDED"

    assert fetch_athlete(held["id"])["training_clearance"] == "MEDICAL_HOLD"
    reread = fetch_group_session(session["id"])
    assert reread["athlete_units"] == pytest.approx(3.0, abs=0.05)
    assert reread["required_coach_count"] == 1
    assert reread["compliant_coach_count"] == 1
    assert reread["staffing_status"] == "STAFFED"
    assert reread["reserved_count"] == 2
    for row in booked:
        assert row["charge_cents"] == 6000


def test_04_without_the_hold_the_third_booking_breaches_the_ratio(
        api, front_desk_headers):
    """The ratio rung really is live: an unheld third junior raises the requirement.

    "A booking that would push the recomputed `required_coach_count` above the
    session's current `compliant_coach_count` refuses with
    `ERR_COACH_RATIO_EXCEEDED`, again unless `request_waitlist` is true."

    Design: Difficulty/priority_pair_validation_conflict/medical_hold_safety_error_outranks_coach_ratio_error_on_offsite_enrollment
    """
    coach, _cert, coach_headers = create_compliant_coach(full_name="Coach Travel")
    juniors = []
    for name in ("Junior One", "Junior Two", "Junior Three"):
        junior = register_athlete(full_name=name, date_of_birth="2015-01-15")
        run_movement_screen(junior["id"], coach_headers)
        juniors.append(junior)

    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        site_code="OFFSITE", offsite_location=OFFSITE_VENUE, station_count=3,
        max_athletes=10)
    for junior in juniors[:2]:
        enroll_athlete(junior["id"], session["id"])

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(juniors[-1]["id"], session["id"]),
            front_desk_headers),
        "ERR_COACH_RATIO_EXCEEDED", expected_status=422)

    reread = fetch_group_session(session["id"])
    assert reread["athlete_units"] == pytest.approx(3.0, abs=0.05)
    assert reread["reserved_count"] == 2


def test_05_an_athlete_may_hold_two_back_to_back_enrollments(api):
    """The athlete clash rule uses half-open intervals, so an eleven o'clock handoff is fine.

    "An athlete may not hold two `RESERVED` or `WAITLISTED` enrollments in sessions
    whose half-open intervals overlap, which returns `ERR_ATHLETE_SCHEDULE_CONFLICT`;
    back-to-back sessions are permitted precisely because the interval excludes its
    own end."

    Design: Difficulty/resource_temporal_overlap/athlete_half_open_back_to_back_enrollments_allowed_but_overlap_rejected
    """
    (coach_a, headers_a), _second = create_two_compliant_coaches()
    athlete = register_athlete(full_name="Back To Back Athlete",
                              date_of_birth="2010-01-15")
    run_movement_screen(athlete["id"], headers_a)

    first = setup_session_with_coach(
        coach_a["id"], start_at="2026-08-12T10:00:00Z", end_at="2026-08-12T11:00:00Z",
        station_count=3, max_athletes=10)
    second = setup_session_with_coach(
        coach_a["id"], start_at="2026-08-12T11:00:00Z", end_at="2026-08-12T12:00:00Z",
        station_count=3, max_athletes=10)

    early = enroll_athlete(athlete["id"], first["id"])
    late = enroll_athlete(athlete["id"], second["id"])

    assert early["status"] == "RESERVED"
    assert late["status"] == "RESERVED"
    assert fetch_group_session(first["id"])["reserved_count"] == 1
    assert fetch_group_session(second["id"])["reserved_count"] == 1


def test_06_a_session_that_straddles_both_is_a_schedule_conflict(
        api, front_desk_headers):
    """A thirty-minute straddle overlaps two held enrollments and is refused.

    "An athlete may not hold two `RESERVED` or `WAITLISTED` enrollments in sessions
    whose half-open intervals overlap, which returns `ERR_ATHLETE_SCHEDULE_CONFLICT`;
    back-to-back sessions are permitted precisely because the interval excludes its
    own end."

    Design: Difficulty/resource_temporal_overlap/athlete_half_open_back_to_back_enrollments_allowed_but_overlap_rejected
    """
    (coach_a, headers_a), (coach_b, _headers_b) = create_two_compliant_coaches()
    athlete = register_athlete(full_name="Straddle Athlete", date_of_birth="2010-01-15")
    run_movement_screen(athlete["id"], headers_a)

    first = setup_session_with_coach(
        coach_a["id"], start_at="2026-08-12T10:00:00Z", end_at="2026-08-12T11:00:00Z",
        station_count=3, max_athletes=10)
    second = setup_session_with_coach(
        coach_a["id"], start_at="2026-08-12T11:00:00Z", end_at="2026-08-12T12:00:00Z",
        station_count=3, max_athletes=10)
    straddling = setup_session_with_coach(
        coach_b["id"], start_at="2026-08-12T10:30:00Z", end_at="2026-08-12T11:30:00Z",
        station_count=3, max_athletes=10)
    held = [enroll_athlete(athlete["id"], first["id"]),
            enroll_athlete(athlete["id"], second["id"])]

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], straddling["id"]),
            front_desk_headers),
        "ERR_ATHLETE_SCHEDULE_CONFLICT", expected_status=409)

    assert [row["status"] for row in held] == ["RESERVED", "RESERVED"]
    reread = fetch_group_session(straddling["id"])
    assert reread["reserved_count"] == 0
    assert reread["athlete_units"] == pytest.approx(0.0, abs=0.05)
    assert reread["staffing_status"] == "STAFFED"


def test_07_one_athlete_may_hold_only_one_live_row_on_a_session(
        api, front_desk_headers):
    """The duplicate check outranks the identical-interval schedule conflict.

    "An athlete already holding an enrollment on this same session in `RESERVED`,
    `WAITLISTED`, `ATTENDED` or `NO_SHOW` state is refused with
    `ERR_DUPLICATE_ENROLLMENT` — at most one such row may exist per athlete per
    session."

    Design: Corner/errors/second_enrollment_on_same_session_returns_duplicate_enrollment
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Duplicate Enroller",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Duplicate")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, max_athletes=8)
    first = enroll_athlete(athlete["id"], session["id"])
    assert first["status"] == "RESERVED"

    error = validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], session["id"]),
            front_desk_headers),
        "ERR_DUPLICATE_ENROLLMENT", expected_status=409)
    assert error["error_id"] != "ERR_ATHLETE_SCHEDULE_CONFLICT"

    assert fetch_group_session(session["id"])["reserved_count"] == 1


def test_08_the_enrollment_window_shuts_the_moment_the_session_starts(
        api, front_desk_headers):
    """Equality already closes the window, while the session itself is still scheduled.

    "And enrollment closes once the session's `start_at` is at or before the current
    logical clock, which returns `ERR_ENROLLMENT_WINDOW_CLOSED`."

    Design: Corner/validations/enrollment_after_start_at_returns_enrollment_window_closed
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Late Enroller",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Late")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=8)

    advance_clock("2026-08-20T16:00:00Z")

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], session["id"]),
            front_desk_headers),
        "ERR_ENROLLMENT_WINDOW_CLOSED", expected_status=409)

    reread = fetch_group_session(session["id"])
    assert reread["session_status"] == "SCHEDULED"
    assert reread["reserved_count"] == 0
