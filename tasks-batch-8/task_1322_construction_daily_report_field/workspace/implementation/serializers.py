"""Entity -> API dict. Computed fields are derived at read time."""
import calc
from db import store
from util import fmt_dt, out_num


def _common(rec):
    return {
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_project(p):
    units, cost, _ = calc.project_percents(p["id"])
    out = {
        "id": p["id"],
        "name": p["name"],
        "contract_number": p["contract_number"],
        "scheduled_shift_start": p["scheduled_shift_start"],
        "scheduled_shift_hours": out_num(p["scheduled_shift_hours"]),
        "retention_days": p["retention_days"],
        "status": p["status"],
        "percent_complete_units": out_num(units),
        "percent_complete_cost": out_num(cost),
    }
    out.update(_common(p))
    return out


def ser_work_area(w):
    out = {
        "id": w["id"],
        "project_id": w["project_id"],
        "code": w["code"],
        "description": w["description"],
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def ser_delivery_zone(z):
    out = {
        "id": z["id"],
        "project_id": z["project_id"],
        "zone_code": z["zone_code"],
        "buffer_minutes": z["buffer_minutes"],
        "status": z["status"],
    }
    out.update(_common(z))
    return out


def ser_work_item(wi):
    installed = calc.installed_to_date(wi["id"])
    out = {
        "id": wi["id"],
        "project_id": wi["project_id"],
        "cost_code": wi["cost_code"],
        "description": wi["description"],
        "budgeted_quantity": out_num(wi["budgeted_quantity"]),
        "unit": wi["unit"],
        "unit_cost_cents": wi["unit_cost_cents"],
        "installed_to_date": out_num(installed),
        "status": calc.work_item_status(wi, installed),
    }
    out.update(_common(wi))
    return out


def ser_report(r):
    project = store.projects.get(r["project_id"])
    workers, reg, ot, dt = calc.report_manpower(r["id"])
    wlh, wcal, wfrac = calc.report_weather(r["id"], project)
    has_open, retention_class = calc.report_incident_flags(r["id"])
    rel = calc.retention_release(r)
    out = {
        "id": r["id"],
        "project_id": r["project_id"],
        "report_date": r["report_date"].isoformat(),
        "general_notes": r["general_notes"],
        "shift_start_actual": fmt_dt(r["shift_start_actual"]),
        "shift_end_actual": fmt_dt(r["shift_end_actual"]),
        "no_work_performed": r["no_work_performed"],
        "status": r["status"],
        "content_posture": calc.content_posture(r),
        "submitted_by_user_id": r["submitted_by_user_id"],
        "submitted_at": fmt_dt(r["submitted_at"]),
        "revision_count": r["revision_count"],
        "has_open_incident": has_open,
        "distribution_hold": has_open,
        "retention_class": retention_class,
        "retention_release_date": fmt_dt(rel),
        "total_workers": workers,
        "manhours_regular": out_num(reg),
        "manhours_ot": out_num(ot),
        "manhours_dt": out_num(dt),
        "weather_lost_hours": out_num(wlh),
        "weather_lost_day_calendar": wcal,
        "weather_lost_day_fraction": out_num(wfrac),
    }
    out.update(_common(r))
    return out


def ser_crew_entry(c):
    out = {
        "id": c["id"],
        "report_id": c["report_id"],
        "work_area_id": c["work_area_id"],
        "subcontractor": c["subcontractor"],
        "trade": c["trade"],
        "worker_count": c["worker_count"],
        "hours_per_worker": out_num(c["hours_per_worker"]),
        "work_performed": c["work_performed"],
        "regular_hours": out_num(c["regular_hours"]),
        "ot_hours": out_num(c["ot_hours"]),
        "dt_hours": out_num(c["dt_hours"]),
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_equipment_entry(e):
    out = {
        "id": e["id"],
        "report_id": e["report_id"],
        "work_area_id": e["work_area_id"],
        "equipment_type": e["equipment_type"],
        "unit_count": e["unit_count"],
        "hours_used": out_num(e["hours_used"]),
        "hours_idle": out_num(e["hours_idle"]),
        "status": e["status"],
    }
    out.update(_common(e))
    return out


def ser_weather(w):
    # immutable log: id + created_at only, no updated_at / version
    return {
        "id": w["id"],
        "report_id": w["report_id"],
        "observed_at": fmt_dt(w["observed_at"]),
        "condition": w["condition"],
        "temperature_f": out_num(w["temperature_f"]),
        "precipitation_in": out_num(w["precipitation_in"]),
        "wind_mph": out_num(w["wind_mph"]),
        "work_impact": w["work_impact"],
        "created_at": fmt_dt(w["created_at"]),
    }


def ser_delay_event(ev):
    out = {
        "id": ev["id"],
        "report_id": ev["report_id"],
        "work_area_id": ev["work_area_id"],
        "start_at": fmt_dt(ev["start_at"]),
        "end_at": fmt_dt(ev["end_at"]),
        "cause": ev["cause"],
        "classification": ev["classification"],
        "lost_hours": out_num(ev["lost_hours"]),
        "status": ev["status"],
        "dispute_reason": ev["dispute_reason"],
    }
    out.update(_common(ev))
    return out


def ser_safety_observation(o):
    out = {
        "id": o["id"],
        "report_id": o["report_id"],
        "work_area_id": o["work_area_id"],
        "description": o["description"],
        "risk_level": o["risk_level"],
        "corrective_action": o["corrective_action"],
        "due_date": o["due_date"].isoformat() if o["due_date"] else None,
        "media_attachment_id": o["media_attachment_id"],
        "status": o["status"],
        "created_by_user_id": o["created_by_user_id"],
        "incident_id": o["incident_id"],
    }
    out.update(_common(o))
    return out


def ser_incident(i):
    out = {
        "id": i["id"],
        "report_id": i["report_id"],
        "work_area_id": i["work_area_id"],
        "safety_observation_id": i["safety_observation_id"],
        "occurred_at": fmt_dt(i["occurred_at"]),
        "severity": i["severity"],
        "injured_count": i["injured_count"],
        "days_away": i["days_away"],
        "narrative": i["narrative"],
        "recordable": i["recordable"],
        "osha_notification_deadline": fmt_dt(i["osha_notification_deadline"]),
        "osha_notified_at": fmt_dt(i["osha_notified_at"]),
        "notification_overdue": calc.notification_overdue(i),
        "status": i["status"],
        "created_by_user_id": i["created_by_user_id"],
    }
    out.update(_common(i))
    return out


def ser_media(m):
    out = {
        "id": m["id"],
        "report_id": m["report_id"],
        "work_area_id": m["work_area_id"],
        "media_type": m["media_type"],
        "file_url": m["file_url"],
        "captured_at": fmt_dt(m["captured_at"]),
        "gps_lat": out_num(m["gps_lat"]),
        "gps_lng": out_num(m["gps_lng"]),
        "linked_incident_id": m["linked_incident_id"],
        "linked_delivery_id": m["linked_delivery_id"],
        "status": m["status"],
    }
    out.update(_common(m))
    return out


def ser_delivery(d):
    out = {
        "id": d["id"],
        "report_id": d["report_id"],
        "delivery_zone_id": d["delivery_zone_id"],
        "po_number": d["po_number"],
        "material_description": d["material_description"],
        "delivered_qty": out_num(d["delivered_qty"]),
        "unit": d["unit"],
        "scheduled_window_start": fmt_dt(d["scheduled_window_start"]),
        "scheduled_window_end": fmt_dt(d["scheduled_window_end"]),
        "accepted_qty": out_num(d["accepted_qty"]),
        "rejected_qty": out_num(d["rejected_qty"]),
        "pending_recount_qty": out_num(d["pending_recount_qty"]),
        "inspection_notes": d["inspection_notes"],
        "status": d["status"],
    }
    out.update(_common(d))
    return out


def _ser_lines(lines):
    out = []
    for ln in lines:
        out.append({k: out_num(v) for k, v in ln.items()})
    return out


def ser_ticket(t):
    out = {
        "id": t["id"],
        "report_id": t["report_id"],
        "work_item_id": t["work_item_id"],
        "description": t["description"],
        "authorized_ceiling_cents": t["authorized_ceiling_cents"],
        "labor_lines": _ser_lines(t["labor_lines"]),
        "equipment_lines": _ser_lines(t["equipment_lines"]),
        "material_lines": _ser_lines(t["material_lines"]),
        "labor_cost_cents": t["labor_cost_cents"],
        "equipment_cost_cents": t["equipment_cost_cents"],
        "materials_subtotal_cents": t["materials_subtotal_cents"],
        "materials_markup_cents": t["materials_markup_cents"],
        "materials_cost_cents": t["materials_cost_cents"],
        "total_cents": t["total_cents"],
        "status": t["status"],
        "created_by_user_id": t["created_by_user_id"],
        "contractor_signed_by": t["contractor_signed_by"],
        "owner_signed_by": t["owner_signed_by"],
        "revision_count": t["revision_count"],
        "reject_reason": t["reject_reason"],
    }
    out.update(_common(t))
    return out


def ser_quantity_entry(q):
    out = {
        "id": q["id"],
        "report_id": q["report_id"],
        "work_item_id": q["work_item_id"],
        "work_area_id": q["work_area_id"],
        "quantity_installed": out_num(q["quantity_installed"]),
        "rounded_quantity": out_num(q["rounded_quantity"]),
        "supersedes_id": q["supersedes_id"],
        "status": q["status"],
    }
    out.update(_common(q))
    return out


def ser_distribution(d):
    out = {
        "id": d["id"],
        "report_id": d["report_id"],
        "recipient_email": d["recipient_email"],
        "recipient_role": d["recipient_role"],
        "status": d["status"],
        "sent_at": fmt_dt(d["sent_at"]),
        "acknowledged_at": fmt_dt(d["acknowledged_at"]),
    }
    out.update(_common(d))
    return out
