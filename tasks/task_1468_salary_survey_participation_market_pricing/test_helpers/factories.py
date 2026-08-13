"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "ORG_NAME": "Acme",
    "BASE_CURRENCY": "USD",
    "MARKET_AS_OF_DATE": "2026-08-01",
    "JOB_CODE": "ENG.IC3",
    "JOB_TITLE": "Sr Eng",
    "JOB_FAMILY": "ENG",
    "GEO_CODE": "US-SF",
    "ANALYST_SALARY": 10000000,
    "MANAGER_SALARY": 15000000,
    "SUBJECT_SALARY": 9000000,
    "STRATEGY_NAME": "FY26",
    "EFFECTIVE_FROM": "2026-01-01",
    "EFFECTIVE_TO": "2027-01-01",
    "VENDOR_NAME": "V1",
    "CONTRACT_START": "2026-01-01",
    "CONTRACT_END": "2027-01-01",
    "SURVEY_CODE": "S1",
    "EDITION_YEAR": 2026,
    "DATA_EFFECTIVE_DATE": "2026-01-01",
    "SUBMISSION_DEADLINE": "2026-12-31",
    "CYCLE_NAME": "2026-Q3",
    "CYCLE_EFFECTIVE_DATE": "2026-09-01",
    "CYCLE_BUDGET": 1000000,
    "REPORT_TITLE": "Q3 Committee Report",
    "PERIOD_START": "2026-07-01",
    "PERIOD_END": "2026-10-01",
}


def create_org_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ORG_NAME"],
        "base_currency": DEFAULTS["BASE_CURRENCY"],
        "market_as_of_date": DEFAULTS["MARKET_AS_OF_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_strategy_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["STRATEGY_NAME"],
        "target_percentile": 50,
        "geo_differential_policy": "NATIONAL",
        "industry_cut": "ALL_INDUSTRIES",
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(**overrides) -> dict:
    defaults = {
        "job_code": DEFAULTS["JOB_CODE"],
        "title": DEFAULTS["JOB_TITLE"],
        "job_family": DEFAULTS["JOB_FAMILY"],
        "career_level": "IC3",
        "flsa_status": "EXEMPT",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(job_id, **overrides) -> dict:
    defaults = {
        "full_name": "Subject S",
        "email": "subject@x.com",
        "job_id": job_id,
        "geo_code": DEFAULTS["GEO_CODE"],
        "base_salary_annual_cents": DEFAULTS["SUBJECT_SALARY"],
        "hire_date": "2024-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "contract_start_date": DEFAULTS["CONTRACT_START"],
        "contract_end_date": DEFAULTS["CONTRACT_END"],
        "data_use_scope": "FULL_PARTICIPATION",
        "confidentiality_tier": "CONFIDENTIAL",
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(**overrides) -> dict:
    defaults = {
        "survey_code": DEFAULTS["SURVEY_CODE"],
        "edition_year": DEFAULTS["EDITION_YEAR"],
        "data_effective_date": DEFAULTS["DATA_EFFECTIVE_DATE"],
        "submission_deadline": DEFAULTS["SUBMISSION_DEADLINE"],
        "industry_cut_supported": ["ALL_INDUSTRIES"],
    }
    defaults.update(overrides)
    return defaults


def create_benchmark_payload(**overrides) -> dict:
    defaults = {
        "benchmark_code": "B1",
        "benchmark_title": "SWE IC3",
        "career_level": "IC3",
        "industry_cut": "ALL_INDUSTRIES",
        "geo_scope": "NATIONAL",
        "p25_cents": 8000000,
        "p50_cents": 10000000,
        "p75_cents": 12500000,
        "p90_cents": 15000000,
        "sample_size": 50,
    }
    defaults.update(overrides)
    return defaults


def snapshot_entry(employee_id, job_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "job_id": job_id,
        "base_salary_annual_cents": DEFAULTS["SUBJECT_SALARY"],
        "geo_code": DEFAULTS["GEO_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(submitted_by_employee_id, incumbent_snapshot,
                              **overrides) -> dict:
    defaults = {
        "submitted_by_employee_id": submitted_by_employee_id,
        "incumbent_snapshot": incumbent_snapshot,
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(job_id, benchmark_id, proposed_by_employee_id,
                         **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "benchmark_id": benchmark_id,
        "match_confidence": "HIGH",
        "match_weight_pct": 100,
        "proposed_by_employee_id": proposed_by_employee_id,
    }
    defaults.update(overrides)
    return defaults


def create_composite_payload(strategy_policy_id, **overrides) -> dict:
    defaults = {
        "strategy_policy_id": strategy_policy_id,
        "job_geo_code": DEFAULTS["GEO_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CYCLE_NAME"],
        "effective_date": DEFAULTS["CYCLE_EFFECTIVE_DATE"],
        "budget_cents": DEFAULTS["CYCLE_BUDGET"],
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(employee_id, proposed_by_employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "proposed_amount_cents": 100000,
        "proposed_by_employee_id": proposed_by_employee_id,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(pinned_strategy_policy_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["REPORT_TITLE"],
        "reporting_period_start": DEFAULTS["PERIOD_START"],
        "reporting_period_end": DEFAULTS["PERIOD_END"],
        "pinned_strategy_policy_id": pinned_strategy_policy_id,
    }
    defaults.update(overrides)
    return defaults
