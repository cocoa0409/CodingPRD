"""Entity serializers — public JSON shapes with derived fields."""
from store import db
from services import domain as dom


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def bus(b):
    out = _common(b)
    out.update({
        "fleet_number": b["fleet_number"],
        "vin": b["vin"],
        "model_year": b["model_year"],
        "in_service_date": b["in_service_date"],
        "initial_odometer_miles": b["initial_odometer_miles"],
        "odometer_miles": b["odometer_miles"],
        "replacement_cost_cents": b["replacement_cost_cents"],
        "base_warranty_expiry_miles": b["base_warranty_expiry_miles"],
        "base_warranty_expiry_date": b["base_warranty_expiry_date"],
        "extended_warranty_limit_miles": b.get("extended_warranty_limit_miles"),
        "extended_warranty_limit_months": b.get("extended_warranty_limit_months"),
        "overhaul_interval_miles": b["overhaul_interval_miles"],
        "last_overhaul_miles": b.get("last_overhaul_miles", 0),
        "service_status": b["service_status"],
        "availability_status": b["availability_status"],
        "hold_reasons": sorted(b.get("hold_reasons") or []),
        "emissions_cert_expiry_date": b.get("emissions_cert_expiry_date"),
        "emissions_compliance": dom.bus_emissions_compliance(b),
        "last_pm_a_miles": b["last_pm_a_miles"],
        "last_pm_a_date": b["last_pm_a_date"],
        "last_pm_b_miles": b["last_pm_b_miles"],
        "last_pm_b_date": b["last_pm_b_date"],
        "last_pm_c_miles": b["last_pm_c_miles"],
        "last_pm_c_date": b["last_pm_c_date"],
        "pm_due_status": b.get("pm_due_status", "CURRENT"),
        "total_maintenance_cost_cents": b.get("total_maintenance_cost_cents", 0),
        "retirement_reason": b.get("retirement_reason"),
    })
    return out


def pm_policy(p):
    out = _common(p)
    out.update({
        "level_a_interval_miles": p["level_a_interval_miles"],
        "level_b_interval_miles": p["level_b_interval_miles"],
        "level_c_interval_miles": p["level_c_interval_miles"],
        "tolerance_miles": p["tolerance_miles"],
        "calendar_interval_days": p["calendar_interval_days"],
        "status": p["status"],
    })
    return out


def mechanic(m):
    out = _common(m)
    out.update({
        "name": m["name"],
        "employee_ref": m["employee_ref"],
        "employment_status": m["employment_status"],
    })
    return out


def certification(c):
    out = _common(c)
    out.update({
        "mechanic_id": c["mechanic_id"],
        "cert_type": c["cert_type"],
        "issued_date": c["issued_date"],
        "expiry_date": c["expiry_date"],
        "status": c["status"],
    })
    return out


def shift(s):
    out = _common(s)
    coverage, coverage_status = dom.shift_coverage(s)
    out.update({
        "shift_date": s["shift_date"],
        "shift_type": s["shift_type"],
        "required_headcount": s.get("required_headcount") or {},
        "status": s["status"],
        "coverage_by_cert": coverage,
        "coverage_status": coverage_status,
    })
    return out


def assignment(a):
    out = _common(a)
    out.update({
        "shift_id": a["shift_id"],
        "mechanic_id": a["mechanic_id"],
        "role_in_shift": a["role_in_shift"],
        "status": a["status"],
    })
    return out


def part(p):
    out = _common(p)
    out.update({
        "sku": p["sku"],
        "description": p["description"],
        "part_class": p["part_class"],
        "unit_cost_cents": p["unit_cost_cents"],
        "reorder_point": p["reorder_point"],
        "quantity_on_hand": p["quantity_on_hand"],
        "quantity_reserved": p["quantity_reserved"],
        "quantity_available": dom.part_available(p),
        "stock_status": p["stock_status"],
        "core_charge_cents": p.get("core_charge_cents"),
        "warranty_eligible": p["warranty_eligible"],
        "superseded_by_id": p.get("superseded_by_id"),
    })
    return out


def work_order(wo):
    dom.recompute_wo_costs(wo)
    out = _common(wo)
    out.update({
        "bus_id": wo["bus_id"],
        "wo_type": wo["wo_type"],
        "priority": wo["priority"],
        "defect_report_id": wo.get("defect_report_id"),
        "campaign_id": wo.get("campaign_id"),
        "emissions_inspection_id": wo.get("emissions_inspection_id"),
        "lead_mechanic_id": wo.get("lead_mechanic_id"),
        "planned_start_date": wo["planned_start_date"],
        "planned_end_date": wo["planned_end_date"],
        "estimated_labor_hours": wo["estimated_labor_hours"],
        "estimated_cost_cents": wo["estimated_cost_cents"],
        "odometer_at_open": wo["odometer_at_open"],
        "opened_date": wo["opened_date"],
        "started_date": wo.get("started_date"),
        "closed_date": wo.get("closed_date"),
        "status": wo["status"],
        "labor_entries": wo.get("labor_entries", []),
        "labor_total_cents": wo.get("labor_total_cents", 0),
        "parts_total_cents": wo.get("parts_total_cents", 0),
        "core_charges_accrued_cents": wo.get("core_charges_accrued_cents", 0),
        "core_credits_cents": wo.get("core_credits_cents", 0),
        "parts_net_cents": wo.get("parts_net_cents", 0),
        "total_cost_cents": wo.get("total_cost_cents", 0),
        "qa_reject_count": wo.get("qa_reject_count", 0),
        "qa_note": wo.get("qa_note"),
        "cancel_reason": wo.get("cancel_reason"),
    })
    return out


def part_line(l):
    out = _common(l)
    out.update({
        "work_order_id": l["work_order_id"],
        "part_id": l["part_id"],
        "qty": l["qty"],
        "qty_issued": l["qty_issued"],
        "unit_cost_cents": l["unit_cost_cents"],
        "issue_status": l["issue_status"],
        "core_status": l["core_status"],
        "core_due_date": l.get("core_due_date"),
        "line_total_cents": dom.line_total_cents(l),
    })
    return out


def defect(d):
    out = _common(d)
    out.update({
        "bus_id": d["bus_id"],
        "reported_by": d.get("reported_by"),
        "severity": d["severity"],
        "defect_code": d["defect_code"],
        "description": d["description"],
        "odometer_at_report": d["odometer_at_report"],
        "status": d["status"],
        "disposition": d.get("disposition"),
        "road_call_mechanic_id": d.get("road_call_mechanic_id"),
        "defer_until_date": d.get("defer_until_date"),
        "defer_justification": d.get("defer_justification"),
        "defer_count": d.get("defer_count", 0),
        "linked_work_order_id": d.get("linked_work_order_id"),
        "resolution": d.get("resolution"),
        "flagged_by_log_id": d.get("flagged_by_log_id"),
    })
    return out


def campaign(c):
    out = _common(c)
    count, pct = dom.campaign_progress(c)
    out.update({
        "code": c["code"],
        "title": c["title"],
        "model_year_from": c["model_year_from"],
        "model_year_to": c["model_year_to"],
        "required_part_id": c.get("required_part_id"),
        "required_cert_type": c.get("required_cert_type"),
        "labor_hours_per_bus": c["labor_hours_per_bus"],
        "deadline_date": c["deadline_date"],
        "status": c["status"],
        "scope_bus_ids": c.get("scope_bus_ids") or [],
        "activated_date": c.get("activated_date"),
        "buses_completed_count": count,
        "progress_pct": pct,
    })
    return out


def mileage_log(l):
    out = _common(l)
    out.update({
        "bus_id": l["bus_id"],
        "log_date": l["log_date"],
        "odometer_end": l["odometer_end"],
        "fuel_gallons": l["fuel_gallons"],
        "miles_driven": l["miles_driven"],
        "status": l["status"],
    })
    if l.get("void_reason") is not None:
        out["void_reason"] = l["void_reason"]
    return out


def inspection(i):
    out = _common(i)
    out.update({
        "bus_id": i["bus_id"],
        "test_type": i["test_type"],
        "test_date": i["test_date"],
        "result": i["result"],
        "failed_component_part_id": i.get("failed_component_part_id"),
        "certificate_expiry_date": i.get("certificate_expiry_date"),
        "status": i["status"],
    })
    return out


def claim(c):
    out = _common(c)
    approved = c.get("approved_cents")
    received = c.get("received_cents")
    variance = None
    if approved is not None and received is not None:
        variance = approved - received
    out.update({
        "work_order_id": c["work_order_id"],
        "bus_id": c["bus_id"],
        "claim_type": c["claim_type"],
        "proration_basis": c.get("proration_basis"),
        "manual_claimed_cents": c.get("manual_claimed_cents"),
        "status": c["status"],
        "eligible_cents": c.get("eligible_cents"),
        "claimed_cents": c.get("claimed_cents"),
        "approved_cents": approved,
        "received_cents": received,
        "variance_cents": variance,
        "appeal_count": c.get("appeal_count", 0),
        "oem_reference": c.get("oem_reference"),
        "auto_created": c.get("auto_created", False),
        "submitted_by_user_id": c.get("submitted_by_user_id"),
        "recovered_by_user_id": c.get("recovered_by_user_id"),
    })
    return out


def plan(p):
    out = _common(p)
    out.update({
        "plan_year": p["plan_year"],
        "status": p["status"],
        "scores": p.get("scores", []),
    })
    return out
