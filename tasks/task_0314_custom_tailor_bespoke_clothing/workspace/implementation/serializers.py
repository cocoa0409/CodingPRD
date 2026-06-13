"""Serialize internal entity dicts into their public JSON shape.

Each serializer lists exactly the fields the PRD/scaffold declares for that
entity, so internal bookkeeping fields never leak into responses.
"""


def customer(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "full_name": c["full_name"],
        "email": c["email"],
        "store_credit_cents": c["store_credit_cents"],
        "remake_count": c["remake_count"],
        "completed_order_count": c["completed_order_count"],
        "remake_risk_band": c["remake_risk_band"],
    }


def measurement_profile(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "customer_id": p["customer_id"],
        "chest_cm": p["chest_cm"],
        "waist_cm": p["waist_cm"],
        "hip_cm": p["hip_cm"],
        "inseam_cm": p["inseam_cm"],
        "source": p["source"],
        "body_scan_ref": p["body_scan_ref"],
        "status": p["status"],
    }


def fabric(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "name": f["name"],
        "price_per_meter_cents": f["price_per_meter_cents"],
        "bolt_meters_remaining": f["bolt_meters_remaining"],
        "status": f["status"],
    }


def tailor(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "display_name": t["display_name"],
        "skill_tier": t["skill_tier"],
        "status": t["status"],
    }


def fitting_room(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "room_name": r["room_name"],
        "cleanup_buffer_minutes": r["cleanup_buffer_minutes"],
        "status": r["status"],
    }


def garment_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "customer_id": o["customer_id"],
        "measurement_profile_id": o["measurement_profile_id"],
        "group_order_id": o["group_order_id"],
        "garment_type": o["garment_type"],
        "base_labor_cents": o["base_labor_cents"],
        "is_rush": o["is_rush"],
        "promised_date": o["promised_date"],
        "fabric_meters_required": o["fabric_meters_required"],
        "quoted_total_cents": o["quoted_total_cents"],
        "locked_total_cents": o["locked_total_cents"],
        "deposit_due_cents": o["deposit_due_cents"],
        "amount_paid_cents": o["amount_paid_cents"],
        "balance_due_cents": o["balance_due_cents"],
        "store_credit_applied_cents": o["store_credit_applied_cents"],
        "remake_round": o["remake_round"],
        "status": o["status"],
    }


def option_line(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "order_id": l["order_id"],
        "fabric_id": l["fabric_id"],
        "option_code": l["option_code"],
        "upcharge_cents": l["upcharge_cents"],
        "fabric_price_per_meter_cents": l["fabric_price_per_meter_cents"],
    }


def fitting(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "order_id": f["order_id"],
        "tailor_id": f["tailor_id"],
        "room_id": f["room_id"],
        "milestone": f["milestone"],
        "start_at": f["start_at"],
        "end_at": f["end_at"],
        "outcome": f["outcome"],
    }


def alteration_ticket(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "order_id": t["order_id"],
        "description": t["description"],
        "billable_cents": t["billable_cents"],
        "status": t["status"],
    }


def payment(p):
    # Payment is append-only: id + created_at only, no updated_at / version.
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "order_id": p["order_id"],
        "kind": p["kind"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
    }


def group_order(g):
    return {
        "id": g["id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "event_name": g["event_name"],
        "event_date": g["event_date"],
        "lead_order_id": g["lead_order_id"],
        "member_order_count": g["member_order_count"],
        "group_total_cents": g["group_total_cents"],
        "status": g["status"],
    }


def pickup(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "order_id": p["order_id"],
        "released_to_name": p["released_to_name"],
        "picked_up_at": p["picked_up_at"],
    }
