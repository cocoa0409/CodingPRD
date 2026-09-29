"""Payload factories - one per write endpoint, carrying only input fields."""

from .constants import (
    AUCTION_OPENING_BID_CENTS,
    AUCTION_RESERVE_PRICE_CENTS,
    AUCTION_WINDOW_END,
    AUCTION_WINDOW_START,
    CANONICAL_BUYER_TAX_ID,
    CANONICAL_CREDIT_LIMIT_CENTS,
    CANONICAL_SCAC_CODE,
    CANONICAL_SELLER_TAX_ID,
    DEFAULT_BID_INCREMENT_CENTS,
)


def seller_account_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Northline Returns LLC",
        "tax_id": CANONICAL_SELLER_TAX_ID,
        "state_code": "OH",
        "contact_email": "ops@northline-returns.example",
    }
    payload.update(overrides)
    return payload


def buyer_account_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Gulf Resale Co",
        "tax_id": CANONICAL_BUYER_TAX_ID,
        "state_code": "TX",
        "contact_email": "buying@gulfresale.example",
        "resale_certificate_number": "TX-RC-77",
        "resale_certificate_expires_on": "2027-01-31",
        "requested_credit_limit_cents": CANONICAL_CREDIT_LIMIT_CENTS,
    }
    payload.update(overrides)
    return payload


def qualification_decision_payload(decision="QUALIFY", **overrides) -> dict:
    payload = {"decision": decision, "business_verified": True}
    payload.update(overrides)
    return payload


def credit_limit_payload(approved_credit_limit_cents=CANONICAL_CREDIT_LIMIT_CENTS,
                        **overrides) -> dict:
    payload = {"approved_credit_limit_cents": approved_credit_limit_cents}
    payload.update(overrides)
    return payload


def warehouse_payload(**overrides) -> dict:
    payload = {
        "name": "Columbus DC",
        "state_code": "OH",
        "dock_door_count": 2,
        "turnaround_buffer_minutes": 15,
    }
    payload.update(overrides)
    return payload


def carrier_payload(**overrides) -> dict:
    payload = {
        "name": "Keystone Freight",
        "scac_code": CANONICAL_SCAC_CODE,
        "daily_pickup_capacity": 5,
    }
    payload.update(overrides)
    return payload


def brand_policy_payload(brand_code="ARCLIGHT",
                        permitted_channels=None, **overrides) -> dict:
    payload = {
        "brand_code": brand_code,
        "permitted_channels": permitted_channels or ["MARKETPLACE_RESALE", "DISCOUNT_RETAIL"],
    }
    payload.update(overrides)
    return payload


def lot_payload(seller_id, warehouse_id, **overrides) -> dict:
    payload = {
        "seller_id": seller_id,
        "warehouse_id": warehouse_id,
        "title": "Mixed apparel customer returns",
        "category_code": "APPAREL",
        "condition_grade": "CUSTOMER_RETURNS",
    }
    payload.update(overrides)
    return payload


def manifest_line_payload(**overrides) -> dict:
    payload = {
        "sku": "APP-RET-0001",
        "unit_count": 100,
        "unit_retail_cents": 40_000,
        "declared_condition": "USED_GOOD",
    }
    payload.update(overrides)
    return payload


def manifest_review_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def auction_listing_payload(**overrides) -> dict:
    payload = {
        "listing_format": "AUCTION",
        "resale_channel": "MARKETPLACE_RESALE",
        "window_start_at": AUCTION_WINDOW_START,
        "window_end_at": AUCTION_WINDOW_END,
        "opening_bid_cents": AUCTION_OPENING_BID_CENTS,
        "reserve_price_cents": AUCTION_RESERVE_PRICE_CENTS,
        "bid_increment_cents": DEFAULT_BID_INCREMENT_CENTS,
    }
    payload.update(overrides)
    return payload


def fixed_price_listing_payload(ask_price_cents=1_000_000, **overrides) -> dict:
    payload = {
        "listing_format": "FIXED_PRICE",
        "resale_channel": "MARKETPLACE_RESALE",
        "window_start_at": AUCTION_WINDOW_START,
        "window_end_at": "2026-08-20T00:00:00Z",
        "ask_price_cents": ask_price_cents,
    }
    payload.update(overrides)
    return payload


def negotiated_listing_payload(min_offer_cents=900_000, **overrides) -> dict:
    payload = {
        "listing_format": "NEGOTIATED",
        "resale_channel": "MARKETPLACE_RESALE",
        "window_start_at": AUCTION_WINDOW_START,
        "window_end_at": "2026-08-20T00:00:00Z",
        "min_offer_cents": min_offer_cents,
    }
    payload.update(overrides)
    return payload


def bid_payload(buyer_id, amount_cents, **overrides) -> dict:
    payload = {"buyer_id": buyer_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def proxy_bid_payload(buyer_id, max_amount_cents, expected_listing_version,
                     **overrides) -> dict:
    payload = {
        "buyer_id": buyer_id,
        "max_amount_cents": max_amount_cents,
        "expected_listing_version": expected_listing_version,
    }
    payload.update(overrides)
    return payload


def negotiation_payload(buyer_id, opening_offer_cents, **overrides) -> dict:
    payload = {"buyer_id": buyer_id, "opening_offer_cents": opening_offer_cents}
    payload.update(overrides)
    return payload


def counter_offer_payload(amount_cents, expected_negotiation_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_negotiation_version": expected_negotiation_version,
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def pickup_appointment_payload(warehouse_id, carrier_id, window_start_at,
                              window_end_at, bol_number="BOL-0001", **overrides) -> dict:
    payload = {
        "warehouse_id": warehouse_id,
        "carrier_id": carrier_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "bol_number": bol_number,
    }
    payload.update(overrides)
    return payload


def completion_payload(actual_freight_cents, picked_up_unit_count, **overrides) -> dict:
    payload = {
        "actual_freight_cents": actual_freight_cents,
        "picked_up_unit_count": picked_up_unit_count,
    }
    payload.update(overrides)
    return payload


def claim_payload(manifest_line_id, claim_type="UNIT_SHORTAGE", claimed_units=80,
                 evidence_urls=None, **overrides) -> dict:
    payload = {
        "manifest_line_id": manifest_line_id,
        "claim_type": claim_type,
        "claimed_units": claimed_units,
    }
    if evidence_urls is not None:
        payload["evidence_urls"] = evidence_urls
    payload.update(overrides)
    return payload


def claim_decision_payload(decision, verified_units=None, **overrides) -> dict:
    payload = {"decision": decision}
    if verified_units is not None:
        payload["verified_units"] = verified_units
    payload.update(overrides)
    return payload


def claim_reversal_payload(reversal_reason="evidence was attributed to another lot",
                          **overrides) -> dict:
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


def clock_payload(current_utc) -> dict:
    return {"current_utc": current_utc}
