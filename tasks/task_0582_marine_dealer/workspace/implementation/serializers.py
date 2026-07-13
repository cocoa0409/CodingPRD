"""Serialize internal records into public JSON dicts, computing read-time
derived fields (aging, interest, payoff, part availability, etc.)."""
from store import db, now, fmt_dt
import calc


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def active_floor_plan_for_unit(unit_id):
    """The unit's single ACTIVE or CURTAILED plan, if any."""
    for fp in db.floor_plans.values():
        if fp["unit_id"] == unit_id and fp["status"] in ("ACTIVE", "CURTAILED"):
            return fp
    return None


def unit_floor_plan_balance(unit_id):
    fp = active_floor_plan_for_unit(unit_id)
    return fp["outstanding_principal_cents"] if fp else 0


def part_reserved_qty(part_id):
    total = 0
    for sl in db.service_lines.values():
        if (sl["line_type"] == "PART" and sl["status"] == "ACTIVE"
                and sl.get("part_id") == part_id):
            total += sl["quantity"]
    return total


def serialize_unit(u):
    d = _common(u)
    d.update({
        "hin": u["hin"],
        "make": u["make"],
        "model": u["model"],
        "model_year": u["model_year"],
        "unit_type": u["unit_type"],
        "length_ft": u["length_ft"],
        "cost_cents": u["cost_cents"],
        "list_price_cents": u["list_price_cents"],
        "acquisition_type": u["acquisition_type"],
        "open_recall": u["open_recall"],
        "status": u["status"],
        "warranty_registered": (u["status"] == "DELIVERED"),
        "aging_days": calc.days_out(now(), u["created_at"]),
        "floor_plan_balance_cents": unit_floor_plan_balance(u["id"]),
    })
    return d


def serialize_floor_plan(fp):
    d = _common(fp)
    d_out = calc.days_out(now(), fp["advanced_at"])
    accrued = calc.accrued_interest(fp["outstanding_principal_cents"], fp["apr_bps"], d_out)
    if fp["status"] == "PAID_OFF" and fp.get("_payoff_snapshot") is not None:
        payoff_cents = fp["_payoff_snapshot"]
    else:
        payoff_cents = calc.payoff(fp["outstanding_principal_cents"], fp["apr_bps"], d_out)
    d.update({
        "unit_id": fp["unit_id"],
        "lender_name": fp["lender_name"],
        "principal_cents": fp["principal_cents"],
        "outstanding_principal_cents": fp["outstanding_principal_cents"],
        "apr_bps": fp["apr_bps"],
        "advanced_at": fmt_dt(fp["advanced_at"]),
        "curtailment_pct_bps": fp["curtailment_pct_bps"],
        "status": fp["status"],
        "accrued_interest_cents": accrued,
        "payoff_cents": payoff_cents,
    })
    return d


def serialize_deal(dl):
    d = _common(dl)
    d.update({
        "unit_id": dl["unit_id"],
        "customer_name": dl["customer_name"],
        "sale_price_cents": dl["sale_price_cents"],
        "financing_type": dl["financing_type"],
        "tax_rate_bps": dl["tax_rate_bps"],
        "doc_fee_cents": dl["doc_fee_cents"],
        "down_payment_cents": dl["down_payment_cents"],
        "trade_allowance_cents": dl["trade_allowance_cents"],
        "trade_lien_payoff_cents": dl["trade_lien_payoff_cents"],
        "status": dl["status"],
        "trade_equity_cents": dl["trade_equity_cents"],
        "tax_cents": dl["tax_cents"],
        "amount_due_cents": dl["amount_due_cents"],
    })
    return d


def serialize_consignment(c):
    d = _common(c)
    d.update({
        "unit_id": c["unit_id"],
        "consignor_name": c["consignor_name"],
        "agreed_floor_cents": c["agreed_floor_cents"],
        "commission_bps": c["commission_bps"],
        "status": c["status"],
        "payout_cents": c["payout_cents"],
    })
    return d


def serialize_repair_order(ro):
    d = _common(ro)
    d.update({
        "unit_id": ro["unit_id"],
        "service_bay_id": ro["service_bay_id"],
        "customer_name": ro["customer_name"],
        "ro_type": ro["ro_type"],
        "flat_rate_code": ro.get("flat_rate_code"),
        "flat_rate_hours": ro.get("flat_rate_hours"),
        "flat_rate_parts_cents": ro.get("flat_rate_parts_cents"),
        "estimated_hours": ro.get("estimated_hours"),
        "labor_rate_cents_per_hour": ro["labor_rate_cents_per_hour"],
        "tax_rate_bps": ro["tax_rate_bps"],
        "scheduled_start": fmt_dt(ro["scheduled_start"]),
        "scheduled_end": fmt_dt(ro["scheduled_end"]),
        "status": ro["status"],
        "estimate_total_cents": ro["estimate_total_cents"],
        "final_total_cents": ro["final_total_cents"],
    })
    return d


def line_effective_price(sl):
    if sl.get("unit_price_cents") is not None:
        return sl["unit_price_cents"]
    if sl["line_type"] == "PART":
        part = db.parts.get(sl["part_id"])
        return part["list_price_cents"] if part else 0
    ro = db.repair_orders.get(sl["repair_order_id"])
    return ro["labor_rate_cents_per_hour"] if ro else 0


def line_extended_cents(sl):
    return calc.line_extended(sl["line_type"], sl.get("hours"),
                              sl.get("quantity"), line_effective_price(sl))


def serialize_service_line(sl):
    d = _common(sl)
    d.update({
        "repair_order_id": sl["repair_order_id"],
        "line_type": sl["line_type"],
        "part_id": sl.get("part_id"),
        "hours": sl.get("hours"),
        "quantity": sl.get("quantity"),
        "unit_price_cents": sl.get("unit_price_cents"),
        "warranty_covered": sl["warranty_covered"],
        "status": sl["status"],
        "extended_cents": line_extended_cents(sl),
    })
    return d


def serialize_part(p):
    d = _common(p)
    reserved = part_reserved_qty(p["id"])
    available = p["on_hand_qty"] - reserved
    d.update({
        "sku": p["sku"],
        "name": p["name"],
        "on_hand_qty": p["on_hand_qty"],
        "unit_cost_cents": p["unit_cost_cents"],
        "list_price_cents": p["list_price_cents"],
        "reorder_point": p["reorder_point"],
        "reserved_qty": reserved,
        "available_qty": available,
        "is_low": available <= p["reorder_point"],
    })
    return d


def serialize_berth(b):
    d = _common(b)
    d.update({
        "berth_code": b["berth_code"],
        "berth_type": b["berth_type"],
        "max_length_ft": b["max_length_ft"],
        "status": b["status"],
    })
    return d


def serialize_service_bay(sb):
    d = _common(sb)
    d.update({
        "bay_code": sb["bay_code"],
        "bay_type": sb["bay_type"],
    })
    return d


def serialize_slip_reservation(sr):
    d = _common(sr)
    d.update({
        "berth_id": sr["berth_id"],
        "unit_id": sr["unit_id"],
        "start_date": fmt_dt(sr["start_date"]),
        "end_date": fmt_dt(sr["end_date"]),
        "daily_rate_cents": sr["daily_rate_cents"],
        "status": sr["status"],
        "nights": sr["nights"],
        "total_cents": sr["total_cents"],
    })
    return d
