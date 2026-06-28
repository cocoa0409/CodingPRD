"""Completion gating and certification rollup (PRD §3.7).

Difficulty queue: dual_variant_calc (certification PROVISIONAL vs CERTIFIED),
                  boundary_precision_check (completion blocked when no progress report).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, set_clock,
    create_cohort, create_placed_student, create_enrollment, confirm,
    mark_attendance, add_progress_report,
)

REG = TEST_USERS["registrar_headers"]
INSTR = TEST_USERS["instructor_headers"]


def _complete_one_cohort(student, schedule_block, speaking, listening, reading, writing,
                         complete_at, name):
    """Enroll the existing student into a fresh short-term cohort (term 2026-04-01
    .. 2026-04-10), mark one PRESENT session + one progress report, advance the
    clock past term_end, and complete. Returns the completed enrollment data."""
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=9, base_tuition_cents=100000,
                           schedule_block=schedule_block, term_start="2026-04-01T00:00:00Z",
                           term_end="2026-04-10T00:00:00Z", total_sessions=10, name=name)
    enr = create_enrollment(student["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    mark_attendance(enr["id"], 1, "PRESENT")
    add_progress_report(enr["id"], speaking, listening, reading, writing)
    set_clock(complete_at)
    return get_success_data(api_client.complete_enrollment(enr["id"], REG))


# =====================================================================
# Difficulty / dual_variant_calc / certification_provisional_vs_certified_rollup_on_student
# =====================================================================
def test_certification_provisional_after_first_completion(api):
    """PRD §3.7: "If the student has completed fewer than 2 enrollments, the
    certification_status is PROVISIONAL and final_progress_score is the current
    running mean, which may still move as further enrollments complete."

    Design: Difficulty/dual_variant_calc/certification_provisional_vs_certified_rollup_on_student
    """
    stu = create_placed_student(level="B1", track="GENERAL")
    # One completed enrollment: skills 80/82/78/84 -> rhu(81)=81; attendance rhu(100)=100;
    # rhu(0.7*81+0.3*100)=rhu(56.7+30)=rhu(86.7)=87.
    _complete_one_cohort(stu, "MORNING", 80, 82, 78, 84, "2026-04-11T00:00:00Z", "Cert-A")
    data = validate_success(api.get_student(stu["id"], REG))
    assert data["certification_status"] == "PROVISIONAL", (
        f"one completion -> PROVISIONAL, got {data['certification_status']}")


def test_certification_certified_after_second_completion(api):
    """PRD §3.7: "If the student has completed at least 2 enrollments and the
    rounded mean is at least 70, the certification_status is CERTIFIED and the
    final_progress_score is frozen at that value."
    PRD §3.7: "computes final_progress_score as the mean of their completion_score
    values, rounded half up to a whole number; this aggregate is order-independent."

    Design: Difficulty/dual_variant_calc/certification_provisional_vs_certified_rollup_on_student
    """
    stu = create_placed_student(level="B1", track="GENERAL")
    # First completion: 80/82/78/84 -> completion_score 87.
    _complete_one_cohort(stu, "MORNING", 80, 82, 78, 84, "2026-04-11T00:00:00Z", "Cert-A")
    # Second completion: 70/70/70/70 -> skills rhu(70)=70; attendance 100; rhu(0.7*70+0.3*100)=rhu(79)=79.
    set_clock("2026-04-01T00:00:00Z")  # reset clock so the 2nd term has not yet ended
    _complete_one_cohort(stu, "AFTERNOON", 70, 70, 70, 70, "2026-04-11T00:00:00Z", "Cert-B")
    data = validate_success(api.get_student(stu["id"], REG))
    assert data["certification_status"] == "CERTIFIED", (
        f"two completions, mean>=70 -> CERTIFIED, got {data['certification_status']}")
    # mean of 87 and 79 = 83.0 -> rhu(83.0)=83.
    assert data["final_progress_score"] == 83, (
        f"expected final_progress_score 83, got {data['final_progress_score']}")


# =====================================================================
# Difficulty / boundary_precision_check / completion_blocked_when_no_progress_report_empty_set_edge
# =====================================================================
def test_completion_blocked_when_no_progress_report(api):
    """PRD §3.7: "Completion is gated: the current logical clock must be on or after
    the cohort's term_end, the enrollment's attendance_rate must be at least 0.70
    (the minimum passing attendance), and at least one progress report must exist
    for the enrollment. If any of these three conditions fails — completing before
    the term ends, an attendance rate below 0.70, or no progress report on file —
    the request is rejected with ERR_COMPLETION_REQUIREMENTS_UNMET (HTTP 409)."

    Design: Difficulty/boundary_precision_check/completion_blocked_when_no_progress_report_empty_set_edge
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=9, base_tuition_cents=100000,
                           schedule_block="MORNING", term_start="2026-04-01T00:00:00Z",
                           term_end="2026-04-10T00:00:00Z", total_sessions=10)
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    mark_attendance(enr["id"], 1, "PRESENT")  # attendance fine, but NO progress report
    set_clock("2026-04-11T00:00:00Z")  # term ended
    validate_error(api.complete_enrollment(enr["id"], REG), ApiErrorId.ERR_COMPLETION_REQUIREMENTS_UNMET.value)
    after = validate_success(api.get_enrollment(enr["id"], REG))
    assert after["status"] == "ENROLLED", "enrollment must stay ENROLLED after a rejected completion"


def test_completion_blocked_before_term_end(api):
    """PRD §3.7: "the current logical clock must be on or after the cohort's
    term_end ... If any of these three conditions fails — completing before the term
    ends ... the request is rejected with ERR_COMPLETION_REQUIREMENTS_UNMET (HTTP 409)."

    Design: Difficulty/boundary_precision_check/completion_blocked_when_no_progress_report_empty_set_edge
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=9, base_tuition_cents=100000,
                           schedule_block="MORNING", term_start="2026-04-01T00:00:00Z",
                           term_end="2026-04-10T00:00:00Z", total_sessions=10)
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    mark_attendance(enr["id"], 1, "PRESENT")
    add_progress_report(enr["id"], 80, 80, 80, 80)
    # Clock default 2026-04-01 is BEFORE term_end 2026-04-10.
    set_clock("2026-04-05T00:00:00Z")
    validate_error(api.complete_enrollment(enr["id"], REG), ApiErrorId.ERR_COMPLETION_REQUIREMENTS_UNMET.value)
