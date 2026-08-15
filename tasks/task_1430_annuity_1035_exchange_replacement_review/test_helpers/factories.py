"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import K_STD_SCHEDULE, TEST_DEFAULTS


def create_producer_payload(**overrides) -> dict:
    defaults = {
        "license_number": TEST_DEFAULTS["PRODUCER_LICENSE"],
        "full_name": TEST_DEFAULTS["PRODUCER_NAME"],
        "home_state_code": TEST_DEFAULTS["PRODUCER_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Sue Senior",
        "date_of_birth": TEST_DEFAULTS["SENIOR_DOB"],
        "state_code": TEST_DEFAULTS["CLIENT_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(client_id: str, **overrides) -> dict:
    """Canonical in-force contract: issued 2021-09-01, value 10,000,000,
    basis 8,000,000, 7-year schedule 700..100 bps, rider base 12,000,000."""
    defaults = {
        "client_id": client_id,
        "carrier_name": TEST_DEFAULTS["CARRIER_NAME"],
        "contract_number": TEST_DEFAULTS["CONTRACT_NUMBER"],
        "issue_date": TEST_DEFAULTS["ISSUE_DATE"],
        "account_value_cents": TEST_DEFAULTS["ACCOUNT_VALUE_CENTS"],
        "tax_basis_cents": TEST_DEFAULTS["TAX_BASIS_CENTS"],
        "surrender_schedule": [dict(e) for e in K_STD_SCHEDULE],
        "living_benefit_rider": True,
        "rider_benefit_base_cents": TEST_DEFAULTS["RIDER_BENEFIT_BASE_CENTS"],
        "rider_annual_fee_bps": TEST_DEFAULTS["RIDER_ANNUAL_FEE_BPS"],
    }
    defaults.update(overrides)
    if defaults.get("living_benefit_rider") is False:
        # Rider economics only exist when a rider is attached (PRD §3.1).
        if "rider_benefit_base_cents" not in overrides:
            defaults["rider_benefit_base_cents"] = 0
        if "rider_annual_fee_bps" not in overrides:
            defaults["rider_annual_fee_bps"] = 0
    return defaults


def create_case_payload(
    producer_id: str, client_id: str, existing_contract_id: str, **overrides
) -> dict:
    defaults = {
        "producer_id": producer_id,
        "client_id": client_id,
        "existing_contract_id": existing_contract_id,
        "exchange_type": "FULL",
        "new_product_code": TEST_DEFAULTS["NEW_PRODUCT_CODE"],
        "new_product_surrender_years": TEST_DEFAULTS["NEW_PRODUCT_SURRENDER_YEARS"],
        "new_product_bonus_bps": TEST_DEFAULTS["NEW_PRODUCT_BONUS_BPS"],
        "new_product_annual_fee_bps": TEST_DEFAULTS["NEW_PRODUCT_ANNUAL_FEE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(doc_type: str = "REPLACEMENT_DISCLOSURE", **overrides) -> dict:
    defaults = {"doc_type": doc_type}
    defaults.update(overrides)
    return defaults


def create_analysis_payload(expected_case_version: int, **overrides) -> dict:
    defaults = {
        "expected_case_version": expected_case_version,
        "assumed_old_growth_bps": TEST_DEFAULTS["ASSUMED_OLD_GROWTH_BPS"],
        "assumed_new_growth_bps": TEST_DEFAULTS["ASSUMED_NEW_GROWTH_BPS"],
    }
    defaults.update(overrides)
    return defaults


def rationale_payload(rationale: str = "reviewed", **overrides) -> dict:
    defaults = {"rationale": rationale}
    defaults.update(overrides)
    return defaults
