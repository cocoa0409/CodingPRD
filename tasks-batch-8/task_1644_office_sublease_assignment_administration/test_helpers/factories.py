"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS as D


def create_party_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Landlord One LLC",
        "party_kind": "LANDLORD",
        "credit_rating_bps": D["PARTY_CREDIT_LANDLORD"],
    }
    defaults.update(overrides)
    return defaults


def create_building_payload(**overrides) -> dict:
    defaults = {
        "name": D["BUILDING_NAME"],
        "total_rentable_sf": D["BUILDING_TOTAL_RENTABLE_SF"],
        "loss_factor_bps": D["BUILDING_LOSS_FACTOR_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "base_rent_per_rsf_annual_cents": D["BASE_RENT_PER_RSF_ANNUAL_CENTS"],
        "leased_rsf": D["LEASED_RSF"],
        "consent_window_business_days": D["CONSENT_WINDOW_BUSINESS_DAYS"],
        "deemed_approval_enabled": D["DEEMED_APPROVAL_ENABLED"],
        "profit_share_tier1_pct_bps": D["TIER1_PCT_BPS"],
        "profit_share_tier1_threshold_annual_cents": D["TIER1_THRESHOLD_ANNUAL_CENTS"],
        "profit_share_tier2_pct_bps": D["TIER2_PCT_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(**overrides) -> dict:
    defaults = {
        "transfer_type": "SUBLEASE",
        "proposed_rent_per_rsf_annual_cents": D["PROPOSED_RENT_PER_RSF_ANNUAL_CENTS"],
        "term_start": D["TERM_START"],
        "term_end": D["TERM_END"],
        "marketing_period_days": D["MARKETING_PERIOD_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_demised_area_payload(**overrides) -> dict:
    defaults = {
        "measurement_standard": D["MEASUREMENT_STANDARD"],
        "usable_sf": D["USABLE_SF"],
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision: str, expected_consent_review_version: int,
                   **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_consent_review_version": expected_consent_review_version,
    }
    payload.update(overrides)
    return payload


def attest_payload(reviewed_credit_rating_bps: int = None, **overrides) -> dict:
    payload = {
        "reviewed_credit_rating_bps": (
            D["ATTESTED_CREDIT_RATING_BPS"]
            if reviewed_credit_rating_bps is None
            else reviewed_credit_rating_bps
        ),
    }
    payload.update(overrides)
    return payload


def respond_payload(response: str = "ACCEPTED") -> dict:
    return {"response": response}


def document_payload(**overrides) -> dict:
    defaults = {
        "executed_rent_per_rsf_annual_cents": D["PROPOSED_RENT_PER_RSF_ANNUAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def sign_payload(signatory: str = "LANDLORD") -> dict:
    return {"signatory": signatory}


def create_settlement_payload(**overrides) -> dict:
    defaults = {
        "period_start": D["PERIOD_START_OCT"],
        "period_end": D["PERIOD_END_NOV"],
        "subrent_collected_cents": D["SUBRENT_COLLECTED_CENTS"],
    }
    defaults.update(overrides)
    return defaults
