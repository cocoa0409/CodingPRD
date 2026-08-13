"""Serializers: project stored entity dicts to their public representation.

Computed fields (scaffold §1.1 source: computed) are derived on read; internal
bookkeeping keys (underscore-prefixed) are stripped.
"""

from __future__ import annotations

from services import domain


def serialize_steward(s: dict) -> dict:
    rec = domain.steward_recognition(s)
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "email": s["email"],
        "region_code": s["region_code"],
        "status": s["status"],
        "training_level": rec["training_level"],
        "lifetime_points": rec["lifetime_points"],
        "rolling_points": rec["rolling_points"],
        "recognition_tier": rec["recognition_tier"],
        "strike_count": rec["strike_count"],
        "suspended_at": s.get("suspended_at"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_module(m: dict) -> dict:
    return {
        "id": m["id"],
        "code": m["code"],
        "title": m["title"],
        "level": m["level"],
        "prerequisite_module_id": m.get("prerequisite_module_id"),
        "active": m.get("active", True),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_completion(t: dict) -> dict:
    return {
        "id": t["id"],
        "steward_id": t["steward_id"],
        "module_id": t["module_id"],
        "score": t["score"],
        "result": t["result"],
        "created_at": t["created_at"],
    }


def serialize_box(b: dict) -> dict:
    return {
        "id": b["id"],
        "steward_id": b["steward_id"],
        "name": b["name"],
        "latitude": b["latitude"],
        "longitude": b["longitude"],
        "capacity_books": b["capacity_books"],
        "region_code": b["region_code"],
        "charter_number": b.get("charter_number"),
        "charter_status": b["charter_status"],
        "listing_posture": b["listing_posture"],
        "installed_at": b.get("installed_at"),
        "suspended_at": b.get("suspended_at"),
        "last_activity_at": b.get("last_activity_at"),
        "current_stock": domain.box_current_stock(b),
        "open_critical_maintenance_count": domain.box_open_maintenance_count(b, "CRITICAL"),
        "open_high_maintenance_count": domain.box_open_maintenance_count(b, "HIGH"),
        "upheld_complaints_90d": domain.box_upheld_complaints_90d(b),
        "days_since_activity": domain.box_days_since_activity(b),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_inspection(r: dict) -> dict:
    return {
        "id": r["id"],
        "box_id": r["box_id"],
        "inspector_user_id": r["inspector_user_id"],
        "result": r["result"],
        "notes": r.get("notes"),
        "created_at": r["created_at"],
    }


def serialize_maintenance(m: dict) -> dict:
    return {
        "id": m["id"],
        "box_id": m["box_id"],
        "category": m["category"],
        "description": m["description"],
        "severity": m.get("severity"),
        "status": m["status"],
        "season_at_report": m["season_at_report"],
        "season_multiplier": m["season_multiplier"],
        "sla_deadline_at": m.get("sla_deadline_at"),
        "triaged_at": m.get("triaged_at"),
        "scheduled_date": m.get("scheduled_date"),
        "resolved_at": m.get("resolved_at"),
        "resolution_count": m.get("resolution_count", 0),
        "reimbursement_cents": m.get("reimbursement_cents"),
        "sla_breached": m.get("sla_breached", False),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_complaint(c: dict) -> dict:
    return {
        "id": c["id"],
        "box_id": c["box_id"],
        "category": c["category"],
        "target_category": c.get("target_category"),
        "description": c["description"],
        "evidence_url": c.get("evidence_url"),
        "status": c["status"],
        "triaged_by_user_id": c.get("triaged_by_user_id"),
        "response_due_at": c.get("response_due_at"),
        "response_text": c.get("response_text"),
        "resolved_by_user_id": c.get("resolved_by_user_id"),
        "resolution_notes": c.get("resolution_notes"),
        "outcome": c.get("outcome"),
        "upheld_at": c.get("upheld_at"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_school(s: dict) -> dict:
    return {
        "id": s["id"],
        "name": s["name"],
        "district_code": s["district_code"],
        "contact_email": s["contact_email"],
        "region_code": s["region_code"],
        "restricted_categories": s.get("restricted_categories", []),
        "status": s["status"],
        "drives_completed_count": domain.school_drives_completed(s),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_drive(d: dict) -> dict:
    metrics = domain.drive_metrics(d)
    return {
        "id": d["id"],
        "school_id": d["school_id"],
        "coordinator_steward_id": d["coordinator_steward_id"],
        "goal_books": d["goal_books"],
        "starts_at": d["starts_at"],
        "ends_at": d["ends_at"],
        "status": d["status"],
        "school_approval_status": d["school_approval_status"],
        "network_approval_status": d["network_approval_status"],
        "collected_count": metrics["collected_count"],
        "accepted_count": metrics["accepted_count"],
        "fulfillment_pct_gross": metrics["fulfillment_pct_gross"],
        "fulfillment_pct_net": metrics["fulfillment_pct_net"],
        "qualifies_for_bonus": metrics["qualifies_for_bonus"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_batch(b: dict) -> dict:
    item_count, graded_count = domain.batch_counters(b)
    return {
        "id": b["id"],
        "source_type": b["source_type"],
        "drive_id": b.get("drive_id"),
        "region_code": b["region_code"],
        "status": b["status"],
        "item_count": item_count,
        "graded_count": graded_count,
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_item(i: dict) -> dict:
    return {
        "id": i["id"],
        "batch_id": i["batch_id"],
        "title": i["title"],
        "category": i["category"],
        "condition_grade": i.get("condition_grade"),
        "status": i["status"],
        "box_id": i.get("box_id"),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_run(r: dict) -> dict:
    return {
        "id": r["id"],
        "batch_id": r["batch_id"],
        "status": r["status"],
        "plan_snapshot": r.get("plan_snapshot", []),
        "planned_item_count": r.get("planned_item_count", 0),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_allocation(a: dict) -> dict:
    return {
        "id": a["id"],
        "run_id": a["run_id"],
        "book_item_id": a["book_item_id"],
        "box_id": a["box_id"],
        "status": a["status"],
        "placed_at": a.get("placed_at"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_recognition_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "steward_id": e["steward_id"],
        "event_type": e["event_type"],
        "points_delta": e["points_delta"],
        "source_type": e["source_type"],
        "source_id": e["source_id"],
        "created_at": e["created_at"],
    }
