"""Calculation rules (SCAFFOLD §1.3 / PRD §2.8, §3.5, §3.7, §3.9).

  final_grade            HIGHEST_SCORE | LATEST_ATTEMPT over current-cycle attempts
  ceu_accrual            STANDARD | SCORE_WEIGHTED, round AFTER multiply, 2dp half-up
  path_progress_pct      weighted mandatory steps, ratio*100 rounded ONCE, 2dp half-up
  escalation_tier        floored days_overdue -> 0/1/2/3 threshold
  compliance_score       (compliant/n)*100 - sum(tier*5), clamp [0,100], 2dp half-up
  compliance_invariants  total_ceu_earned / compliant_required_count maintenance
"""

from db import db
from timeutil import days_overdue as _days_overdue
from services.common import round2


# --- final_grade ----------------------------------------------------------

def current_cycle_attempts(enrollment):
    eid = enrollment["id"]
    cyc = enrollment["cycle_index"]
    return [a for a in db.quiz_attempts.values()
            if a["enrollment_id"] == eid and a["cycle_index"] == cyc]


def compute_final_grade(enrollment, course):
    attempts = current_cycle_attempts(enrollment)
    if not attempts:
        return None
    if course["grading_policy"] == "HIGHEST_SCORE":
        return max(a["score"] for a in attempts)
    # LATEST_ATTEMPT: greatest created_at, tie-break greatest attempt_number
    latest = max(attempts, key=lambda a: (a["created_at"], a["attempt_number"]))
    return latest["score"]


# --- ceu_accrual ----------------------------------------------------------

def compute_ceu_credited(course, final_grade):
    base = course.get("ceu_credits", 0) or 0
    if course["ceu_policy"] == "STANDARD":
        return round2(base)
    # SCORE_WEIGHTED — tiered multiplier on the certifying final_grade
    g = final_grade if final_grade is not None else 0
    if g >= 90:
        mult = 1.00
    elif g >= 80:
        mult = 0.75
    else:
        mult = 0.50
    return round2(base * mult)


# --- path_progress_pct ----------------------------------------------------

def mandatory_steps(path_id):
    return [s for s in db.path_steps.values()
            if s["learning_path_id"] == path_id and s["is_mandatory"]]


def compute_path_progress(path_enrollment):
    path_id = path_enrollment["learning_path_id"]
    employee_id = path_enrollment["employee_id"]
    steps = mandatory_steps(path_id)
    total_weight = sum(s["weight"] for s in steps)
    if total_weight == 0:
        return 0.0
    earned = 0
    for s in steps:
        child = child_enrollment_for_step(path_enrollment, s)
        if child is not None and child["status"] in ("COMPLETED", "WAIVED"):
            earned += s["weight"]
    # ROUNDING ORDER PINNED: ratio, *100, round ONCE.
    return round2((earned / total_weight) * 100)


def child_enrollment_for_step(path_enrollment, step):
    """The child Enrollment of this path enrollment for the step's course."""
    pe_id = path_enrollment["id"]
    course_id = step["course_id"]
    for e in db.enrollments.values():
        if e["path_enrollment_id"] == pe_id and e["course_id"] == course_id:
            return e
    return None


# --- escalation_tier ------------------------------------------------------

def compute_days_overdue(enrollment):
    return _days_overdue(db.now(), enrollment["due_date"])


def compute_escalation_tier(enrollment):
    d = compute_days_overdue(enrollment)
    if d <= 0:
        return 0
    if d <= 7:
        return 1
    if d <= 30:
        return 2
    return 3


# --- compliance invariants & score ----------------------------------------

def linked_active_certificate(enrollment):
    cert_id = enrollment.get("certificate_id")
    if not cert_id:
        return None
    cert = db.certificates.get(cert_id)
    if cert is not None and cert["status"] == "ACTIVE":
        return cert
    return None


def recompute_employee_invariants(employee):
    """Reconcile total_ceu_earned & compliant_required_count to definition."""
    emp_id = employee["id"]
    total = 0.0
    for c in db.certificates.values():
        if c["employee_id"] == emp_id and c["status"] == "ACTIVE":
            total += c.get("ceu_credited", 0) or 0
    employee["total_ceu_earned"] = round2(total)

    count = 0
    for e in db.enrollments.values():
        if (e["employee_id"] == emp_id and e.get("is_required")
                and e["status"] == "COMPLETED"
                and linked_active_certificate(e) is not None):
            count += 1
    employee["compliant_required_count"] = count


def latest_cycle_required_enrollments(employee_id):
    """Required enrollments for the employee, latest cycle per (employee,course)."""
    by_course = {}
    for e in db.enrollments.values():
        if e["employee_id"] != employee_id or not e.get("is_required"):
            continue
        key = e["course_id"]
        cur = by_course.get(key)
        if cur is None or e["cycle_index"] > cur["cycle_index"]:
            by_course[key] = e
    return list(by_course.values())


def compute_compliance_score(employee):
    req = latest_cycle_required_enrollments(employee["id"])
    n = len(req)
    if n == 0:
        return 100.00
    compliant = sum(1 for e in req
                    if e["status"] == "COMPLETED"
                    and linked_active_certificate(e) is not None)
    overdue_pts = sum(compute_escalation_tier(e) * 5 for e in req)
    base = (compliant / n) * 100
    raw = base - overdue_pts
    raw = max(0, min(100, raw))
    return round2(raw)


def recompute_employee_compliance_score(employee):
    employee["compliance_score"] = compute_compliance_score(employee)


def recompute_employee_all(employee):
    recompute_employee_invariants(employee)
    recompute_employee_compliance_score(employee)
