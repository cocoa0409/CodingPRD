"""Grade / credit / GPA math per SCAFFOLD calculations §1.3.

Constants and helpers:
  - grade values A=4, B=3, C=2, D=1, F=0; W has no value.
  - credits_earned: course.credits when COMPLETED with grade in {A,B,C,D}, else 0.
  - grade_points:   credits_attempted * grade value for grade in {A..F}; W excluded.
  - GPA: sum(grade_points)/sum(credits_attempted) over GPA-bearing set,
         rounded ONCE at the end to 3 decimals, round_half_up.
         denominator 0 -> 0.000.
"""

from decimal import Decimal, ROUND_HALF_UP

import db

GRADE_VALUE = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
PASSING_GRADES = ("A", "B", "C", "D")
GPA_GRADES = ("A", "B", "C", "D", "F")
ALL_GRADES = ("A", "B", "C", "D", "F", "W")


def apply_grade_to_enrollment(enrollment, grade):
    """Set status/credits_earned/grade_points on an enrollment per
    grade_point_and_credit_award.

    grade in A..F -> COMPLETED; grade W -> WITHDRAWN.
    """
    course = db.courses[enrollment["course_id"]]
    credits = course["credits"]
    enrollment["grade"] = grade
    if grade == "W":
        enrollment["status"] = "WITHDRAWN"
        enrollment["credits_earned"] = 0
        enrollment["grade_points"] = 0
    else:
        enrollment["status"] = "COMPLETED"
        if grade in PASSING_GRADES:
            enrollment["credits_earned"] = credits
        else:
            enrollment["credits_earned"] = 0
        enrollment["grade_points"] = credits * GRADE_VALUE[grade]


def compute_gpa(enrollments):
    """Credit-weighted GPA over the given enrollment list; only GPA-bearing
    enrollments (COMPLETED with grade A..F) enter. Returns a float with
    exactly 3 decimals (round-half-up once at the end)."""
    total_points = 0
    total_credits = 0
    for e in enrollments:
        if e["status"] != "COMPLETED":
            continue
        if e["grade"] not in GPA_GRADES:
            continue
        total_points += e["grade_points"]
        total_credits += e["credits_attempted"]
    if total_credits == 0:
        return 0.0
    gpa = Decimal(str(total_points)) / Decimal(str(total_credits))
    gpa = gpa.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(gpa)


def recompute_student_derived(student):
    """Recompute total_earned_credits, institutional_earned_credits,
    institutional_gpa, cumulative_gpa. Returns True if any field changed."""
    enrolls = [e for e in db.enrollments.values() if e["student_id"] == student["id"]]
    total_earned = sum(
        e["credits_earned"] for e in enrolls if e["status"] == "COMPLETED"
    )
    institutional_earned = sum(
        e["credits_earned"]
        for e in enrolls
        if e["status"] == "COMPLETED" and not e["is_transfer"]
    )
    institutional_set = [e for e in enrolls if not e["is_transfer"]]
    institutional_gpa = compute_gpa(institutional_set)
    cumulative_gpa = compute_gpa(enrolls)

    changed = (
        student["total_earned_credits"] != total_earned
        or student["institutional_earned_credits"] != institutional_earned
        or student["institutional_gpa"] != institutional_gpa
        or student["cumulative_gpa"] != cumulative_gpa
    )
    if changed:
        student["total_earned_credits"] = total_earned
        student["institutional_earned_credits"] = institutional_earned
        student["institutional_gpa"] = institutional_gpa
        student["cumulative_gpa"] = cumulative_gpa
    return changed
