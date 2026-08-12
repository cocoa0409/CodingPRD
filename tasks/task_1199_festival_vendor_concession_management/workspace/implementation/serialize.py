"""Entity serializers — every field from the scaffold entity table.

Internal bookkeeping keys are prefixed with '_' and never serialized.
Datetime fields are stored as datetime objects and rendered here.
"""
from calc import zone_reserved, slot_reserved
from util import fmt_dt, fmt_ts


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def serialize_festival(f):
    out = _common(f)
    out.update({
        "name": f["name"],
        "event_start": fmt_dt(f["event_start"]),
        "event_end": fmt_dt(f["event_end"]),
        "category_cap_per_category": f["category_cap_per_category"],
        "status": f["status"],
    })
    return out


def serialize_vendor(v):
    out = _common(v)
    out.update({
        "legal_name": v["legal_name"],
        "contact_email": v["contact_email"],
        "status": v["status"],
        "compliance_strikes": v["compliance_strikes"],
    })
    return out


def serialize_application(a):
    out = _common(a)
    out.update({
        "vendor_id": a["vendor_id"],
        "festival_id": a["festival_id"],
        "category": a["category"],
        "fee_model": a["fee_model"],
        "proposed_flat_fee_cents": a["proposed_flat_fee_cents"],
        "proposed_revenue_share_pct_bp": a["proposed_revenue_share_pct_bp"],
        "power_needed_amps": a["power_needed_amps"],
        "requires_water": a["requires_water"],
        "supersedes_application_id": a["supersedes_application_id"],
        "review_round": a["review_round"],
        "curated_fee_model": a["curated_fee_model"],
        "curated_flat_fee_cents": a["curated_flat_fee_cents"],
        "curated_revenue_share_pct_bp": a["curated_revenue_share_pct_bp"],
        "curated_tier_mode": a["curated_tier_mode"],
        "curated_minimum_guarantee_cents": a["curated_minimum_guarantee_cents"],
        "curated_free_allowance_cents": a["curated_free_allowance_cents"],
        "status": a["status"],
    })
    return out


def serialize_zone(z):
    power, water = zone_reserved(z["id"])
    out = _common(z)
    out.update({
        "festival_id": z["festival_id"],
        "name": z["name"],
        "power_capacity_amps": z["power_capacity_amps"],
        "water_hookup_total": z["water_hookup_total"],
        "reserved_power_amps": power,
        "reserved_water_hookups": water,
    })
    return out


def serialize_booth(b):
    out = _common(b)
    out.update({
        "zone_id": b["zone_id"],
        "label": b["label"],
        "power_outlet_max_amps": b["power_outlet_max_amps"],
        "has_water_hookup": b["has_water_hookup"],
        "status": b["status"],
    })
    return out


def serialize_assignment(a):
    out = _common(a)
    out.update({
        "application_id": a["application_id"],
        "booth_id": a["booth_id"],
        "festival_id": a["festival_id"],
        "zone_id": a["zone_id"],
        "status": a["status"],
        "utility_status": a["utility_status"],
        "power_draw_amps": a["power_draw_amps"],
        "requires_water": a["requires_water"],
        "fee_model": a["fee_model"],
        "flat_fee_cents": a["flat_fee_cents"],
        "revenue_share_pct_bp": a["revenue_share_pct_bp"],
        "tier_mode": a["tier_mode"],
        "minimum_guarantee_cents": a["minimum_guarantee_cents"],
        "free_allowance_cents": a["free_allowance_cents"],
    })
    return out


def serialize_inspection(rec):
    # Immutable event: id + created_at only; no updated_at / version.
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "assignment_id": rec["assignment_id"],
        "festival_id": rec["festival_id"],
        "type": rec["type"],
        "result": rec["result"],
        "notes": rec["notes"],
        "status": rec["status"],
    }


def serialize_slot(s):
    out = _common(s)
    out.update({
        "festival_id": s["festival_id"],
        "gate": s["gate"],
        "window_start": fmt_dt(s["window_start"]),
        "window_end": fmt_dt(s["window_end"]),
        "max_vehicles": s["max_vehicles"],
        "reserved_vehicle_count": slot_reserved(s["id"]),
    })
    return out


def serialize_reservation(r):
    out = _common(r)
    out.update({
        "assignment_id": r["assignment_id"],
        "slot_id": r["slot_id"],
        "festival_id": r["festival_id"],
        "vehicle_count": r["vehicle_count"],
        "status": r["status"],
        "checked_in_at": fmt_dt(r["checked_in_at"]) if r["checked_in_at"] else None,
    })
    return out


def serialize_transaction(t):
    out = _common(t)
    out.update({
        "assignment_id": t["assignment_id"],
        "festival_id": t["festival_id"],
        "amount_cents": t["amount_cents"],
        "occurred_at": fmt_dt(t["occurred_at"]),
        "idempotency_key": t["idempotency_key"],
        "status": t["status"],
    })
    return out


def serialize_settlement(s):
    out = _common(s)
    out.update({
        "assignment_id": s["assignment_id"],
        "festival_id": s["festival_id"],
        "status": s["status"],
        "provisional_gross_cents": s["provisional_gross_cents"],
        "provisional_share_cents": s["provisional_share_cents"],
        "provisional_payout_cents": s["provisional_payout_cents"],
        "gross_sales_cents": s["gross_sales_cents"],
        "festival_share_cents": s["festival_share_cents"],
        "fine_deduction_cents": s["fine_deduction_cents"],
        "vendor_payout_cents": s["vendor_payout_cents"],
        "vendor_balance_due_cents": s["vendor_balance_due_cents"],
        "reconciled_by_user_id": s["reconciled_by_user_id"],
        "finalized_by_user_id": s["finalized_by_user_id"],
        "dispute_reason": s["dispute_reason"],
    })
    return out


def serialize_fine(f):
    out = _common(f)
    out.update({
        "assignment_id": f["assignment_id"],
        "festival_id": f["festival_id"],
        "type": f["type"],
        "amount_cents": f["amount_cents"],
        "description": f["description"],
        "status": f["status"],
        "created_by_user_id": f["created_by_user_id"],
        "waived_by_user_id": f["waived_by_user_id"],
    })
    return out


def serialize_review(r):
    out = _common(r)
    out.update({
        "assignment_id": r["assignment_id"],
        "festival_id": r["festival_id"],
        "vendor_id": r["vendor_id"],
        "status": r["status"],
        "sales_percentile": r["sales_percentile"],
        "compliance_component": r["compliance_component"],
        "operations_component": r["operations_component"],
        "official_score": r["official_score"],
        "strict_score": r["strict_score"],
    })
    return out
