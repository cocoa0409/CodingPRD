from common import fmt_ts, money_str
from db import db


def _common(entity: dict) -> dict:
    return {
        "id": entity["id"],
        "created_at": fmt_ts(entity["created_at"]),
        "updated_at": fmt_ts(entity["updated_at"]),
        "version": entity["version"],
    }


def serialize_slot(slot: dict) -> dict:
    return {
        **_common(slot),
        "cabinet_id": slot["cabinet_id"],
        "slot_index": slot["slot_index"],
        "device_id": slot.get("device_id"),
        "slot_status": slot["slot_status"],
    }


def serialize_cabinet(cab: dict, *, embed_slots: bool = True) -> dict:
    out = {
        **_common(cab),
        "cabinet_code": cab["cabinet_code"],
        "city_code": cab["city_code"],
        "location_partner_id": cab["location_partner_id"],
        "model": cab["model"],
        "total_slots": cab["total_slots"],
        "firmware_version": cab["firmware_version"],
        "online_status": cab["online_status"],
        "last_heartbeat_at": fmt_ts(cab["last_heartbeat_at"]),
    }
    if embed_slots:
        slots = [s for s in db.slots.values() if s["cabinet_id"] == cab["id"]]
        slots.sort(key=lambda s: s["slot_index"])
        out["slots"] = [serialize_slot(s) for s in slots]
    return out


def serialize_device(d: dict) -> dict:
    return {
        **_common(d),
        "device_code": d["device_code"],
        "model": d["model"],
        "battery_level": d["battery_level"],
        "status": d["status"],
        "current_cabinet_id": d.get("current_cabinet_id"),
        "current_slot_index": d.get("current_slot_index"),
    }


def serialize_pricing_plan(p: dict) -> dict:
    return {
        **_common(p),
        "city_code": p["city_code"],
        "hourly_rate": money_str(p["hourly_rate"]),
        "daily_cap": money_str(p["daily_cap"]),
        "free_minutes": p["free_minutes"],
        "cross_city_surcharge": money_str(p["cross_city_surcharge"]),
    }


def serialize_user(u: dict) -> dict:
    return {
        **_common(u),
        "phone": u["phone"],
        "wallet_balance": money_str(u["wallet_balance"]),
        "deposit_balance": money_str(u["deposit_balance"]),
        "refund_count_30d": u["refund_count_30d"],
        "borrow_count_24h": u["borrow_count_24h"],
    }


def serialize_rental(r: dict) -> dict:
    return {
        **_common(r),
        "user_id": r["user_id"],
        "start_cabinet_id": r["start_cabinet_id"],
        "start_slot_index": r["start_slot_index"],
        "device_id": r["device_id"],
        "rented_at": fmt_ts(r["rented_at"]),
        "return_cabinet_id": r.get("return_cabinet_id"),
        "return_slot_index": r.get("return_slot_index"),
        "returned_at": fmt_ts(r["returned_at"]) if r.get("returned_at") else None,
        "rental_status": r["rental_status"],
        "payment_status": r["payment_status"],
        "charged_amount": money_str(r["charged_amount"]) if r.get("charged_amount") is not None else None,
        "refund_amount": money_str(r["refund_amount"]) if r.get("refund_amount") is not None else None,
    }


def serialize_repair_ticket(t: dict) -> dict:
    return {
        **_common(t),
        "target_type": t["target_type"],
        "target_id": t["target_id"],
        "source": t["source"],
        "issue_code": t["issue_code"],
        "status": t["status"],
        "assigned_operator_id": t.get("assigned_operator_id"),
    }


def serialize_operator_task(t: dict) -> dict:
    return {
        **_common(t),
        "cabinet_id": t["cabinet_id"],
        "task_type": t["task_type"],
        "priority_score": t["priority_score"],
        "status": t["status"],
        "assigned_operator_id": t.get("assigned_operator_id"),
        "linked_repair_ticket_id": t.get("linked_repair_ticket_id"),
    }


def serialize_location_partner(p: dict) -> dict:
    return {
        **_common(p),
        "partner_code": p["partner_code"],
        "name": p["name"],
        "revenue_share_pct": float(p["revenue_share_pct"]),
    }


def serialize_settlement(s: dict) -> dict:
    return {
        **_common(s),
        "location_partner_id": s["location_partner_id"],
        "period_start": fmt_ts(s["period_start"]),
        "period_end": fmt_ts(s["period_end"]),
        "gross_revenue": money_str(s["gross_revenue"]),
        "partner_amount": money_str(s["partner_amount"]),
        "refund_adjustment": money_str(s["refund_adjustment"]),
        "status": s["status"],
        "invoice_number": s.get("invoice_number"),
    }


def serialize_payment_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "idempotency_key": e["idempotency_key"],
        "event_type": e["event_type"],
        "rental_id": e["rental_id"],
        "amount": money_str(e["amount"]),
        "occurred_at": fmt_ts(e["occurred_at"]),
    }


def serialize_maintenance_window(w: dict) -> dict:
    return {
        **_common(w),
        "cabinet_id": w["cabinet_id"],
        "window_start": fmt_ts(w["window_start"]),
        "window_end": fmt_ts(w["window_end"]),
        "status": w["status"],
    }
