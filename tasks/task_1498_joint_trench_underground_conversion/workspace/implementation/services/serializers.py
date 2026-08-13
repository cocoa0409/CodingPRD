"""Entity serializers: stored fields + derived-at-read fields, per the
SCAFFOLD entity table. Internal helper keys (prefixed ``_``) never leak."""

from __future__ import annotations

from services import domain


def project_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "rule20_credit_cents": p["rule20_credit_cents"],
        "estimated_total_cost_cents": p["estimated_total_cost_cents"],
        "contingency_days": p["contingency_days"],
        "target_cutover_on": p["target_cutover_on"],
        "status": p["status"],
        "posture": domain.compute_posture(p),
        "cumulative_delay_days": domain.compute_cumulative_delay_days(p),
        "liquidated_damages_cents": domain.compute_liquidated_damages(p),
        "latest_true_up_run_id": p.get("latest_true_up_run_id"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def participation_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "project_id": p["project_id"],
        "utility_name": p["utility_name"],
        "utility_type": p["utility_type"],
        "cost_share_bp": p["cost_share_bp"],
        "sequence_order": p["sequence_order"],
        "has_separation_waiver": p["has_separation_waiver"],
        "status": p["status"],
        "provisional_share_cents": p["provisional_share_cents"],
        "final_share_cents": p.get("final_share_cents"),
        "variance_flag": p["variance_flag"],
        "withdrawn_on": p.get("withdrawn_on"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def segment_view(s: dict) -> dict:
    occupied = domain.occupied_depth(s)
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "segment_code": s["segment_code"],
        "length_ft": s["length_ft"],
        "max_depth_inches": s["max_depth_inches"],
        "parcel_ids": list(s.get("parcel_ids") or []),
        "excavation_start_on": s.get("excavation_start_on"),
        "excavation_end_on": s.get("excavation_end_on"),
        "status": s["status"],
        "occupied_depth_inches": occupied,
        "available_depth_inches": s["max_depth_inches"] - occupied,
        "frozen": domain.is_segment_frozen(s),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def slot_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "trench_segment_id": s["trench_segment_id"],
        "participation_id": s["participation_id"],
        "depth_top_inches": s["depth_top_inches"],
        "depth_bottom_inches": s["depth_bottom_inches"],
        "install_start_at": s["install_start_at"],
        "install_end_at": s["install_end_at"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def parcel_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "project_id": p["project_id"],
        "address": p["address"],
        "owner_name": p["owner_name"],
        "existing_panel_amps": p["existing_panel_amps"],
        "load_calc_amps": p["load_calc_amps"],
        # >= is deliberate: exactly 80% requires the upgrade
        "panel_upgrade_required": (p["load_calc_amps"] * 5 >= p["existing_panel_amps"] * 4),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def easement_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "parcel_id": e["parcel_id"],
        "easement_type": e["easement_type"],
        "status": e["status"],
        "requested_on": e.get("requested_on"),
        "signed_on": e.get("signed_on"),
        "recorded_on": e.get("recorded_on"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def permit_view(p: dict) -> dict:
    domain.refresh_permit(p)  # lazy ISSUED -> EXPIRED at read
    return {
        "id": p["id"],
        "project_id": p["project_id"],
        "permit_type": p["permit_type"],
        "valid_from": p["valid_from"],
        "valid_to": p["valid_to"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def conversion_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "parcel_id": c["parcel_id"],
        "project_id": c["project_id"],
        "work_status": c["work_status"],
        "temp_service_status": c["temp_service_status"],
        "panel_capacity_amps": c.get("panel_capacity_amps"),
        "last_inspection_outcome": c.get("last_inspection_outcome"),
        "energized_on": c.get("energized_on"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def outage_view(o: dict) -> dict:
    return {
        "id": o["id"],
        "project_id": o["project_id"],
        "feeder_id": o["feeder_id"],
        "start_at": o["start_at"],
        "end_at": o["end_at"],
        "conversion_ids": list(o.get("conversion_ids") or []),
        "status": o["status"],
        "notified_at": o.get("notified_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def change_order_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "project_id": c["project_id"],
        "description": c["description"],
        "segment_ids": list(c.get("segment_ids") or []),
        "delta_cost_cents": c.get("delta_cost_cents"),
        "delta_delay_days": c.get("delta_delay_days"),
        "delay_cause": c.get("delay_cause"),
        "status": c["status"],
        "revision_count": c["revision_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def cost_entry_view(e: dict) -> dict:
    # Append-only entity: id + created_at only, no updated_at / version.
    return {
        "id": e["id"],
        "project_id": e["project_id"],
        "participation_id": e.get("participation_id"),
        "cost_code": e["cost_code"],
        "amount_cents": e["amount_cents"],
        "incurred_on": e["incurred_on"],
        "submitted_by_user_id": e["submitted_by_user_id"],
        "created_at": e["created_at"],
    }


def trueup_run_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "status": r["status"],
        "created_by_user_id": r["created_by_user_id"],
        "published_by_user_id": r.get("published_by_user_id"),
        "total_actual_cost_cents": r["total_actual_cost_cents"],
        "rule20_credit_applied_cents": r["rule20_credit_applied_cents"],
        "lines": r["lines"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def invoice_view(i: dict) -> dict:
    fee = domain.invoice_late_fee(i)
    return {
        "id": i["id"],
        "true_up_run_id": i["true_up_run_id"],
        "participation_id": i["participation_id"],
        "principal_cents": i["principal_cents"],
        "issued_on": i["issued_on"],
        "due_on": i["due_on"],
        "status": i["status"],
        "late_fee_cents": fee,
        "amount_due_cents": i["principal_cents"] + fee,
        "paid_on": i.get("paid_on"),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def restoration_task_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "trench_segment_id": t["trench_segment_id"],
        "parcel_id": t["parcel_id"],
        "task_type": t["task_type"],
        "status": t["status"],
        "completed_on": t.get("completed_on"),
        "accepted_on": t.get("accepted_on"),
        "warranty_expires_on": t.get("warranty_expires_on"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }
