"""Discipline: referral/review/adjudication, the OSS suspension attendance cascade,
rescind compensation, and segregation of duties.

Covers difficulty instances under transitive_cascade (OSS depth-3),
compensating_invariant (rescind), non_linear_state_machine (incident branch),
priority_pair_validation_conflict (begin-review state vs SoD), plus corner
instances under state_machines.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    make_teacher_headers, make_administrator_headers,
    fixtures as fx,
)

REG = TEST_USERS["registrar_headers"]


def _attendance_records(api, enrollment_id, **params):
    p = {"enrollment_id": enrollment_id}
    p.update(params)
    data, _ = validate_paginated(api.list_attendance_records(REG, params=p))
    return data


# ---------------------------------------------------------------------------
# transitive_cascade / oss_suspension_cascade_depth3_present_days
# ---------------------------------------------------------------------------
def test_oss_cascade_writes_system_suspension_and_drops_present_days(api):
    """PRD §3.10: "For each day index d in the span from start_day_index up to but
    not including start_day_index plus duration_days, and for each ENROLLED schedule
    assignment of the enrollment, the system writes an AttendanceRecord with code
    ABSENT_EXCUSED and source SYSTEM_SUSPENSION; any existing RECORDED record for that
    assignment and day is moved to SUPERSEDED."
    PRD §3.10: "the enrollment's present_days is recomputed."

    Design: Difficulty/transitive_cascade/oss_suspension_cascade_depth3_present_days
    """
    ctx = fx.setup_oss_ready_scenario(present_days=[1, 2, 3, 4, 5], incident_day_index=2,
                                      clock_days=5, meeting_minutes=240,
                                      ada_method="AGGREGATE_MEMBERSHIP")
    cons = fx.attach_consequence(ctx["incident"]["id"], "OUT_OF_SCHOOL_SUSPENSION",
                                 adjudicator_user_id="admin-1", start_day_index=3, duration_days=2)
    assert cons["absence_code_applied"] == "ABSENT_EXCUSED", \
        f"OSS absence_code_applied expected ABSENT_EXCUSED, got {cons['absence_code_applied']}"
    susp = _attendance_records(api, ctx["enrollment"]["id"], status="RECORDED")
    susp_days = {r["day_index"] for r in susp if r["source"] == "SYSTEM_SUSPENSION"}
    assert {3, 4} <= susp_days, f"SYSTEM_SUSPENSION records expected on days 3 and 4, got {susp_days}"
    enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))
    assert enr["present_days"] == 3, f"present_days expected 3 after OSS, got {enr['present_days']}"


def test_oss_cascade_flips_daily_attendance_absent(api):
    """PRD §3.10: "Each affected enrollment-and-day DailyAttendance row is then
    recomputed via the daily rollup". PRD §3.6: "Under a school whose ada_method is
    AGGREGATE_MEMBERSHIP, a day is eligible whenever its daily_code is anything other
    than ABSENT".

    Design: Difficulty/transitive_cascade/oss_suspension_cascade_depth3_present_days
    """
    ctx = fx.setup_oss_ready_scenario(present_days=[1, 2, 3, 4, 5], incident_day_index=2,
                                      clock_days=5, meeting_minutes=240,
                                      ada_method="AGGREGATE_MEMBERSHIP")
    fx.attach_consequence(ctx["incident"]["id"], "OUT_OF_SCHOOL_SUSPENSION",
                          adjudicator_user_id="admin-1", start_day_index=3, duration_days=2)
    data, _ = validate_paginated(
        api.list_daily_attendance(ctx["enrollment"]["id"], REG, params={"day_index": 3}))
    assert data, "expected a daily-attendance row for day 3"
    row = data[0]
    # ABSENT_EXCUSED contributes 0 present minutes -> daily_code ABSENT, not eligible.
    assert row["daily_code"] == "ABSENT", f"day-3 daily_code expected ABSENT, got {row['daily_code']}"
    assert row["ada_eligible"] is False, "ABSENT day is not ADA-eligible"


# ---------------------------------------------------------------------------
# compensating_invariant / suspension_rescind_preserves_present_days
# ---------------------------------------------------------------------------
def test_rescind_restores_present_days(api):
    """PRD §3.10: "This is a true compensating action: after a rescind, the
    enrollment's present_days must return to exactly the value it held before the
    suspension was applied."

    Design: Difficulty/compensating_invariant/suspension_rescind_preserves_present_days
    """
    ctx = fx.setup_oss_ready_scenario(present_days=[1, 2, 3, 4, 5], incident_day_index=2,
                                      clock_days=5, meeting_minutes=240,
                                      ada_method="AGGREGATE_MEMBERSHIP", severity=3)
    cons = fx.attach_consequence(ctx["incident"]["id"], "OUT_OF_SCHOOL_SUSPENSION",
                                 adjudicator_user_id="admin-1", start_day_index=3, duration_days=2)
    assert validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))["present_days"] == 3
    rescinded = validate_success(
        api.rescind_consequence(cons["id"], make_administrator_headers("admin-1")))
    assert rescinded["status"] == "RESCINDED"
    enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))
    assert enr["present_days"] == 5, f"present_days restored to 5, got {enr['present_days']}"


def test_rescind_removes_system_suspension_records(api):
    """PRD §3.10: "The rescind reverses the cascade exactly: every SYSTEM_SUSPENSION
    record this consequence created and still holding RECORDED status is deleted, and
    for each affected assignment-and-day the most recent record that had been
    superseded — the latest SUPERSEDED record by created_at descending — is restored
    to RECORDED."

    Design: Difficulty/compensating_invariant/suspension_rescind_preserves_present_days
    """
    ctx = fx.setup_oss_ready_scenario(present_days=[1, 2, 3, 4, 5], incident_day_index=2,
                                      clock_days=5, meeting_minutes=240,
                                      ada_method="AGGREGATE_MEMBERSHIP", severity=3)
    cons = fx.attach_consequence(ctx["incident"]["id"], "OUT_OF_SCHOOL_SUSPENSION",
                                 adjudicator_user_id="admin-1", start_day_index=3, duration_days=2)
    validate_success(api.rescind_consequence(cons["id"], make_administrator_headers("admin-1")))
    recorded = _attendance_records(api, ctx["enrollment"]["id"], status="RECORDED")
    assert not any(r["source"] == "SYSTEM_SUSPENSION" for r in recorded), \
        "no RECORDED SYSTEM_SUSPENSION record remains after rescind"


# ---------------------------------------------------------------------------
# non_linear_state_machine / incident_branch_referred_to_dismissed_vs_adjudicated
# ---------------------------------------------------------------------------
def test_incident_branch_dismiss_is_terminal(api):
    """PRD §3.9: "a dismiss moves the incident to DISMISSED and rescinds any
    still-active consequence of the incident". PRD §3.9: "Both ADJUDICATED and
    DISMISSED are terminal."

    Design: Difficulty/non_linear_state_machine/incident_branch_referred_to_dismissed_vs_adjudicated
    """
    base = fx.setup_incident_under_review(referring_user_id="teacher-1",
                                          adjudicator_user_id="admin-1")
    inc_id = base["incident"]["id"]
    dismissed = validate_success(api.dismiss_incident(inc_id, make_administrator_headers("admin-1")))
    assert dismissed["status"] == "DISMISSED"


def test_dismissed_incident_cannot_be_adjudicated(api):
    """PRD §3.9: "Finally the administrator may adjudicate, permitted only while the
    incident is UNDER_REVIEW (otherwise ERR_INCIDENT_NOT_UNDER_REVIEW)".

    Design: Difficulty/non_linear_state_machine/incident_branch_referred_to_dismissed_vs_adjudicated
    """
    base = fx.setup_incident_under_review(referring_user_id="teacher-1",
                                          adjudicator_user_id="admin-1")
    inc_id = base["incident"]["id"]
    validate_success(api.dismiss_incident(inc_id, make_administrator_headers("admin-1")))
    resp = api.adjudicate(inc_id, make_administrator_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_UNDER_REVIEW.value, expected_status=409)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / begin_review_state_vs_segregation_priority
# ---------------------------------------------------------------------------
def test_begin_review_state_check_wins_over_segregation(api):
    """PRD §2.12: "Then the target resource's state is checked for whether it permits
    the requested transition (the relevant state error, such as
    ERR_ENROLLMENT_NOT_ACTIVE or ERR_INCIDENT_NOT_UNDER_REVIEW). Only after all of
    these do the domain-specific business-safety, temporal, and constraint checks run
    — segregation of duties".
    PRD §3.9: "An administrator opens review, which is permitted only while the
    incident is REFERRED (otherwise ERR_INCIDENT_NOT_REFERRED)".

    Design: Difficulty/priority_pair_validation_conflict/begin_review_state_vs_segregation_priority
    """
    base = fx.setup_enrolled_student()
    inc = fx.file_incident(base["enrollment"]["id"], category="DISRUPTION", severity=1,
                           incident_day_index=1, referring_user_id="u-dual", as_role="Administrator")
    validate_success(api.dismiss_incident(inc["id"], make_administrator_headers("admin-1")))
    # begin-review by the original referrer (u-dual) on a DISMISSED incident:
    # state error (NOT_REFERRED) takes precedence over SoD.
    resp = api.begin_review(inc["id"], make_administrator_headers("u-dual"))
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_REFERRED.value, expected_status=409)
    refreshed = validate_success(api.get_discipline_incident(inc["id"], REG))
    assert refreshed["status"] == "DISMISSED", "incident unchanged after rejected begin-review"


def test_begin_review_state_error_when_only_state_violated(api):
    """PRD §3.9: "An administrator opens review, which is permitted only while the
    incident is REFERRED (otherwise ERR_INCIDENT_NOT_REFERRED)".

    Isolates the lower-priority rule of the pair: a non-referrer (SoD satisfied)
    begins review on a DISMISSED incident, so only the state precondition fails and
    ERR_INCIDENT_NOT_REFERRED is returned — confirming it is the rule that wins when
    both state and segregation are violated.

    Design: Difficulty/priority_pair_validation_conflict/begin_review_state_vs_segregation_priority
    """
    base = fx.setup_enrolled_student()
    inc = fx.file_incident(base["enrollment"]["id"], category="DISRUPTION", severity=1,
                           incident_day_index=1, referring_user_id="u-ref", as_role="Administrator")
    validate_success(api.dismiss_incident(inc["id"], make_administrator_headers("admin-1")))
    # acting admin (admin-2) is NOT the referrer, so SoD passes; only state is bad.
    resp = api.begin_review(inc["id"], make_administrator_headers("admin-2"))
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_REFERRED.value, expected_status=409)


def test_begin_review_by_referrer_on_referred_is_segregation(api):
    """PRD §3.9: "An administrator opens review, which is permitted only while the
    incident is REFERRED (otherwise ERR_INCIDENT_NOT_REFERRED) and only when the
    acting X-User-ID differs from the referring_user_id (otherwise
    ERR_SEGREGATION_OF_DUTIES)".

    Design: Corner/state_machines/begin_review_by_referrer_segregation_denied
    """
    base = fx.setup_enrolled_student()
    inc = fx.file_incident(base["enrollment"]["id"], category="DISRUPTION", severity=2,
                           incident_day_index=1, referring_user_id="admin-dual", as_role="Administrator")
    resp = api.begin_review(inc["id"], make_administrator_headers("admin-dual"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)
    refreshed = validate_success(api.get_discipline_incident(inc["id"], REG))
    assert refreshed["status"] == "REFERRED", "incident stays REFERRED"


# ---------------------------------------------------------------------------
# corner: adjudicate_before_consequence_returns_no_consequence
# ---------------------------------------------------------------------------
def test_adjudicate_before_consequence_rejected(api):
    """PRD §3.9: "and only once a consequence already exists for the incident
    (otherwise ERR_NO_CONSEQUENCE_RECORDED)".

    Design: Corner/state_machines/adjudicate_before_consequence_returns_no_consequence
    """
    base = fx.setup_incident_under_review(referring_user_id="teacher-1",
                                          adjudicator_user_id="admin-1")
    resp = api.adjudicate(base["incident"]["id"], make_administrator_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_NO_CONSEQUENCE_RECORDED.value, expected_status=409)
    refreshed = validate_success(api.get_discipline_incident(base["incident"]["id"], REG))
    assert refreshed["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# corner: adjudicate_by_non_reviewer_denied
# ---------------------------------------------------------------------------
def test_adjudicate_by_non_reviewer_rejected(api):
    """PRD §3.9: "only when the acting X-User-ID equals the pinned adjudicator_user_id
    so that only the reviewer who opened the case may close it (otherwise
    ERR_NOT_ASSIGNED_ADJUDICATOR)".

    Design: Corner/state_machines/adjudicate_by_non_reviewer_denied
    """
    base = fx.setup_incident_under_review(referring_user_id="teacher-1",
                                          adjudicator_user_id="admin-1")
    fx.attach_consequence(base["incident"]["id"], "WARNING", adjudicator_user_id="admin-1")
    resp = api.adjudicate(base["incident"]["id"], make_administrator_headers("admin-2"))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_ADJUDICATOR.value, expected_status=403)


# ---------------------------------------------------------------------------
# corner: weapon_suspension_cap_exceeded_rejected
# ---------------------------------------------------------------------------
def test_weapon_oss_over_cap_rejected(api):
    """PRD §3.10: "a WEAPON-category out-of-school suspension is capped at a statutory
    maximum of 10 days, so a duration_days exceeding 10 for that category is rejected
    with ERR_SUSPENSION_CAP_EXCEEDED."

    Design: Corner/state_machines/weapon_suspension_cap_exceeded_rejected
    """
    school = fx.create_school(ada_method="AGGREGATE_MEMBERSHIP", minimum_daily_minutes=240)
    fx.advance_clock(school["id"], 20)
    student = fx.create_student(school["id"], grade_level="10")
    enr = fx.create_enrollment(student["id"], entry_day_index=1)
    inc = fx.file_incident(enr["id"], category="WEAPON", severity=5, incident_day_index=1,
                           referring_user_id="teacher-1")
    fx.begin_review(inc["id"], adjudicator_user_id="admin-1")
    resp = api.create_consequence(
        inc["id"], {"type": "OUT_OF_SCHOOL_SUSPENSION", "start_day_index": 1, "duration_days": 11},
        make_administrator_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_SUSPENSION_CAP_EXCEEDED.value, expected_status=422)
