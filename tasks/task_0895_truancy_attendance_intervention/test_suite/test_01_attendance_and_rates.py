"""Attendance recording, dual-variant rate calculation, the unexcused tally, and
chronic-absence flagging."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures as fx,
    assert_student, TEST_USERS,
)

ADMIN = TEST_USERS["administrator_headers"]


def test_student_create_returns_system_and_computed_fields(api):
    """PRD §3.1: "Every new student begins with `enrollment_status` of `ENROLLED`,
    all counters at zero, and rates recomputed — which leaves `attendance_rate_recorded`
    null until the first record arrives."

    Design: Corner/entities/student_create_returns_system_and_computed_fields
    """
    school = fx.make_school(api)
    res = api.create_student(
        {"school_id": school["id"], "full_name": "Sam New", "grade_level": 7}, ADMIN
    )
    student = validate_success(res, 201)
    assert_student(student)
    assert student["enrollment_status"] == "ENROLLED"
    assert student["unexcused_count"] == 0 and student["present_count"] == 0
    assert student["attendance_rate_recorded"] is None


def test_attendance_rate_recorded_basis(api):
    """PRD §2.6: "The recorded-basis rate `attendance_rate_recorded` is *attended*
    divided by the sum of *attended* and *absent*, multiplied by 100; when that sum
    is zero — the student has no non-voided records at all — `attendance_rate_recorded`
    is null."

    Design: Difficulty/dual_variant_calc/attendance_rate_recorded_vs_official
    """
    school = fx.make_school(api, required_instructional_days=180)
    student = fx.make_student(api, school["id"], grade_level=9)
    for d, s in [("2026-09-01", "PRESENT"), ("2026-09-02", "PRESENT"),
                 ("2026-09-03", "PRESENT"), ("2026-09-04", "EXCUSED"),
                 ("2026-09-05", "UNEXCUSED"), ("2026-09-06", "UNEXCUSED")]:
        fx.record_attendance(api, student["id"], d, s)
    data = validate_success(api.get_student(student["id"], ADMIN), 200)
    # attended=3, absent=3 -> 3/6*100
    assert data["attendance_rate_recorded"] == 50.00


def test_attendance_rate_official_basis_diverges(api):
    """PRD §2.6: "The official-basis rate `attendance_rate_official` uses the school's
    `required_instructional_days` as its denominator: compute *remaining* as
    `required_instructional_days` minus `excused_count` minus `unexcused_count`, take
    the larger of *remaining* and zero, divide by `required_instructional_days`, and
    multiply by 100."

    Design: Difficulty/dual_variant_calc/attendance_rate_recorded_vs_official
    """
    school = fx.make_school(api, required_instructional_days=180)
    student = fx.make_student(api, school["id"], grade_level=9)
    for d, s in [("2026-09-01", "PRESENT"), ("2026-09-02", "PRESENT"),
                 ("2026-09-03", "PRESENT"), ("2026-09-04", "EXCUSED"),
                 ("2026-09-05", "UNEXCUSED"), ("2026-09-06", "UNEXCUSED")]:
        fx.record_attendance(api, student["id"], d, s)
    data = validate_success(api.get_student(student["id"], ADMIN), 200)
    # remaining = 180 - 1 - 2 = 177 -> 177/180*100 = 98.33
    assert data["attendance_rate_official"] == 98.33
    assert data["attendance_rate_recorded"] != data["attendance_rate_official"]


def test_attendance_rate_recorded_null_with_no_records(api):
    """PRD §2.6: "when that sum is zero — the student has no non-voided records at all —
    `attendance_rate_recorded` is null."

    Design: Difficulty/boundary_precision_check/attendance_rate_empty_records_null
    """
    school = fx.make_school(api)
    student = fx.make_student(api, school["id"], grade_level=9)
    data = validate_success(api.get_student(student["id"], ADMIN), 200)
    assert data["attendance_rate_recorded"] is None


def test_empty_records_counters_zero(api):
    """PRD §3.1: "Every new student begins with `enrollment_status` of `ENROLLED`,
    all counters at zero, and rates recomputed — which leaves `attendance_rate_recorded`
    null until the first record arrives."

    Design: Difficulty/boundary_precision_check/attendance_rate_empty_records_null
    """
    school = fx.make_school(api)
    student = fx.make_student(api, school["id"], grade_level=9)
    data = validate_success(api.get_student(student["id"], ADMIN), 200)
    assert data["present_count"] == 0 and data["unexcused_count"] == 0


def test_reclassify_unexcused_to_excused_updates_record(api):
    """PRD §3.2: "A record may move `UNEXCUSED → EXCUSED`, which decrements
    `unexcused_count` and increments `excused_count`."

    Design: Difficulty/compensating_invariant/unexcused_tally_conserved_on_reclassify
    """
    school = fx.make_school(api)
    student = fx.make_student(api, school["id"], grade_level=9)
    rec = fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    res = api.reclassify_attendance_record(student["id"], rec["id"], {"to_status": "EXCUSED"}, ADMIN)
    updated = validate_success(res, 200)
    assert updated["status"] == "EXCUSED"


def test_reclassify_conserves_unexcused_tally(api):
    """PRD §2.6: "The `unexcused_count` is the single figure that drives case-tier
    escalation, so it must always equal the number of non-voided records currently
    carrying `UNEXCUSED`; the reclassification actions in §3.2 are the compensating
    operations that keep this tally exact."

    Design: Difficulty/compensating_invariant/unexcused_tally_conserved_on_reclassify
    """
    school = fx.make_school(api)
    student = fx.make_student(api, school["id"], grade_level=9)
    rec = fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    api.reclassify_attendance_record(student["id"], rec["id"], {"to_status": "EXCUSED"}, ADMIN)
    data = validate_success(api.get_student(student["id"], ADMIN), 200)
    assert data["unexcused_count"] == 0 and data["excused_count"] == 1


def test_chronic_absent_true_at_threshold(api):
    """PRD §2.6: "The boolean `chronic_absent` is true when the student's absence
    percentage over the required instructional term is at least the school's
    `chronic_absence_pct_threshold`."

    Design: Corner/calculations/chronic_absent_true_at_threshold
    """
    school = fx.make_school(api, required_instructional_days=10, chronic_absence_pct_threshold=10.0)
    student = fx.make_student(api, school["id"], grade_level=9)
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    data = validate_success(api.get_student(student["id"], ADMIN), 200)
    # (0 + 1) / 10 * 100 == 10.0 >= 10.0
    assert data["chronic_absent"] is True


def test_duplicate_attendance_rejected(api):
    """PRD §3.2: "At most one non-voided record may exist for any given student and
    date; a second attempt at the same `attendance_date` is rejected with
    `ERR_DUPLICATE_ATTENDANCE`."

    Design: Corner/validations/duplicate_attendance_rejected
    """
    school = fx.make_school(api)
    student = fx.make_student(api, school["id"], grade_level=9)
    fx.record_attendance(api, student["id"], "2026-09-01", "PRESENT")
    res = api.create_attendance_record(
        student["id"], {"attendance_date": "2026-09-01", "status": "UNEXCUSED"}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ATTENDANCE.value)


def test_withdrawn_student_attendance_blocked(api):
    """PRD §3.1: "While a student is `WITHDRAWN` or `GRADUATED` — that is, not
    `ENROLLED` — any attendance-recording or case-mutating operation on them is
    rejected with `ERR_STUDENT_NOT_ENROLLED`."

    Design: Corner/state_machines/withdrawn_student_attendance_blocked
    """
    school = fx.make_school(api)
    student = fx.make_student(api, school["id"], grade_level=9)
    api.change_enrollment(student["id"], {"to_status": "WITHDRAWN"}, ADMIN)
    res = api.create_attendance_record(
        student["id"], {"attendance_date": "2026-09-01", "status": "UNEXCUSED"}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_STUDENT_NOT_ENROLLED.value)
