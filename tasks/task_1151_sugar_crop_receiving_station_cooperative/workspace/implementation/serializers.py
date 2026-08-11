"""Entity serializers — convert internal dicts to API representations.

Numeric convention: values stored as Decimal/int internally are converted to
JSON-safe types. Numbers that are conceptually decimal (tonnages, percents,
factors, prices-per-lb, pounds) serialize as JSON numbers (floats), integers
stay ints, datetimes serialize as ISO 8601 UTC strings with 3 fractional
digits.
"""
from decimal import Decimal

import db


def _num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def _int(v):
    if v is None:
        return None
    return int(v)


def _dt(v):
    return db.format_iso(v) if v is not None else None


def campaign(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "window_start": _dt(c["window_start"]),
        "window_end": _dt(c["window_end"]),
        "base_price_cents_per_ton": _int(c["base_price_cents_per_ton"]),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def member(m):
    return {
        "id": m["id"],
        "name": m["name"],
        "member_code": m["member_code"],
        "haul_distance_miles": _num(m["haul_distance_miles"]),
        "status": m["status"],
        "net_ledger_cents": _int(m["net_ledger_cents"]),
        "deterioration_loss_lbs": _num(m["deterioration_loss_lbs"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def station(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "booking_capacity_tons": _num(s["booking_capacity_tons"]),
        "booked_tons": _num(s["booked_tons"]),
        "received_tons": _num(s["received_tons"]),
        "stored_tons": _num(s["stored_tons"]),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def pile(p):
    return {
        "id": p["id"],
        "station_id": p["station_id"],
        "capacity_tons": _num(p["capacity_tons"]),
        "fill_status": p["fill_status"],
        "condition_status": p["condition_status"],
        "stored_lbs": _num(p["stored_lbs"]),
        "sealed_stored_lbs": _num(p["sealed_stored_lbs"]),
        "sealed_at": _dt(p["sealed_at"]),
        "reclaim_started_at": _dt(p["reclaim_started_at"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def booking(b):
    return {
        "id": b["id"],
        "member_id": b["member_id"],
        "station_id": b["station_id"],
        "campaign_id": b["campaign_id"],
        "slot_start": _dt(b["slot_start"]),
        "slot_end": _dt(b["slot_end"]),
        "estimated_tons": _num(b["estimated_tons"]),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ticket(t):
    return {
        "id": t["id"],
        "booking_id": t["booking_id"],
        "member_id": t["member_id"],
        "station_id": t["station_id"],
        "gross_weight_lbs": _num(t["gross_weight_lbs"]),
        "tare_weight_lbs": _num(t["tare_weight_lbs"]),
        "net_weight_lbs": _num(t["net_weight_lbs"]),
        "status": t["status"],
        "provisional_trash_pct": _num(t["provisional_trash_pct"]),
        "provisional_sugar_pct": _num(t["provisional_sugar_pct"]),
        "provisional_factor": _num(t["provisional_factor"]),
        "provisional_adjusted_net_tons": _num(t["provisional_adjusted_net_tons"]),
        "provisional_value_cents": _int(t["provisional_value_cents"]),
        "final_trash_pct": _num(t["final_trash_pct"]),
        "final_sugar_pct": _num(t["final_sugar_pct"]),
        "final_factor": _num(t["final_factor"]),
        "adjusted_net_tons_final": _num(t["adjusted_net_tons_final"]),
        "adjusted_net_lbs_final": _num(t["adjusted_net_lbs_final"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def sample(s):
    return {
        "id": s["id"],
        "ticket_id": s["ticket_id"],
        "sample_type": s["sample_type"],
        "sugar_pct": _num(s["sugar_pct"]),
        "trash_pct": _num(s["trash_pct"]),
        "recorded_by_user_id": s["recorded_by_user_id"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def pile_allocation(a):
    return {
        "id": a["id"],
        "ticket_id": a["ticket_id"],
        "pile_id": a["pile_id"],
        "member_id": a["member_id"],
        "allocated_lbs": _num(a["allocated_lbs"]),
        "remaining_lbs": _num(a["remaining_lbs"]),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def loss_event(e):
    return {
        "id": e["id"],
        "pile_id": e["pile_id"],
        "method": e["method"],
        "survey_at": _dt(e["survey_at"]),
        "window_start": _dt(e["window_start"]),
        "window_end": _dt(e["window_end"]),
        "measured_remaining_lbs": _num(e["measured_remaining_lbs"]),
        "loss_lbs": _num(e["loss_lbs"]),
        "unallocated_lbs": _num(e["unallocated_lbs"]),
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def pool(p):
    return {
        "id": p["id"],
        "campaign_id": p["campaign_id"],
        "status": p["status"],
        "estimated_pool_value_cents": _int(p["estimated_pool_value_cents"]),
        "gross_pool_value_cents": _int(p["gross_pool_value_cents"]),
        "accrued_provisional_cents": _int(p["accrued_provisional_cents"]),
        "final_price_cents_per_lb": _num(p["final_price_cents_per_lb"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def installment(i):
    return {
        "id": i["id"],
        "pool_id": i["pool_id"],
        "pct_of_estimated": _num(i["pct_of_estimated"]),
        "target_amount_cents": _int(i["target_amount_cents"]),
        "distributed_amount_cents": _int(i["distributed_amount_cents"]),
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ledger_entry(e):
    # Append-only: id + created_at only; no updated_at / version
    return {
        "id": e["id"],
        "member_id": e["member_id"],
        "pool_id": e["pool_id"],
        "installment_id": e["installment_id"],
        "settlement_id": e["settlement_id"],
        "kind": e["kind"],
        "amount_cents": _int(e["amount_cents"]),
        "reversal_of_id": e["reversal_of_id"],
        "created_at": e["created_at"],
    }


def settlement(s):
    return {
        "id": s["id"],
        "member_id": s["member_id"],
        "campaign_id": s["campaign_id"],
        "pool_id": s["pool_id"],
        "sugar_lbs": _num(s["sugar_lbs"]),
        "price_cents_per_lb": _num(s["price_cents_per_lb"]),
        "gross_entitlement_cents": _int(s["gross_entitlement_cents"]),
        "advances_posted_cents": _int(s["advances_posted_cents"]),
        "transport_credit_cents": _int(s["transport_credit_cents"]),
        "final_payment_cents": _int(s["final_payment_cents"]),
        "total_payment_cents": _int(s["total_payment_cents"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
