"""In-memory data store. Empty on every boot: no seeding, ever."""

import itertools
import uuid
from datetime import date, datetime

from util import clock, iso

_seq = itertools.count(1)

sellers = {}
buyers = {}
warehouses = {}
carriers = {}
brand_policies = {}
lots = {}
manifest_lines = {}
listings = {}
bids = {}
negotiations = {}
offers = {}
sale_orders = {}
appointments = {}
claims = {}

ALL_STORES = (
    sellers, buyers, warehouses, carriers, brand_policies, lots, manifest_lines,
    listings, bids, negotiations, offers, sale_orders, appointments, claims,
)


def new_id():
    return str(uuid.uuid4())


def new_row(**fields):
    """Create a row carrying the common identity fields (PRD 2.5)."""
    moment = clock.now()
    row = {
        "id": new_id(),
        "created_at": moment,
        "updated_at": moment,
        "version": 1,
        "_seq": next(_seq),
    }
    row.update(fields)
    return row


def new_offer_row(**fields):
    """Offers carry only id and created_at (PRD 2.5)."""
    row = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": next(_seq),
    }
    row.update(fields)
    return row


def touch(row):
    """Direct mutation: refresh updated_at and advance version."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def touch_soft(row):
    """Derived-aggregate recomputation: refresh updated_at only."""
    row["updated_at"] = clock.now()
    return row


def ordered(rows):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


COMMON = ["created_at", "updated_at", "version"]

FIELDS = {
    "seller": [
        "id", "legal_name", "tax_id", "state_code", "contact_email",
        "account_status", "commission_tier", "commission_rate_bps",
        "gross_hammer_cents", "listed_retail_value_cents", "gross_recovery_rate",
        "net_proceeds_cents", "sold_retail_value_cents", "net_recovery_rate",
        "manifest_accuracy_avg", "scored_lot_count",
    ] + COMMON,
    "buyer": [
        "id", "legal_name", "tax_id", "state_code", "contact_email",
        "resale_certificate_number", "resale_certificate_expires_on",
        "requested_credit_limit_cents", "business_verification_status",
        "qualification_status", "approved_credit_limit_cents",
        "outstanding_exposure_cents", "wallet_credit_cents",
        "available_credit_cents",
    ] + COMMON,
    "warehouse": [
        "id", "name", "state_code", "dock_door_count", "turnaround_buffer_minutes",
    ] + COMMON,
    "carrier": ["id", "name", "scac_code", "daily_pickup_capacity"] + COMMON,
    "brand_policy": [
        "id", "brand_code", "permitted_channels", "de_branding_required",
        "debranding_fee_cents_per_unit", "prohibited_buyer_state_codes",
        "embargo_start_at", "embargo_end_at",
    ] + COMMON,
    "lot": [
        "id", "seller_id", "warehouse_id", "brand_policy_id", "title",
        "category_code", "condition_grade", "lot_status", "manifest_line_count",
        "declared_unit_count", "declared_retail_value_cents",
        "manifest_reviewed_by_user_id", "manifest_accuracy_score",
        "de_branding_required",
    ] + COMMON,
    "manifest_line": [
        "id", "lot_id", "sku", "unit_count", "unit_retail_cents",
        "declared_condition", "line_status", "verified_unit_count",
    ] + COMMON,
    "listing": [
        "id", "lot_id", "listing_format", "resale_channel", "window_start_at",
        "window_end_at", "effective_close_at", "extension_count",
        "opening_bid_cents", "reserve_price_cents", "ask_price_cents",
        "min_offer_cents", "bid_increment_cents", "de_branding_attested",
        "listing_status", "bid_count", "current_high_bid_cents",
        "current_high_bidder_id", "reserve_met", "min_next_bid_cents",
    ] + COMMON,
    "bid": [
        "id", "listing_id", "buyer_id", "bid_type", "amount_cents",
        "max_amount_cents", "ceiling_cents", "bid_status", "placed_at",
        "meets_reserve",
    ] + COMMON,
    "negotiation": [
        "id", "listing_id", "buyer_id", "negotiation_status", "round_number",
        "current_offer_cents", "current_offer_side", "current_offer_expires_at",
        "accepted_price_cents",
    ] + COMMON,
    "offer": [
        "id", "negotiation_id", "offer_side", "amount_cents", "round_number",
        "expires_at", "created_at",
    ],
    "sale_order": [
        "id", "listing_id", "buyer_id", "sale_source", "hammer_price_cents",
        "buyer_premium_bps", "buyer_premium_cents", "pallet_count",
        "estimated_freight_cents", "actual_freight_cents", "claim_credit_cents",
        "late_fee_cents", "pre_fee_total_cents", "total_due_cents",
        "amount_paid_cents", "balance_due_cents", "paid_at", "picked_up_at",
        "abandoned_at", "settlement_basis", "payment_status", "logistics_status",
        "payment_due_at", "pickup_deadline_at", "claim_window_closes_at",
        "seller_commission_rate_bps", "seller_commission_cents",
        "seller_debranding_fee_cents", "seller_net_proceeds_cents",
    ] + COMMON,
    "appointment": [
        "id", "sale_order_id", "warehouse_id", "carrier_id", "window_start_at",
        "window_end_at", "dock_door_number", "bol_number", "appointment_status",
        "completed_at", "picked_up_unit_count",
    ] + COMMON,
    "claim": [
        "id", "sale_order_id", "manifest_line_id", "claim_type", "claimed_units",
        "verified_units", "evidence_item_count", "evidence_request_count",
        "claim_status", "refund_cents", "decided_by_user_id",
        "reversed_by_user_id", "filed_at",
    ] + COMMON,
}


def view(kind, row):
    """Serialize a row for the wire."""
    if row is None:
        return None
    out = {}
    for field in FIELDS[kind]:
        value = row.get(field)
        if isinstance(value, datetime):
            out[field] = iso(value)
        elif isinstance(value, date):
            out[field] = value.isoformat()
        elif isinstance(value, list):
            out[field] = list(value)
        else:
            out[field] = value
    if kind == "buyer":
        out["available_credit_cents"] = (
            row.get("approved_credit_limit_cents", 0)
            + row.get("wallet_credit_cents", 0)
            - row.get("outstanding_exposure_cents", 0)
        )
    return out


def views(kind, rows):
    return [view(kind, row) for row in rows]
