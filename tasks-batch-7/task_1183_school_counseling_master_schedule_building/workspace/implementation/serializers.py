"""Entity -> public JSON dict (derived fields computed at read time)."""

from decimal import Decimal

import domain
from util import num


def _common(r):
    return {"id": r["id"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "version": r["version"]}


def _slim(r):
    return {"id": r["id"], "created_at": r["created_at"]}


def term(t):
    out = _common(t)
    out.update({
        "code": t["code"],
        "posture": t["posture"],
        "periods_per_day": t["periods_per_day"],
        "max_students_per_section": t["max_students_per_section"],
        "class_size_target": t["class_size_target"],
        "singleton_section_cap": t["singleton_section_cap"],
        "change_window_open": t["posture"] == "CHANGE_WINDOW",
        "change_request_max_per_student": t["change_request_max_per_student"],
        "rebalance_epoch": t["rebalance_epoch"],
        "total_requested_seats": domain.term_total_requested_seats(t["id"]),
    })
    return out


def student(s):
    out = _common(s)
    out.update({
        "external_ref": s["external_ref"],
        "full_name": s["full_name"],
        "grade_level": s["grade_level"],
        "special_program": s["special_program"],
        "counselor_id": s["counselor_id"],
        "earned_credits": num(s["earned_credits"]),
        "planned_credit_load": num(domain.student_planned_credit_load(s["id"])),
        "credit_deficient": domain.student_credit_deficient(s["id"]),
    })
    return out


def counselor(c):
    out = _common(c)
    out.update({
        "full_name": c["full_name"],
        "max_caseload": c["max_caseload"],
        "caseload_count": domain.counselor_caseload_count(c["id"]),
    })
    return out


def teacher(t):
    out = _common(t)
    out.update({
        "full_name": t["full_name"],
        "max_sections": t["max_sections"],
        "assigned_section_count": domain.teacher_assigned_section_count(t["id"]),
    })
    return out


def qualification(q):
    out = _slim(q)
    out.update({"teacher_id": q["teacher_id"], "course_id": q["course_id"],
                "qualified_at": q["qualified_at"]})
    return out


def room(r):
    out = _common(r)
    out.update({"room_number": r["room_number"], "capacity": r["capacity"],
                "room_type": r["room_type"]})
    return out


def course(c):
    out = _common(c)
    out.update({
        "course_code": c["course_code"],
        "title": c["title"],
        "credits": num(c["credits"]),
        "subject_area": c["subject_area"],
        "required_room_type": c["required_room_type"],
        "singleton": c["singleton"],
        "grade_band_min": c["grade_band_min"],
        "grade_band_max": c["grade_band_max"],
        "special_program_exclusive": c["special_program_exclusive"],
        "prerequisite_course_id": c["prerequisite_course_id"],
    })
    return out


def course_request(r):
    out = _common(r)
    out.update({
        "student_id": r["student_id"],
        "course_id": r["course_id"],
        "term_id": r["term_id"],
        "priority_rank": r["priority_rank"],
        "is_alternate": r["is_alternate"],
        "state": r["state"],
        "tally_weight": domain.request_tally_weight(r),
    })
    return out


def section(s):
    out = _common(s)
    out.update({
        "term_id": s["term_id"],
        "course_id": s["course_id"],
        "teacher_id": s["teacher_id"],
        "room_id": s["room_id"],
        "period": s["period"],
        "capacity": s["capacity"],
        "enrolled_count": domain.section_enrolled_count(s["id"]),
        "cohort_counts": domain.section_cohort_counts(s["id"]),
        "state": s["state"],
        "under_enrolled": domain.section_under_enrolled(s),
    })
    return out


def schedule_entry(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "section_id": e["section_id"],
        "term_id": e["term_id"],
        "state": e["state"],
        "origin": e["origin"],
        "moved_to_section_id": e["moved_to_section_id"],
        "epoch_placed": e["epoch_placed"],
    })
    return out


def change_request(r):
    out = _common(r)
    out.update({
        "student_id": r["student_id"],
        "term_id": r["term_id"],
        "kind": r["kind"],
        "drop_entry_id": r["drop_entry_id"],
        "add_section_id": r["add_section_id"],
        "reason": r["reason"],
        "state": r["state"],
        "reviewed_by_counselor_id": r["reviewed_by_counselor_id"],
        "decided_by_admin": r["decided_by_admin"],
    })
    return out


def appointment(a):
    out = _common(a)
    out.update({
        "counselor_id": a["counselor_id"],
        "student_id": a["student_id"],
        "start_at": a["start_at"],
        "end_at": a["end_at"],
        "state": a["state"],
        "no_show_count_snapshot": a["no_show_count_snapshot"],
    })
    return out


def credit_audit(a):
    out = _slim(a)
    out.update({
        "student_id": a["student_id"],
        "term_id": a["term_id"],
        "required_credits": num(a["required_credits"]),
        "projected_credits": num(a["projected_credits"]),
        "deficiency_credits": num(a["deficiency_credits"]),
        "deficient_subjects": list(a["deficient_subjects"]),
        "audit_epoch": a["audit_epoch"],
    })
    return out


def recovery_placement(p):
    out = _common(p)
    out.update({
        "student_id": p["student_id"],
        "term_id": p["term_id"],
        "target_course_id": p["target_course_id"],
        "section_id": p["section_id"],
        "state": p["state"],
        "priority_score": num(p["priority_score"]),
    })
    return out


def rebalance_run(r):
    out = _slim(r)
    out.update({
        "term_id": r["term_id"],
        "epoch": r["epoch"],
        "moves_proposed": r["moves_proposed"],
        "imbalance_score_before": num(r["imbalance_score_before"]),
        "imbalance_score_after": num(r["imbalance_score_after"]),
        "executed_at": r["executed_at"],
    })
    return out
