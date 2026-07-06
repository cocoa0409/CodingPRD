"""Response envelope + resource serializers.

Envelope field names (meta/api_request_id/api_request_timestamp/response_type/
data, and pagination limit/offset/total_count/has_more) are taken verbatim from
SCAFFOLD response_envelope and PRD 2.2 / 2.3.
"""

import random
import string

from flask import jsonify

import db

_ALNUM = string.ascii_letters + string.digits


def gen_request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta(pagination=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": db.wall_now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


# ---------------------------------------------------------------------------
# Explicit field whitelists per entity (never dump internal _ fields)
# ---------------------------------------------------------------------------
_COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "Farm": _COMMON + [
        "name", "region_code", "commission_pct", "snap_authorized",
        "payout_balance_cents", "settled_cycle_count",
    ],
    "Product": _COMMON + [
        "farm_id", "name", "category", "pricing_mode", "unit_price_cents",
        "price_per_kg_cents", "estimated_weight_kg", "snap_eligible",
    ],
    "MarketCycle": _COMMON + [
        "cycle_code", "region_code", "order_open_at", "order_cutoff_at",
        "fulfillment_date", "status",
    ],
    "Offering": _COMMON + [
        "product_id", "market_cycle_id", "offered_qty", "unit_price_cents",
        "price_per_kg_cents", "reserved_qty", "committed_qty", "remaining_qty",
    ],
    "PickupHub": _COMMON + ["name", "hub_type", "slot_capacity", "region_code"],
    "Customer": _COMMON + [
        "name", "snap_balance_cents", "wallet_credit_cents", "doubleup_used_cents",
    ],
    "Subscription": _COMMON + [
        "customer_id", "pickup_hub_id", "box_size", "cadence", "price_cap_cents",
        "status",
    ],
    "Order": _COMMON + [
        "customer_id", "market_cycle_id", "pickup_hub_id", "subscription_id",
        "fulfillment_type", "delivery_slot_start", "delivery_slot_end",
        "subtotal_cents", "eligible_subtotal_cents", "snap_applied_cents",
        "doubleup_match_cents", "customer_owed_cents", "final_total_cents",
        "refunded_snap_cents", "refunded_wallet_cents", "order_status",
        "payment_status",
    ],
    "OrderLine": _COMMON + [
        "order_id", "offering_id", "requested_qty", "allocated_qty",
        "fulfilled_qty", "actual_weight_kg", "snap_eligible",
        "estimated_line_cents", "final_line_cents", "substitute_offering_id",
        "price_delta_cents", "line_status",
    ],
    # VendorSettlement is immutable: only id + created_at, no updated_at/version.
    "VendorSettlement": ["id", "created_at"] + [
        "farm_id", "market_cycle_id", "gross_sales_cents", "commission_cents",
        "snap_reimbursable_cents", "net_payout_cents", "line_count",
    ],
}


def serialize(entity):
    fields = FIELDS[entity["_kind"]]
    return {k: entity.get(k) for k in fields}
