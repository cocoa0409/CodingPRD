"""Credit hour conversion, GPA, graduation credit audit, transcript view."""
from decimal import Decimal, ROUND_HALF_UP

import db
from services import core

HOURS_PER_HALF_CREDIT = 60
MIN_COMPLETION_HOURS = 60
TOTAL_CREDITS_REQUIRED = Decimal("22.0")
SUBJECT_MINIMUMS = {
    "ENGLISH": Decimal("4.0"),
    "MATH": Decimal("3.0"),
    "SCIENCE": Decimal("3.0"),
    "SOCIAL_STUDIES": Decimal("3.0"),
}
GRADE_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
CREDIT_SUBJECTS = [
    "ENGLISH", "MATH", "SCIENCE", "SOCIAL_STUDIES",
    "FOREIGN_LANGUAGE", "FINE_ARTS", "PHYS_ED", "ELECTIVE",
]


def compute_credit_value(completed_hours):
    return Decimal(completed_hours // HOURS_PER_HALF_CREDIT) * Decimal("0.5")


def credits_of_student(student):
    out = []
    for en in db.enrollments.values():
        if en["student_id"] != student["id"]:
            continue
        for cc in db.course_credits.values():
            if cc["enrollment_id"] == en["id"]:
                out.append(cc)
    return out


def audit(student, statuses):
    """Bucket totals + grand total over credits in the given statuses."""
    buckets = {s: Decimal("0") for s in CREDIT_SUBJECTS}
    total = Decimal("0")
    for cc in credits_of_student(student):
        if cc["status"] not in statuses:
            continue
        val = cc["credit_value"]
        if val is None:
            continue
        buckets[cc["subject"]] += val
        total += val
    return total, buckets


def audit_eligible(student):
    """Official (POSTED-only) graduation credit audit."""
    total, buckets = audit(student, {"POSTED"})
    if total < TOTAL_CREDITS_REQUIRED:
        return False
    for subj, minimum in SUBJECT_MINIMUMS.items():
        if buckets[subj] < minimum:
            return False
    return True


def gpa_official(student):
    num = Decimal("0")
    den = Decimal("0")
    for cc in credits_of_student(student):
        if cc["status"] != "POSTED":
            continue
        val = cc["credit_value"]
        if val is None:
            continue
        num += Decimal(GRADE_POINTS[cc["letter_grade"]]) * val
        den += val
    if den == 0:
        return None
    return (num / den).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def transcript_view(student):
    official_total, official_buckets = audit(student, {"POSTED"})
    projected_total, _ = audit(student, {"POSTED", "VERIFIED", "COMPLETED"})
    gpa = gpa_official(student)
    return {
        "official_credits_total": float(official_total),
        "projected_credits_total": float(projected_total),
        "gpa_official": float(gpa) if gpa is not None else None,
        "subject_credits_official": {k: float(v) for k, v in official_buckets.items()},
        "transcript_sealed": student["transcript_sealed"],
        "diploma_number": student["diploma_number"],
    }
