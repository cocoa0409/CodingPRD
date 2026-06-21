"""PathEnrollment creation: fan out one child Enrollment per PathStep.

Used by POST /path-enrollments and by the assignment-rule sweep (PRD §3.7, §3.3).
"""

from db import db
from services.common import stamp_create
from services import calculations as calc


def create_path_enrollment(employee_id, learning_path_id, due_date, assignment_rule_id=None):
    pe = {
        "employee_id": employee_id,
        "learning_path_id": learning_path_id,
        "assignment_rule_id": assignment_rule_id,
        "due_date": due_date,
        "progress_pct": 0,
        "status": "NOT_STARTED",
    }
    stamp_create(pe)
    db.path_enrollments[pe["id"]] = pe

    # fan out one child Enrollment per PathStep
    steps = [s for s in db.path_steps.values() if s["learning_path_id"] == learning_path_id]
    steps.sort(key=lambda s: s["sequence_index"])
    for s in steps:
        child = {
            "employee_id": employee_id,
            "course_id": s["course_id"],
            "path_enrollment_id": pe["id"],
            "assignment_rule_id": None,
            "is_required": True,
            "due_date": due_date,
            "best_score": None,
            "latest_score": None,
            "final_grade": None,
            "attempts_used": 0,
            "cycle_index": 1,
            "escalation_tier": 0,
            "certificate_id": None,
            "status": "NOT_STARTED",
        }
        stamp_create(child)
        db.enrollments[child["id"]] = child

    pe["progress_pct"] = calc.compute_path_progress(pe)
    return pe
