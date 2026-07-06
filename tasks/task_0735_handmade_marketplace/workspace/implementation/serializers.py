"""Serialize entity records to JSON-friendly dicts (formatting timestamps)."""
from db import fmt_ts


def _common(rec, with_version=True):
    out = {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
    }
    if with_version:
        out["updated_at"] = fmt_ts(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def shop_view(rec):
    r = _common(rec)
    r.update({
        "owner_seller_id": rec["owner_seller_id"],
        "name": rec["name"],
        "currency": rec["currency"],
        "status": rec["status"],
        "max_concurrent_production": rec["max_concurrent_production"],
        "announcement": rec.get("announcement"),
        "vacation_auto_reply": rec.get("vacation_auto_reply"),
        "published_review_count": rec.get("published_review_count", 0),
        "simple_avg_rating": rec.get("simple_avg_rating"),
        "weighted_shop_rating": rec.get("weighted_shop_rating"),
        "available_balance_cents": rec.get("available_balance_cents", 0),
        "pending_balance_cents": rec.get("pending_balance_cents", 0),
        "lifetime_gross_cents": rec.get("lifetime_gross_cents", 0),
        "lifetime_fees_cents": rec.get("lifetime_fees_cents", 0),
    })
    return r


def shipping_profile_view(rec):
    r = _common(rec)
    r.update({
        "shop_id": rec["shop_id"],
        "name": rec["name"],
        "origin_country": rec["origin_country"],
        "base_cost_cents": rec["base_cost_cents"],
        "per_item_cost_cents": rec["per_item_cost_cents"],
        "free_shipping_threshold_cents": rec["free_shipping_threshold_cents"],
        "processing_time_days": rec["processing_time_days"],
    })
    return r


def material_view(rec):
    r = _common(rec)
    r.update({
        "shop_id": rec["shop_id"],
        "name": rec["name"],
        "unit": rec["unit"],
        "stock_qty": rec["stock_qty"],
        "reorder_threshold": rec["reorder_threshold"],
        "status": rec["status"],
    })
    return r


def listing_view(rec):
    r = _common(rec)
    r.update({
        "shop_id": rec["shop_id"],
        "shipping_profile_id": rec["shipping_profile_id"],
        "primary_material_id": rec.get("primary_material_id"),
        "material_qty_per_unit": rec.get("material_qty_per_unit", 0),
        "title": rec["title"],
        "fulfillment_type": rec["fulfillment_type"],
        "processing_time_days": rec["processing_time_days"],
        "price_cents": rec["price_cents"],
        "quantity": rec.get("quantity", 0),
        "status": rec["status"],
        "personalization_enabled": rec.get("personalization_enabled", False),
        "personalization_required": rec.get("personalization_required", False),
        "personalization_char_limit": rec.get("personalization_char_limit", 256),
        "variations": rec.get("variations", []),
        "expires_at": fmt_ts(rec["expires_at"]) if rec.get("expires_at") else None,
    })
    return r


def vacation_period_view(rec):
    # No updated_at / version
    r = _common(rec, with_version=False)
    r.update({
        "shop_id": rec["shop_id"],
        "starts_at": fmt_ts(rec["starts_at"]),
        "ends_at": fmt_ts(rec["ends_at"]),
        "status": rec["status"],
        "message": rec.get("message"),
    })
    return r


def order_view(rec):
    r = _common(rec)
    r.update({
        "shop_id": rec["shop_id"],
        "listing_id": rec["listing_id"],
        "variation_id": rec.get("variation_id"),
        "payout_id": rec.get("payout_id"),
        "buyer_id": rec["buyer_id"],
        "quantity": rec["quantity"],
        "personalization_note": rec.get("personalization_note"),
        "item_subtotal_cents": rec.get("item_subtotal_cents", 0),
        "shipping_cents": rec.get("shipping_cents", 0),
        "order_total_cents": rec.get("order_total_cents", 0),
        "order_fee_cents": rec.get("order_fee_cents", 0),
        "order_net_cents": rec.get("order_net_cents", 0),
        "refunded_cents": rec.get("refunded_cents", 0),
        "payment_status": rec["payment_status"],
        "fulfillment_status": rec["fulfillment_status"],
        "has_open_case": rec.get("has_open_case", False),
        "paid_at": fmt_ts(rec.get("paid_at")),
        "ship_by_date": fmt_ts(rec.get("ship_by_date")),
        "shipped_at": fmt_ts(rec.get("shipped_at")),
        "cancel_reason": rec.get("cancel_reason"),
    })
    return r


def review_view(rec):
    r = _common(rec)
    r.update({
        "order_id": rec["order_id"],
        "listing_id": rec.get("listing_id"),
        "shop_id": rec.get("shop_id"),
        "buyer_id": rec["buyer_id"],
        "rating": rec["rating"],
        "body": rec.get("body"),
        "seller_response": rec.get("seller_response"),
        "status": rec["status"],
    })
    return r


def case_view(rec):
    r = _common(rec)
    r.update({
        "order_id": rec["order_id"],
        "opener_buyer_id": rec["opener_buyer_id"],
        "type": rec["type"],
        "status": rec["status"],
        "reason": rec.get("reason"),
        "resolution": rec.get("resolution"),
        "refund_amount_cents": rec.get("refund_amount_cents", 0),
    })
    return r


def payout_view(rec):
    r = _common(rec)
    r.update({
        "shop_id": rec["shop_id"],
        "status": rec["status"],
        "order_count": rec["order_count"],
        "gross_cents": rec["gross_cents"],
        "fees_cents": rec["fees_cents"],
        "estimated_net_cents": rec["estimated_net_cents"],
        "settled_net_cents": rec.get("settled_net_cents"),
        "net_cents": rec["net_cents"],
        "scheduled_at": fmt_ts(rec.get("scheduled_at")),
        "paid_at": fmt_ts(rec.get("paid_at")),
    })
    return r
