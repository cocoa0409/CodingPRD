"""Entity serializers — output exactly the fields declared in the scaffold
entity table. ResultRecord and TrainingRecord carry only id/created_at system
fields (PRD 2.5 exception); everything else carries id/created_at/updated_at/
version. The internal "_seq" insertion key is never serialized."""
from timeutil import fmt_dt


def _common(e):
    return {
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_facility(f):
    out = {
        "id": f["id"],
        "facility_name": f["facility_name"],
        "state_code": f["state_code"],
        "owner_account_id": f["owner_account_id"],
        "annual_fee_paid_through": fmt_dt(f["annual_fee_paid_through"]),
        "fund_program_election": f["fund_program_election"],
        "posture_score": f["posture_score"],
        "compliance_posture": f["compliance_posture"],
        "fund_cap_remaining_cents": f["fund_cap_remaining_cents"],
        "fund_year_deductible_remaining_cents": f["fund_year_deductible_remaining_cents"],
        "status": f["status"],
    }
    out.update(_common(f))
    return out


def ser_tank(t):
    out = {
        "id": t["id"],
        "facility_id": t["facility_id"],
        "tank_tag": t["tank_tag"],
        "substance": t["substance"],
        "capacity_gallons": t["capacity_gallons"],
        "installed_on": fmt_dt(t["installed_on"]),
        "tank_construction": t["tank_construction"],
        "piping_type": t["piping_type"],
        "release_detection_mode": t["release_detection_mode"],
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def ser_component(c):
    out = {
        "id": c["id"],
        "tank_system_id": c["tank_system_id"],
        "component_type": c["component_type"],
        "install_date": fmt_dt(c["install_date"]),
        "serial_no": c["serial_no"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_technician(t):
    out = {
        "id": t["id"],
        "full_name": t["full_name"],
        "endorsements": list(t["endorsements"]),
        "trainer": t["trainer"],
        "active": t["active"],
    }
    out.update(_common(t))
    return out


def ser_order(o):
    out = {
        "id": o["id"],
        "facility_id": o["facility_id"],
        "tank_system_id": o["tank_system_id"],
        "component_id": o["component_id"],
        "service_type": o["service_type"],
        "technician_id": o["technician_id"],
        "window_start": fmt_dt(o["window_start"]),
        "window_end": fmt_dt(o["window_end"]),
        "line_items": o["line_items"],
        "quote_total_cents": o["quote_total_cents"],
        "result_outcome": o["result_outcome"],
        "performed_by_technician_id": o["performed_by_technician_id"],
        "certified_by_technician_id": o["certified_by_technician_id"],
        "linked_deficiency_id": o["linked_deficiency_id"],
        "status": o["status"],
    }
    out.update(_common(o))
    return out


def ser_result_record(r):
    # Immutable ledger (common_fields: false): id + created_at only.
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "service_order_id": r["service_order_id"],
        "readings": r["readings"],
        "outcome": r["outcome"],
        "recorded_at": fmt_dt(r["recorded_at"]),
    }


def ser_deficiency(d):
    out = {
        "id": d["id"],
        "facility_id": d["facility_id"],
        "tank_system_id": d["tank_system_id"],
        "component_id": d["component_id"],
        "source_service_order_id": d["source_service_order_id"],
        "verified_by_service_order_id": d["verified_by_service_order_id"],
        "origin": d["origin"],
        "period_month": d["period_month"],
        "severity": d["severity"],
        "description": d["description"],
        "correction_deadline": fmt_dt(d["correction_deadline"]),
        "escalated_at": fmt_dt(d["escalated_at"]),
        "status": d["status"],
    }
    out.update(_common(d))
    return out


def ser_submission(s):
    out = {
        "id": s["id"],
        "facility_id": s["facility_id"],
        "submission_type": s["submission_type"],
        "period_month": s["period_month"],
        "release_detection_record_ids": s["release_detection_record_ids"],
        "service_order_ids": s["service_order_ids"],
        "release_event_id": s["release_event_id"],
        "submitted_at": fmt_dt(s["submitted_at"]),
        "is_late": s["is_late"],
        "state_reviewer_note": s["state_reviewer_note"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_record(r):
    out = {
        "id": r["id"],
        "tank_system_id": r["tank_system_id"],
        "period_month": r["period_month"],
        "method": r["method"],
        "readings_summary": r["readings_summary"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_operator(o):
    out = {
        "id": o["id"],
        "facility_id": o["facility_id"],
        "full_name": o["full_name"],
        "operator_class": o["operator_class"],
        "status": o["status"],
    }
    out.update(_common(o))
    return out


def ser_training_record(t):
    # Immutable ledger (common_fields: false): id + created_at only.
    return {
        "id": t["id"],
        "created_at": fmt_dt(t["created_at"]),
        "operator_id": t["operator_id"],
        "instructor_technician_id": t["instructor_technician_id"],
        "course_class": t["course_class"],
        "completed_at": fmt_dt(t["completed_at"]),
        "expires_at": fmt_dt(t["expires_at"]),
    }


def ser_release_event(r):
    out = {
        "id": r["id"],
        "facility_id": r["facility_id"],
        "tank_system_id": r["tank_system_id"],
        "discovered_at": fmt_dt(r["discovered_at"]),
        "source_description": r["source_description"],
        "report_deadline": fmt_dt(r["report_deadline"]),
        "reported_to_state_at": fmt_dt(r["reported_to_state_at"]),
        "late_notification": r["late_notification"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_fund_claim(c):
    out = {
        "id": c["id"],
        "facility_id": c["facility_id"],
        "release_event_id": c["release_event_id"],
        "expense_lines": c["expense_lines"],
        "deductible_applied_cents": c["deductible_applied_cents"],
        "eligible_amount_cents": c["eligible_amount_cents"],
        "payable_amount_cents": c["payable_amount_cents"],
        "approved_amount_cents": c["approved_amount_cents"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out
