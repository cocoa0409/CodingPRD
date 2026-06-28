"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_policyholder_payload(**overrides) -> dict:
    defaults = {
        "email": "holder@example.com",
        "full_name": "Test Holder",
        "residence_zip": "10001",
    }
    defaults.update(overrides)
    return defaults


def create_risk_zone_payload(**overrides) -> dict:
    defaults = {
        "zip_prefix": "100",
        "risk_band": "MODERATE",
        "rate_per_thousand_cents": 300,
    }
    defaults.update(overrides)
    return defaults


def create_repair_shop_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Jeweler",
        "service_zip": "10005",
        "in_network": True,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(policyholder_id: str, **overrides) -> dict:
    defaults = {
        "policyholder_id": policyholder_id,
        "appraised_value_cents": 2000000,
        "effective_date_iso": "2026-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(policyholder_id: str, **overrides) -> dict:
    defaults = {
        "policyholder_id": policyholder_id,
        "coverage_type": "ALL_RISK",
        "valuation_basis": "AGREED_VALUE",
        "deductible_option": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_scheduled_item_payload(**overrides) -> dict:
    defaults = {
        "description": "Test ring",
        "category": "RING",
        "location_zip": "10001",
        "scheduled_value_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(endorsement_type: str, **overrides) -> dict:
    defaults = {"endorsement_type": endorsement_type}
    defaults.update(overrides)
    return defaults


def create_claim_payload(scheduled_item_id: str, **overrides) -> dict:
    defaults = {
        "scheduled_item_id": scheduled_item_id,
        "peril": "THEFT",
        "loss_type": "TOTAL_LOSS",
        "claimed_amount_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
