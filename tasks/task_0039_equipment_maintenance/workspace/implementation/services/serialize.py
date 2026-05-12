"""Serializers for entity dicts -> JSON-friendly dicts."""
from db import fmt_iso


def _common(entity):
    out = {
        "id": entity["id"],
        "created_at": fmt_iso(entity["created_at"]),
    }
    if "updated_at" in entity:
        out["updated_at"] = fmt_iso(entity["updated_at"])
    if "version" in entity:
        out["version"] = entity["version"]
    return out


def serialize_site(s):
    out = _common(s)
    out.update({
        "name": s["name"],
        "clock_now": fmt_iso(s["clock_now"]),
        "sweep_run_index": s["sweep_run_index"],
    })
    return out


def serialize_equipment(e):
    out = _common(e)
    out.update({
        "site_id": e["site_id"],
        "asset_tag": e["asset_tag"],
        "category": e["category"],
        "location": e["location"],
        "responsible_user_id": e["responsible_user_id"],
        "technical_spec": e["technical_spec"],
        "criticality": e["criticality"],
        "warranty_start": fmt_iso(e["warranty_start"]),
        "warranty_end": fmt_iso(e["warranty_end"]),
        "lifecycle_status": e["lifecycle_status"],
        "usage_counter": e["usage_counter"],
        "last_failure_at": fmt_iso(e.get("last_failure_at")) if e.get("last_failure_at") else None,
        "last_repair_completed_at": fmt_iso(e.get("last_repair_completed_at")) if e.get("last_repair_completed_at") else None,
        "open_work_order_id": e.get("open_work_order_id"),
    })
    return out


def serialize_template(t):
    return {
        "id": t["id"],
        "created_at": fmt_iso(t["created_at"]),
        "site_id": t["site_id"],
        "code": t["code"],
        "title": t["title"],
        "equipment_category": t["equipment_category"],
        "required_skill": t["required_skill"],
        "estimated_minutes": t["estimated_minutes"],
        "default_priority": t["default_priority"],
    }


def serialize_plan(p):
    out = _common(p)
    out.update({
        "site_id": p["site_id"],
        "equipment_id": p["equipment_id"],
        "template_id": p["template_id"],
        "kind": p["kind"],
        "interval_days": p.get("interval_days"),
        "interval_usage": p.get("interval_usage"),
        "alarm_code": p.get("alarm_code"),
        "threshold_metric": p.get("threshold_metric"),
        "threshold_op": p.get("threshold_op"),
        "threshold_value": p.get("threshold_value"),
        "status": p["status"],
        "last_generated_at": fmt_iso(p.get("last_generated_at")) if p.get("last_generated_at") else None,
        "last_generated_usage": p.get("last_generated_usage"),
        "next_due_at": fmt_iso(p.get("next_due_at")) if p.get("next_due_at") else None,
    })
    return out


def serialize_spare_part(sp):
    out = _common(sp)
    out.update({
        "site_id": sp["site_id"],
        "sku": sp["sku"],
        "name": sp["name"],
        "unit_cost_cents": sp["unit_cost_cents"],
        "stock_on_hand": sp["stock_on_hand"],
        "stock_reserved": sp["stock_reserved"],
        "reorder_point": sp["reorder_point"],
        "replenish_pending": sp["replenish_pending"],
    })
    return out


def serialize_technician(t):
    out = _common(t)
    out.update({
        "site_id": t["site_id"],
        "name": t["name"],
        "skills": list(t["skills"]),
        "status": t["status"],
        "open_load": t["open_load"],
    })
    return out


def serialize_work_order(w):
    out = _common(w)
    out.update({
        "site_id": w["site_id"],
        "equipment_id": w["equipment_id"],
        "template_id": w["template_id"],
        "plan_id": w.get("plan_id"),
        "source": w["source"],
        "priority": w["priority"],
        "priority_score": w["priority_score"],
        "required_skill": w["required_skill"],
        "estimated_minutes": w["estimated_minutes"],
        "assigned_technician_id": w.get("assigned_technician_id"),
        "status": w["status"],
        "opened_at": fmt_iso(w["opened_at"]),
        "started_at": fmt_iso(w.get("started_at")) if w.get("started_at") else None,
        "completed_at": fmt_iso(w.get("completed_at")) if w.get("completed_at") else None,
        "closed_at": fmt_iso(w.get("closed_at")) if w.get("closed_at") else None,
        "sla_due_at": fmt_iso(w["sla_due_at"]),
        "sla_breached": w["sla_breached"],
        "pause_reason": w.get("pause_reason"),
        "total_active_minutes": w["total_active_minutes"],
        "parts_cost_cents": w.get("parts_cost_cents"),
        "reassign_count": w["reassign_count"],
        "cancel_reason": w.get("cancel_reason"),
    })
    return out


def serialize_requisition(r):
    out = _common(r)
    out.update({
        "work_order_id": r["work_order_id"],
        "part_id": r["part_id"],
        "qty": r["qty"],
        "status": r["status"],
        "unit_cost_cents_at_issue": r.get("unit_cost_cents_at_issue"),
        "returned_qty": r["returned_qty"],
    })
    return out


def serialize_repair_record(rr):
    return {
        "id": rr["id"],
        "created_at": fmt_iso(rr["created_at"]),
        "work_order_id": rr["work_order_id"],
        "fault_description": rr["fault_description"],
        "root_cause": rr["root_cause"],
        "repair_actions": rr["repair_actions"],
        "working_minutes": rr["working_minutes"],
        "before_evidence_url": rr["before_evidence_url"],
        "after_evidence_url": rr["after_evidence_url"],
        "parts_replaced": rr["parts_replaced"],
        "acceptance_user_id": rr.get("acceptance_user_id"),
        "acceptance_at": fmt_iso(rr.get("acceptance_at")) if rr.get("acceptance_at") else None,
    }


def serialize_alarm(a):
    return {
        "id": a["id"],
        "created_at": fmt_iso(a["created_at"]),
        "equipment_id": a["equipment_id"],
        "alarm_code": a["alarm_code"],
        "severity": a["severity"],
        "emitted_at": fmt_iso(a["emitted_at"]),
        "generated_work_order_id": a.get("generated_work_order_id"),
        "metric_value": a.get("metric_value"),
    }


def serialize_audit(a):
    return {
        "id": a["id"],
        "created_at": fmt_iso(a["created_at"]),
        "site_id": a["site_id"],
        "actor_role": a["actor_role"],
        "actor_user_id": a["actor_user_id"],
        "action": a["action"],
        "target_id": a["target_id"],
        "from_value": a["from_value"],
        "to_value": a["to_value"],
        "occurred_at": fmt_iso(a["occurred_at"]),
    }
