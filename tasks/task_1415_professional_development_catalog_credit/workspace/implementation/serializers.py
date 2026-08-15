"""Entity serializers; computed fields are derived here on read."""
from decimal import Decimal

from db import store, fmt_ts


def lane_balance_decimal(emp):
    """SUM(district_credit over AWARDED entries with counts_toward_lane)
    minus 12.0 per completed lane advancement. Per-entry values summed
    without re-rounding (Decimal arithmetic, 0.1 steps)."""
    total = Decimal("0.0")
    for e in store.transcript_entries.values():
        if (e["employee_id"] == emp["id"] and e["status"] == "AWARDED"
                and e["counts_toward_lane"]):
            total += e["district_credit"]
    total -= Decimal("12.0") * emp.get("_adv_count", 0)
    return total


def compliance_standing_of(emp):
    """NON_COMPLIANT iff any of the employee's assignments is ESCALATED."""
    for a in store.assignments.values():
        if a["employee_id"] == emp["id"] and a["status"] == "ESCALATED":
            return "NON_COMPLIANT"
    return "COMPLIANT"


def plan_aligned_decimal(plan):
    total = Decimal("0.0")
    for e in store.transcript_entries.values():
        if e.get("growth_plan_id") == plan["id"] and e["status"] == "AWARDED":
            total += e["district_credit"]
    return total


def budget_available(b):
    """Encumbrance basis (the blocking variant)."""
    return b["allocated_cents"] - b["encumbered_cents"] - b["spent_cents"]


def section_seats_registered(section):
    n = 0
    for r in store.registrations.values():
        if r["section_id"] == section["id"] and r["status"] == "REGISTERED":
            n += 1
    return n


def _base(o):
    return {
        "id": o["id"],
        "created_at": fmt_ts(o["created_at"]),
        "updated_at": fmt_ts(o["updated_at"]),
        "version": o["version"],
    }


def ser_building(b):
    d = _base(b)
    d.update({"name": b["name"], "building_code": b["building_code"],
              "status": b["status"]})
    return d


def ser_employee(e):
    d = _base(e)
    d.update({
        "full_name": e["full_name"],
        "email": e["email"],
        "employee_kind": e["employee_kind"],
        "primary_building_id": e["primary_building_id"],
        "base_lane": e["base_lane"],
        "current_lane": e["current_lane"],
        "status": e["status"],
        "lane_credit_balance": float(lane_balance_decimal(e)),
        "last_advancement_fiscal_year": e["last_advancement_fiscal_year"],
        "compliance_standing": compliance_standing_of(e),
    })
    return d


def ser_budget(b):
    d = _base(b)
    d.update({
        "building_id": b["building_id"],
        "fiscal_year": b["fiscal_year"],
        "allocated_cents": b["allocated_cents"],
        "status": b["status"],
        "encumbered_cents": b["encumbered_cents"],
        "spent_cents": b["spent_cents"],
        "available_cents": budget_available(b),
    })
    return d


def ser_course(c):
    d = _base(c)
    d.update({
        "course_code": c["course_code"],
        "title": c["title"],
        "delivery_mode": c["delivery_mode"],
        "clock_hours": c["clock_hours"],
        "fee_cents": c["fee_cents"],
        "compliance_tag": c["compliance_tag"],
        "recurrence_months": c["recurrence_months"],
        "prerequisite_course_id": c["prerequisite_course_id"],
        "status": c["status"],
    })
    return d


def ser_section(s):
    d = _base(s)
    registered = section_seats_registered(s)
    d.update({
        "course_id": s["course_id"],
        "term": s["term"],
        "instructor_id": s["instructor_id"],
        "building_id": s["building_id"],
        "room": s["room"],
        "seat_capacity": s["seat_capacity"],
        "fee_cents": s["fee_cents"],
        "starts_at": fmt_ts(s["starts_at"]),
        "ends_at": fmt_ts(s["ends_at"]),
        "registration_opens_at": fmt_ts(s["registration_opens_at"]),
        "registration_closes_at": fmt_ts(s["registration_closes_at"]),
        "status": s["status"],
        "seats_registered": registered,
        "seats_open": s["seat_capacity"] - registered,
    })
    return d


def ser_meeting(m):
    d = _base(m)
    d.update({
        "section_id": m["section_id"],
        "starts_at": fmt_ts(m["starts_at"]),
        "ends_at": fmt_ts(m["ends_at"]),
        "room": m["room"],
    })
    return d


def ser_registration(r):
    d = _base(r)
    d.update({
        "teacher_id": r["teacher_id"],
        "section_id": r["section_id"],
        "growth_plan_id": r["growth_plan_id"],
        "aligned_focus_area": r["aligned_focus_area"],
        "status": r["status"],
        "attendance_status": r["attendance_status"],
        "survey_status": r["survey_status"],
        "waitlist_seq": r["waitlist_seq"],
        "encumbered_cents": r["encumbered_cents"],
        "completed_at": fmt_ts(r["completed_at"]) if r["completed_at"] else None,
    })
    return d


def ser_attendance(a):
    d = _base(a)
    d.update({
        "registration_id": a["registration_id"],
        "meeting_id": a["meeting_id"],
        "mark": a["mark"],
        "recorded_by_user_id": a["recorded_by_user_id"],
    })
    return d


def ser_survey(s):
    # SurveyResponse is immutable: only id + created_at, no updated_at/version.
    return {
        "id": s["id"],
        "created_at": fmt_ts(s["created_at"]),
        "registration_id": s["registration_id"],
        "overall_rating": s["overall_rating"],
        "would_recommend": s["would_recommend"],
        "comments": s["comments"],
        "submitted_at": fmt_ts(s["submitted_at"]),
    }


def ser_entry(e):
    d = _base(e)
    d.update({
        "employee_id": e["employee_id"],
        "source_type": e["source_type"],
        "source_id": e["source_id"],
        "growth_plan_id": e["growth_plan_id"],
        "fiscal_year": e["fiscal_year"],
        "clock_hours": e["clock_hours"],
        "district_credit": float(e["district_credit"]),
        "state_ceu": float(e["state_ceu"]),
        "counts_toward_lane": e["counts_toward_lane"],
        "status": e["status"],
        "awarded_at": fmt_ts(e["awarded_at"]),
        "reversed_by_entry_id": e["reversed_by_entry_id"],
    })
    return d


def ser_workshop(w):
    d = _base(w)
    d.update({
        "teacher_id": w["teacher_id"],
        "building_id": w["building_id"],
        "title": w["title"],
        "provider": w["provider"],
        "starts_at": fmt_ts(w["starts_at"]),
        "ends_at": fmt_ts(w["ends_at"]),
        "est_cost_cents": w["est_cost_cents"],
        "clock_hours_claimed": w["clock_hours_claimed"],
        "growth_plan_id": w["growth_plan_id"],
        "status": w["status"],
        "revision_count": w["revision_count"],
        "reject_reason": w["reject_reason"],
        "approved_by_user_id": w["approved_by_user_id"],
        "actual_hours": w["actual_hours"],
        "receipt_cents": w["receipt_cents"],
        "reimbursed_cents": w["reimbursed_cents"],
    })
    return d


def ser_plan(p):
    d = _base(p)
    d.update({
        "teacher_id": p["teacher_id"],
        "school_year": p["school_year"],
        "focus_areas": p["focus_areas"],
        "target_credits": p["target_credits"],
        "status": p["status"],
        "aligned_credits": float(plan_aligned_decimal(p)),
    })
    return d


def ser_assignment(a):
    d = _base(a)
    d.update({
        "employee_id": a["employee_id"],
        "course_id": a["course_id"],
        "due_date": fmt_ts(a["due_date"]),
        "status": a["status"],
        "assigned_by_user_id": a["assigned_by_user_id"],
        "satisfied_at": fmt_ts(a["satisfied_at"]) if a["satisfied_at"] else None,
        "extension_count": a["extension_count"],
    })
    return d


def ser_case(c):
    d = _base(c)
    d.update({
        "employee_id": c["employee_id"],
        "fiscal_year": c["fiscal_year"],
        "status": c["status"],
        "findings_count": c["findings_count"],
        "opened_by_user_id": c["opened_by_user_id"],
    })
    return d
