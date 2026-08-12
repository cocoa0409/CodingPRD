"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Program",
        "ami_table_effective_date": "2026-05-01T00:00:00Z",
        "area_median_income_cents": TEST_DEFAULTS["AREA_MEDIAN_INCOME_CENTS"],
        "max_eligibility_ami_pct": TEST_DEFAULTS["MAX_ELIGIBILITY_AMI_PCT"],
        "ground_lease_base_fee_cents": TEST_DEFAULTS["GROUND_LEASE_BASE_FEE_CENTS"],
        "resale_formula_kind": "INDEXED",
    }
    defaults.update(overrides)
    return defaults


def create_household_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Household",
        "household_size": 4,
        "annual_gross_income_cents": 7_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_income_certification_payload(**overrides) -> dict:
    defaults = {
        "tax_year": 2025,
        "reported_annual_income_cents": 7_000_000,
        "verified_annual_income_cents": 7_000_000,
        "household_size_at_cert": 4,
    }
    defaults.update(overrides)
    return defaults


def create_education_course_payload(**overrides) -> dict:
    defaults = {
        "code": "HOME-101",
        "title": "Homebuyer Basics",
        "credit_hours": 8,
        "is_required": True,
        "validity_months": 24,
    }
    defaults.update(overrides)
    return defaults


def create_education_completion_payload(**overrides) -> dict:
    defaults = {
        "course_id": "",
        "completed_at": "2026-04-01T00:00:00Z",
        "score_pct": 0.9,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "address": "1 Main St",
        "bedrooms": 3,
        "original_subsidy_cents": TEST_DEFAULTS["ORIGINAL_SUBSIDY_CENTS"],
        "original_sale_price_cents": TEST_DEFAULTS["ORIGINAL_SALE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "household_id": "",
        "start_date": "2026-05-01T00:00:00Z",
        "purchase_price_cents": TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_default_notice_payload(**overrides) -> dict:
    defaults = {
        "notice_kind": "FEE_ARREARS",
        "amount_due_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "scheduled_for": "2026-05-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(**overrides) -> dict:
    defaults = {
        "desired_bedrooms": 3,
        "max_price_cents": 50_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_resale_listing_payload(**overrides) -> dict:
    defaults = {
        "seller_lease_id": "",
        "appraisal_at_listing_cents": 25_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_refinance_request_payload(**overrides) -> dict:
    defaults = {
        "lender_name": "Test Bank",
        "requested_loan_cents": 15_000_000,
        "requested_cash_out_cents": 0,
        "appraised_value_cents": 20_000_000,
    }
    defaults.update(overrides)
    return defaults
