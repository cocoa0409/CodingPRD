"""Public (API-facing) serialization of stored rows.

Decimal values become JSON numbers (float), datetimes become ISO 8601 UTC
strings, internal bookkeeping keys (prefixed with ``_``) are omitted.
"""

from db import fmt_common, fmt_ts


def _num(value):
    """Decimal -> float for JSON output; None passes through."""
    if value is None:
        return None
    return float(value)


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_common(row["created_at"]),
        "updated_at": fmt_common(row["updated_at"]),
        "version": row["version"],
    }


def pub_program(p):
    out = _common(p)
    out.update({
        "code": p["code"],
        "name": p["name"],
        "required_credits": p["required_credits"],
        "min_gpa": _num(p["min_gpa"]),
        "min_pace_pct": _num(p["min_pace_pct"]),
        "appeal_window_days": p["appeal_window_days"],
        "reminder_offset_days": list(p["reminder_offset_days"]),
    })
    return out


def pub_student(s):
    out = _common(s)
    out.update({
        "student_number": s["student_number"],
        "full_name": s["full_name"],
        "program_id": s["program_id"],
        "sap_status": s["sap_status"],
        "cumulative_attempted_credits": s["cumulative_attempted_credits"],
        "cumulative_earned_credits": s["cumulative_earned_credits"],
        "cumulative_quality_points": _num(s["cumulative_quality_points"]),
        "cumulative_gpa_hours": s["cumulative_gpa_hours"],
        "cumulative_gpa": _num(s["cumulative_gpa"]),
        "pace_pct": _num(s["pace_pct"]),
        "max_tf_exceeded": s["max_tf_exceeded"],
    })
    return out


def pub_term(t):
    out = _common(t)
    out.update({
        "code": t["code"],
        "seq": t["seq"],
        "start_date": t["start_date"],
        "end_date": t["end_date"],
        "status": t["status"],
    })
    return out


def pub_enrollment(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "term_id": e["term_id"],
        "attempted_credits": e["attempted_credits"],
        "earned_credits": e["earned_credits"],
        "quality_points": _num(e["quality_points"]),
        "gpa_hours": e["gpa_hours"],
        "status": e["status"],
        "amendment_count": e["amendment_count"],
        "amendment_reason": e["amendment_reason"],
    })
    return out


def pub_evaluation(ev):
    out = _common(ev)
    out.update({
        "student_id": ev["student_id"],
        "term_id": ev["term_id"],
        "status": ev["status"],
        "pace_pct": _num(ev["pace_pct"]),
        "cumulative_gpa": _num(ev["cumulative_gpa"]),
        "max_tf_headroom_credits": ev["max_tf_headroom_credits"],
        "max_tf_exceeded": ev["max_tf_exceeded"],
        "prior_standing": ev["prior_standing"],
        "result_standing": ev["result_standing"],
        "appeal_deadline_at": fmt_ts(ev["appeal_deadline_at"]),
        "evaluated_at": fmt_ts(ev["evaluated_at"]),
    })
    return out


def pub_appeal(a):
    out = _common(a)
    out.update({
        "student_id": a["student_id"],
        "sap_evaluation_id": a["sap_evaluation_id"],
        "reason_category": a["reason_category"],
        "statement": a["statement"],
        "documents": [dict(d) for d in a["documents"]],
        "status": a["status"],
        "resolution": a["resolution"],
        "rationale": a["rationale"],
        "submitted_at": fmt_ts(a["submitted_at"]),
        "decided_at": fmt_ts(a["decided_at"]) if a["decided_at"] is not None else None,
    })
    return out


def pub_plan(p):
    out = _common(p)
    out.update({
        "student_id": p["student_id"],
        "appeal_id": p["appeal_id"],
        "start_term_id": p["start_term_id"],
        "total_required_credits": p["total_required_credits"],
        "coverage_start_seq": p["coverage_start_seq"],
        "coverage_end_seq_exclusive": p["coverage_end_seq_exclusive"],
        "status": p["status"],
    })
    return out


def pub_checkpoint(c):
    out = _common(c)
    out.update({
        "plan_id": c["plan_id"],
        "term_id": c["term_id"],
        "required_term_gpa": _num(c["required_term_gpa"]),
        "required_term_pace_pct": _num(c["required_term_pace_pct"]),
        "required_earned_credits": c["required_earned_credits"],
        "actual_term_gpa": _num(c["actual_term_gpa"]),
        "actual_term_pace_pct": _num(c["actual_term_pace_pct"]),
        "actual_earned_credits": c["actual_earned_credits"],
        "outcome": c["outcome"],
    })
    return out


def pub_notification(n):
    out = _common(n)
    out.update({
        "student_id": n["student_id"],
        "kind": n["kind"],
        "detail": n["detail"],
        "scheduled_at": fmt_ts(n["scheduled_at"]),
        "sent_at": fmt_ts(n["sent_at"]) if n["sent_at"] is not None else None,
        "status": n["status"],
    })
    return out


def pub_audit_event(a):
    # Audit rows are immutable: id + created_at only (no updated_at / version).
    return {
        "id": a["id"],
        "created_at": fmt_common(a["created_at"]),
        "actor_role": a["actor_role"],
        "actor_id": a["actor_id"],
        "action": a["action"],
        "entity_type": a["entity_type"],
        "entity_id": a["entity_id"],
        "student_id": a["student_id"],
        "before_json": a["before_json"],
        "after_json": a["after_json"],
        "occurred_at": fmt_ts(a["occurred_at"]),
    }
