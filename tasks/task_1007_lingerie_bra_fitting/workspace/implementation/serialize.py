"""Serializers: project stored records into API response objects, computing
derived fields (PRD §2.4, §2.6, §3). Field names are transcribed verbatim from
SCAFFOLD §1.1."""
import store
import calc


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def sku_reserved_count(sku_id):
    total = 0
    for line in store.order_lines.values():
        if line["sku_id"] != sku_id:
            continue
        if line["status"] != "ACTIVE":
            continue
        if line["is_special_order"]:
            continue
        order = store.orders.get(line["order_id"])
        if order and order["fulfillment_status"] == "PLACED":
            total += line["quantity"]
    return total


def sku_available_units(sku):
    return sku["stock_on_hand"] - sku_reserved_count(sku["id"])


def customer_out(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "email": rec["email"],
        "phone": rec.get("phone"),
        "post_mastectomy_flag": rec["post_mastectomy_flag"],
        "loyalty_points": rec["loyalty_points"],
        "loyalty_tier": calc.loyalty_tier(rec["loyalty_points"]),
        "store_credit_cents": rec["store_credit_cents"],
    })
    return out


def fitter_out(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "post_surgical_certified": rec["post_surgical_certified"],
        "is_active": rec["is_active"],
    })
    return out


def room_out(rec):
    out = _common(rec)
    out.update({
        "room_name": rec["room_name"],
        "capacity": rec["capacity"],
        "is_private": rec["is_private"],
        "is_active": rec["is_active"],
    })
    return out


def appointment_out(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "fitter_id": rec["fitter_id"],
        "room_id": rec["room_id"],
        "fitting_type": rec["fitting_type"],
        "scheduled_start": store.iso(rec["scheduled_start"]),
        "duration_minutes": rec["duration_minutes"],
        "scheduled_end": store.iso(rec["scheduled_end"]),
        "underbust_cm": rec.get("underbust_cm"),
        "bust_cm": rec.get("bust_cm"),
        "fit_preference": rec.get("fit_preference"),
        "recommended_band": rec.get("recommended_band"),
        "recommended_cup": rec.get("recommended_cup"),
        "recommended_size": rec.get("recommended_size"),
        "status": rec["status"],
    })
    return out


def product_out(rec):
    out = _common(rec)
    out.update({
        "style_name": rec["style_name"],
        "brand": rec["brand"],
        "category": rec["category"],
        "base_price_cents": rec["base_price_cents"],
        "hygiene_class": rec["hygiene_class"],
        "is_mastectomy": rec["is_mastectomy"],
        "is_active": rec["is_active"],
    })
    return out


def sku_out(rec):
    reserved = sku_reserved_count(rec["id"])
    available = rec["stock_on_hand"] - reserved
    out = _common(rec)
    out.update({
        "product_id": rec["product_id"],
        "band_size": rec["band_size"],
        "cup_size": rec["cup_size"],
        "sku_code": rec["sku_code"],
        "price_cents": rec["price_cents"],
        "stock_on_hand": rec["stock_on_hand"],
        "reserved_count": reserved,
        "available_units": available,
        "is_active": rec["is_active"],
        "stock_status": calc.stock_status(available),
    })
    return out


def order_out(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "order_type": rec["order_type"],
        "is_gift": rec["is_gift"],
        "gift_message": rec.get("gift_message"),
        "gift_recipient_name": rec.get("gift_recipient_name"),
        "payment_status": rec["payment_status"],
        "fulfillment_status": rec["fulfillment_status"],
        "subtotal_cents": rec["subtotal_cents"],
        "discount_cents": rec["discount_cents"],
        "gift_wrap_fee_cents": rec["gift_wrap_fee_cents"],
        "special_order_fee_cents": rec["special_order_fee_cents"],
        "total_cents": rec["total_cents"],
        "provisional_points": rec["provisional_points"],
        "final_points": rec["final_points"],
        "fulfilled_at": store.iso(rec["fulfilled_at"]),
    })
    return out


def order_line_out(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "sku_id": rec["sku_id"],
        "quantity": rec["quantity"],
        "unit_price_cents": rec["unit_price_cents"],
        "line_gross_cents": rec["line_gross_cents"],
        "line_discount_cents": rec["line_discount_cents"],
        "line_net_cents": rec["line_net_cents"],
        "is_special_order": rec["is_special_order"],
        "status": rec["status"],
    })
    return out


def exchange_out(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "order_line_id": rec["order_line_id"],
        "item_condition": rec["item_condition"],
        "reason": rec.get("reason"),
        "store_credit_issued_cents": rec["store_credit_issued_cents"],
        "status": rec["status"],
    })
    return out


def claim_out(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "claim_amount_cents": rec["claim_amount_cents"],
        "adjudicated_amount_cents": rec.get("adjudicated_amount_cents"),
        "decision": rec["decision"],
        "covered_amount_cents": rec["covered_amount_cents"],
        "reimbursed_cents": rec["reimbursed_cents"],
        "status": rec["status"],
    })
    return out


def reminder_out(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "order_line_id": rec["order_line_id"],
        "due_date": store.iso(rec["due_date"]),
        "status": rec["status"],
    })
    return out


def loyalty_event_out(rec):
    # append-only ledger row: id + created_at only (no updated_at / version)
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "customer_id": rec["customer_id"],
        "points_delta": rec["points_delta"],
        "reason": rec["reason"],
        "order_id": rec.get("order_id"),
    }
