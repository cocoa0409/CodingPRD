"""Serializers: produce output representations including computed fields."""
from core import db
from calc import markdown_price


COMMON = ("id", "created_at", "updated_at", "version")


def _base(rec):
    return {k: rec[k] for k in COMMON}


def product_out(p):
    out = _base(p)
    out.update({
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "unit_price_cents": p["unit_price_cents"],
        "dozen_price_cents": p["dozen_price_cents"],
        "bulk_threshold": p["bulk_threshold"],
        "bulk_unit_price_cents": p["bulk_unit_price_cents"],
        "unit_cost_cents": p["unit_cost_cents"],
        "allergens": list(p["allergens"]),
        "active": p["active"],
    })
    return out


def production_day_out(d):
    out = _base(d)
    out.update({
        "business_date": d["business_date"],
        "delivery_cutoff_utc": d["delivery_cutoff_utc"],
        "status": d["status"],
        "gross_sales_cents": d["gross_sales_cents"],
        "markdown_loss_cents": d["markdown_loss_cents"],
        "waste_cost_cents": d["waste_cost_cents"],
        "expected_full_value_cents": d["expected_full_value_cents"],
        "reconciliation_variance_cents": d["reconciliation_variance_cents"],
    })
    return out


def bake_batch_out(b):
    out = _base(b)
    out.update({
        "production_day_id": b["production_day_id"],
        "product_id": b["product_id"],
        "par_qty": b["par_qty"],
        "baked_qty": b["baked_qty"],
        "sold_qty": b["sold_qty"],
        "markdown_sold_qty": b["markdown_sold_qty"],
        "remaining_qty": b["remaining_qty"],
        "wasted_qty": b["wasted_qty"],
        "status": b["status"],
    })
    return out


def retail_order_out(o):
    out = _base(o)
    out.update({
        "production_day_id": o["production_day_id"],
        "loyalty_account_id": o["loyalty_account_id"],
        "line_items": o["line_items"],
        "subtotal_cents": o["subtotal_cents"],
        "loyalty_discount_cents": o["loyalty_discount_cents"],
        "total_cents": o["total_cents"],
        "redeem_reward": o["redeem_reward"],
        "status": o["status"],
    })
    return out


def loyalty_account_out(a):
    out = _base(a)
    out.update({
        "phone": a["phone"],
        "name": a["name"],
        "punch_count": a["punch_count"],
        "reward_balance_cents": a["reward_balance_cents"],
    })
    return out


def wholesale_account_out(a):
    out = _base(a)
    out.update({
        "name": a["name"],
        "discount_pct": a["discount_pct"],
        "credit_limit_cents": a["credit_limit_cents"],
        "outstanding_balance_cents": a["outstanding_balance_cents"],
        "status": a["status"],
    })
    return out


def standing_order_out(s):
    out = _base(s)
    out.update({
        "wholesale_account_id": s["wholesale_account_id"],
        "delivery_dow": s["delivery_dow"],
        "line_items": s["line_items"],
        "status": s["status"],
    })
    return out


def wholesale_delivery_out(d):
    out = _base(d)
    out.update({
        "production_day_id": d["production_day_id"],
        "standing_order_id": d["standing_order_id"],
        "wholesale_account_id": d["wholesale_account_id"],
        "route_window_start": d["route_window_start"],
        "route_window_end": d["route_window_end"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
    })
    return out


def pre_order_out(p):
    out = _base(p)
    out.update({
        "wholesale_account_id": p["wholesale_account_id"],
        "pickup_production_day_id": p["pickup_production_day_id"],
        "pickup_window_start": p["pickup_window_start"],
        "pickup_window_end": p["pickup_window_end"],
        "line_items": p["line_items"],
        "subtotal_cents": p["subtotal_cents"],
        "deposit_due_cents": p["deposit_due_cents"],
        "deposit_paid_cents": p["deposit_paid_cents"],
        "status": p["status"],
    })
    return out
