"""Entity serializers — output exactly the fields declared in the scaffold
entity table. RoomingListRevision carries only id/created_at system fields
(PRD 2.4 exception); everything else carries id/created_at/updated_at/version."""
from calc import screening_is_expired
from timeutil import fmt_dt, fmt_temporal, fmt_opt_dt


def _common(e):
    return {
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_building(b):
    out = {
        "id": b["id"],
        "name": b["name"],
        "fall_opening_date": fmt_temporal(b["fall_opening_date"]),
        "key_pool_size": b["key_pool_size"],
        "status": b["status"],
        "released_bed_count": b["released_bed_count"],
        "reserved_bed_count": b["reserved_bed_count"],
        "available_bed_count": b["available_bed_count"],
        "scheduled_turn_count": b["scheduled_turn_count"],
        "out_of_service_room_count": b["out_of_service_room_count"],
        "available_key_count": b["available_key_count"],
    }
    out.update(_common(b))
    return out


def ser_room(r):
    out = {
        "id": r["id"],
        "building_id": r["building_id"],
        "room_number": r["room_number"],
        "bed_count": r["bed_count"],
        "status": r["status"],
        "active_turn_task_id": r["active_turn_task_id"],
        "out_of_service_window_id": r["out_of_service_window_id"],
    }
    out.update(_common(r))
    return out


def ser_group(g):
    out = {
        "id": g["id"],
        "building_id": g["building_id"],
        "client_name": g["client_name"],
        "contact_email": g["contact_email"],
        "arrival_date": fmt_temporal(g["arrival_date"]),
        "departure_date": fmt_temporal(g["departure_date"]),
        "has_minor_participants": g["has_minor_participants"],
        "linen_tier": g["linen_tier"],
        "contracted_bed_count": g["contracted_bed_count"],
        "deposit_paid_cents": g["deposit_paid_cents"],
        "status": g["status"],
        "provisional_invoice_id": g["provisional_invoice_id"],
        "cancellation_fee_cents": g["cancellation_fee_cents"],
    }
    out.update(_common(g))
    return out


def ser_participant(p):
    out = {
        "id": p["id"],
        "group_id": p["group_id"],
        "full_name": p["full_name"],
        "date_of_birth": fmt_temporal(p["date_of_birth"]),
        "role_in_group": p["role_in_group"],
        "is_minor": p["is_minor"],
    }
    out.update(_common(p))
    return out


def ser_revision(r):
    # Revisions are immutable: only id and created_at, no updated_at/version.
    return {
        "id": r["id"],
        "group_id": r["group_id"],
        "revision_number": r["revision_number"],
        "status": r["status"],
        "assignment_ids": list(r["assignment_ids"]),
        "superseded_at": fmt_opt_dt(r["superseded_at"]),
        "created_at": fmt_dt(r["created_at"]),
    }


def ser_assignment(a):
    out = {
        "id": a["id"],
        "revision_id": a["revision_id"],
        "group_id": a["group_id"],
        "room_id": a["room_id"],
        "participant_id": a["participant_id"],
        "checkin_at": fmt_temporal(a["checkin_at"]),
        "checkout_at": fmt_temporal(a["checkout_at"]),
        "actual_checkin_at": fmt_opt_dt(a["actual_checkin_at"]),
        "actual_checkout_at": fmt_opt_dt(a["actual_checkout_at"]),
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def ser_screening(s):
    out = {
        "id": s["id"],
        "participant_id": s["participant_id"],
        "consent_reference": s["consent_reference"],
        "status": s["status"],
        "decided_at": fmt_opt_dt(s["decided_at"]),
        "cleared_on": s["cleared_on"].isoformat() if s["cleared_on"] is not None else None,
        "is_expired": screening_is_expired(s),
        "appeal_reason": s["appeal_reason"],
    }
    out.update(_common(s))
    return out


def ser_turn_task(t):
    out = {
        "id": t["id"],
        "room_id": t["room_id"],
        "window_start": fmt_dt(t["window_start"]),
        "window_end": fmt_dt(t["window_end"]),
        "linen_tier": t["linen_tier"],
        "status": t["status"],
        "rework_count": t["rework_count"],
        "inspector_note": t["inspector_note"],
    }
    out.update(_common(t))
    return out


def ser_linen_issue(i):
    out = {
        "id": i["id"],
        "group_id": i["group_id"],
        "packs_issued": i["packs_issued"],
        "packs_returned": i["packs_returned"],
        "packs_damaged": i["packs_damaged"],
        "status": i["status"],
        "loss_charge_cents": i["loss_charge_cents"],
    }
    out.update(_common(i))
    return out


def ser_key_credential(k):
    out = {
        "id": k["id"],
        "group_id": k["group_id"],
        "participant_id": k["participant_id"],
        "credential_code": k["credential_code"],
        "status": k["status"],
        "returned_at": fmt_opt_dt(k["returned_at"]),
        "late_fee_cents": k["late_fee_cents"],
        "lost_fee_cents": k["lost_fee_cents"],
    }
    out.update(_common(k))
    return out


def ser_damage_assessment(d):
    out = {
        "id": d["id"],
        "room_id": d["room_id"],
        "group_id": d["group_id"],
        "line_items": d["line_items"],
        "estimate_total_cents": d["estimate_total_cents"],
        "assessed_total_cents": d["assessed_total_cents"],
        "assessed_at": fmt_opt_dt(d["assessed_at"]),
        "dispute_reason": d["dispute_reason"],
        "status": d["status"],
    }
    out.update(_common(d))
    return out


def ser_invoice(v):
    out = {
        "id": v["id"],
        "group_id": v["group_id"],
        "status": v["status"],
        "provisional_bed_night_subtotal_cents": v["provisional_bed_night_subtotal_cents"],
        "provisional_total_cents": v["provisional_total_cents"],
        "final_bed_night_subtotal_cents": v["final_bed_night_subtotal_cents"],
        "linen_charge_cents": v["linen_charge_cents"],
        "key_charge_cents": v["key_charge_cents"],
        "damage_charge_cents": v["damage_charge_cents"],
        "total_cents": v["total_cents"],
        "balance_due_cents": v["balance_due_cents"],
        "finalized_at": fmt_opt_dt(v["finalized_at"]),
        "paid_at": fmt_opt_dt(v["paid_at"]),
    }
    out.update(_common(v))
    return out


def ser_maintenance_window(w):
    out = {
        "id": w["id"],
        "building_id": w["building_id"],
        "start_date": fmt_temporal(w["start_date"]),
        "end_date": fmt_temporal(w["end_date"]),
        "buffer_days": w["buffer_days"],
        "blocked_start_date": w["blocked_start_date"].isoformat(),
        "blocked_end_date": w["blocked_end_date"].isoformat(),
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def ser_allocation_run(r):
    out = {
        "id": r["id"],
        "building_id": r["building_id"],
        "period_start": fmt_temporal(r["period_start"]),
        "period_end": fmt_temporal(r["period_end"]),
        "gross_cents": r["gross_cents"],
        "overhead_cents": r["overhead_cents"],
        "reserve_cents": r["reserve_cents"],
        "ops_cents": r["ops_cents"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out
