"""Translate internal dicts into API response dicts.

Internal records carry extra bookkeeping (e.g. rider offer/delivery history)
that must not leak into responses. These serializers strip that bookkeeping
and ensure field ordering matches the PRD where it matters.
"""
from __future__ import annotations


def restaurant_out(r: dict) -> dict:
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


def menu_item_out(m: dict) -> dict:
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


def rider_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "phone": r["phone"],
        "status": r["status"],
        "on_time_rate": r["on_time_rate"],
        "acceptance_rate": r["acceptance_rate"],
        "rating": r["rating"],
        "wallet_balance_cents": r["wallet_balance_cents"],
        "bonus_tier": r["bonus_tier"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def customer_out(c: dict) -> dict:
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


def order_out(o: dict) -> dict:
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "restaurant_id": o["restaurant_id"],
        "items": [dict(i) for i in o["items"]],
        "subtotal_cents": o["subtotal_cents"],
        "distance_km": o["distance_km"],
        "is_peak": o["is_peak"],
        "status": o["status"],
        "payment_status": o["payment_status"],
        "promised_delivery_time": o["promised_delivery_time"],
        "actual_delivery_time": o["actual_delivery_time"],
        "minutes_late": o["minutes_late"],
        "provisional_delivery_fee_cents": o["provisional_delivery_fee_cents"],
        "final_delivery_fee_cents": o["final_delivery_fee_cents"],
        "provisional_commission_cents": o["provisional_commission_cents"],
        "final_commission_cents": o["final_commission_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def assignment_out(a: dict) -> dict:
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "rider_id": a["rider_id"],
        "status": a["status"],
        "offered_at": a.get("offered_at"),
        "accepted_at": a.get("accepted_at"),
        "picked_up_at": a.get("picked_up_at"),
        "delivered_at": a.get("delivered_at"),
        "route_group_id": a.get("route_group_id"),
        "final_delivery_fee_cents": a.get("final_delivery_fee_cents"),
        "created_at": a["created_at"],
    }


def route_group_out(g: dict) -> dict:
    return {
        "id": g["id"],
        "rider_id": g["rider_id"],
        "assignment_ids": list(g["assignment_ids"]),
        "merged_at": g["merged_at"],
        "status": g["status"],
        "created_at": g["created_at"],
    }


def return_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "reason": r["reason"],
        "requested_refund_cents": r["requested_refund_cents"],
        "approved_refund_cents": r.get("approved_refund_cents"),
        "status": r["status"],
        "reviewer_cs_user_id": r.get("reviewer_cs_user_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def work_order_out(w: dict) -> dict:
    return {
        "id": w["id"],
        "opened_by_role": w["opened_by_role"],
        "opened_by_id": w["opened_by_id"],
        "category": w["category"],
        "related_order_id": w.get("related_order_id"),
        "related_return_id": w.get("related_return_id"),
        "status": w["status"],
        "resolution_notes": w.get("resolution_notes"),
        "assigned_cs_user_id": w.get("assigned_cs_user_id"),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def fine_out(f: dict) -> dict:
    return {
        "id": f["id"],
        "subject_type": f["subject_type"],
        "subject_id": f["subject_id"],
        "reason": f["reason"],
        "amount_cents": f["amount_cents"],
        "settlement_status": f["settlement_status"],
        "order_id": f.get("order_id"),
        "created_at": f["created_at"],
    }
