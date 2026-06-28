"""Serialization of internal records into API output objects.

Internal records carry private bookkeeping fields prefixed with '_' (e.g. _seq)
that must never leak into responses. Each serializer projects the exact field
set the PRD declares for that entity.
"""


def _clean(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def member_out(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "date_of_birth": m["date_of_birth"],
        "membership_tier": m["membership_tier"],
        "membership_expires_at": m["membership_expires_at"],
        "waiver_status": m["waiver_status"],
        "waiver_signed_at": m["waiver_signed_at"],
        "training_level": m["training_level"],
        "deposit_hold_cents": m["deposit_hold_cents"],
        "lifetime_damage_strikes": m["lifetime_damage_strikes"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def guide_out(g):
    return {
        "id": g["id"],
        "full_name": g["full_name"],
        "max_class": g["max_class"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def trail_out(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "required_class": t["required_class"],
        "max_riders": t["max_riders"],
        "condition": t["condition"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def unit_out(u):
    return {
        "id": u["id"],
        "vin_tag": u["vin_tag"],
        "unit_class": u["unit_class"],
        "daily_rate_cents": u["daily_rate_cents"],
        "deposit_cents": u["deposit_cents"],
        "tank_capacity_liters": u["tank_capacity_liters"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def gear_out(g):
    return {
        "id": g["id"],
        "kind": g["kind"],
        "size_code": g["size_code"],
        "replacement_cost_cents": g["replacement_cost_cents"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def departure_out(d):
    return {
        "id": d["id"],
        "trail_id": d["trail_id"],
        "starts_at": d["starts_at"],
        "ends_at": d["ends_at"],
        "required_guide_class": d["required_guide_class"],
        "capacity_riders": d["capacity_riders"],
        "rider_count": d["rider_count"],
        "guide_count": d["guide_count"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def guide_assignment_out(a):
    # Lightweight audit record: id + created_at only (PRD §2.4). Domain FKs and
    # the active flag are part of its data payload.
    return {
        "id": a["id"],
        "tour_departure_id": a["tour_departure_id"],
        "guide_id": a["guide_id"],
        "active": a["active"],
        "created_at": a["created_at"],
    }


def reservation_out(r):
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "tour_departure_id": r["tour_departure_id"],
        "unit_id": r["unit_id"],
        "helmet_gear_id": r["helmet_gear_id"],
        "suit_gear_id": r["suit_gear_id"],
        "reservation_status": r["reservation_status"],
        "settlement_status": r["settlement_status"],
        "estimated_total_cents": r["estimated_total_cents"],
        "deposit_hold_cents": r["deposit_hold_cents"],
        "checked_out_at": r["checked_out_at"],
        "returned_at": r["returned_at"],
        "fuel_return_fraction": r["fuel_return_fraction"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def settlement_out(s):
    return {
        "id": s["id"],
        "reservation_id": s["reservation_id"],
        "rental_charge_cents": s["rental_charge_cents"],
        "fuel_charge_cents": s["fuel_charge_cents"],
        "late_charge_cents": s["late_charge_cents"],
        "damage_assessed_cents": s["damage_assessed_cents"],
        "gear_loss_cents": s["gear_loss_cents"],
        "deposit_applied_cents": s["deposit_applied_cents"],
        "refund_cents": s["refund_cents"],
        "net_charge_cents": s["net_charge_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def closure_event_out(c):
    # Lightweight audit record: id + created_at only (PRD §2.4).
    return {
        "id": c["id"],
        "trail_id": c["trail_id"],
        "new_condition": c["new_condition"],
        "reason": c["reason"],
        "cancelled_departure_count": c["cancelled_departure_count"],
        "created_at": c["created_at"],
    }
