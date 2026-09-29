"""Entity serializers — field lists come straight from SCAFFOLD §1.1."""

from datetime import datetime

from util import fmt_dt

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "seller": (
        "org_name", "seller_type", "contact_email", "settlement_account_ref",
        "default_commission_bps", "settled_net_cents",
    ),
    "asset_listing": (
        "seller_id", "street_address", "city", "county_code", "state_code",
        "estimated_value_cents", "occupancy_status", "title_condition",
        "eviction_risk_tier", "listing_status", "title_clearance_status",
        "relist_count", "second_chance_eligible", "disclosure_ack_at",
    ),
    "trustee_sale": (
        "asset_listing_id", "county_code", "sale_scheduled_at",
        "statutory_max_postponements", "postponement_count", "status",
        "confirmation_reference", "cancellation_reason",
    ),
    "auction_event": (
        "title", "county_code", "trustee_sale_id", "starts_at", "ends_at",
        "event_status", "reschedule_count", "opened_at", "lot_count",
    ),
    "auction_lot": (
        "auction_event_id", "asset_listing_id", "lot_number",
        "lot_window_start_at", "lot_window_end_at", "opening_bid_cents",
        "min_increment_cents", "reserve_price_cents", "required_deposit_cents",
        "bid_close_at", "extension_count", "current_high_bid_cents",
        "hammer_price_cents", "provisional_buyer_premium_cents", "lot_status",
        "closed_by_user_id", "closed_at",
    ),
    "bidder": (
        "legal_name", "email", "mailing_address", "identity_verification_status",
        "identity_verified_at", "registration_status", "deposit_funded_cents",
        "deposit_available_cents", "deposit_forfeited_cents", "fallout_count",
        "screen_risk_score",
    ),
    "exclusion": (
        "bidder_id", "exclusion_type", "county_code", "effective_at", "status",
        "lifted_at", "notes",
    ),
    "deposit_hold": (
        "bidder_id", "auction_lot_id", "amount_cents", "status", "expires_at",
        "extension_count", "released_reason",
    ),
    "bid": (
        "auction_lot_id", "bidder_id", "amount_cents", "placed_at",
        "bid_status", "is_above_reserve", "triggered_extension",
    ),
    "sale_contract": (
        "auction_lot_id", "winning_bidder_id", "contract_price_cents",
        "final_buyer_premium_cents", "doc_fee_cents", "total_due_cents",
        "closing_window_days", "closing_deadline_at", "contract_status",
        "execution_at", "executed_by_user_id", "settlement_status",
        "settlement_gross_cents", "seller_net_cents", "platform_fee_cents",
        "buyer_premium_cents", "forfeited_deposit_cents",
        "forfeiture_seller_net_cents", "forfeiture_platform_fee_cents",
        "fallout_reason", "closing_reference", "closed_at", "fallout_at",
    ),
    "offer": (
        "auction_lot_id", "offered_bidder_id", "offer_price_cents",
        "expires_at", "status", "responded_at",
    ),
}


def _value(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    return v


def dump(kind, rec):
    out = {}
    for key in COMMON:
        out[key] = _value(rec.get(key))
    for key in FIELDS[kind]:
        out[key] = _value(rec.get(key))
    return out


def dump_many(kind, recs):
    return [dump(kind, r) for r in recs]
