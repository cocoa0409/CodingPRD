"""The term evaluation pipeline, standing assignment, and notification cadence.

Pinned per-student order: recompute cumulative metrics -> evaluate any PENDING
checkpoint of an ACTIVE plan for this term -> derive plan fate -> assign
standing -> queue notifications -> append audit rows (EVALUATION_POSTED,
CHECKPOINT_EVALUATED, PLAN_COMPLETED/PLAN_FAILED, STANDING_CHANGED,
NOTIFICATION_QUEUED per row). The term run closes with TERM_EVALUATED.
"""

from datetime import timedelta

from db import _new_id, now, store
from serializers import (
    pub_checkpoint,
    pub_evaluation,
    pub_notification,
    pub_plan,
    pub_student,
    pub_term,
)
from services import audit
from services.metrics import (
    max_tf_headroom,
    max_tf_projection_exceeded,
    recompute_student,
    term_metrics,
)

STANDING_GOOD = "GOOD_STANDING"
STANDING_WARNING = "WARNING"
STANDING_SUSPENSION = "SUSPENSION"
STANDING_PROBATION = "PROBATION"
STANDING_PLAN_PENDING = "PLAN_PENDING"
STANDING_PLAN_ACTIVE = "PLAN_ACTIVE"

# Progressive failure ladder for standings that fall short of the standards.
_FAILURE_NEXT = {
    STANDING_GOOD: STANDING_WARNING,
    STANDING_WARNING: STANDING_SUSPENSION,
    STANDING_SUSPENSION: STANDING_SUSPENSION,
    STANDING_PROBATION: STANDING_SUSPENSION,
    STANDING_PLAN_PENDING: STANDING_PLAN_PENDING,
    STANDING_PLAN_ACTIVE: STANDING_PLAN_ACTIVE,
}


def queue_notification(student_id, kind, detail, scheduled_at):
    row = {
        "id": _new_id(),
        "student_id": student_id,
        "kind": kind,
        "detail": detail,
        "scheduled_at": scheduled_at,
        "sent_at": None,
        "status": "QUEUED",
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.notifications[row["id"]] = row
    return row


def _assign_standing(prior, pace_ok, gpa_ok, max_tf_exceeded, checkpoint):
    """Fixed decision order: checkpoint outcome, then max timeframe, then the
    standards pass (reinstatement), then progressive failure by prior standing."""
    if checkpoint is not None:
        if checkpoint["outcome"] == "MISSED":
            return STANDING_SUSPENSION
        if checkpoint["is_final"]:
            return STANDING_GOOD
        return STANDING_PLAN_ACTIVE
    if max_tf_exceeded:
        return STANDING_SUSPENSION
    if pace_ok and gpa_ok:
        return STANDING_GOOD
    return _FAILURE_NEXT[prior]


def _find_pending_checkpoint(student_id, term_id):
    """An ACTIVE plan of the student with a PENDING checkpoint for this term."""
    for plan in sorted(store.plans.values(), key=lambda p: (p["created_at"], p["_seq"])):
        if plan["student_id"] != student_id or plan["status"] != "ACTIVE":
            continue
        for cp in store.checkpoints.values():
            if cp["plan_id"] == plan["id"] and cp["term_id"] == term_id and cp["outcome"] == "PENDING":
                return plan, cp
    return None, None


def _plan_max_seq(plan_id):
    seqs = []
    for cp in store.checkpoints.values():
        if cp["plan_id"] == plan_id:
            term = store.terms.get(cp["term_id"])
            if term is not None:
                seqs.append(term["seq"])
    return max(seqs) if seqs else None


def run_student_pipeline(student, term):
    """Create the OFFICIAL evaluation, reassign standing, queue notifications,
    append audit rows. Returns the result standing."""
    current = now()
    program = store.programs.get(student["program_id"])

    # Step 1: cumulative metrics from the official basis.
    attempted, earned, qp, gh, gpa, pace = recompute_student(student)
    exceeded = max_tf_projection_exceeded(program, attempted, earned)
    headroom = max_tf_headroom(program, attempted)

    # Steps 2-3: plan checkpoint evaluation and plan fate.
    checkpoint_info = None
    evaluated_checkpoint = None
    plan_fate = None
    plan, cp = _find_pending_checkpoint(student["id"], term["id"])
    if plan is not None and cp is not None:
        _t_att, t_earned, t_gpa, t_pace = term_metrics(student["id"], term["id"])
        met = (
            (t_gpa is None or t_gpa >= cp["required_term_gpa"])
            and (t_pace is not None and t_pace >= cp["required_term_pace_pct"])
            and (t_earned >= cp["required_earned_credits"])
        )
        cp["actual_term_gpa"] = t_gpa
        cp["actual_term_pace_pct"] = t_pace
        cp["actual_earned_credits"] = t_earned
        cp["outcome"] = "MET" if met else "MISSED"
        cp["updated_at"] = current
        cp["version"] += 1
        evaluated_checkpoint = cp

        max_seq = _plan_max_seq(plan["id"])
        is_final = max_seq is not None and term["seq"] == max_seq
        if not met:
            plan["status"] = "FAILED"
            plan["updated_at"] = current
            plan["version"] += 1
            plan_fate = ("PLAN_FAILED", plan)
        elif is_final:
            plan["status"] = "COMPLETED"
            plan["updated_at"] = current
            plan["version"] += 1
            plan_fate = ("PLAN_COMPLETED", plan)
        checkpoint_info = {"outcome": cp["outcome"], "is_final": is_final}

    # Step 4: standing assignment.
    pace_ok = pace is not None and pace >= program["min_pace_pct"]
    gpa_ok = gpa is None or gpa >= program["min_gpa"]
    prior = student["sap_status"]
    result = _assign_standing(prior, pace_ok, gpa_ok, exceeded, checkpoint_info)

    # Step 5: notifications per cadence. Continued SUSPENSION is the lone
    # exception that re-issues the full cadence plus a STANDING_CHANGED audit.
    continued_suspension = result == prior == STANDING_SUSPENSION
    standing_changed = (result != prior) or continued_suspension

    deadline = current + timedelta(days=program["appeal_window_days"])
    notices = []
    if evaluated_checkpoint is not None:
        notices.append((
            "PLAN_RESULT",
            current,
            "Plan checkpoint evaluated %s for term %s" % (evaluated_checkpoint["outcome"], term["code"]),
        ))
    if standing_changed:
        if result == STANDING_SUSPENSION:
            notices.append((
                "STANDING_CHANGE",
                current,
                "Standing transition %s->%s" % (prior, result),
            ))
            for offset in program["reminder_offset_days"]:
                notices.append((
                    "APPEAL_DEADLINE_REMINDER",
                    current + timedelta(days=offset),
                    "Appeal deadline reminder: submit by %s" % deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
                ))
        elif result == STANDING_GOOD and prior in (
            STANDING_SUSPENSION, STANDING_PROBATION, STANDING_PLAN_ACTIVE,
        ):
            notices.append((
                "REINSTATEMENT",
                current,
                "Standing transition %s->%s" % (prior, result),
            ))
        else:
            notices.append((
                "STANDING_CHANGE",
                current,
                "Standing transition %s->%s" % (prior, result),
            ))

    # Create the OFFICIAL evaluation row (snapshots + appeal window).
    evaluation = {
        "id": _new_id(),
        "student_id": student["id"],
        "term_id": term["id"],
        "status": "OFFICIAL",
        "pace_pct": pace,
        "cumulative_gpa": gpa,
        "max_tf_headroom_credits": headroom,
        "max_tf_exceeded": exceeded,
        "prior_standing": prior,
        "result_standing": result,
        "appeal_deadline_at": deadline,
        "evaluated_at": current,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.evaluations[evaluation["id"]] = evaluation

    # Reassign standing (cascade mutation of the student row).
    student_before = pub_student(student)
    student["sap_status"] = result
    student["max_tf_exceeded"] = exceeded
    student["updated_at"] = current
    student["version"] += 1

    queued = [queue_notification(student["id"], kind, detail, sched)
              for kind, sched, detail in notices]

    # Audit rows in the pinned cascade order.
    audit.record("EVALUATION_POSTED", "SapEvaluation", evaluation["id"],
                 student["id"], None, pub_evaluation(evaluation))
    if evaluated_checkpoint is not None:
        audit.record("CHECKPOINT_EVALUATED", "PlanCheckpoint", evaluated_checkpoint["id"],
                     student["id"], None, pub_checkpoint(evaluated_checkpoint))
    if plan_fate is not None:
        action, fate_plan = plan_fate
        audit.record(action, "AcademicPlan", fate_plan["id"],
                     student["id"], None, pub_plan(fate_plan))
    if standing_changed:
        audit.record("STANDING_CHANGED", "Student", student["id"],
                     student["id"], student_before, pub_student(student))
    for n in queued:
        audit.record("NOTIFICATION_QUEUED", "Notification", n["id"],
                     student["id"], None, pub_notification(n))
    return result


def run_term_evaluation(term):
    """Whole-term pipeline over the sweep set. Returns the summary counters."""
    student_ids = set()
    for e in store.enrollments.values():
        if e["term_id"] == term["id"] and e["status"] in ("POSTED", "AMENDED"):
            student_ids.add(e["student_id"])
    for plan in store.plans.values():
        if plan["status"] != "ACTIVE":
            continue
        for cp in store.checkpoints.values():
            if cp["plan_id"] == plan["id"] and cp["outcome"] == "PENDING" and cp["term_id"] == term["id"]:
                student_ids.add(plan["student_id"])
                break

    students = [store.students[sid] for sid in student_ids if sid in store.students]
    students.sort(key=lambda s: (s["created_at"], s["_seq"]))

    summary = {
        "evaluated_count": 0,
        "good_standing_count": 0,
        "warning_count": 0,
        "suspension_count": 0,
    }
    for student in students:
        result = run_student_pipeline(student, term)
        summary["evaluated_count"] += 1
        if result == STANDING_GOOD:
            summary["good_standing_count"] += 1
        elif result == STANDING_WARNING:
            summary["warning_count"] += 1
        elif result == STANDING_SUSPENSION:
            summary["suspension_count"] += 1

    before = pub_term(term)
    term["status"] = "EVALUATED"
    term["updated_at"] = now()
    term["version"] += 1
    audit.record("TERM_EVALUATED", "Term", term["id"], None, before, pub_term(term))
    return summary
