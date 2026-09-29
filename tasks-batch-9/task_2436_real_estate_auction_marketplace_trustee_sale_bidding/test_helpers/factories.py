"""Payload factories — one per write endpoint, carrying only client-supplied fields.

Each factory fills the required fields with a plausible default and lets a test
override any of them with a keyword argument. Optional fields are omitted unless
a test passes them, so the PRD's declared defaults are exercised by default.
"""

from .constants import (
    COUNTY_PRIMARY,
    EVENT_END,
    EVENT_START,
    LOT_WINDOW_END,
    LOT_WINDOW_START,
    STATE_CODE,
)

DEFAULTS = {
    "ORG_NAME": "Coastline Bank REO",
    "SELLER_TYPE": "BANK",
    "CONTACT_EMAIL": "reo@coastline.example",
    "SETTLEMENT_ACCOUNT_REF": "ACH-COAST-5",
    "STREET_ADDRESS": "9 Seaview Ter",
    "CITY": "Alameda",
    "ESTIMATED_VALUE_CENTS": 29000000,
    "TITLE_REPORT_REFERENCE": "TR-0001",
    "CONFIRMATION_REFERENCE": "TS-ALA-7302",
    "POSTPONEMENT_REASON": "county calendar congestion",
    "CANCELLATION_REASON": "notice rescinded by beneficiary",
    "EVENT_TITLE": "Alameda REO Session",
    "OPENING_BID_CENTS": 20000000,
    "RESERVE_PRICE_CENTS": 20000000,
    "BIDDER_LEGAL_NAME": "Seaview Acquisitions LLC",
    "BIDDER_EMAIL": "bid@seaviewacq.example",
    "MAILING_ADDRESS": "2 Ferry Point, Alameda CA",
    "DOCUMENT_REFERENCE": "KYC-5151",
    "FUNDING_REFERENCE": "WIRE-13579",
    "EXCLUSION_NOTES": "county affiliate screening hit",
    "CLOSING_REFERENCE": "ESC-2026-4471",
    "FALLOUT_REASON": "buyer financing collapsed",
}


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_seller_payload(**overrides) -> dict:
    payload = {
        "org_name": DEFAULTS["ORG_NAME"],
        "seller_type": DEFAULTS["SELLER_TYPE"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "settlement_account_ref": DEFAULTS["SETTLEMENT_ACCOUNT_REF"],
    }
    payload.update(overrides)
    return payload


def create_asset_listing_payload(seller_id: str, **overrides) -> dict:
    payload = {
        "seller_id": seller_id,
        "street_address": DEFAULTS["STREET_ADDRESS"],
        "city": DEFAULTS["CITY"],
        "county_code": COUNTY_PRIMARY,
        "state_code": STATE_CODE,
        "estimated_value_cents": DEFAULTS["ESTIMATED_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def disclosures_payload(
    occupancy_status: str = "VACANT", title_condition: str = "CLEAR", **overrides
) -> dict:
    payload = {"occupancy_status": occupancy_status, "title_condition": title_condition}
    payload.update(overrides)
    return payload


def title_clearance_payload(
    clearance_outcome: str = "CLEARED",
    verified_title_condition: str = "CLEAR",
    **overrides,
) -> dict:
    payload = {
        "clearance_outcome": clearance_outcome,
        "verified_title_condition": verified_title_condition,
        "title_report_reference": DEFAULTS["TITLE_REPORT_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def relist_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def create_trustee_sale_payload(
    asset_listing_id: str, sale_scheduled_at: str, **overrides
) -> dict:
    payload = {
        "asset_listing_id": asset_listing_id,
        "county_code": COUNTY_PRIMARY,
        "sale_scheduled_at": sale_scheduled_at,
    }
    payload.update(overrides)
    return payload


def confirm_trustee_sale_payload(**overrides) -> dict:
    payload = {"confirmation_reference": DEFAULTS["CONFIRMATION_REFERENCE"]}
    payload.update(overrides)
    return payload


def postpone_trustee_sale_payload(new_sale_at: str, **overrides) -> dict:
    payload = {
        "new_sale_at": new_sale_at,
        "postponement_reason": DEFAULTS["POSTPONEMENT_REASON"],
    }
    payload.update(overrides)
    return payload


def cancel_trustee_sale_payload(**overrides) -> dict:
    payload = {"cancellation_reason": DEFAULTS["CANCELLATION_REASON"]}
    payload.update(overrides)
    return payload


def create_auction_event_payload(**overrides) -> dict:
    payload = {
        "title": DEFAULTS["EVENT_TITLE"],
        "county_code": COUNTY_PRIMARY,
        "starts_at": EVENT_START,
        "ends_at": EVENT_END,
    }
    payload.update(overrides)
    return payload


def add_lot_payload(
    asset_listing_id: str,
    expected_auction_event_version: int,
    lot_number: int = 1,
    **overrides,
) -> dict:
    payload = {
        "asset_listing_id": asset_listing_id,
        "lot_number": lot_number,
        "lot_window_start_at": LOT_WINDOW_START,
        "lot_window_end_at": LOT_WINDOW_END,
        "opening_bid_cents": DEFAULTS["OPENING_BID_CENTS"],
        "reserve_price_cents": DEFAULTS["RESERVE_PRICE_CENTS"],
        "expected_auction_event_version": expected_auction_event_version,
    }
    payload.update(overrides)
    return payload


def reserve_price_payload(
    reserve_price_cents: int, expected_auction_lot_version: int, **overrides
) -> dict:
    payload = {
        "reserve_price_cents": reserve_price_cents,
        "expected_auction_lot_version": expected_auction_lot_version,
    }
    payload.update(overrides)
    return payload


def open_event_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def reschedule_payload(new_starts_at: str, new_ends_at: str, **overrides) -> dict:
    payload = {"new_starts_at": new_starts_at, "new_ends_at": new_ends_at}
    payload.update(overrides)
    return payload


def create_bidder_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["BIDDER_LEGAL_NAME"],
        "email": DEFAULTS["BIDDER_EMAIL"],
        "mailing_address": DEFAULTS["MAILING_ADDRESS"],
    }
    payload.update(overrides)
    return payload


def identity_verification_payload(decision: str = "VERIFIED", **overrides) -> dict:
    payload = {"decision": decision, "document_reference": DEFAULTS["DOCUMENT_REFERENCE"]}
    payload.update(overrides)
    return payload


def fund_deposit_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "funding_reference": DEFAULTS["FUNDING_REFERENCE"]}
    payload.update(overrides)
    return payload


def create_exclusion_payload(
    bidder_id: str, exclusion_type: str, effective_at: str, **overrides
) -> dict:
    payload = {
        "bidder_id": bidder_id,
        "exclusion_type": exclusion_type,
        "effective_at": effective_at,
    }
    payload.update(overrides)
    return payload


def lift_exclusion_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def place_bid_payload(bidder_id: str, amount_cents: int, **overrides) -> dict:
    payload = {"bidder_id": bidder_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def close_lot_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def sale_contract_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def close_contract_payload(**overrides) -> dict:
    payload = {"closing_reference": DEFAULTS["CLOSING_REFERENCE"]}
    payload.update(overrides)
    return payload


def fallout_payload(**overrides) -> dict:
    payload = {"fallout_reason": DEFAULTS["FALLOUT_REASON"]}
    payload.update(overrides)
    return payload


def second_chance_offer_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def respond_to_offer_payload(decision: str = "ACCEPTED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload
