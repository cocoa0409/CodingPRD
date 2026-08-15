"""Payload factories — one per entity, input fields only (PRD §4)."""
from .constants import TEST_DEFAULTS as TD


def create_acquisition_payload(**overrides) -> dict:
    defaults = {
        "property_name": TD["PROPERTY_NAME"],
        "address": TD["ADDRESS"],
        "agreed_purchase_price_cents": TD["PURCHASE_PRICE_CENTS"],
        "earnest_money_cents": TD["EARNEST_MONEY_CENTS"],
        "closing_date": TD["CLOSING_DATE"],
        "diligence_deadline": TD["DILIGENCE_DEADLINE"],
        "assessment_ratio": TD["ASSESSMENT_RATIO"],
        "millage_rate": TD["MILLAGE_RATE"],
        "prior_year_tax_cents": TD["PRIOR_YEAR_TAX_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(acquisition_id, **overrides) -> dict:
    defaults = {
        "acquisition_id": acquisition_id,
        "unit_number": TD["UNIT_NUMBER"],
        "floor_plan": TD["FLOOR_PLAN"],
        "sqft": TD["SQFT"],
        "market_rent_cents": TD["MARKET_RENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_file_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "resident_name": TD["RESIDENT_NAME"],
        "lease_start_date": TD["LEASE_START"],
        "lease_end_date": TD["LEASE_END"],
        "contract_rent_cents": TD["CONTRACT_RENT_CENTS"],
        "term_months": TD["TERM_MONTHS"],
        "deposit_amount_cents": TD["DEPOSIT_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rent_roll_entry_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "reported_resident_name": TD["RESIDENT_NAME"],
        "reported_rent_cents": TD["CONTRACT_RENT_CENTS"],
        "reported_concession_cents": 0,
        "reported_deposit_cents": TD["STATED_DEPOSIT_RECONCILED_CENTS"],
        "move_in_date": TD["LEASE_START"],
    }
    defaults.update(overrides)
    return defaults


def create_concession_payload(lease_file_id, **overrides) -> dict:
    defaults = {
        "lease_file_id": lease_file_id,
        "concession_type": "RECURRING_MONTHLY",
        "value_cents": 10_000,
        "coverage_start_date": "2026-01-01T00:00:00Z",
        "coverage_end_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "inspector_ref": TD["INSPECTOR_REF"],
        "walk_start": TD["WALK_START"],
        "walk_end": TD["WALK_END"],
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(inspection_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "category": "COSMETIC",
        "severity": 2,
        "seller_estimate_cents": 100_000,
        "inspector_estimate_cents": 120_000,
    }
    defaults.update(overrides)
    return defaults


def create_utility_record_payload(acquisition_id, **overrides) -> dict:
    defaults = {
        "acquisition_id": acquisition_id,
        "period_month": "2026-07",
        "category": "ELECTRIC",
        "amount_cents": 100_000,
        "source": "SELLER_T12",
    }
    defaults.update(overrides)
    return defaults


def create_tax_projection_payload(expected_acquisition_version, **overrides) -> dict:
    defaults = {
        "method": "PURCHASE_PRICE_ANCHORED",
        "expected_acquisition_version": expected_acquisition_version,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(lease_file_id, **overrides) -> dict:
    defaults = {
        "lease_file_id": lease_file_id,
        "seller_stated_amount_cents": TD["STATED_DEPOSIT_RECONCILED_CENTS"],
        "interest_required": True,
        "annual_interest_rate": TD["ANNUAL_INTEREST_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_decision_payload(acquisition_id, **overrides) -> dict:
    defaults = {
        "acquisition_id": acquisition_id,
        "employee_ref": "emp-1",
        "position": "LEASING_MANAGER",
        "hire_date": "2020-01-01T00:00:00Z",
        "annual_salary_cents": TD["ANNUAL_SALARY_CENTS"],
        "accrued_pto_hours": TD["ACCRUED_PTO_HOURS"],
        "decision": "TERMINATE",
        "notice_date": "2026-08-10T00:00:00Z",
        "effective_date": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_contract_payload(acquisition_id, **overrides) -> dict:
    defaults = {
        "acquisition_id": acquisition_id,
        "vendor_name": "LiftCo",
        "service_type": "ELEVATOR",
        "monthly_cost_cents": 300_000,
        "term_end_date": "2026-12-31T00:00:00Z",
        "auto_renew": False,
        "cancellation_notice_days": 60,
        "cancellation_penalty_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(acquisition_id, **overrides) -> dict:
    defaults = {
        "acquisition_id": acquisition_id,
        "policy_type": "PROPERTY",
        "carrier_name": "Acme Mutual",
        "annual_premium_cents": 1_200_000,
        "expiration_date": "2027-06-30T00:00:00Z",
        "prepaid_through_date": "2027-03-31T00:00:00Z",
        "loss_run_total_cents": 100_000,
        "open_claims_count": 0,
    }
    defaults.update(overrides)
    return defaults


def generate_statement_payload(statement_type, day_count_method,
                               expected_acquisition_version) -> dict:
    return {
        "statement_type": statement_type,
        "day_count_method": day_count_method,
        "expected_acquisition_version": expected_acquisition_version,
    }


def add_statement_line_payload(expected_statement_version, **overrides) -> dict:
    defaults = {
        "expected_statement_version": expected_statement_version,
        "line_type": "ADJUSTMENT",
        "direction": "CREDIT_BUYER",
        "amount_cents": 25_000,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(acquisition_id, **overrides) -> dict:
    defaults = {
        "acquisition_id": acquisition_id,
        "adjustment_type": "EXPENSE_RECON",
        "amount_cents": 500_000,
        "direction": "CREDIT_BUYER",
    }
    defaults.update(overrides)
    return defaults
