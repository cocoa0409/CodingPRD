"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS

# Canonical matrix rules used by most scenarios: a single broad rule that makes
# any recent serious violent felony adverse-eligible.
ADVERSE_RULES = [
    {
        "offense_category": "VIOLENT_FELONY",
        "min_severity": "HIGH",
        "max_recency_years": 10,
        "action": "ADVERSE_ELIGIBLE",
    }
]

IA_RULES = [
    {
        "offense_category": "NONVIOLENT_FELONY",
        "min_severity": "LOW",
        "max_recency_years": 99,
        "action": "IA_REQUIRED",
    }
]


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Vendor",
        "base_tat_business_hours": TEST_DEFAULTS["VENDOR_BASE_TAT"],
        "max_concurrent_orders": TEST_DEFAULTS["VENDOR_MAX_CONCURRENT"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(vendor_id, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "sample_size": 10,
        "mismatches_found": 0,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Package",
        "risk_tier": TEST_DEFAULTS["RISK_TIER"],
        "check_types": ["CRIMINAL_COUNTY"],
        "tat_business_hours": TEST_DEFAULTS["PACKAGE_TAT"],
        "fee_cents": TEST_DEFAULTS["PACKAGE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_rule_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "screening_gate_stage": "ANYTIME",
        "lookback_years_limit": 7,
        "arrest_records_considerable": True,
        "lookback_exemption_salary_cents": 0,
        "pre_adverse_wait_business_days": 5,
        "individualized_assessment_required": False,
        "credit_check_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def create_matrix_payload(**overrides) -> dict:
    defaults = {
        "risk_tier": TEST_DEFAULTS["RISK_TIER"],
        "rules": list(ADVERSE_RULES),
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(package_id, **overrides) -> dict:
    defaults = {
        "title": "Analyst",
        "department": "Ops",
        "risk_tier": TEST_DEFAULTS["RISK_TIER"],
        "package_id": package_id,
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "annual_salary_cents": TEST_DEFAULTS["POSITION_SALARY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Candidate",
        "email": "candidate@example.com",
        "home_jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(candidate_id, position_id, **overrides) -> dict:
    defaults = {
        "candidate_id": candidate_id,
        "position_id": position_id,
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    defaults = {
        "disclosure_form_id": "DISC-1",
        "contains_extraneous_terms": False,
        "authorization_signed_at": "2026-08-04T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "check_type": "CRIMINAL_COUNTY",
        "offense_category": "VIOLENT_FELONY",
        "severity": "HIGH",
        "offense_date": "2024-06-01T00:00:00Z",
        "disposition": "CONVICTION",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(order_id, findings=None, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "findings": findings if findings is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "green_factor_nature_gravity": "HIGH",
        "green_factor_time_elapsed": "LOW",
        "green_factor_job_relatedness": "HIGH",
        "evidence_considered": True,
        "decision": "PROCEED_ADVERSE",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "reason": "the reported record is inaccurate",
    }
    defaults.update(overrides)
    return defaults
