"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_customer_payload(**overrides) -> dict:
    """INDIVIDUAL customer by default. Override customer_type/incorporation_date
    for a LEGAL_ENTITY (PRD §3.1)."""
    defaults = {
        "legal_name": "Test Customer",
        "customer_type": "INDIVIDUAL",
        "country_code": "US",
        "date_of_birth": "1980-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_legal_entity_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Entity",
        "customer_type": "LEGAL_ENTITY",
        "country_code": "US",
        "incorporation_date": "2010-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_risk_assessment_payload(**overrides) -> dict:
    defaults = {
        "variant": "PROVISIONAL",
        "geography_factor": 1,
        "product_factor": 1,
        "pep_factor": 1,
        "adverse_media_factor": 1,
    }
    defaults.update(overrides)
    return defaults


def create_beneficial_owner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Owner",
        "ownership_pct": 50.00,
        "country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def create_screening_hit_payload(**overrides) -> dict:
    defaults = {
        "list_type": "OFAC_SDN",
        "matched_name": "Test Match",
        "match_score": 0.97,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_ref": "AC-TEST-1",
        "opening_balance_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(**overrides) -> dict:
    defaults = {
        "direction": "CASH_IN",
        "amount_cents": 5000,
        "posted_at": "2026-06-01T08:00:00Z",
        "counterparty_country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_lookback_review_payload(**overrides) -> dict:
    defaults = {
        "reason": "Test lookback",
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-06-08T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
