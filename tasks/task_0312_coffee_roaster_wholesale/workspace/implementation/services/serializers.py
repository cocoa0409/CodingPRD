"""Public serializers: convert stored records to API response objects.

Internal bookkeeping keys are prefixed with '_' and never surfaced.
"""
from helpers import common_public
from db import iso_z
from services import inventory


def tier_public(rec):
    out = common_public(rec)
    out.update({
        "code": rec["code"],
        "discount_bps": rec["discount_bps"],
        "min_monthly_kg": rec["min_monthly_kg"],
        "freshness_max_days": rec["freshness_max_days"],
        "archived": rec["archived"],
    })
    return out


def account_public(rec):
    # outstanding_balance_cents is recomputed by the caller before serialization
    out = common_public(rec)
    out.update({
        "name": rec["name"],
        "price_tier_id": rec["price_tier_id"],
        "net_terms_days": rec["net_terms_days"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "outstanding_balance_cents": rec["outstanding_balance_cents"],
        "status": rec["status"],
    })
    return out


def roast_profile_public(rec):
    out = common_public(rec)
    out.update({
        "name": rec["name"],
        "roast_level": rec["roast_level"],
        "expected_shrink_bps": rec["expected_shrink_bps"],
        "charge_temp_c": rec["charge_temp_c"],
    })
    return out


def product_public(rec):
    out = common_public(rec)
    out.update({
        "sku": rec["sku"],
        "name": rec["name"],
        "roast_profile_id": rec["roast_profile_id"],
        "base_price_cents_per_kg": rec["base_price_cents_per_kg"],
        "freshness_window_days": rec["freshness_window_days"],
        "archived": rec["archived"],
    })
    return out


def green_lot_public(rec):
    out = common_public(rec)
    out.update({
        "origin": rec["origin"],
        "lot_ref": rec["lot_ref"],
        "received_kg": rec["received_kg"],
        "on_hand_kg": rec["on_hand_kg"],
        "reserved_kg": rec["reserved_kg"],
        "available_kg": rec["available_kg"],
        "par_level_kg": rec["par_level_kg"],
        "reorder_status": rec["reorder_status"],
    })
    return out


def roast_batch_public(rec):
    out = common_public(rec)
    out.update({
        "green_lot_id": rec["green_lot_id"],
        "product_id": rec["product_id"],
        "roast_profile_id": rec["roast_profile_id"],
        "planned_green_kg": rec["planned_green_kg"],
        "planned_roasted_kg": rec["planned_roasted_kg"],
        "actual_green_kg": rec.get("actual_green_kg"),
        "actual_roasted_kg": rec.get("actual_roasted_kg"),
        "actual_shrink_bps": rec.get("actual_shrink_bps"),
        "roast_date": iso_z(rec.get("roast_date")),
        "status": rec["status"],
    })
    return out


def roasted_lot_public(rec):
    out = common_public(rec)
    out.update({
        "roast_batch_id": rec["roast_batch_id"],
        "product_id": rec["product_id"],
        "roast_date": iso_z(rec["roast_date"]),
        "produced_kg": rec["produced_kg"],
        "reserved_kg": rec["reserved_kg"],
        "on_hand_kg": rec["on_hand_kg"],
        "available_kg": rec["available_kg"],
    })
    return out


def standing_order_public(rec):
    out = common_public(rec)
    out.update({
        "account_id": rec["account_id"],
        "product_id": rec["product_id"],
        "qty_kg": rec["qty_kg"],
        "cadence_days": rec["cadence_days"],
        "next_release_at": iso_z(rec["next_release_at"]),
        "cycles_released": rec["cycles_released"],
        "status": rec["status"],
    })
    return out


def order_public(rec):
    out = common_public(rec)
    out.update({
        "account_id": rec["account_id"],
        "standing_order_id": rec.get("standing_order_id"),
        "lines": [{"product_id": l["product_id"], "qty_kg": l["qty_kg"]} for l in rec["lines"]],
        "subtotal_cents": rec["subtotal_cents"],
        "discount_cents": rec["discount_cents"],
        "total_cents": rec["total_cents"],
        "fulfillment_status": rec["fulfillment_status"],
        "billing_status": rec["billing_status"],
    })
    return out


def fulfillment_public(rec):
    out = common_public(rec)
    out.update({
        "order_id": rec["order_id"],
        "product_id": rec["product_id"],
        "roasted_lot_id": rec["roasted_lot_id"],
        "allocated_kg": rec["allocated_kg"],
        "roast_date": iso_z(rec["roast_date"]),
        "status": rec["status"],
    })
    return out


def sample_request_public(rec):
    out = common_public(rec)
    out.update({
        "account_id": rec["account_id"],
        "product_id": rec["product_id"],
        "sample_kg": rec["sample_kg"],
        "cupping_score": rec.get("cupping_score"),
        "status": rec["status"],
    })
    return out


def invoice_public(rec):
    out = common_public(rec)
    out.update({
        "account_id": rec["account_id"],
        "order_id": rec["order_id"],
        "amount_cents": rec["amount_cents"],
        "paid_cents": inventory.invoice_paid(rec),
        "amount_due_cents": inventory.invoice_amount_due(rec),
        "issued_at": iso_z(rec["issued_at"]),
        "due_at": iso_z(rec["due_at"]),
        "status": rec["status"],
    })
    return out


def payment_public(rec):
    out = common_public(rec, with_version=False)
    out.update({
        "invoice_id": rec["invoice_id"],
        "amount_cents": rec["amount_cents"],
        "status": rec["status"],
    })
    return out
