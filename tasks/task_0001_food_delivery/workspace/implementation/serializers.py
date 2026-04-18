"""Serializers for entities to produce API response bodies."""
from common import format_iso


def serialize_restaurant(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "address": r["address"],
        "lat": r["lat"],
        "lng": r["lng"],
        "status": r["status"],
        "commission_rate_override": r["commission_rate_override"],
        "pending_settlement_cents": r["pending_settlement_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_rider(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "phone": r["phone"],
        "status": r["status"],
        "on_time_rate": r["on_time_rate"],
        "acceptance_rate": r["acceptance_rate"],
        "rating": r["rating"],
        "bonus_tier": r["bonus_tier"],
        "wallet_balance_cents": r["wallet_balance_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_customer(c: dict) -> dict:
    return {
        "id": c["id"],
        "name": c["name"],
        "phone": c["phone"],
        "address": c["address"],
        "lat": c["lat"],
        "lng": c["lng"],
        "credit_balance_cents": c["credit_balance_cents"],
        "trust_score": c["trust_score"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_menu_item(m: dict) -> dict:
    return {
        "id": m["id"],
        "restaurant_id": m["restaurant_id"],
        "name": m["name"],
        "price_cents": m["price_cents"],
        "is_listed": m["is_listed"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_order(o: dict) -> dict:
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "restaurant_id": o["restaurant_id"],
        "status": o["status"],
        "items": o["items"],
        "subtotal_cents": o["subtotal_cents"],
        "distance_km": o["distance_km"],
        "is_peak": o["is_peak"],
        "provisional_delivery_fee_cents": o["provisional_delivery_fee_cents"],
        "final_delivery_fee_cents": o["final_delivery_fee_cents"],
        "provisional_commission_cents": o["provisional_commission_cents"],
        "final_commission_cents": o["final_commission_cents"],
        "promised_delivery_time": o["promised_delivery_time"],
        "actual_delivery_time": o["actual_delivery_time"],
        "minutes_late": o["minutes_late"],
        "payment_status": o["payment_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_assignment(a: dict) -> dict:
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "rider_id": a["rider_id"],
        "status": a["status"],
        "offered_at": a["offered_at"],
        "accepted_at": a["accepted_at"],
        "picked_up_at": a["picked_up_at"],
        "delivered_at": a["delivered_at"],
        "route_group_id": a["route_group_id"],
        "final_delivery_fee_cents": a["final_delivery_fee_cents"],
        "created_at": a["created_at"],
    }


def serialize_route_group(rg: dict) -> dict:
    return {
        "id": rg["id"],
        "rider_id": rg["rider_id"],
        "assignment_ids": rg["assignment_ids"],
        "merged_at": rg["merged_at"],
        "status": rg["status"],
        "created_at": rg["created_at"],
    }


def serialize_fine(f: dict) -> dict:
    return {
        "id": f["id"],
        "subject_type": f["subject_type"],
        "subject_id": f["subject_id"],
        "order_id": f["order_id"],
        "reason": f["reason"],
        "amount_cents": f["amount_cents"],
        "settlement_status": f["settlement_status"],
        "created_at": f["created_at"],
    }


def serialize_return(r: dict) -> dict:
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "reason": r["reason"],
        "requested_refund_cents": r["requested_refund_cents"],
        "status": r["status"],
        "approved_refund_cents": r["approved_refund_cents"],
        "reviewer_cs_user_id": r["reviewer_cs_user_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_work_order(w: dict) -> dict:
    return {
        "id": w["id"],
        "opened_by_role": w["opened_by_role"],
        "opened_by_id": w["opened_by_id"],
        "related_order_id": w["related_order_id"],
        "related_return_id": w["related_return_id"],
        "category": w["category"],
        "status": w["status"],
        "assigned_cs_user_id": w["assigned_cs_user_id"],
        "resolution_notes": w["resolution_notes"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }
