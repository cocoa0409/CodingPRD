"""Payload factories — one per entity, input fields only (PRD sections 3.1-3.8)."""
import uuid

from .constants import DEFAULT_CLOCK, LIST_PRICE_FLOOR_CENTS

SUPPORTED_STATES = ["FL", "CA", "WA", "NY", "TX", "RI", "MD", "NC", "SC", "MA", "GA", "NJ"]

_hin_counter = 0


def unique_hin() -> str:
    """A fresh, globally unique 12-character uppercase alphanumeric HIN."""
    global _hin_counter
    _hin_counter += 1
    # 'US' + 10 chars drawn from an uppercase uuid hex digest, counter-mixed.
    digest = uuid.uuid4().hex.upper()
    return ("US" + digest[:8] + f"{_hin_counter % 100:02d}")[:12]


def create_brokerage_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Harbor Yacht Sales",
        "home_state_code": "FL",
        "escrow_account_ref": "TRUST-001",
        "license_no": "FL-BRK-1",
        "default_commission_tier_code": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(brokerage_id: str, **overrides) -> dict:
    defaults = {
        "brokerage_id": brokerage_id,
        "full_name": "Lena Lister",
        "license_no": "FL-AG-" + uuid.uuid4().hex[:6].upper(),
        "split_pct_basis": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "kind": "SELLER",
        "full_name": "Sally Vessel",
        "residency_state_code": "FL",
        "tax_id_last4": "1234",
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "hin": unique_hin(),
        "make": "Hatteras",
        "model": "M60",
        "year_built": 2020,
        "length_overall_ft": 40.0,
        "documentation_mode": "USCG",
        "uscg_official_no": "1234567",
        "current_location_state_code": "FL",
    }
    defaults.update(overrides)
    return defaults


def create_state_vessel_payload(**overrides) -> dict:
    """STATE-titled vessel: state_title_no carried, no uscg_official_no."""
    payload = create_vessel_payload(
        documentation_mode="STATE", state_title_no="FL-TITLE-1", **overrides
    )
    payload.pop("uscg_official_no", None)
    return payload


def create_listing_payload(
    brokerage_id: str, listing_agent_id: str, seller_id: str, vessel_id: str, **overrides
) -> dict:
    defaults = {
        "brokerage_id": brokerage_id,
        "listing_agent_id": listing_agent_id,
        "seller_id": seller_id,
        "vessel_id": vessel_id,
        "agreement_type": "CENTRAL",
        "list_price_cents": LIST_PRICE_FLOOR_CENTS,
        "start_date": "2026-08-01T00:00:00Z",
        "end_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(
    listing_id: str, buyer_id: str, selling_agent_id: str, **overrides
) -> dict:
    defaults = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "selling_agent_id": selling_agent_id,
        "offer_price_cents": 100000000,
        "deposit_pct_basis": 1000,
        "acceptance_deadline": "2026-08-10T00:00:00Z",
        "settlement_state_code": "FL",
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(expected_offer_version: int, **overrides) -> dict:
    defaults = {
        "expected_offer_version": expected_offer_version,
        "offer_price_cents": 105000000,
        "deposit_pct_basis": 1000,
        "acceptance_deadline": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_escrow_entry_payload(**overrides) -> dict:
    defaults = {
        "entry_type": "DEPOSIT",
        "amount_cents": 10000000,
        "value_date": "2026-08-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_lien_payload(**overrides) -> dict:
    defaults = {
        "lienholder_name": "Big Bank",
        "instrument_type": "UCC1",
        "amount_cents": 1000000,
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_documentation_record_payload(**overrides) -> dict:
    defaults = {
        "record_kind": "USCG_COD",
        "instrument_no": "1234567",
        "issue_date": "2026-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_syndication_event_payload(**overrides) -> dict:
    defaults = {
        "channel": "YACHTWORLD",
        "payload_price_cents": LIST_PRICE_FLOOR_CENTS,
        "outcome": "ACKED",
    }
    defaults.update(overrides)
    return defaults


def create_closing_statement_payload(offer_id: str, **overrides) -> dict:
    defaults = {
        "offer_id": offer_id,
        "rounding_mode": "PER_LINE_THEN_SUM",
    }
    defaults.update(overrides)
    return defaults


def create_title_transfer_payload(
    vessel_id: str, from_client_id: str, to_client_id: str, **overrides
) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "from_client_id": from_client_id,
        "to_client_id": to_client_id,
        "warranty_of_title": "FULL",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    return {"to_iso8601": to_iso8601}
