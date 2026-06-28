"""F-1 full-course-of-study boundaries and placement banding (PRD §3.2, §3.8).

Difficulty queue: boundary_precision_check (full course exactly 18 hours passes activation).
Corner queue: full course under 18 blocks activation, placement band raw60 -> B2.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS,
    create_cohort, create_placed_student, create_enrollment, confirm,
    issue_i20,
)

REG = TEST_USERS["registrar_headers"]
DSO = TEST_USERS["dso_headers"]
INSTR = TEST_USERS["instructor_headers"]


# =====================================================================
# Difficulty / boundary_precision_check / full_course_load_exactly_18_hours_passes_activation
# =====================================================================
def test_full_course_load_exactly_18_passes_activation(api):
    """PRD §3.8: "the sum of weekly_hours over the cohorts of the student's currently
    ENROLLED enrollments is at least the student's i20_required_weekly_hours ... The
    boundary is inclusive: a student whose enrolled weekly hours sum to exactly 18
    satisfies the full course of study."

    Design: Difficulty/boundary_precision_check/full_course_load_exactly_18_hours_passes_activation
    """
    # Two 9-hour cohorts in different schedule blocks: 9 + 9 == 18 == required.
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)
    issue_i20(stu["id"])
    cohort_a = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING", name="9a")
    cohort_b = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="AFTERNOON", name="9b")
    enr_a = create_enrollment(stu["id"], cohort_a["id"])
    confirm(enr_a["id"], cohort_a["version"], require_seat=True)
    enr_b = create_enrollment(stu["id"], cohort_b["id"])
    confirm(enr_b["id"], cohort_b["version"], require_seat=True)
    data = validate_success(api.activate_status(stu["id"], DSO, {}))
    assert data["visa_status"] == "ACTIVE", f"9+9==18 satisfies >=18, got {data['visa_status']}"


def test_full_course_load_18_via_single_cohort_passes(api):
    """PRD §3.8: "A DSO may activate only when the current visa_status is INITIAL and
    the student is meeting a full course of study — that is, the sum of weekly_hours
    over the cohorts of the student's currently ENROLLED enrollments is at least the
    student's i20_required_weekly_hours."

    Design: Difficulty/boundary_precision_check/full_course_load_exactly_18_hours_passes_activation
    """
    # A single 18-hour cohort meets the boundary exactly.
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)
    issue_i20(stu["id"])
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    data = validate_success(api.activate_status(stu["id"], DSO, {}))
    assert data["visa_status"] == "ACTIVE"


# =====================================================================
# Corner / calculations / full_course_load_under_18_blocks_activation
# =====================================================================
def test_full_course_load_under_18_blocks_activation(api):
    """PRD §3.8: "When the full-course-of-study sum falls short of
    i20_required_weekly_hours, activation is rejected with
    ERR_NOT_FULL_COURSE_OF_STUDY (HTTP 409)."
    PRD §3.8: "Only enrollments in ENROLLED state count toward this sum; enrollments
    in PLACEMENT_PENDING, WAITLISTED, or any terminal state are excluded."

    Design: Corner/calculations/full_course_load_under_18_blocks_activation
    """
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)
    issue_i20(stu["id"])
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)  # only 9h ENROLLED
    validate_error(api.activate_status(stu["id"], DSO, {}), ApiErrorId.ERR_NOT_FULL_COURSE_OF_STUDY.value)
    after = validate_success(api.get_student(stu["id"], REG))
    assert after["visa_status"] == "INITIAL", "activation blocked, status stays INITIAL"


# =====================================================================
# Corner / calculations / placement_band_boundary_raw60_yields_b2
# =====================================================================
def test_placement_band_raw60_yields_b2(api):
    """PRD §3.2: "A score below 75 but at least 60 yields B2. ... The thresholds are
    inclusive on the lower bound, so a raw score of exactly 60 lands in B2 while a
    raw score of 59 lands in B1."

    Design: Corner/calculations/placement_band_boundary_raw60_yields_b2
    """
    # Build a registered (unscored) test directly.
    student = get_success_data(api.create_student({"full_name": "Band S", "email": "bands60@x.com"}, REG))
    pt = get_success_data(api.create_placement_test({"student_id": student["id"]}, REG))
    data = validate_success(api.score_placement_test(pt["id"], {"raw_score": 60}, INSTR))
    assert data["assigned_level"] == "B2", f"raw 60 -> B2 boundary, got {data['assigned_level']}"
    assert data["status"] == "SCORED"


def test_placement_band_raw59_yields_b1(api):
    """PRD §3.2: "The thresholds are inclusive on the lower bound, so a raw score of
    exactly 60 lands in B2 while a raw score of 59 lands in B1."

    Design: Corner/calculations/placement_band_boundary_raw60_yields_b2
    """
    student = get_success_data(api.create_student({"full_name": "Band S2", "email": "bands59@x.com"}, REG))
    pt = get_success_data(api.create_placement_test({"student_id": student["id"]}, REG))
    data = validate_success(api.score_placement_test(pt["id"], {"raw_score": 59}, INSTR))
    assert data["assigned_level"] == "B1", f"raw 59 -> B1 (just below B2), got {data['assigned_level']}"
