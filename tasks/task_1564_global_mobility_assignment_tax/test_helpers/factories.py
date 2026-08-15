"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROGRAM_NAME": "GM Program",
    "HOME_COUNTRY": "US",
    "EMPLOYEE_REF": "E1001",
    "EMPLOYEE_NAME": "Ada Assignee",
    "FAMILY_SIZE": 2,
    "ANNUAL_BASE_SALARY_CENTS": 10800000,
    "POLICY_NAME": "JP Standard",
    "HOST_COUNTRY": "JP",
    "POLICY_FROM": "2026-01-01",
    "POLICY_TO": "2027-12-31",
    "PER_DIEM_DAILY_CENTS": 7500,
    "HOUSING_MONTHLY_CAP_CENTS": 300000,
    "COLA_PCT": 15,
    "HOST_BU": "BU-TOKYO",
    "START_DATE": "2026-09-01",
    "PLANNED_END_DATE": "2027-08-31",
    "LETTER_TITLE": "Letter A",
    "HOME_PCT": 60,
    "HOST_PCT": 40,
    "TAX_YEAR": 2026,
    "VENDOR_NAME": "TaxCo",
    "FEE_CENTS": 500000,
    "APPLICATION_REF": "COC-1",
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "home_country_code": DEFAULTS["HOME_COUNTRY"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "employee_ref": DEFAULTS["EMPLOYEE_REF"],
        "full_name": DEFAULTS["EMPLOYEE_NAME"],
        "home_country_code": DEFAULTS["HOME_COUNTRY"],
        "family_size": DEFAULTS["FAMILY_SIZE"],
        "annual_base_salary_cents": DEFAULTS["ANNUAL_BASE_SALARY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_name": DEFAULTS["POLICY_NAME"],
        "host_country_code": DEFAULTS["HOST_COUNTRY"],
        "effective_from": DEFAULTS["POLICY_FROM"],
        "effective_to": DEFAULTS["POLICY_TO"],
        "per_diem_daily_cents": DEFAULTS["PER_DIEM_DAILY_CENTS"],
        "housing_monthly_cap_cents": DEFAULTS["HOUSING_MONTHLY_CAP_CENTS"],
        "cola_pct": DEFAULTS["COLA_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(program_id, employee_id, policy_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "employee_id": employee_id,
        "policy_id": policy_id,
        "host_country_code": DEFAULTS["HOST_COUNTRY"],
        "host_business_unit": DEFAULTS["HOST_BU"],
        "assignment_type": "LONG_TERM",
        "totalization_applies": False,
        "start_date": DEFAULTS["START_DATE"],
        "planned_end_date": DEFAULTS["PLANNED_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "letter_title": DEFAULTS["LETTER_TITLE"],
        "home_base_annual_cents": DEFAULTS["ANNUAL_BASE_SALARY_CENTS"],
        "goods_services_differential_pct": 0,
        "relocation_lump_sum_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_split_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "home_payroll_pct": DEFAULTS["HOME_PCT"],
        "host_payroll_pct": DEFAULTS["HOST_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_record_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "tax_year": DEFAULTS["TAX_YEAR"],
        "period_month": 9,
        "total_gross_cents": 900000,
        "per_diem_days": 20,
        "housing_receipts_cents": 310000,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "tax_year": DEFAULTS["TAX_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "tax_year": DEFAULTS["TAX_YEAR"],
        "scope": "DUAL",
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "fee_cents": DEFAULTS["FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "application_ref": DEFAULTS["APPLICATION_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_projection_payload(assignment_id, expected_assignment_version, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "expected_assignment_version": expected_assignment_version,
    }
    defaults.update(overrides)
    return defaults


def create_extension_payload(assignment_id, requested_new_end_date, expected_assignment_version, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "requested_new_end_date": requested_new_end_date,
        "expected_assignment_version": expected_assignment_version,
    }
    defaults.update(overrides)
    return defaults


def mark_filed_payload(filed_total_gross_cents, filed_home_tax_cents) -> dict:
    return {
        "filed_total_gross_cents": filed_total_gross_cents,
        "filed_home_tax_cents": filed_home_tax_cents,
    }


def mark_issued_payload(valid_from, valid_until) -> dict:
    return {"valid_from": valid_from, "valid_until": valid_until}


def initiate_repatriation_payload(expected_assignment_version) -> dict:
    return {"expected_assignment_version": expected_assignment_version}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
