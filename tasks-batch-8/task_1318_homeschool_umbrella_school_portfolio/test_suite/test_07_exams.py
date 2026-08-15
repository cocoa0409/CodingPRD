"""Standardized testing: session lifecycle, registration gates, buffer rule,
scoring boundary, and standing cascades."""
from test_helpers import (
    ApiErrorId,
    assert_test_registration,
    create_exam_session,
    create_open_exam_session,
    create_open_year,
    get_success_data,
    register_exam,
    register_exam_ok,
    set_clock,
    setup_active_enrollment,
    setup_administered_registration,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]


def _setup_two_scored_registrations(api):
    """Grade-5 enrollment (testing required) with two ATTENDED registrations on
    consecutive days, both sessions ADMINISTERED."""
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 5, family_name="Fam Exam",
                                  district_code="D-16", date_of_birth="2015-06-06")
    s1 = create_open_exam_session(year["id"], session_date="2026-09-15",
                                  target_grades=[5])
    s2 = create_open_exam_session(year["id"], session_date="2026-09-16",
                                  target_grades=[5])
    reg1 = register_exam_ok(s1["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    reg2 = register_exam_ok(s2["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    for s in (s1, s2):
        get_success_data(api.close_exam_registration(s["id"], REGISTRAR))
        get_success_data(api.administer_exam_session(s["id"], REGISTRAR))
    for reg in (reg1, reg2):
        get_success_data(
            api.record_attendance(reg["id"], {"attendance_outcome": "ATTENDED"}, REGISTRAR)
        )
    return ctx, reg1, reg2


def test_record_score_22_fails(api):
    """PRD §3.6: "A percentile of at least 23 passes — 22 fails, 23 passes —
    and the result is stored on `passed`; `testing_satisfied` is then recomputed,
    a passing score satisfying the requirement."

    Design: Difficulty/boundary_precision_check/exam_passing_percentile_boundary
    """
    _ctx, reg1, _reg2 = _setup_two_scored_registrations(api)
    scored = validate_success(
        api.record_score(reg1["id"], {"composite_percentile": 22}, REGISTRAR)
    )
    assert_test_registration(scored)
    assert scored["status"] == "SCORED"
    assert scored["composite_percentile"] == 22
    assert scored["passed"] is False


def test_record_score_23_passes_and_satisfies(api):
    """PRD §3.6: "A percentile of at least 23 passes — 22 fails, 23 passes —
    and the result is stored on `passed`; `testing_satisfied` is then recomputed,
    a passing score satisfying the requirement."
    PRD §3.6: "`testing_satisfied` flips true once the enrollment has a
    registration that reached `SCORED` with `passed` true, or one that was
    `EXCUSED`."

    Design: Difficulty/boundary_precision_check/exam_passing_percentile_boundary
    """
    ctx, reg1, reg2 = _setup_two_scored_registrations(api)
    get_success_data(api.record_score(reg1["id"], {"composite_percentile": 22}, REGISTRAR))
    scored2 = validate_success(
        api.record_score(reg2["id"], {"composite_percentile": 23}, REGISTRAR)
    )
    assert scored2["passed"] is True, "exactly 23 satisfies >= 23"

    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["testing_required"] is True, "grade 5 is in the default testing_grades"
    assert enrollment["testing_satisfied"] is True


def test_exam_buffer_conflict_at_15_minutes(api):
    """PRD §3.6: "A sixth check protects the student's own day: the new sitting
    must keep a thirty-minute buffer against every other session of the same
    student on the same date holding a registration in `REGISTERED`, `ATTENDED`,
    or `SCORED` — a gap under thirty minutes conflicts as
    `ERR_EXAM_SCHEDULE_CONFLICT`, while exactly thirty minutes is allowed."

    Design: Difficulty/resource_temporal_overlap/exam_session_thirty_minute_buffer_overlap
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 3, family_name="Fam Buf",
                                  district_code="D-23", date_of_birth="2017-11-11")
    sa = create_open_exam_session(year["id"], test_name="IOWA",
                                  session_date="2026-09-15",
                                  start_minutes=540, end_minutes=660, target_grades=[3])
    sb = create_open_exam_session(year["id"], test_name="STANFORD",
                                  session_date="2026-09-15",
                                  start_minutes=675, end_minutes=750, target_grades=[3])
    reg_a = register_exam_ok(sa["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    assert reg_a["status"] == "REGISTERED"

    # Gap 675 - 660 = 15 minutes < 30: conflicts.
    resp = register_exam(sb["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_EXAM_SCHEDULE_CONFLICT)
    sb_after = get_success_data(api.get_exam_session(sb["id"], REGISTRAR))
    assert sb_after["seats_taken"] == 0, "conflict holds no seat"


def test_exam_buffer_exactly_30_minutes_allowed(api):
    """PRD §3.6: "a gap under thirty minutes conflicts as
    `ERR_EXAM_SCHEDULE_CONFLICT`, while exactly thirty minutes is allowed."

    Design: Difficulty/resource_temporal_overlap/exam_session_thirty_minute_buffer_overlap
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 3, family_name="Fam Buf",
                                  district_code="D-23", date_of_birth="2017-11-11")
    sa = create_open_exam_session(year["id"], test_name="IOWA",
                                  session_date="2026-09-15",
                                  start_minutes=540, end_minutes=660, target_grades=[3])
    sc = create_open_exam_session(year["id"], test_name="CAT",
                                  session_date="2026-09-15",
                                  start_minutes=690, end_minutes=750, target_grades=[3])
    register_exam_ok(sa["id"], ctx["enrollment"]["id"], ctx["family"]["id"])

    # Gap 690 - 660 = 30 minutes: exactly the permitted buffer.
    reg_c = validate_success(
        register_exam(sc["id"], ctx["enrollment"]["id"], ctx["family"]["id"]), 201
    )
    assert_test_registration(reg_c)
    assert reg_c["status"] == "REGISTERED"


def test_record_attendance_requires_administered_session(api):
    """PRD §3.6: "Once the session is `ADMINISTERED` — attendance recording
    against a session in any other state fails with `ERR_EXAM_SESSION_NOT_OPEN`
    — the registrar records each registration's `attendance_outcome`."

    Design: Corner/state_machines/record_attendance_requires_administered_session
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 5, family_name="Fam S",
                                  district_code="D-39", date_of_birth="2015-07-07")
    session = create_open_exam_session(year["id"], target_grades=[5])
    reg = register_exam_ok(session["id"], ctx["enrollment"]["id"], ctx["family"]["id"])

    resp = api.record_attendance(reg["id"], {"attendance_outcome": "ATTENDED"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_EXAM_SESSION_NOT_OPEN)
    current = get_success_data(api.get_test_registration(reg["id"], REGISTRAR))
    assert current["status"] == "REGISTERED"


def test_no_show_cascades_standing_noncompliant(api):
    """PRD §3.6: "`NO_SHOW` is terminal and, when the enrollment's
    `testing_required` is true, drives the enrollment's standing to
    `NONCOMPLIANT` with the full co-op cascade of §3.7."

    Design: Corner/state_machines/no_show_cascades_standing_noncompliant
    """
    year = create_open_year()
    ctx, _session, reg = setup_administered_registration(
        year["id"], 8, family_name="Fam N", district_code="D-40",
        date_of_birth="2012-08-08",
    )
    outcome = validate_success(
        api.record_attendance(reg["id"], {"attendance_outcome": "NO_SHOW"}, REGISTRAR)
    )
    assert outcome["status"] == "NO_SHOW"

    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["testing_required"] is True, "grade 8 is in the default testing_grades"
    assert enrollment["compliance_standing"] == "NONCOMPLIANT", "immediate cascade, no sweep"
    assert enrollment["testing_satisfied"] is False


def test_testing_satisfied_via_excused_exemption(api):
    """PRD §3.6: "`EXCUSED` requires an `exemption_note` (omitting it is
    `ERR_INVALID_REQUEST`) and moves the registration to the terminal state
    `EXCUSED`, which itself satisfies the testing requirement and triggers a
    recompute of `testing_satisfied`."

    Design: Corner/calculations/testing_satisfied_via_excused_exemption
    """
    year = create_open_year()
    ctx, _session, reg = setup_administered_registration(
        year["id"], 8, family_name="Fam X", district_code="D-48",
        date_of_birth="2012-01-01",
    )
    outcome = validate_success(
        api.record_attendance(
            reg["id"],
            {"attendance_outcome": "EXCUSED",
             "exemption_note": "documented medical exemption"},
            REGISTRAR,
        )
    )
    assert outcome["status"] == "EXCUSED"

    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["testing_satisfied"] is True, "EXCUSED satisfies the requirement"
    assert enrollment["compliance_standing"] == "GOOD_STANDING", "no NO_SHOW cascade"


def test_exam_registration_after_deadline(api):
    """PRD §3.6: "the logical clock must read at or before the session's
    `registration_deadline` (else `ERR_EXAM_REGISTRATION_DEADLINE_PASSED`)"

    Design: Corner/validations/exam_registration_after_deadline
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 5, family_name="Fam Dl",
                                  district_code="D-50")
    session = create_open_exam_session(
        year["id"], registration_deadline="2026-08-15T00:00:00Z", target_grades=[5]
    )
    set_clock("2026-08-16T00:00:00Z")
    resp = register_exam(session["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_EXAM_REGISTRATION_DEADLINE_PASSED)


def test_exam_grade_mismatch_rejected(api):
    """PRD §3.6: "the enrollment's `grade_level` must be a member of
    `target_grades` (else `ERR_EXAM_GRADE_MISMATCH`)"

    Design: Corner/validations/exam_grade_mismatch_rejected
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Gm",
                                  district_code="D-51")
    session = create_open_exam_session(year["id"], target_grades=[5])
    resp = register_exam(session["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_EXAM_GRADE_MISMATCH)


def test_exam_session_full_rejected(api):
    """PRD §3.6: "`seats_taken` counts registrations in `REGISTERED`,
    `ATTENDED`, `NO_SHOW`, `EXCUSED`, or `SCORED`, and when it has reached
    `capacity` the registration fails with `ERR_EXAM_SESSION_FULL`, there being
    no waitlist for exams."

    Design: Corner/errors/exam_session_full_rejected
    """
    year = create_open_year()
    ctx_a = setup_active_enrollment(year["id"], 5, family_name="Fam Fa",
                                    district_code="D-74")
    ctx_b = setup_active_enrollment(year["id"], 5, family_name="Fam Fb",
                                    district_code="D-75", student_name="Kid Fb",
                                    date_of_birth="2015-02-02")
    session = create_open_exam_session(year["id"], capacity=1, target_grades=[5])
    register_exam_ok(session["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"])

    resp = register_exam(session["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_EXAM_SESSION_FULL)
    current = get_success_data(api.get_exam_session(session["id"], REGISTRAR))
    assert current["seats_taken"] == 1
