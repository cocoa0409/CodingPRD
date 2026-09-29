"""Temporal overlap rules for clinicians, patients and therapy-week windows."""

from test_helpers import (
    OFFICER_HEADERS,
    ApiErrorId,
    api_client,
    create_therapy_session_payload,
    create_therapy_week_payload,
    discharge,
    open_therapy_week,
    read_therapy_session,
    schedule_session,
    setup_admitted_cohort,
    setup_facility_with_staff,
    setup_stay_with_week,
    sign_plan_of_care,
    validate_error,
    validate_paginated,
    validate_success,
)

PLAN_DAILY_PT = {"three_hour_rule_mode": "DAILY_3HR", "disciplines": ["PT"]}
PATIENT_B = {
    "impairment_group_code": "0704",
    "etiologic_diagnosis_code": "S72.001A",
    "full_name": "Bo Whitaker",
}


def test_session_starting_exactly_when_the_previous_one_ends_is_accepted():
    """A clinician's back-to-back sessions for two patients are legal.

    PRD §3.6: "A treating clinician may not be double-booked: the new session's
    half-open interval from `start_at` up to but excluding `end_at` must not
    intersect the interval of any other `SCHEDULED` or `DELIVERED` session of
    the same `clinician_id`, though exact adjacency — where a previous
    session's `end_at` equals the new `start_at` — is allowed; an intersection
    is `ERR_CLINICIAN_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/clinician_half_open_interval_allows_adjacency_and_rejects_overlap
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stays = setup_admitted_cohort(env, [
        {"mrn": "MRN-A"},
        {"mrn": "MRN-B", "patient_overrides": PATIENT_B},
    ])
    admission_a = stays[0]["admission"]["id"]
    admission_b = stays[1]["admission"]["id"]
    for admission_id in (admission_a, admission_b):
        sign_plan_of_care(env, admission_id, three_hour_rule_mode="DAILY_3HR",
                          disciplines=["PT"])
    open_therapy_week(env, admission_a, week_start_date="2026-08-04")
    week_b = open_therapy_week(env, admission_b, week_start_date="2026-08-04")
    schedule_session(env, admission_a,
                     "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")

    response = api_client.create_therapy_session(
        create_therapy_session_payload(admission_b, env["pt"]["id"],
                                       "2026-08-05T12:00:00Z",
                                       "2026-08-05T13:00:00Z"),
        env["pt_headers"],
    )

    adjacent = validate_success(response, expected_status=201)
    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["credited_minutes"] == 60
    assert adjacent["therapy_week_id"] == week_b["id"]


def test_session_overlapping_the_same_clinician_is_refused():
    """An interval that intersects the clinician's other session is rejected.

    PRD §3.6: "A treating clinician may not be double-booked: the new session's
    half-open interval from `start_at` up to but excluding `end_at` must not
    intersect the interval of any other `SCHEDULED` or `DELIVERED` session of
    the same `clinician_id`, though exact adjacency — where a previous
    session's `end_at` equals the new `start_at` — is allowed; an intersection
    is `ERR_CLINICIAN_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/clinician_half_open_interval_allows_adjacency_and_rejects_overlap
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stays = setup_admitted_cohort(env, [
        {"mrn": "MRN-A"},
        {"mrn": "MRN-B", "patient_overrides": PATIENT_B},
    ])
    admission_a = stays[0]["admission"]["id"]
    admission_b = stays[1]["admission"]["id"]
    for admission_id in (admission_a, admission_b):
        sign_plan_of_care(env, admission_id, three_hour_rule_mode="DAILY_3HR",
                          disciplines=["PT"])
    open_therapy_week(env, admission_a, week_start_date="2026-08-04")
    open_therapy_week(env, admission_b, week_start_date="2026-08-04")
    first = schedule_session(env, admission_a,
                             "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")
    schedule_session(env, admission_b,
                     "2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z")

    response = api_client.create_therapy_session(
        create_therapy_session_payload(admission_b, env["pt"]["id"],
                                       "2026-08-05T11:30:00Z",
                                       "2026-08-05T11:45:00Z"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CLINICIAN_SCHEDULE_CONFLICT)
    _, meta = validate_paginated(api_client.list_therapy_sessions(
        OFFICER_HEADERS, {"clinician_id": env["pt"]["id"]}
    ))
    assert meta["total_count"] == 2
    assert read_therapy_session(first["id"])["status"] == "SCHEDULED"


def test_session_exactly_ten_minutes_after_the_last_one_is_accepted():
    """Ten minutes of separation satisfies the patient's rest buffer.

    PRD §3.6: "The patient is owed a rest buffer: across the `SCHEDULED` and
    `DELIVERED` sessions of the same `admission_id`, the new session is refused
    when its `start_at` falls earlier than another session's `end_at` plus ten
    minutes while that other session's `start_at` falls earlier than the new
    session's `end_at` plus ten minutes; exactly ten minutes of separation is
    acceptable, and a violation is `ERR_PATIENT_REST_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/patient_rest_buffer_allows_exactly_ten_minutes_and_rejects_nine
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt", "pt2"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    schedule_session(env, admission_id,
                     "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")

    response = api_client.create_therapy_session(
        create_therapy_session_payload(admission_id, env["pt2"]["id"],
                                       "2026-08-05T10:10:00Z",
                                       "2026-08-05T11:00:00Z"),
        env["pt2_headers"],
    )

    rested = validate_success(response, expected_status=201)
    assert rested["status"] == "SCHEDULED"
    assert rested["credited_minutes"] == 50


def test_session_nine_minutes_after_the_last_one_is_refused():
    """Nine minutes of separation breaches the patient's rest buffer.

    PRD §3.6: "The patient is owed a rest buffer: across the `SCHEDULED` and
    `DELIVERED` sessions of the same `admission_id`, the new session is refused
    when its `start_at` falls earlier than another session's `end_at` plus ten
    minutes while that other session's `start_at` falls earlier than the new
    session's `end_at` plus ten minutes; exactly ten minutes of separation is
    acceptable, and a violation is `ERR_PATIENT_REST_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/patient_rest_buffer_allows_exactly_ten_minutes_and_rejects_nine
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt", "pt2"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    base = schedule_session(env, admission_id,
                            "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    schedule_session(env, admission_id, "2026-08-05T10:10:00Z",
                     "2026-08-05T11:00:00Z", clinician_key="pt2")

    response = api_client.create_therapy_session(
        create_therapy_session_payload(admission_id, env["pt"]["id"],
                                       "2026-08-05T10:09:00Z",
                                       "2026-08-05T10:20:00Z"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PATIENT_REST_BUFFER_VIOLATION)
    _, meta = validate_paginated(api_client.list_therapy_sessions(
        OFFICER_HEADERS, {"admission_id": admission_id}
    ))
    assert meta["total_count"] == 2
    assert read_therapy_session(base["id"])["credited_minutes"] == 60


def test_therapy_week_windows_that_merely_touch_are_legal():
    """A window opening the day after the previous one ends is accepted.

    PRD §3.6: "The window may not start before the day the patient was admitted
    (`ERR_WEEK_BEFORE_ADMISSION`) and may not overlap any existing window of
    the same admission, although windows that merely touch — where the previous
    window's `week_end_date` plus one day equals the new `week_start_date` — are
    perfectly legal; an actual overlap is `ERR_THERAPY_WEEK_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/therapy_week_windows_touch_allowed_and_overlap_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(
        env, plan_overrides={"three_hour_rule_mode": "DAILY_3HR",
                             "disciplines": ["PT"], "target_los_days": 21},
    )
    assert stay["week"]["week_end_date"] == "2026-08-10"

    response = api_client.create_therapy_week(
        create_therapy_week_payload(stay["admission"]["id"], week_index=2,
                                    week_start_date="2026-08-11"),
        env["pt_headers"],
    )

    second = validate_success(response, expected_status=201)
    assert second["week_start_date"] == "2026-08-11"
    assert second["week_end_date"] == "2026-08-17"
    assert second["status"] == "OPEN"


def test_therapy_week_window_overlapping_an_existing_window_is_refused():
    """A window starting inside an existing window is rejected.

    PRD §3.6: "The `week_end_date` is derived as the `week_start_date` plus six
    days, so the window covers seven inclusive calendar dates."

    Design: Difficulty/resource_temporal_overlap/therapy_week_windows_touch_allowed_and_overlap_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(
        env, plan_overrides={"three_hour_rule_mode": "DAILY_3HR",
                             "disciplines": ["PT"], "target_los_days": 21},
    )
    admission_id = stay["admission"]["id"]
    open_therapy_week(env, admission_id, week_index=2,
                      week_start_date="2026-08-11")

    response = api_client.create_therapy_week(
        create_therapy_week_payload(admission_id, week_index=3,
                                    week_start_date="2026-08-16"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_THERAPY_WEEK_OVERLAP)
    _, meta = validate_paginated(api_client.list_therapy_weeks(
        OFFICER_HEADERS, {"admission_id": admission_id}
    ))
    assert meta["total_count"] == 2


def test_scheduling_on_a_discharged_stay_reports_the_admission_state_first():
    """The admission-state check outranks the clinician double-booking check.

    PRD §2.5: "Implementations must evaluate checks in the following fixed
    order, so that an early failure masks every later one; a request that
    violates three rules reports only the highest-ranked violation."

    Design: Difficulty/priority_pair_validation_conflict/session_create_rejected_by_admission_state_over_clinician_overlap
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    schedule_session(env, admission_id,
                     "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")
    discharge(env, admission_id, "2026-08-06T12:00:00Z")

    response = api_client.create_therapy_session(
        create_therapy_session_payload(admission_id, env["pt"]["id"],
                                       "2026-08-05T10:00:00Z",
                                       "2026-08-05T11:00:00Z"),
        env["pt_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ADMISSION_NOT_ACTIVE)


def test_refused_scheduling_adds_no_session_row_to_the_stay():
    """The rejected request leaves the single existing session untouched.

    PRD §2.5: "**Admission is `ADMITTED`** — required by plan-of-care signing,
    therapy-week opening, session scheduling, session delivery and
    team-conference recording, else `ERR_ADMISSION_NOT_ACTIVE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/session_create_rejected_by_admission_state_over_clinician_overlap
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    kept = schedule_session(env, admission_id,
                            "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")
    discharge(env, admission_id, "2026-08-06T12:00:00Z")

    api_client.create_therapy_session(
        create_therapy_session_payload(admission_id, env["pt"]["id"],
                                       "2026-08-05T10:00:00Z",
                                       "2026-08-05T11:00:00Z"),
        env["pt_headers"],
    )

    _, meta = validate_paginated(api_client.list_therapy_sessions(
        OFFICER_HEADERS, {"admission_id": admission_id}
    ))
    assert meta["total_count"] == 1
    assert read_therapy_session(kept["id"])["status"] == "SCHEDULED"
