"""Payload factories — one per entity, input fields only."""
from .constants import PROGRAM_DEFAULTS


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "CA ABLE",
        "state_code": "CA",
        "annual_contribution_cap_cents": PROGRAM_DEFAULTS["annual_contribution_cap_cents"],
        "able_to_work_fpl_cents": PROGRAM_DEFAULTS["able_to_work_fpl_cents"],
        "ssi_suspension_threshold_cents": PROGRAM_DEFAULTS["ssi_suspension_threshold_cents"],
        "ssi_resource_limit_cents": PROGRAM_DEFAULTS["ssi_resource_limit_cents"],
        "program_fee_bps": PROGRAM_DEFAULTS["program_fee_bps"],
        "nonqualified_additional_tax_pct": PROGRAM_DEFAULTS["nonqualified_additional_tax_pct"],
        "max_investment_changes_per_year": PROGRAM_DEFAULTS["max_investment_changes_per_year"],
        "disability_onset_max_age": PROGRAM_DEFAULTS["disability_onset_max_age"],
    }
    defaults.update(overrides)
    return defaults


def create_investment_option_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Moderate",
        "risk_tier": "MODERATE",
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "full_name": "Test Beneficiary",
        "birth_date": "2005-03-01",
        "disability_onset_date": "2018-06-01",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "basis": "SSI_SSDI_ENTITLEMENT",
        "effective_date": "2026-01-01",
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(beneficiary_id, investment_option_id, **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "investment_option_id": investment_option_id,
    }
    defaults.update(overrides)
    return defaults


def create_representative_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Representative",
        "relationship": "PARENT",
        "authority_start": "2026-01-01",
        "authority_end": "2030-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(amount_cents, expected_account_version, **overrides) -> dict:
    defaults = {
        "contribution_type": "REGULAR",
        "amount_cents": amount_cents,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "category": "HEALTH",
    }
    defaults.update(overrides)
    return defaults


def create_qde_record_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "expense_category": "HEALTH",
        "amount_cents": amount_cents,
        "receipt_reference": "R-1",
        "expense_date": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_medicaid_claim_payload(claimed_amount_cents, **overrides) -> dict:
    defaults = {
        "claimed_amount_cents": claimed_amount_cents,
    }
    defaults.update(overrides)
    return defaults
