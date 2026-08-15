"""Payload factories — one per entity, input fields only (PRD section 4)."""
from .constants import TEST_DEFAULTS as D


def create_association_payload(**overrides) -> dict:
    defaults = {"name": D["ASSOCIATION_NAME"], "charter_number": D["CHARTER_NUMBER"]}
    defaults.update(overrides)
    return defaults


def declare_disaster_payload(**overrides) -> dict:
    defaults = {
        "disaster_ref": "DR-2026-07",
        "counties": [D["COUNTY"]],
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "association_id": None,
        "legal_name": D["LEGAL_NAME"],
        "tax_id": D["TAX_ID"],
        "county": D["COUNTY"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(**overrides) -> dict:
    defaults = {
        "borrower_id": None,
        "requested_commitment_cents": D["COMMITMENT_CENTS"],
        "rate_bps": D["RATE_BPS"],
        "season_year": D["SEASON_YEAR"],
        "maturity_date": D["MATURITY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def approve_loan_payload(**overrides) -> dict:
    defaults = {"approved_commitment_cents": D["COMMITMENT_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_budget_payload(**overrides) -> dict:
    defaults = {
        "loan_account_id": None,
        "season_year": D["SEASON_YEAR"],
        "crop_type": D["CROP_TYPE"],
        "acres": 1000,
        "projected_revenue_cents": 20_000_000,
        "projected_expenses_cents": 12_000_000,
        "expected_loan_version": None,
    }
    defaults.update(overrides)
    return defaults


def record_actuals_payload(**overrides) -> dict:
    defaults = {"actual_revenue_cents": 10_000_000}
    defaults.update(overrides)
    return defaults


def create_collateral_payload(**overrides) -> dict:
    defaults = {
        "loan_account_id": None,
        "collateral_type": "EQUIPMENT",
        "description": "Sprayer",
        "appraised_value_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def appraise_payload(**overrides) -> dict:
    defaults = {"appraised_value_cents": 9_000_000, "expected_collateral_version": None}
    defaults.update(overrides)
    return defaults


def create_ucc_filing_payload(**overrides) -> dict:
    defaults = {
        "collateral_id": None,
        "filing_number": "UCC-26-001",
        "jurisdiction": D["JURISDICTION"],
        "filed_date": "2026-03-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "borrower_id": None,
        "policy_number": "POL-001",
        "crop_type": D["CROP_TYPE"],
        "county": D["COUNTY"],
        "coverage_start": D["COVERAGE_START"],
        "coverage_end": D["COVERAGE_END"],
        "coverage_amount_cents": D["COVERAGE_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def assign_policy_payload(**overrides) -> dict:
    defaults = {"loan_account_id": None}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {"policy_id": None, "loan_account_id": None, "claimed_loss_cents": 3_000_000}
    defaults.update(overrides)
    return defaults


def adjuster_report_payload(**overrides) -> dict:
    defaults = {"adjuster_approved_cents": 2_000_000}
    defaults.update(overrides)
    return defaults


def create_draw_payload(**overrides) -> dict:
    defaults = {"loan_account_id": None, "amount_cents": 1_000_000, "purpose": "SEED"}
    defaults.update(overrides)
    return defaults


def create_repayment_payload(**overrides) -> dict:
    defaults = {"loan_account_id": None, "amount_cents": 1_000_000, "source": "HARVEST_PROCEEDS"}
    defaults.update(overrides)
    return defaults


def create_covenant_evaluation_payload(**overrides) -> dict:
    defaults = {
        "loan_account_id": None,
        "as_of_date": "2026-03-15T00:00:00Z",
        "current_assets_cents": 125_000,
        "current_liabilities_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "loan_account_id": None,
        "plan_type": "STANDARD",
        "amortization_style": "BALLOON",
        "extension_months": 12,
        "new_rate_bps": 600,
        "capitalize_interest": True,
        "expected_loan_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_deferral_payload(**overrides) -> dict:
    defaults = {
        "loan_account_id": None,
        "disaster_ref": "DR-2026-07",
        "requested_start": "2026-06-01T00:00:00Z",
        "requested_end": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(**overrides) -> dict:
    defaults = {"association_id": None, "fiscal_year": 2028, "pool_cents": 100_000}
    defaults.update(overrides)
    return defaults
