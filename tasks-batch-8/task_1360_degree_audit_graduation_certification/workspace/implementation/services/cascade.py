"""Recompute cascade per PRD §2.11 and SCAFFOLD state machine side effects.

Chain on every grade event or waiver approve/revoke:
  1. Student derived measures (credits, GPAs)
  2. Every CURRENT DegreeAudit of kind STANDARD/CONDITIONAL/FINAL on every
     ACTIVE StudentProgram of the student — WHAT_IF and SUPERSEDED untouched
  3. StudentProgram.latest_audit_satisfied refreshed from CURRENT FINAL audit
     (increments StudentProgram.version when the flag changes)
  4. CONDITIONALLY_CLEARED GraduationApplication auto-resolves when the
     student's IN_PROGRESS enrollment count reaches zero
"""

import db
from util import touch

from .academic import recompute_student_derived
from .audit import compute_audit


def recompute_student_cascade(student_id):
    """Run the full cascade for a student whose enrollments or waivers changed."""
    student = db.students.get(student_id)
    if student is None:
        return

    # Step 1: student derived fields
    if recompute_student_derived(student):
        touch(student)

    # Steps 2-4 per ACTIVE declaration
    sps = [
        sp
        for sp in db.student_programs.values()
        if sp["student_id"] == student_id and sp["status"] == "ACTIVE"
    ]
    for sp in sps:
        _recompute_student_program_audits(student, sp)
        _maybe_resolve_conditional_application(student, sp)


def _recompute_student_program_audits(student, sp):
    """Recompute CURRENT STANDARD/CONDITIONAL/FINAL audits for one declaration."""
    currents = [
        a
        for a in db.degree_audits.values()
        if a["student_program_id"] == sp["id"]
        and a["status"] == "CURRENT"
        and a["audit_kind"] in ("STANDARD", "CONDITIONAL", "FINAL")
    ]
    final_current = None
    for a in currents:
        program = db.programs[a["target_program_id"]]
        result = compute_audit(student, sp, program, a["audit_kind"])
        changed = (
            a["total_credits_applied"] != result["total_credits_applied"]
            or a["in_progress_credits_counted"] != result["in_progress_credits_counted"]
            or a["outstanding_credits"] != result["outstanding_credits"]
            or a["gpa_at_audit"] != result["gpa_at_audit"]
            or a["overall_satisfied"] != result["overall_satisfied"]
            or a["groups_result"] != result["groups_result"]
        )
        if changed:
            a.update(result)
            touch(a)
        if a["audit_kind"] == "FINAL":
            final_current = a

    # Refresh latest_audit_satisfied from CURRENT FINAL audit
    if final_current is not None:
        new_flag = bool(final_current["overall_satisfied"])
        if sp["latest_audit_satisfied"] != new_flag:
            sp["latest_audit_satisfied"] = new_flag
            touch(sp)


def _maybe_resolve_conditional_application(student, sp):
    """CONDITIONALLY_CLEARED -> CLEARED | DENIED once IN_PROGRESS count hits 0."""
    in_progress_count = sum(
        1
        for e in db.enrollments.values()
        if e["student_id"] == student["id"] and e["status"] == "IN_PROGRESS"
    )
    if in_progress_count > 0:
        return
    apps = [
        a
        for a in db.graduation_applications.values()
        if a["student_program_id"] == sp["id"] and a["status"] == "CONDITIONALLY_CLEARED"
    ]
    if not apps:
        return
    final_current = next(
        (
            a
            for a in db.degree_audits.values()
            if a["student_program_id"] == sp["id"]
            and a["audit_kind"] == "FINAL"
            and a["status"] == "CURRENT"
        ),
        None,
    )
    satisfied = bool(final_current and final_current["overall_satisfied"])
    for app in apps:
        if satisfied:
            app["status"] = "CLEARED"
        else:
            app["status"] = "DENIED"
            app["decision_reason"] = "CONTINGENCY_FAILED"
        touch(app)


def refresh_student_program_flag_and_conditional(student_id, student_program_id):
    """Lightweight entry for waiver approve/revoke where no enrollment mutated.

    Per PRD §3.5: approval/revocation recomputes CURRENT audits and refreshes
    latest_audit_satisfied, but the CONDITIONALLY_CLEARED auto-resolution only
    fires on enrollment mutations (zero IN_PROGRESS transition), so it is not
    run here.
    """
    student = db.students.get(student_id)
    sp = db.student_programs.get(student_program_id)
    if student is None or sp is None or sp["status"] != "ACTIVE":
        return
    _recompute_student_program_audits(student, sp)
