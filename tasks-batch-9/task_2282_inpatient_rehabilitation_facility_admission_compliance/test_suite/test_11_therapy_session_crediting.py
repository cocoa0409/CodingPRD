"""Therapy session credited minutes, the daily cap, voids and session guards."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_therapy_session,
    assert_week_counters,
    create_therapy_session_payload,
    deliver_session,
    read_therapy_session,
    read_therapy_week,
    register_clinician,
    register_facility,
    schedule_session,
    set_clock,
    setup_facility_with_staff,
    setup_stay_with_week,
    validate_success,
    validate_error,
    void_session_payload,
)

PLAN_PT = {"three_hour_rule_mode": "DAILY_3HR", "disciplines": ["PT"]}
PLAN_PT_AND_OT = {"three_hour_rule_mode": "DAILY_3HR", "disciplines": ["PT", "OT"]}


def test_concurrent_session_credits_half_its_raw_minutes_and_discards_the_half():
    """A 51-minute concurrent session credits 25 minutes, not 25.5.

    PRD §3.6: "`credited_minutes` is then derived from `raw_minutes` by modality:
    an `INDIVIDUAL` session credits its raw minutes in full; a `CONCURRENT`
    session credits its raw minutes divided by two with any fraction discarded; a
    `GROUP` session credits its raw minutes divided by `group_size` with any
    fraction discarded."

    Design: Corner/calculations/concurrent_modality_credits_half_of_raw_minutes
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)

    session = schedule_session(env, stay["admission"]["id"],
                               "2026-08-05T09:00:00Z", "2026-08-05T09:51:00Z",
                               modality="CONCURRENT", group_size=2)

    assert_therapy_session(session)
    assert session["raw_minutes"] == 51
    assert session["credited_minutes"] == 25
    assert session["status"] == "SCHEDULED"
    assert session["session_date"] == "2026-08-05"
    assert session["therapy_week_id"] == stay["week"]["id"]


def test_group_session_of_six_credits_the_floor_of_its_share():
    """One hundred raw minutes shared six ways credit 16, discarding two thirds.

    PRD §3.6: "a `GROUP` session credits its raw minutes divided by `group_size`
    with any fraction discarded."

    Design: Corner/calculations/group_session_credits_floor_of_raw_minutes_over_group_size
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)

    session = schedule_session(env, stay["admission"]["id"],
                               "2026-08-05T09:00:00Z", "2026-08-05T10:40:00Z",
                               modality="GROUP", group_size=6)

    assert session["raw_minutes"] == 100
    assert session["credited_minutes"] == 16
    assert session["group_size"] == 6
    assert session["modality"] == "GROUP"


def test_week_counts_the_delivered_session_and_ignores_the_scheduled_one():
    """Two identical hours are booked but only the documented hour is credited.

    PRD §3.6: "Documenting a session as delivered moves it from `SCHEDULED` to
    `DELIVERED`, requires the admission to still be `ADMITTED`
    (`ERR_ADMISSION_NOT_ACTIVE`) and the treating clinician to still be `ACTIVE`,
    and stamps `documented_at` from the logical clock. The session's
    `credited_minutes` are added to its week's `delivered_credited_minutes` and
    the week's `qualifying_days_count` is refreshed"

    Design: Corner/calculations/week_minutes_count_delivered_sessions_only
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    admission_id = stay["admission"]["id"]
    delivered_session = schedule_session(env, admission_id,
                                         "2026-08-05T09:00:00Z",
                                         "2026-08-05T10:00:00Z")
    scheduled_session = schedule_session(env, admission_id,
                                         "2026-08-05T11:00:00Z",
                                         "2026-08-05T12:00:00Z")

    set_clock("2026-08-05T18:00:00Z")
    deliver_session(env, delivered_session["id"])

    assert read_therapy_session(scheduled_session["id"])["status"] == "SCHEDULED"
    week = read_therapy_week(stay["week"]["id"])
    assert_week_counters(week, delivered_credited_minutes=60,
                         qualifying_days_count=0)


def test_daily_cap_accepts_exactly_three_hundred_minutes_then_refuses_more():
    """Three hours plus two hours fill the 300-minute ceiling to the minute.

    PRD §3.6: "the credited minutes already booked for that admission on the same
    `session_date`, counting both `SCHEDULED` and `DELIVERED` sessions, plus the
    new session's own `credited_minutes`, must not exceed the facility's
    `daily_therapy_cap_minutes`; exceeding it is `ERR_DAILY_THERAPY_CAP_EXCEEDED`."

    Design: Corner/calculations/daily_therapy_cap_admits_exactly_three_hundred_then_rejects
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    admission_id = stay["admission"]["id"]
    morning = schedule_session(env, admission_id, "2026-08-05T09:00:00Z",
                               "2026-08-05T12:00:00Z")
    afternoon = schedule_session(env, admission_id, "2026-08-05T12:10:00Z",
                                 "2026-08-05T14:10:00Z")
    assert morning["credited_minutes"] == 180
    assert afternoon["credited_minutes"] == 120

    response = api_client.create_therapy_session(
        create_therapy_session_payload(admission_id, env["pt"]["id"],
                                       "2026-08-05T14:20:00Z",
                                       "2026-08-05T14:50:00Z"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DAILY_THERAPY_CAP_EXCEEDED)
    assert read_therapy_week(stay["week"]["id"])["delivered_credited_minutes"] == 0


def test_voiding_a_scheduled_session_moves_no_minutes():
    """The booking is released while the week's counters stay exactly where they were.

    PRD §3.6: "Voiding a `SCHEDULED` session also moves it to `VOIDED` but
    adjusts no minutes at all, because a scheduled session never contributed
    any"

    Design: Corner/state_machines/scheduled_session_void_leaves_week_minutes_untouched
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    session = schedule_session(env, stay["admission"]["id"],
                               "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")

    response = api_client.void_therapy_session(
        session["id"], void_session_payload(void_reason="Booked on the wrong stay"),
        env["pt_headers"],
    )

    voided = validate_success(response, expected_status=200)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "Booked on the wrong stay"
    assert voided["credited_minutes"] == 180
    week = read_therapy_week(stay["week"]["id"])
    assert_week_counters(week, delivered_credited_minutes=0,
                         qualifying_days_count=0, status="OPEN")


def test_session_shorter_than_one_whole_minute_is_rejected():
    """Thirty seconds of therapy is not a schedulable interval.

    PRD §3.6: "`end_at` must be strictly after `start_at` and the interval must be
    at least one whole minute long, or the request is
    `ERR_INVALID_SESSION_INTERVAL`."

    Design: Corner/validations/therapy_session_of_thirty_seconds_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)

    response = api_client.create_therapy_session(
        create_therapy_session_payload(stay["admission"]["id"], env["pt"]["id"],
                                       "2026-08-05T09:00:00Z",
                                       "2026-08-05T09:00:30Z"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_SESSION_INTERVAL)


def test_group_session_of_only_two_patients_is_rejected():
    """A group of two is the concurrent modality, not the group modality.

    PRD §3.6: "Group size and modality must agree: `INDIVIDUAL` requires exactly
    1, `CONCURRENT` requires exactly 2, and `GROUP` requires between 3 and 6
    inclusive; anything else is `ERR_GROUP_SIZE_INVALID`."

    Design: Corner/validations/group_session_with_group_size_two_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)

    response = api_client.create_therapy_session(
        create_therapy_session_payload(stay["admission"]["id"], env["pt"]["id"],
                                       "2026-08-05T09:00:00Z",
                                       "2026-08-05T10:00:00Z",
                                       modality="GROUP", group_size=2),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_GROUP_SIZE_INVALID)


def test_session_treated_by_a_clinician_of_another_facility_is_rejected():
    """The outside therapist holds the right credential but the wrong employer.

    PRD §2.10: "Clinical records in this system are facility-scoped, and a
    referenced clinician or patient must belong to the same facility as the
    resource being written; a cross-facility reference is a conflict, reported as
    `ERR_CROSS_FACILITY_MISMATCH`, and it is checked on screening creation,
    therapy-session scheduling, team-conference recording, assessment opening and
    plan-of-care signing."

    Design: Corner/validations/session_with_clinician_from_another_facility_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    rival = register_facility(name="Rival Rehab Institute", cms_ccn="200043")
    outsider = register_clinician(rival["id"], "THERAPIST_PT", "1000000077",
                                  full_name="Olga Outsider")

    response = api_client.create_therapy_session(
        create_therapy_session_payload(stay["admission"]["id"], outsider["id"],
                                       "2026-08-05T09:00:00Z",
                                       "2026-08-05T10:00:00Z"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CROSS_FACILITY_MISMATCH)
    assert read_therapy_week(stay["week"]["id"])["delivered_credited_minutes"] == 0


def test_session_in_a_discipline_the_plan_never_named_is_rejected():
    """The plan authorises physical therapy only, so occupational therapy fails.

    PRD §3.6: "The declared `discipline` must appear in the active plan's
    `disciplines` (`ERR_DISCIPLINE_NOT_IN_PLAN`), and the treating clinician's
    credential must match it exactly — `THERAPIST_PT` for `PT`, `THERAPIST_OT`
    for `OT`, `THERAPIST_SLP` for `SLP` — with a mismatch reported as
    `ERR_CLINICIAN_DISCIPLINE_MISMATCH`."

    Design: Corner/validations/session_discipline_outside_plan_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt", "ot"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)

    response = api_client.create_therapy_session(
        create_therapy_session_payload(stay["admission"]["id"], env["ot"]["id"],
                                       "2026-08-05T09:00:00Z",
                                       "2026-08-05T10:00:00Z", discipline="OT"),
        env["ot_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DISCIPLINE_NOT_IN_PLAN)


def test_occupational_therapy_treated_by_a_physical_therapist_is_rejected():
    """Occupational therapy is in the plan, but the therapist is a PT.

    PRD §3.6: "the treating clinician's credential must match it exactly —
    `THERAPIST_PT` for `PT`, `THERAPIST_OT` for `OT`, `THERAPIST_SLP` for `SLP` —
    with a mismatch reported as `ERR_CLINICIAN_DISCIPLINE_MISMATCH`."

    Design: Corner/validations/session_clinician_credential_mismatched_to_discipline_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT_AND_OT)

    response = api_client.create_therapy_session(
        create_therapy_session_payload(stay["admission"]["id"], env["pt"]["id"],
                                       "2026-08-05T09:00:00Z",
                                       "2026-08-05T10:00:00Z", discipline="OT"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CLINICIAN_DISCIPLINE_MISMATCH)


def test_session_dated_beyond_every_open_window_is_rejected():
    """The only window closes on 08-10, so an 08-12 session has no home.

    PRD §3.6: "`therapy_week_id` is resolved to the one week of that admission
    whose window contains `session_date`"

    PRD §3.6: "when no candidate week exists the request fails with
    `ERR_NO_OPEN_THERAPY_WEEK`"

    Design: Corner/validations/session_outside_every_week_window_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_PT)
    assert stay["week"]["week_end_date"] == "2026-08-10"

    response = api_client.create_therapy_session(
        create_therapy_session_payload(stay["admission"]["id"], env["pt"]["id"],
                                       "2026-08-12T09:00:00Z",
                                       "2026-08-12T10:00:00Z"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_NO_OPEN_THERAPY_WEEK)
