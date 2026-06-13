"""Entity -> JSON output shaping. Computes derived read-fields per PRD §2.5/§3.

Internal bookkeeping keys (prefixed with '_') are stripped from output.
"""
from services import derive


def _common(rec, with_version=True):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }
    if with_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def customer(rec):
    out = _common(rec)
    out.update({
        "email": rec["email"],
        "full_name": rec["full_name"],
        "store_credit_cents": derive.customer_store_credit_cents(rec["id"]),
        "lifetime_purchased_cents": derive.customer_lifetime_purchased_cents(rec["id"]),
        "lifetime_refunded_cents": derive.customer_lifetime_refunded_cents(rec["id"]),
        "return_risk_score": derive.customer_return_risk_score(rec["id"]),
    })
    return out


def warehouse(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "name": rec["name"],
        "fulfillment_priority": rec["fulfillment_priority"],
        "accepts_returns": rec["accepts_returns"],
    })
    return out


def product(rec):
    out = _common(rec)
    out.update({
        "sku": rec["sku"],
        "title": rec["title"],
        "unit_price_cents": rec["unit_price_cents"],
        "tax_rate_bps": rec["tax_rate_bps"],
        "restocking_fee_bps": rec["restocking_fee_bps"],
        "return_window_days": rec["return_window_days"],
        "final_sale": rec["final_sale"],
    })
    return out


def inventory_item(rec):
    out = _common(rec)
    reserved = derive.inventory_reserved_qty(rec["product_id"], rec["warehouse_id"])
    available = max(0, rec["on_hand_qty"] - reserved)
    out.update({
        "product_id": rec["product_id"],
        "warehouse_id": rec["warehouse_id"],
        "on_hand_qty": rec["on_hand_qty"],
        "reserved_qty": reserved,
        "available_qty": available,
    })
    return out


def order(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "payment_status": rec["payment_status"],
        "fulfillment_status": rec["fulfillment_status"],
        "promo_flat_cents": rec["promo_flat_cents"],
        "subtotal_cents": rec["subtotal_cents"],
        "discounted_subtotal_cents": rec["discounted_subtotal_cents"],
        "tax_total_cents": rec["tax_total_cents"],
        "shipping_fee_cents": rec["shipping_fee_cents"],
        "grand_total_cents": rec["grand_total_cents"],
        "captured_total_cents": rec["captured_total_cents"],
    })
    return out


def order_line(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "product_id": rec["product_id"],
        "qty": rec["qty"],
        "unit_price_cents_snapshot": rec["unit_price_cents_snapshot"],
        "tax_rate_bps_snapshot": rec["tax_rate_bps_snapshot"],
        "line_tax_cents": rec["line_tax_cents"],
        "reserved_qty": derive.order_line_reserved_qty(rec["id"]),
        "backordered_qty": rec.get("backordered_qty", 0),
        "shipped_qty": derive.order_line_shipped_qty(rec["id"]),
        "returned_qty": derive.order_line_returned_qty(rec["id"]),
    })
    return out


def reservation(rec):
    out = _common(rec)
    out.update({
        "order_line_id": rec["order_line_id"],
        "warehouse_id": rec["warehouse_id"],
        "product_id": rec["product_id"],
        "qty": rec["qty"],
        "status": rec["status"],
    })
    return out


def shipment(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "warehouse_id": rec["warehouse_id"],
        "status": rec["status"],
        "shipped_at": rec["shipped_at"],
        "delivered_at": rec["delivered_at"],
    })
    return out


def shipment_line(rec):
    out = _common(rec)
    out.update({
        "shipment_id": rec["shipment_id"],
        "reservation_id": rec["reservation_id"],
        "order_line_id": rec["order_line_id"],
        "qty": rec["qty"],
    })
    return out


def return_authorization(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "customer_id": rec["customer_id"],
        "status": rec["status"],
        "reason": rec["reason"],
        "resolution": rec["resolution"],
        "refund_subtotal_cents": rec["refund_subtotal_cents"],
        "restocking_fee_cents": rec["restocking_fee_cents"],
        "settlement_cents": rec["settlement_cents"],
    })
    return out


def return_line(rec):
    out = _common(rec)
    out.update({
        "return_authorization_id": rec["return_authorization_id"],
        "order_line_id": rec["order_line_id"],
        "return_qty": rec["return_qty"],
        "exchange_product_id": rec.get("exchange_product_id"),
    })
    return out


def refund(rec):
    out = _common(rec)
    out.update({
        "return_authorization_id": rec["return_authorization_id"],
        "order_id": rec["order_id"],
        "customer_id": rec["customer_id"],
        "destination": rec["destination"],
        "amount_cents": rec["amount_cents"],
        "status": rec["status"],
    })
    return out


def credit_ledger_entry(rec):
    # immutable audit record: only id + created_at (no updated_at/version)
    out = _common(rec, with_version=False)
    out.update({
        "customer_id": rec["customer_id"],
        "refund_id": rec.get("refund_id"),
        "amount_cents": rec["amount_cents"],
        "kind": rec["kind"],
    })
    return out
