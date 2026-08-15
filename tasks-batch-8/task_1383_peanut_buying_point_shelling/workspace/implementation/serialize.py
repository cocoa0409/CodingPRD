"""Entity serializers — output exactly the fields declared in the scaffold
entity table. AllocationLine carries only id/created_at system fields
(PRD 2.4 exception); everything else carries id/created_at/updated_at/version.

Tonnages and percentages serialize as JSON numbers via float(); cents are
integers; timestamps are ISO 8601 UTC with three fractional digits.
"""
from decimal import Decimal

import calc
from db import store
from timeutil import fmt_dt


def _num(d):
    """Decimal -> JSON number (float preserves shortest round-trip)."""
    if d is None:
        return None
    return float(d)


def _common(e):
    return {
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_buying_point(bp):
    out = {
        "id": bp["id"],
        "name": bp["name"],
        "crop_year": bp["crop_year"],
        "drying_rate_per_cycle_cents": bp["drying_rate_per_cycle_cents"],
        "quota_price_cents_per_ton": bp["quota_price_cents_per_ton"],
        "additional_price_cents_per_ton": bp["additional_price_cents_per_ton"],
        "loan_rate_quota_cents_per_ton": bp["loan_rate_quota_cents_per_ton"],
        "loan_rate_additional_cents_per_ton": bp["loan_rate_additional_cents_per_ton"],
        "intake_posture": calc.intake_posture(bp["id"]),
        "ops_run_index": bp["ops_run_index"],
    }
    out.update(_common(bp))
    return out


def ser_grower(g):
    out = {
        "id": g["id"],
        "name": g["name"],
        "farm_number": g["farm_number"],
        "status": g["status"],
        "no_show_strikes": g["no_show_strikes"],
    }
    out.update(_common(g))
    return out


def _ser_tier(t):
    return {
        "up_to_pct": _num(t["up_to_pct"]) if t["up_to_pct"] is not None else None,
        "discount_cents_per_ton": t["discount_cents_per_ton"],
    }


def ser_schedule(s):
    out = {
        "id": s["id"],
        "schedule_code": s["schedule_code"],
        "effective_from": fmt_dt(s["effective_from"]),
        "effective_to": fmt_dt(s["effective_to"]),
        "moisture_tiers": [_ser_tier(t) for t in s["moisture_tiers"]],
        "foreign_material_tiers": [_ser_tier(t) for t in s["foreign_material_tiers"]],
        "damage_rate_cents_per_pct": s["damage_rate_cents_per_pct"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_load(l):
    out = {
        "id": l["id"],
        "grower_id": l["grower_id"],
        "crop_year": l["crop_year"],
        "gross_tons": _num(l["gross_tons"]),
        "weighed_at": fmt_dt(l["weighed_at"]),
        "status": l["status"],
        "aflatoxin_status": l["aflatoxin_status"],
        "drying_status": l["drying_status"],
        "payable_tons": _num(l["payable_tons"]),
        "provisional_net_estimate_cents": l["provisional_net_estimate_cents"],
        "settlement_id": l["settlement_id"],
    }
    out.update(_common(l))
    return out


def ser_grade_sheet(s):
    out = {
        "id": s["id"],
        "load_id": s["load_id"],
        "inspector_ref": s["inspector_ref"],
        "schedule_id": s["schedule_id"],
        "moisture_pct": _num(s["moisture_pct"]),
        "foreign_material_pct": _num(s["foreign_material_pct"]),
        "damage_pct": _num(s["damage_pct"]),
        "lsk_pct": _num(s["lsk_pct"]),
        "payable_tons": _num(s["payable_tons"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_certificate(c):
    out = {
        "id": c["id"],
        "load_id": c["load_id"],
        "sample_ref": c["sample_ref"],
        "lab_tech_ref": c["lab_tech_ref"],
        "result_ppb": _num(c["result_ppb"]),
        "result_recorded_by": c["result_recorded_by"],
        "confirmed_by": c["confirmed_by"],
        "determination": c["determination"],
        "retest_count": c["retest_count"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_dryer(d):
    out = {
        "id": d["id"],
        "buying_point_id": d["buying_point_id"],
        "name": d["name"],
        "cycle_capacity_tons": d["cycle_capacity_tons"],
        "cycle_hours": d["cycle_hours"],
    }
    out.update(_common(d))
    return out


def ser_booking(b):
    out = {
        "id": b["id"],
        "dryer_id": b["dryer_id"],
        "load_id": b["load_id"],
        "tons": _num(b["tons"]),
        "starts_at": fmt_dt(b["starts_at"]),
        "ends_at": fmt_dt(b["ends_at"]),
        "moisture_at_booking": _num(b["moisture_at_booking"]),
        "actual_moisture_after": _num(b["actual_moisture_after"]),
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def ser_warehouse(w):
    stored = calc.wh_stored_tons(w["id"])
    reserved = calc.wh_reserved_tons(w["id"])
    out = {
        "id": w["id"],
        "buying_point_id": w["buying_point_id"],
        "name": w["name"],
        "compartment": w["compartment"],
        "capacity_tons": w["capacity_tons"],
        "stored_tons": _num(stored),
        "reserved_tons": _num(reserved),
        "free_tons": _num(Decimal(w["capacity_tons"]) - stored - reserved),
    }
    out.update(_common(w))
    return out


def ser_receipt(r):
    shelled = sum((l["shelled_tons"] for l in store.allocation_lines.values()
                   if l["storage_receipt_id"] == r["id"]), Decimal(0))
    out = {
        "id": r["id"],
        "warehouse_id": r["warehouse_id"],
        "load_id": r["load_id"],
        "segregated": r["segregated"],
        "tons_initial": _num(r["tons_initial"]),
        "tons_remaining": _num(r["tons_remaining"]),
        "shelled_tons": _num(shelled),
        "stored_at": fmt_dt(r["stored_at"]),
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_pledge(p):
    bp = calc.pledge_bp(p)
    standard, conservative = calc.collateral_values(p, bp)
    out = {
        "id": p["id"],
        "grower_id": p["grower_id"],
        "storage_receipt_id": p["storage_receipt_id"],
        "pledged_tons": _num(p["pledged_tons"]),
        "quota_part_tons": _num(p["quota_part_tons"]),
        "additional_part_tons": _num(p["additional_part_tons"]),
        "principal_cents": p["principal_cents"],
        "outstanding_principal_cents": p["outstanding_principal_cents"],
        "accrued_interest_cents": calc.accrued_interest_cents(p, store.clock),
        "pledged_at": fmt_dt(p["pledged_at"]),
        "maturity_date": fmt_dt(p["maturity_date"]),
        "collateral_value_standard_cents": standard,
        "collateral_value_conservative_cents": conservative,
        "margin_status": calc.margin_status(p, bp, store.clock),
        "foreclosure_credit_cents": p["foreclosure_credit_cents"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_contract(c):
    out = {
        "id": c["id"],
        "buying_point_id": c["buying_point_id"],
        "sheller_ref": c["sheller_ref"],
        "total_units_tons": _num(c["total_units_tons"]),
        "fulfilled_units_tons": _num(calc.contract_fulfilled_tons(c["id"])),
        "remaining_units_tons": _num(calc.contract_remaining_tons(c["id"])),
        "price_per_ton_cents": c["price_per_ton_cents"],
        "accepts_segregated": c["accepts_segregated"],
        "window_start": fmt_dt(c["window_start"]),
        "window_end": fmt_dt(c["window_end"]),
        "default_count": c["default_count"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_delivery_call(c):
    out = {
        "id": c["id"],
        "contract_id": c["contract_id"],
        "requested_tons": _num(c["requested_tons"]),
        "dock_window_start": fmt_dt(c["dock_window_start"]),
        "dock_window_end": fmt_dt(c["dock_window_end"]),
        "allocated_tons": _num(calc.call_allocated_tons(c["id"])),
        "delivered_tons": _num(calc.call_delivered_tons(c["id"])),
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_allocation_line(l):
    # AllocationLine: only id and created_at system fields (PRD 2.4).
    return {
        "id": l["id"],
        "delivery_call_id": l["delivery_call_id"],
        "storage_receipt_id": l["storage_receipt_id"],
        "allocated_tons": _num(l["allocated_tons"]),
        "shipped_tons": _num(l["shipped_tons"]),
        "shelled_tons": _num(l["shelled_tons"]),
        "created_at": fmt_dt(l["created_at"]),
    }


def ser_settlement(s):
    out = {
        "id": s["id"],
        "grower_id": s["grower_id"],
        "crop_year": s["crop_year"],
        "supersedes_settlement_id": s["supersedes_settlement_id"],
        "included_load_ids": list(s["included_load_ids"]),
        "offset_pledge_ids": list(s["offset_pledge_ids"]),
        "quota_tons_applied": _num(s["quota_tons_applied"]),
        "additional_tons_applied": _num(s["additional_tons_applied"]),
        "gross_value_cents": s["gross_value_cents"],
        "discount_cents": s["discount_cents"],
        "drying_cents": s["drying_cents"],
        "loan_offset_cents": s["loan_offset_cents"],
        "hull_credit_cents": s["hull_credit_cents"],
        "net_payment_cents": s["net_payment_cents"],
        "computed_by": s["computed_by"],
        "approved_by": s["approved_by"],
        "paid_by": s["paid_by"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_quota_history(q):
    out = {
        "id": q["id"],
        "grower_id": q["grower_id"],
        "crop_year": q["crop_year"],
        "quota_tons": _num(q["quota_tons"]),
        "used_quota_tons": _num(q["used_quota_tons"]),
    }
    out.update(_common(q))
    return out


def ser_hull_lot(h):
    out = {
        "id": h["id"],
        "delivery_call_id": h["delivery_call_id"],
        "tons": _num(h["tons"]),
        "sale_price_cents_per_ton": h["sale_price_cents_per_ton"],
        "revenue_cents": h["revenue_cents"],
        "sold_at": fmt_dt(h["sold_at"]),
        "disposition_ref": h["disposition_ref"],
        "status": h["status"],
    }
    out.update(_common(h))
    return out
