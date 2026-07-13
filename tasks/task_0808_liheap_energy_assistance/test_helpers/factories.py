"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_funding_pool_payload(**overrides) -> dict:
    defaults = {
        "season_year": 2026,
        "program_component": "HEATING",
        "total_allocation_cents": 100_000_000,
        "depletion_threshold_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_household_payload(**overrides) -> dict:
    defaults = {
        "primary_applicant_name": "Test Applicant",
        "household_size": 3,
        "annual_income_cents": 1_700_000,
        "state_code": "CA",
        "county": "Alameda",
        "has_elderly_or_disabled": False,
        "has_child_under_6": False,
        "heating_source": "NATURAL_GAS",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(household_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "season_year": 2026,
        "program_component": "HEATING",
    }
    defaults.update(overrides)
    return defaults


def create_income_document_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "doc_type": "PAYSTUB",
        "reported_income_cents": 1_700_000,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Vendor",
        "vendor_type": "GAS",
        "remittance_account": "rmt-test-1",
    }
    defaults.update(overrides)
    return defaults


def create_utility_account_payload(household_id, vendor_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "vendor_id": vendor_id,
        "account_number": "ACCT-1",
        "service_type": "HEATING",
        "current_balance_cents": 40_000,
        "arrearage_cents": 0,
        "is_disconnected": False,
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(vendor_id, funding_pool_id, utility_account_id,
                          expected_pool_version, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "funding_pool_id": funding_pool_id,
        "utility_account_id": utility_account_id,
        "pledge_type": "HEATING",
        "pledged_amount_cents": 30_000,
        "benefit_period_start": "2026-03-01T00:00:00Z",
        "benefit_period_end": "2026-03-15T00:00:00Z",
        "expected_pool_version": expected_pool_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(pledge_id, **overrides) -> dict:
    defaults = {
        "pledge_id": pledge_id,
        "amount_cents": 30_000,
    }
    defaults.update(overrides)
    return defaults


def create_crisis_benefit_payload(household_id, utility_account_id, funding_pool_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "utility_account_id": utility_account_id,
        "funding_pool_id": funding_pool_id,
        "crisis_type": "NO_HEAT",
    }
    defaults.update(overrides)
    return defaults


def create_weatherization_referral_payload(household_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "referral_reason": "HIGH_ENERGY_BURDEN",
    }
    defaults.update(overrides)
    return defaults
