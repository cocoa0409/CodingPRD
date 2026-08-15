"""Entity -> response dict serializers (exact PRD field shapes)."""

from helpers import fmt_date, fmt_dt, fmt_ts
from services import compute_posture, compute_topics, compute_unit_status


def _common(rec):
    return {
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_case(c):
    out = {
        "id": c["id"],
        "case_number": c["case_number"],
        "agency_affiliate_code": c["agency_affiliate_code"],
        "household_size": c["household_size"],
        "scheduled_arrival_date": fmt_date(c["scheduled_arrival_date"]),
        "actual_arrival_date": fmt_date(c["actual_arrival_date"]),
        "airport_pickup_completed": c["airport_pickup_completed"],
        "status": c["status"],
        "posture": compute_posture(c),
        "topics_completed": compute_topics(c["id"]),
        "open_transfer_id": c["open_transfer_id"],
    }
    out.update(_common(c))
    return out


def ser_member(m):
    out = {
        "id": m["id"],
        "case_id": m["case_id"],
        "full_name": m["full_name"],
        "date_of_birth": fmt_date(m["date_of_birth"]),
        "relationship": m["relationship"],
        "work_eligible": m["work_eligible"],
        "age_at_arrival": m["age_at_arrival"],
        "school_age_at_arrival": m["school_age_at_arrival"],
    }
    out.update(_common(m))
    return out


def ser_unit(u):
    out = {
        "id": u["id"],
        "address": u["address"],
        "bedrooms": u["bedrooms"],
        "status": compute_unit_status(u["id"]),
    }
    out.update(_common(u))
    return out


def ser_setup(s):
    out = {
        "id": s["id"],
        "case_id": s["case_id"],
        "housing_unit_id": s["housing_unit_id"],
        "occupancy_start": fmt_date(s["occupancy_start"]),
        "occupancy_end": fmt_date(s["occupancy_end"]),
        "furnishing_items_completed": list(s["furnishing_items_completed"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_benchmark(b):
    out = {
        "id": b["id"],
        "case_id": b["case_id"],
        "service_type": b["service_type"],
        "due_rule": b["due_rule"],
        "planned_due_date": fmt_date(b["planned_due_date"]),
        "due_date": fmt_date(b["due_date"]),
        "fulfilled_on": fmt_date(b["fulfilled_on"]),
        "evidence_note_id": b["evidence_note_id"],
        "on_time": b["on_time"],
        "status": b["status"],
        "waived_reason": b["waived_reason"],
    }
    out.update(_common(b))
    return out


def ser_application(a):
    out = {
        "id": a["id"],
        "case_id": a["case_id"],
        "member_id": a["member_id"],
        "benefit_type": a["benefit_type"],
        "status": a["status"],
        "filed_on": fmt_date(a["filed_on"]),
        "decided_on": fmt_date(a["decided_on"]),
    }
    out.update(_common(a))
    return out


def ser_plan(p):
    out = {
        "id": p["id"],
        "case_id": p["case_id"],
        "monthly_income_cents": p["monthly_income_cents"],
        "trailing_3m_income_cents": p["trailing_3m_income_cents"],
        "job_start_date": fmt_date(p["job_start_date"]),
        "employed_members_count": p["employed_members_count"],
        "status": p["status"],
        "self_sufficient": p["self_sufficient"],
        "determination_variant": p["determination_variant"],
        "certified_on": fmt_date(p["certified_on"]),
    }
    out.update(_common(p))
    return out


def ser_session(s):
    out = {
        "id": s["id"],
        "case_id": s["case_id"],
        "topic": s["topic"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "status": s["status"],
        "completed_on": fmt_date(s["completed_on"]),
    }
    out.update(_common(s))
    return out


def ser_note(n):
    # Append-only: id + created_at only; NO updated_at / version keys.
    return {
        "id": n["id"],
        "case_id": n["case_id"],
        "note_type": n["note_type"],
        "body": n["body"],
        "service_date": fmt_date(n["service_date"]),
        "author_role": n["author_role"],
        "created_at": fmt_ts(n["created_at"]),
    }


def ser_transfer(t):
    out = {
        "id": t["id"],
        "case_id": t["case_id"],
        "receiving_affiliate_code": t["receiving_affiliate_code"],
        "reason": t["reason"],
        "status": t["status"],
        "initiated_by_user_id": t["initiated_by_user_id"],
        "responded_by_user_id": t["responded_by_user_id"],
        "decision_note": t["decision_note"],
    }
    out.update(_common(t))
    return out


def ser_report(r):
    out = {
        "id": r["id"],
        "period_start": fmt_date(r["period_start"]),
        "period_end": fmt_date(r["period_end"]),
        "cases_arrived_count": r["cases_arrived_count"],
        "benchmarks_met_count": r["benchmarks_met_count"],
        "benchmarks_met_on_time_count": r["benchmarks_met_on_time_count"],
        "benchmarks_pending_count": r["benchmarks_pending_count"],
        "benchmarks_waived_count": r["benchmarks_waived_count"],
        "per_capita_allocation_cents": r["per_capita_allocation_cents"],
        "status": r["status"],
        "revision_count": r["revision_count"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
    }
    out.update(_common(r))
    return out
