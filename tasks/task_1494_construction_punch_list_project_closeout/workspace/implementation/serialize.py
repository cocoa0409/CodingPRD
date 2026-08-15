"""Entity serializers — output exactly the fields declared in the scaffold
entity table plus the four common system fields (PRD 2.5)."""
from timeutil import fmt_dt, fmt_sec, fmt_opt_sec


def _common(e):
    return {
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_project(p):
    out = {
        "id": p["id"],
        "name": p["name"],
        "contract_value_cents": p["contract_value_cents"],
        "retainage_pct": p["retainage_pct"],
        "reduction_policy": p["reduction_policy"],
        "warranty_sla_mode": p["warranty_sla_mode"],
        "status": p["status"],
        "open_life_safety_count": p["open_life_safety_count"],
        "open_major_count": p["open_major_count"],
        "open_minor_count": p["open_minor_count"],
        "sc_eligible": p["sc_eligible"],
        "substantial_completion_date": fmt_opt_sec(p["substantial_completion_date"]),
        "warranty_start_date": fmt_opt_sec(p["warranty_start_date"]),
        "beneficial_occupancy_registered": p["beneficial_occupancy_registered"],
        "beneficial_occupancy_date": fmt_opt_sec(p["beneficial_occupancy_date"]),
        "retainage_held_cents": p["retainage_held_cents"],
        "retainage_paid_cents": p["retainage_paid_cents"],
        "retainage_outstanding_cents": p["retainage_outstanding_cents"],
        "sc_rejection_count": p["sc_rejection_count"],
        "closed_at": fmt_opt_sec(p["closed_at"]),
    }
    out.update(_common(p))
    return out


def ser_trade(t):
    out = {
        "id": t["id"],
        "project_id": t["project_id"],
        "trade_name": t["trade_name"],
        "responsible_type": t["responsible_type"],
        "subcontractor_org": t["subcontractor_org"],
        "has_completed_walk": t["has_completed_walk"],
        "open_item_count": t["open_item_count"],
        "om_doc_approved": t["om_doc_approved"],
        "warranty_doc_approved": t["warranty_doc_approved"],
        "asbuilt_doc_approved": t["asbuilt_doc_approved"],
        "has_conducted_training": t["has_conducted_training"],
        "lien_waiver_status": t["lien_waiver_status"],
        "lien_waiver_type": t["lien_waiver_type"],
        "lien_waiver_amount_cents": t["lien_waiver_amount_cents"],
        "lien_waiver_file_ref": t["lien_waiver_file_ref"],
        "closeout_ready": t["closeout_ready"],
    }
    out.update(_common(t))
    return out


def ser_walk(w):
    out = {
        "id": w["id"],
        "project_id": w["project_id"],
        "trade_package_id": w["trade_package_id"],
        "lead_inspector_id": w["lead_inspector_id"],
        "scheduled_start": fmt_sec(w["scheduled_start"]),
        "scheduled_end": fmt_sec(w["scheduled_end"]),
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def ser_item(i):
    out = {
        "id": i["id"],
        "project_id": i["project_id"],
        "trade_package_id": i["trade_package_id"],
        "punch_walk_id": i["punch_walk_id"],
        "title": i["title"],
        "severity": i["severity"],
        "location_building": i["location_building"],
        "location_floor": i["location_floor"],
        "location_area": i["location_area"],
        "photo_ref": i["photo_ref"],
        "status": i["status"],
        "ready_by_user_id": i["ready_by_user_id"],
        "ready_at": fmt_opt_sec(i["ready_at"]),
        "verified_by_user_id": i["verified_by_user_id"],
        "rejection_count": i["rejection_count"],
        "rejection_reason": i["rejection_reason"],
    }
    out.update(_common(i))
    return out


def ser_doc(d):
    out = {
        "id": d["id"],
        "project_id": d["project_id"],
        "trade_package_id": d["trade_package_id"],
        "doc_type": d["doc_type"],
        "file_ref": d["file_ref"],
        "revision": d["revision"],
        "status": d["status"],
        "rejection_reason": d["rejection_reason"],
    }
    out.update(_common(d))
    return out


def ser_session(s):
    out = {
        "id": s["id"],
        "project_id": s["project_id"],
        "trade_package_id": s["trade_package_id"],
        "system_name": s["system_name"],
        "location_room": s["location_room"],
        "scheduled_start": fmt_sec(s["scheduled_start"]),
        "scheduled_end": fmt_sec(s["scheduled_end"]),
        "reschedule_count": s["reschedule_count"],
        "attendee_count": s["attendee_count"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_release(r):
    out = {
        "id": r["id"],
        "project_id": r["project_id"],
        "kind": r["kind"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_case(c):
    out = {
        "id": c["id"],
        "project_id": c["project_id"],
        "title": c["title"],
        "severity": c["severity"],
        "description": c["description"],
        "reported_at": fmt_opt_sec(c["reported_at"]),
        "sla_due_at": fmt_opt_sec(c["sla_due_at"]),
        "resolution_note": c["resolution_note"],
        "denial_reason": c["denial_reason"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out
