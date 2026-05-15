"""Entity serializers — convert internal dicts into JSON-friendly view dicts.

Each serializer also performs any computed-field refresh that the PRD requires
to be available at read time (e.g., Housekeeper workload counters).
"""

from db import DB


def serialize_room(room: dict) -> dict:
    out = {
        "id": room["id"],
        "room_number": room["room_number"],
        "zone_code": room["zone_code"],
        "room_type": room["room_type"],
        "vip_flag": bool(room.get("vip_flag", False)),
        "pms_occupancy": room.get("pms_occupancy"),
        "pms_synced_at": room.get("pms_synced_at"),
        "status": room["status"],
        "discrepancy_flag": bool(room.get("discrepancy_flag", False)),
        "out_of_order_ticket_id": room.get("out_of_order_ticket_id"),
        "last_cleaned_at": room.get("last_cleaned_at"),
        "created_at": room["created_at"],
        "updated_at": room["updated_at"],
        "version": room["version"],
    }
    return out


def serialize_housekeeper(hk: dict) -> dict:
    # Lazy import to avoid circular dependency
    from services.workload import (
        compute_provisional_workload,
        compute_realized_workload,
    )
    return {
        "id": hk["id"],
        "employee_code": hk["employee_code"],
        "display_name": hk["display_name"],
        "assigned_zone": hk["assigned_zone"],
        "shift_status": hk.get("shift_status", "OFF_SHIFT"),
        "provisional_workload_minutes": compute_provisional_workload(hk["id"]),
        "realized_workload_minutes": compute_realized_workload(hk["id"]),
        "created_at": hk["created_at"],
        "updated_at": hk["updated_at"],
        "version": hk["version"],
    }


def serialize_cleaning_task(t: dict) -> dict:
    return {
        "id": t["id"],
        "room_id": t["room_id"],
        "task_source": t["task_source"],
        "expedite_flag": bool(t.get("expedite_flag", False)),
        "early_check_in_at": t.get("early_check_in_at"),
        "parent_task_id": t.get("parent_task_id"),
        "priority_score": t.get("priority_score"),
        "priority_tier": t.get("priority_tier"),
        "estimated_minutes": t.get("estimated_minutes"),
        "assigned_housekeeper_id": t.get("assigned_housekeeper_id"),
        "accepted_at": t.get("accepted_at"),
        "started_at": t.get("started_at"),
        "submitted_at": t.get("submitted_at"),
        "actual_minutes": t.get("actual_minutes"),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_inspection(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "cleaning_task_id": rec["cleaning_task_id"],
        "room_id": rec["room_id"],
        "supervisor_id": rec["supervisor_id"],
        "sampled_flag": bool(rec.get("sampled_flag", False)),
        "checklist_items": rec.get("checklist_items", []),
        "outcome": rec["outcome"],
        "notes": rec.get("notes"),
        "created_at": rec["created_at"],
    }


def serialize_minibar_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "sku_code": item["sku_code"],
        "display_name": item["display_name"],
        "unit_price_cents": item["unit_price_cents"],
        "par_level": item["par_level"],
        "replenishment_threshold": item["replenishment_threshold"],
        "status": item.get("status", "ACTIVE"),
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "version": item["version"],
    }


def serialize_minibar_consumption(c: dict) -> dict:
    return {
        "id": c["id"],
        "room_id": c["room_id"],
        "cleaning_task_id": c.get("cleaning_task_id"),
        "source_type": c["source_type"],
        "line_items": c.get("line_items", []),
        "gross_amount_cents": c.get("gross_amount_cents"),
        "tax_cents": c.get("tax_cents"),
        "posted_amount_cents": c.get("posted_amount_cents"),
        "posted_at": c.get("posted_at"),
        "folio_reference": c.get("folio_reference"),
        "dispute_note": c.get("dispute_note"),
        "finding_note": c.get("finding_note"),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_maintenance_ticket(t: dict) -> dict:
    return {
        "id": t["id"],
        "room_id": t["room_id"],
        "reporter_housekeeper_id": t["reporter_housekeeper_id"],
        "category": t["category"],
        "severity": t["severity"],
        "description": t["description"],
        "isolates_room": bool(t.get("isolates_room", False)),
        "engineering_assignee": t.get("engineering_assignee"),
        "completed_at": t.get("completed_at"),
        "verified_at": t.get("verified_at"),
        "re_clean_task_id": t.get("re_clean_task_id"),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_linen_type(lt: dict) -> dict:
    return {
        "id": lt["id"],
        "code": lt["code"],
        "display_name": lt["display_name"],
        "replacement_policy": lt["replacement_policy"],
        "scheduled_interval_days": lt.get("scheduled_interval_days"),
        "par_per_room": lt["par_per_room"],
        "replacement_cost_cents": lt["replacement_cost_cents"],
        "created_at": lt["created_at"],
        "updated_at": lt["updated_at"],
        "version": lt["version"],
    }


def serialize_linen_movement(m: dict) -> dict:
    return {
        "id": m["id"],
        "room_id": m["room_id"],
        "linen_type_id": m["linen_type_id"],
        "cleaning_task_id": m.get("cleaning_task_id"),
        "collected_quantity": m.get("collected_quantity", 0),
        "sent_to_laundry_quantity": m.get("sent_to_laundry_quantity", 0),
        "returned_quantity": m.get("returned_quantity", 0),
        "loss_quantity": m.get("loss_quantity", 0),
        "damage_quantity": m.get("damage_quantity", 0),
        "folio_charge_cents": m.get("folio_charge_cents"),
        "status": m["status"],
        "created_at": m["created_at"],
    }


def serialize_room_status_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "room_id": e["room_id"],
        "previous_status": e.get("previous_status"),
        "new_status": e["new_status"],
        "change_reason": e["change_reason"],
        "actor_id": e["actor_id"],
        "correction_note": e.get("correction_note"),
        "created_at": e["created_at"],
    }


def serialize_audit_log(a: dict) -> dict:
    return {
        "id": a["id"],
        "actor_id": a.get("actor_id"),
        "actor_role": a.get("actor_role"),
        "action_type": a["action_type"],
        "subject_entity": a["subject_entity"],
        "subject_id": a["subject_id"],
        "detail": a.get("detail", {}),
        "created_at": a["created_at"],
    }
