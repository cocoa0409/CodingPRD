"""Entity serializers: expose exactly the scaffold-declared fields.

Internal bookkeeping keys are prefixed with '_' and never serialized.
TestPoint and ProgramVersion carry id + created_at only (no updated_at /
version) per PRD 2.4.
"""


def ser_customer(c):
    return {
        "id": c["id"],
        "company_name": c["company_name"],
        "site_state_code": c["site_state_code"],
        "credit_hold": c["credit_hold"],
        "warranty_labor_tier": c["warranty_labor_tier"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_job(j):
    return {
        "id": j["id"],
        "customer_id": j["customer_id"],
        "job_number": j["job_number"],
        "status": j["status"],
        "quoted_price_cents": j["quoted_price_cents"],
        "approved_co_delta_cents": j["approved_co_delta_cents"],
        "contract_price_cents": j["contract_price_cents"],
        "warranty_months": j["warranty_months"],
        "warranty_expires_at": j["warranty_expires_at"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def ser_panel(p):
    return {
        "id": p["id"],
        "job_id": p["job_id"],
        "panel_tag": p["panel_tag"],
        "status": p["status"],
        "enclosure_rating": p["enclosure_rating"],
        "design_engineer_id": p["design_engineer_id"],
        "sccr_rating_ka": p["sccr_rating_ka"],
        "label_serial": p["label_serial"],
        "shipped_at": p["shipped_at"],
        "commissioned_at": p["commissioned_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_component(c):
    return {
        "id": c["id"],
        "part_number": c["part_number"],
        "component_class": c["component_class"],
        "unit_cost_cents": c["unit_cost_cents"],
        "lead_time_days": c["lead_time_days"],
        "sccr_ka": c["sccr_ka"],
        "heat_dissipation_w": c["heat_dissipation_w"],
        "active": c["active"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_panel_component(l):
    return {
        "id": l["id"],
        "panel_id": l["panel_id"],
        "component_id": l["component_id"],
        "quantity": l["quantity"],
        "line_status": l["line_status"],
        "substituted_for_id": l["substituted_for_id"],
        "extended_cost_cents": l["extended_cost_cents"],
        "unit_cost_snapshot_cents": l["unit_cost_snapshot_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_substitution_request(s):
    return {
        "id": s["id"],
        "panel_id": s["panel_id"],
        "original_line_id": s["original_line_id"],
        "proposed_component_id": s["proposed_component_id"],
        "status": s["status"],
        "reason": s["reason"],
        "requested_by_id": s["requested_by_id"],
        "lead_time_delta_days": s["lead_time_delta_days"],
        "sccr_impact_ka": s["sccr_impact_ka"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_test_point(t):
    return {
        "id": t["id"],
        "panel_id": t["panel_id"],
        "point_label": t["point_label"],
        "expected_signal": t["expected_signal"],
        "sequence_no": t["sequence_no"],
        "result": t["result"],
        "created_at": t["created_at"],
    }


def ser_test_session(s):
    return {
        "id": s["id"],
        "panel_id": s["panel_id"],
        "technician_id": s["technician_id"],
        "status": s["status"],
        "started_at": s["started_at"],
        "completed_at": s["completed_at"],
        "pass_count": s["pass_count"],
        "fail_count": s["fail_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_program_version(v):
    return {
        "id": v["id"],
        "panel_id": v["panel_id"],
        "version_tag": v["version_tag"],
        "status": v["status"],
        "content_hash": v["content_hash"],
        "site_backup_taken": v["site_backup_taken"],
        "released_at": v["released_at"],
        "created_at": v["created_at"],
    }


def ser_startup_session(s):
    return {
        "id": s["id"],
        "panel_id": s["panel_id"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "status": s["status"],
        "remote_access_granted": s["remote_access_granted"],
        "support_mode": s["support_mode"],
        "engineer_id": s["engineer_id"],
        "labor_hours": s["labor_hours"],
        "billable_cents": s["billable_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_change_order(o):
    return {
        "id": o["id"],
        "job_id": o["job_id"],
        "co_number": o["co_number"],
        "status": o["status"],
        "description": o["description"],
        "price_delta_cents": o["price_delta_cents"],
        "discount_pct": o["discount_pct"],
        "computed_delta_cents": o["computed_delta_cents"],
        "requested_by_id": o["requested_by_id"],
        "supersedes_co_id": o["supersedes_co_id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_warranty_claim(w):
    return {
        "id": w["id"],
        "job_id": w["job_id"],
        "panel_id": w["panel_id"],
        "status": w["status"],
        "defect_description": w["defect_description"],
        "filed_at": w["filed_at"],
        "claimed_labor_hours": w["claimed_labor_hours"],
        "provisional_liability_cents": w["provisional_liability_cents"],
        "final_liability_cents": w["final_liability_cents"],
        "liability_delta_cents": w["liability_delta_cents"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_asbuilt(pkg):
    return {
        "id": pkg["id"],
        "panel_id": pkg["panel_id"],
        "status": pkg["status"],
        "has_wiring_diagram": pkg["has_wiring_diagram"],
        "has_program_archive": pkg["has_program_archive"],
        "has_test_report": pkg["has_test_report"],
        "has_ul_label_photo": pkg["has_ul_label_photo"],
        "completeness_pct": pkg["completeness_pct"],
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }
