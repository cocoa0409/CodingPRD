"""Serialization of stored records into API response objects.

Each serializer returns the entity's fields (from SCAFFOLD §1.1) plus the
common system fields id/created_at/updated_at/version (PRD §2.4). Records are
stored already in API shape, so serialization is largely a field projection /
copy. We copy to avoid leaking internal mutation of the response.
"""

COMMON = ["id", "created_at", "updated_at", "version"]


def _project(rec, fields):
    out = {}
    for f in COMMON:
        out[f] = rec.get(f)
    for f in fields:
        out[f] = rec.get(f)
    return out


def distributor(rec):
    return _project(rec, ["name", "current_utc", "catalog_revision"])


def warehouse(rec):
    return _project(rec, ["distributor_id", "code", "name"])


def route(rec):
    return _project(rec, [
        "distributor_id", "warehouse_id", "code", "delivery_dow",
        "cutoff_lead_hours", "min_delivery_gap_days",
    ])


def product(rec):
    return _project(rec, [
        "distributor_id", "sku", "name", "category", "splits_per_case",
        "split_allowed", "perishable", "substitute_product_id",
        "case_cost_cents", "status",
    ])


def price_tier(rec):
    return _project(rec, [
        "product_id", "distributor_id", "min_cases", "case_price_cents",
    ])


def customer(rec):
    return _project(rec, [
        "distributor_id", "route_id", "name", "credit_limit_cents",
        "split_fee_cents", "ar_balance_cents", "ar_status",
    ])


def order_guide(rec):
    return _project(rec, ["customer_id", "distributor_id", "name"])


def order_guide_item(rec, suggestion=None):
    out = _project(rec, [
        "order_guide_id", "product_id", "par_level_splits", "on_hand_splits",
    ])
    if suggestion is not None:
        out["suggested_uom"] = suggestion["suggested_uom"]
        out["suggested_qty"] = suggestion["suggested_qty"]
    return out


def inventory_lot(rec):
    return _project(rec, [
        "product_id", "warehouse_id", "lot_code", "expires_on",
        "on_hand_splits", "reserved_splits",
    ])


def order(rec):
    return _project(rec, [
        "customer_id", "distributor_id", "route_id", "requested_delivery_date",
        "fulfillment_status", "credit_status", "goods_subtotal_cents",
        "split_fee_total_cents", "order_total_cents", "settled",
    ])


def order_line(rec):
    return _project(rec, [
        "order_id", "product_id", "order_guide_item_id", "uom", "ordered_qty",
        "fulfilled_product_id", "allocated_splits", "substituted",
        "short_splits", "unit_case_price_cents", "extended_price_cents",
        "line_status",
    ])


def shipment(rec):
    return _project(rec, [
        "order_id", "distributor_id", "warehouse_id", "pod_signature",
        "delivered_total_cents", "status",
    ])


def return_(rec):
    return _project(rec, [
        "customer_id", "distributor_id", "order_id", "order_line_id", "reason",
        "return_splits", "restock_fee_cents", "credit_amount_cents", "status",
    ])
