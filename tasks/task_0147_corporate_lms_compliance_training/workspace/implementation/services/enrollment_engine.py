"""The enrollment / grading / certification cascade engine.

Implements the Enrollment state machine and its cross-aggregate side effects
(SCAFFOLD §1.2, PRD §3.5, §3.7, §3.8): quiz-attempt -> COMPLETED/FAILED ->
Certificate issue/CEU -> Employee invariants/score -> PathEnrollment bubble.
"""

from db import db
from services.common import stamp_create, touch
from services import calculations as calc
from timeutil import add_months


# --- attempt recording ----------------------------------------------------

def record_attempt(enrollment, course, score):
    """Append an immutable QuizAttempt for the current cycle, recompute aggregates.

    Returns the new attempt record. Does NOT bump enrollment.version (the caller
    transition does that exactly once).
    """
    attempt_number = enrollment["attempts_used"] + 1
    attempt = {
        "enrollment_id": enrollment["id"],
        "cycle_index": enrollment["cycle_index"],
        "attempt_number": attempt_number,
        "score": score,
        "passed": score >= course["passing_score"],
    }
    stamp_create(attempt, common_fields=False)  # id + created_at only
    db.quiz_attempts[attempt["id"]] = attempt
    recompute_attempt_aggregates(enrollment, course)
    return attempt


def recompute_attempt_aggregates(enrollment, course):
    attempts = calc.current_cycle_attempts(enrollment)
    if attempts:
        enrollment["best_score"] = max(a["score"] for a in attempts)
        latest = max(attempts, key=lambda a: (a["created_at"], a["attempt_number"]))
        enrollment["latest_score"] = latest["score"]
        enrollment["attempts_used"] = len(attempts)
    else:
        enrollment["best_score"] = None
        enrollment["latest_score"] = None
        enrollment["attempts_used"] = 0


# --- the grading cascade --------------------------------------------------

def apply_grading_for_attempt(enrollment, course, score):
    """Given a just-recorded attempt's score, drive the enrollment forward.

    Caller has already validated state (IN_PROGRESS), OCC, and attempts-remaining.
    Returns nothing; mutates enrollment + cascades. Bumps enrollment.version once.
    """
    passed = score >= course["passing_score"]
    if passed:
        _complete_enrollment(enrollment, course)
    else:
        # failing attempt: ends enrollment only if it just exhausted max_attempts
        if enrollment["attempts_used"] >= course["max_attempts"]:
            _fail_enrollment(enrollment, course)
        else:
            # stays IN_PROGRESS; still recompute final_grade? No — final_grade
            # is recorded on COMPLETED/FAILED only. Just bump version.
            touch(enrollment)


def _complete_enrollment(enrollment, course):
    enrollment["final_grade"] = calc.compute_final_grade(enrollment, course)
    enrollment["status"] = "COMPLETED"
    issue_certificate(enrollment, course)
    employee = db.employees.get(enrollment["employee_id"])
    if employee is not None:
        calc.recompute_employee_invariants(employee)
        calc.recompute_employee_compliance_score(employee)
    touch(enrollment)
    _bubble_path_on_child_change(enrollment)


def _fail_enrollment(enrollment, course):
    enrollment["final_grade"] = calc.compute_final_grade(enrollment, course)
    enrollment["status"] = "FAILED"
    touch(enrollment)
    _bubble_path_on_child_change(enrollment)


# --- certificate issuance -------------------------------------------------

def issue_certificate(enrollment, course):
    now = db.now()
    expires_at = None
    if course.get("is_recurring") and course.get("recurrence_months"):
        expires_at = add_months(now, course["recurrence_months"])
    cert = {
        "employee_id": enrollment["employee_id"],
        "course_id": course["id"],
        "enrollment_id": enrollment["id"],
        "ceu_credited": calc.compute_ceu_credited(course, enrollment["final_grade"]),
        "issued_at": now,
        "expires_at": expires_at,
        "status": "ACTIVE",
    }
    stamp_create(cert, common_fields=True)
    db.certificates[cert["id"]] = cert
    enrollment["certificate_id"] = cert["id"]
    return cert


# --- path-enrollment bubble-up --------------------------------------------

def _bubble_path_on_child_change(enrollment):
    pe_id = enrollment.get("path_enrollment_id")
    if not pe_id:
        return
    pe = db.path_enrollments.get(pe_id)
    if pe is None:
        return
    reevaluate_path_enrollment(pe)


def reevaluate_path_enrollment(pe):
    """Derive compound PathEnrollment status from its children + recompute progress.

    Bubble transitions per PRD §3.7. Each transition bumps pe.version once.
    """
    path_id = pe["learning_path_id"]
    mand_steps = calc.mandatory_steps(path_id)

    # gather mandatory child enrollments
    children = []
    for s in mand_steps:
        child = calc.child_enrollment_for_step(pe, s)
        if child is not None:
            children.append(child)

    any_failed = any(c["status"] == "FAILED" for c in children)
    all_satisfied = bool(mand_steps) and all(
        (calc.child_enrollment_for_step(pe, s) or {}).get("status") in ("COMPLETED", "WAIVED")
        for s in mand_steps
    )

    cur = pe["status"]
    new_status = cur

    if cur == "NOT_STARTED":
        # bubble to IN_PROGRESS once any child is IN_PROGRESS (or further)
        if any(c["status"] in ("IN_PROGRESS", "COMPLETED", "FAILED") for c in children):
            new_status = "IN_PROGRESS"
    if new_status in ("NOT_STARTED", "IN_PROGRESS"):
        if any_failed:
            new_status = "FAILED"
        elif all_satisfied:
            new_status = "COMPLETED"
    elif cur == "FAILED":
        if not any_failed:
            new_status = "IN_PROGRESS"
            if all_satisfied:
                new_status = "COMPLETED"

    # COMPLETED is terminal; do not move away from it.
    if cur == "COMPLETED":
        new_status = "COMPLETED"

    pe["progress_pct"] = calc.compute_path_progress(pe)

    if new_status != cur:
        pe["status"] = new_status
        touch(pe)
    else:
        # progress recompute alone is not a versioned mutation per the spec's
        # bubble transitions; only bump when status actually changes. But if
        # progress changed we still persist it (no version bump on pure read-time
        # recompute). Persisting in-place dict is enough.
        pass
