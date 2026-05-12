"""Projection helpers — convert internal entity dicts to public JSON shape."""
from db import rooms as rooms_table


def project_room_type(rt: dict) -> dict:
    from db import rooms
    total_physical = sum(
        1 for r in rooms.values()
        if r.get("room_type_id") == rt["id"] and r.get("lifecycle_status") == "ACTIVE"
    )
    return {
        "id": rt["id"],
        "code": rt["code"],
        "name": rt["name"],
        "base_rate_cents": rt["base_rate_cents"],
        "max_occupancy": rt["max_occupancy"],
        "total_physical_rooms": total_physical,
        "status": rt["status"],
        "created_at": rt["created_at"],
        "updated_at": rt["updated_at"],
        "version": rt["version"],
    }


def project_room(r: dict) -> dict:
    return {
        "id": r["id"],
        "room_number": r["room_number"],
        "room_type_id": r["room_type_id"],
        "housekeeping_status": r["housekeeping_status"],
        "operational_status": r["operational_status"],
        "lifecycle_status": r["lifecycle_status"],
        "current_reservation_id": r.get("current_reservation_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def project_maintenance_block(b: dict) -> dict:
    return {
        "id": b["id"],
        "room_id": b["room_id"],
        "start_date": b["start_date"],
        "end_date": b["end_date"],
        "reason": b["reason"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def project_channel(c: dict) -> dict:
    return {
        "id": c["id"],
        "code": c["code"],
        "channel_type": c["channel_type"],
        "commission_basis_points": c["commission_basis_points"],
        "priority_rank": c["priority_rank"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def project_rate_plan(rp: dict) -> dict:
    return {
        "id": rp["id"],
        "code": rp["code"],
        "room_type_id": rp["room_type_id"],
        "refund_tier_code": rp["refund_tier_code"],
        "modification_allowed": rp["modification_allowed"],
        "status": rp["status"],
        "created_at": rp["created_at"],
        "updated_at": rp["updated_at"],
        "version": rp["version"],
    }


def project_mapping(m: dict) -> dict:
    return {
        "id": m["id"],
        "channel_id": m["channel_id"],
        "rate_plan_id": m["rate_plan_id"],
        "inventory_share_basis_points": m["inventory_share_basis_points"],
        "enabled": m["enabled"],
        "created_at": m["created_at"],
    }


def project_rate_override(o: dict) -> dict:
    return {
        "id": o["id"],
        "room_type_id": o["room_type_id"],
        "stay_date": o["stay_date"],
        "proposed_rate_cents": o["proposed_rate_cents"],
        "recommendation_source": o["recommendation_source"],
        "status": o["status"],
        "approved_by": o.get("approved_by"),
        "applied_rate_cents": o.get("applied_rate_cents"),
        "submitted_by": o.get("submitted_by"),
        "created_by": o.get("created_by"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def project_overbooking_policy(p: dict) -> dict:
    return {
        "id": p["id"],
        "room_type_id": p["room_type_id"],
        "stay_date": p["stay_date"],
        "overbook_ratio_basis_points": p["overbook_ratio_basis_points"],
        "estimated_no_show_probability_basis_points": p["estimated_no_show_probability_basis_points"],
        "walkout_compensation_cents": p["walkout_compensation_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def project_reservation(r: dict) -> dict:
    return {
        "id": r["id"],
        "guest_name": r["guest_name"],
        "room_type_id": r["room_type_id"],
        "rate_plan_id": r["rate_plan_id"],
        "channel_id": r["channel_id"],
        "assigned_room_id": r.get("assigned_room_id"),
        "check_in_date": r["check_in_date"],
        "check_out_date": r["check_out_date"],
        "nights": r["nights"],
        "booking_status": r["booking_status"],
        "payment_status": r["payment_status"],
        "booked_total_cents": r["booked_total_cents"],
        "refund_amount_cents": r["refund_amount_cents"],
        "no_show_charge_cents": r["no_show_charge_cents"],
        "walkout_compensation_cents": r["walkout_compensation_cents"],
        "cancelled_at": r.get("cancelled_at"),
        "dispute_status": r["dispute_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def project_audit_log(a: dict) -> dict:
    return {
        "id": a["id"],
        "event_type": a["event_type"],
        "actor_role": a["actor_role"],
        "actor_id": a["actor_id"],
        "subject_entity": a["subject_entity"],
        "subject_id": a["subject_id"],
        "payload": a["payload"],
        "occurred_at": a["occurred_at"],
        "created_at": a["created_at"],
    }
