"""Serialize store records to API output."""
from db import iso


def program_out(p):
    return {
        "id": p["id"],
        "season_name": p["season_name"],
        "status": p["status"],
        "rental_fee_mode": p["rental_fee_mode"],
        "scoring_mode": p["scoring_mode"],
        "music_budget_cents": p["music_budget_cents"],
        "repair_budget_cents": p["repair_budget_cents"],
        "subsidy_pool_cents": p["subsidy_pool_cents"],
        "delinquency_grace_cents": p["delinquency_grace_cents"],
        "music_spent_cents": p["music_spent_cents"],
        "repair_spent_cents": p["repair_spent_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def student_out(s):
    return {
        "id": s["id"],
        "program_id": s["program_id"],
        "full_name": s["full_name"],
        "grade": s["grade"],
        "section": s["section"],
        "is_section_leader": s["is_section_leader"],
        "enrollment_status": s["enrollment_status"],
        "account_balance_cents": s["account_balance_cents"],
        "is_delinquent": s["is_delinquent"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def instrument_out(i):
    return {
        "id": i["id"],
        "program_id": i["program_id"],
        "serial_number": i["serial_number"],
        "instrument_type": i["instrument_type"],
        "condition_grade": i["condition_grade"],
        "replacement_value_cents": i["replacement_value_cents"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def instrument_assignment_out(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "instrument_id": a["instrument_id"],
        "status": a["status"],
        "checkout_at": a["checkout_at"],
        "due_date": iso(a["due_date"]) if a.get("due_date") else None,
        "returned_at": a["returned_at"],
        "fee_variant": a["fee_variant"],
        "accrued_fee_cents": a["accrued_fee_cents"],
        "late_fee_cents": a["late_fee_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def uniform_out(u):
    return {
        "id": u["id"],
        "program_id": u["program_id"],
        "garment_type": u["garment_type"],
        "size_label": u["size_label"],
        "status": u["status"],
        "cleaning_batch_id": u["cleaning_batch_id"],
        "cleaning_count": u["cleaning_count"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def uniform_assignment_out(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "uniform_id": a["uniform_id"],
        "status": a["status"],
        "issued_at": a["issued_at"],
        "returned_at": a["returned_at"],
        "soiling_level": a["soiling_level"],
        "cleaning_fee_cents": a["cleaning_fee_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def cleaning_batch_out(b):
    return {
        "id": b["id"],
        "program_id": b["program_id"],
        "status": b["status"],
        "garment_count": b["garment_count"],
        "discount_pct": b["discount_pct"],
        "total_cost_cents": b["total_cost_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def arrangement_out(a):
    return {
        "id": a["id"],
        "program_id": a["program_id"],
        "title": a["title"],
        "arranger": a["arranger"],
        "license_type": a["license_type"],
        "cost_cents": a["cost_cents"],
        "rights_end": iso(a["rights_end"]) if a.get("rights_end") else None,
        "status": a["status"],
        "creator_user_id": a["creator_user_id"],
        "approver_user_id": a["approver_user_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def event_out(e):
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "event_type": e["event_type"],
        "facility": e["facility"],
        "starts_at": iso(e["starts_at"]) if e.get("starts_at") else None,
        "ends_at": iso(e["ends_at"]) if e.get("ends_at") else None,
        "is_outdoor": e["is_outdoor"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def trip_out(t):
    return {
        "id": t["id"],
        "event_id": t["event_id"],
        "program_id": t["program_id"],
        "status": t["status"],
        "capacity": t["capacity"],
        "estimated_cost_cents": t["estimated_cost_cents"],
        "actual_cost_cents": t["actual_cost_cents"],
        "subsidy_applied_cents": t["subsidy_applied_cents"],
        "departure_at": iso(t["departure_at"]) if t.get("departure_at") else None,
        "registered_count": t["registered_count"],
        "confirmed_count": t["confirmed_count"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def trip_enrollment_out(e):
    return {
        "id": e["id"],
        "trip_id": e["trip_id"],
        "student_id": e["student_id"],
        "attendance_status": e["attendance_status"],
        "payment_status": e["payment_status"],
        "provisional_share_cents": e["provisional_share_cents"],
        "amount_due_cents": e["amount_due_cents"],
        "final_share_cents": e["final_share_cents"],
        "net_paid_cents": e["net_paid_cents"],
        "refunded_cents": e["refunded_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def payment_out(p):
    return {
        "id": p["id"],
        "student_id": p["student_id"],
        "kind": p["kind"],
        "amount_cents": p["amount_cents"],
        "trip_enrollment_id": p.get("trip_enrollment_id"),
        "fundraiser_id": p.get("fundraiser_id"),
        "reference_payment_id": p.get("reference_payment_id"),
        "allocations": p.get("allocations") or [],
        "note": p.get("note"),
        "created_at": p["created_at"],
    }


def fundraiser_out(f):
    return {
        "id": f["id"],
        "program_id": f["program_id"],
        "name": f["name"],
        "goal_cents": f["goal_cents"],
        "status": f["status"],
        "raised_cents": f["raised_cents"],
        "allocated_credit_cents": f["allocated_credit_cents"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def audition_out(a):
    return {
        "id": a["id"],
        "program_id": a["program_id"],
        "section": a["section"],
        "chair_capacity": a["chair_capacity"],
        "scoring_mode": a["scoring_mode"],
        "status": a["status"],
        "published_at": a["published_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def audition_entry_out(e):
    return {
        "id": e["id"],
        "audition_id": e["audition_id"],
        "student_id": e["student_id"],
        "judge_scores": e["judge_scores"],
        "composite_score": e["composite_score"],
        "rank": e["rank"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def chair_placement_out(c):
    return {
        "id": c["id"],
        "audition_id": c["audition_id"],
        "entry_id": c["entry_id"],
        "chair_number": c["chair_number"],
        "is_alternate": c["is_alternate"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def truck_charter_out(t):
    return {
        "id": t["id"],
        "program_id": t["program_id"],
        "event_id": t["event_id"],
        "vehicle_label": t["vehicle_label"],
        "status": t["status"],
        "capacity_weight_lb": t["capacity_weight_lb"],
        "capacity_volume_cuft": t["capacity_volume_cuft"],
        "window_start": iso(t["window_start"]) if t.get("window_start") else None,
        "window_end": iso(t["window_end"]) if t.get("window_end") else None,
        "loaded_weight_lb": t["loaded_weight_lb"],
        "loaded_volume_cuft": t["loaded_volume_cuft"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def truck_load_out(l):
    return {
        "id": l["id"],
        "charter_id": l["charter_id"],
        "instrument_id": l.get("instrument_id"),
        "description": l["description"],
        "weight_lb": l["weight_lb"],
        "volume_cuft": l["volume_cuft"],
        "created_at": l["created_at"],
    }
