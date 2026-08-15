"""Entity serializers: stored fields + derived fields + common properties (PRD 2.5)."""
from services import derived
from util import fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _dt(value):
    return fmt_dt(value) if value is not None else None


def serialize_cycle(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "status": c["status"],
        "registration_deadline_at": _dt(c["registration_deadline_at"]),
        "order_deadline_at": _dt(c["order_deadline_at"]),
        "score_release_at": _dt(c["score_release_at"]),
        "exam_window_start_at": _dt(c["exam_window_start_at"]),
        "exam_window_end_at": _dt(c["exam_window_end_at"]),
        "late_fee_cents": c["late_fee_cents"],
        "unused_exam_penalty_cents": c["unused_exam_penalty_cents"],
        "fee_reduction_cents": c["fee_reduction_cents"],
        "budget_cap_cents": c["budget_cap_cents"],
        "rebate_rate_bp": c["rebate_rate_bp"],
        "registered_exam_count": derived.cycle_registered_exam_count(c["id"]),
        "rebate_cents": derived.cycle_rebate_cents(c),
    })
    return out


def serialize_course(c):
    out = _common(c)
    out.update({
        "cycle_id": c["cycle_id"],
        "subject_code": c["subject_code"],
        "program": c["program"],
        "exam_fee_cents": c["exam_fee_cents"],
        "credit_threshold": c["credit_threshold"],
        "status": derived.course_status(c["id"]),
        "authorized_teacher_count": derived.authorized_teacher_count(c["id"]),
        "registered_count": derived.course_registered_count(c["id"]),
    })
    return out


def serialize_teacher(t):
    out = _common(t)
    out.update({
        "full_name": t["full_name"],
        "email": t["email"],
    })
    return out


def serialize_teacher_authorization(ta):
    out = _common(ta)
    out.update({
        "teacher_id": ta["teacher_id"],
        "course_id": ta["course_id"],
        "status": ta["status"],
        "training_completed_at": _dt(ta["training_completed_at"]),
        "authorized_until": _dt(ta["authorized_until"]),
    })
    return out


def serialize_student(s):
    balance, projected = derived.student_balances(s["id"])
    out = _common(s)
    out.update({
        "full_name": s["full_name"],
        "grade_level": s["grade_level"],
        "subgroup_code": s["subgroup_code"],
        "balance_cents": balance,
        "projected_balance_cents": projected,
        "transcript_posted_count": derived.student_transcript_posted_count(s["id"]),
    })
    return out


def serialize_application(a):
    out = _common(a)
    out.update({
        "student_id": a["student_id"],
        "cycle_id": a["cycle_id"],
        "eligibility_basis": a["eligibility_basis"],
        "annual_income_cents": a["annual_income_cents"],
        "status": a["status"],
    })
    return out


def serialize_registration(r):
    subsidy = derived.reg_subsidy_cents(r)
    out = _common(r)
    out.update({
        "student_id": r["student_id"],
        "course_id": r["course_id"],
        "cycle_id": r["cycle_id"],
        "accommodation_type": r["accommodation_type"],
        "registration_status": r["registration_status"],
        "score_status": r["score_status"],
        "score": r["score"],
        "is_late": r["is_late"],
        "fee_cents": r["fee_cents"],
        "late_fee_applied_cents": r["late_fee_applied_cents"],
        "subsidy_cents": subsidy,
        "net_fee_cents": r["fee_cents"] + r["late_fee_applied_cents"] - subsidy,
    })
    return out


def serialize_order(o):
    lines, estimate = derived.order_view_fields(o)
    out = _common(o)
    out.update({
        "cycle_id": o["cycle_id"],
        "status": o["status"],
        "adjustments": [dict(a) for a in o["adjustments"]],
        "lines": [dict(l) for l in lines],
        "estimate_total_cents": estimate,
        "final_total_cents": o["final_total_cents"],
        "submitted_late": o["submitted_late"],
        "submitted_at": _dt(o["submitted_at"]),
        "locked_at": _dt(o["locked_at"]),
        "reconciled_at": _dt(o["reconciled_at"]),
    })
    return out


def serialize_session(s):
    out = _common(s)
    out.update({
        "course_id": s["course_id"],
        "room_name": s["room_name"],
        "room_capacity": s["room_capacity"],
        "room_supports_accommodations": s["room_supports_accommodations"],
        "start_at": _dt(s["start_at"]),
        "end_at": _dt(s["end_at"]),
        "status": s["status"],
        "seats_reserved": derived.session_seats_reserved(s),
    })
    return out


def serialize_proctor_assignment(pa):
    out = _common(pa)
    out.update({
        "session_id": pa["session_id"],
        "teacher_id": pa["teacher_id"],
        "status": pa["status"],
    })
    return out


def serialize_irregularity_report(ir):
    out = _common(ir)
    out.update({
        "session_id": ir["session_id"],
        "proctor_teacher_id": ir["proctor_teacher_id"],
        "category": ir["category"],
        "details": ir["details"],
        "status": ir["status"],
    })
    return out
