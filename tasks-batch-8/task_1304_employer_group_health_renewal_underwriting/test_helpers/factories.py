"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BROKER_FIRM_NAME": "Apex Benefits",
    "BROKER_LICENSE": "LIC-CA-1001",
    "BROKER_STATE": "CA",
    "BROKER_COMMISSION_PCT": 0.04,
    "GROUP_NAME": "Test Group Co",
    "GROUP_SIZE": 500,
    "SIC_CODE": "7372",
    "STATE_CODE": "CA",
    "EFFECTIVE_DATE": "2027-01-01T00:00:00Z",
    "CURRENT_PREMIUM_ANNUAL": 24000000,
    "CURRENT_RENEWAL_DATE": "2026-12-31T00:00:00Z",
    "FUNDING_TYPE": "FULLY_INSURED",
    "CENSUS_TOTAL": 500,
    "CENSUS_ENROLLED": 400,
    "CENSUS_DEPENDENTS": 250,
    "CLAIMS_START": "2024-01-01T00:00:00Z",
    "CLAIMS_END": "2025-12-31T00:00:00Z",
    "CLAIMS_TOTAL_PAID": 38400000,
    "CLAIMS_ENROLLMENT_MONTHS": 9600,
    "CLAIMS_LARGE_COUNT": 0,
    "CLAIMS_POOLING_THRESHOLD": 5000000,
    "RATE_GUARANTEE_MONTHS": 12,
    "ENROLLMENT_CHANGE_THRESHOLD": 0.1,
    "SPECIFIC_DEDUCTIBLE": 5000000,
    "AGGREGATE_ATTACHMENT_PCT": 1.25,
}


def create_broker_payload(**overrides) -> dict:
    defaults = {
        "firm_name": DEFAULTS["BROKER_FIRM_NAME"],
        "license_number": DEFAULTS["BROKER_LICENSE"],
        "state_code": DEFAULTS["BROKER_STATE"],
        "commission_pct": DEFAULTS["BROKER_COMMISSION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(broker_id, **overrides) -> dict:
    defaults = {
        "group_name": DEFAULTS["GROUP_NAME"],
        "group_size": DEFAULTS["GROUP_SIZE"],
        "sic_code": DEFAULTS["SIC_CODE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "current_premium_annual": DEFAULTS["CURRENT_PREMIUM_ANNUAL"],
        "current_renewal_date": DEFAULTS["CURRENT_RENEWAL_DATE"],
        "funding_type": DEFAULTS["FUNDING_TYPE"],
        "broker_id": broker_id,
    }
    defaults.update(overrides)
    return defaults


def create_census_payload(**overrides) -> dict:
    defaults = {
        "total_employees": DEFAULTS["CENSUS_TOTAL"],
        "enrolled_employees": DEFAULTS["CENSUS_ENROLLED"],
        "dependent_count": DEFAULTS["CENSUS_DEPENDENTS"],
        "tier_distribution": {"EE": 200, "ES": 80, "EC": 60, "EF": 60},
    }
    defaults.update(overrides)
    return defaults


def create_claims_payload(**overrides) -> dict:
    defaults = {
        "experience_period_start": DEFAULTS["CLAIMS_START"],
        "experience_period_end": DEFAULTS["CLAIMS_END"],
        "total_paid_claims_cents": DEFAULTS["CLAIMS_TOTAL_PAID"],
        "total_enrollment_months": DEFAULTS["CLAIMS_ENROLLMENT_MONTHS"],
        "large_claim_count": DEFAULTS["CLAIMS_LARGE_COUNT"],
        "pooling_threshold_cents": DEFAULTS["CLAIMS_POOLING_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_design_payload(**overrides) -> dict:
    defaults = {
        "plan_name": "Reference PPO",
        "deductible_individual": 0,
        "deductible_family": 0,
        "oop_max_individual": 200000,
        "oop_max_family": 400000,
        "coinsurance_pct": 1.0,
        "copay_primary": 0,
        "copay_specialist": 0,
        "employer_contribution_pct": 0.8,
        "contribution_strategy": "PERCENTAGE",
        "is_reference_plan": True,
    }
    defaults.update(overrides)
    return defaults


def create_buydown_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": "Buydown PPO",
        "deductible_individual": 250000,
        "deductible_family": 500000,
        "oop_max_individual": 500000,
        "oop_max_family": 1000000,
        "coinsurance_pct": 0.8,
        "copay_primary": 2500,
        "copay_specialist": 5000,
        "employer_contribution_pct": 0.75,
        "contribution_strategy": "TIERED",
        "is_reference_plan": False,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(plan_design_id, expected_case_version, **overrides) -> dict:
    defaults = {
        "plan_design_id": plan_design_id,
        "funding_type": DEFAULTS["FUNDING_TYPE"],
        "rate_guarantee_months": DEFAULTS["RATE_GUARANTEE_MONTHS"],
        "enrollment_change_threshold": DEFAULTS["ENROLLMENT_CHANGE_THRESHOLD"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(**overrides) -> dict:
    defaults = {
        "proposed_pepm_cents": 5000,
        "proposed_contribution_pct": 0.85,
        "justification": "Counter proposal for budget relief",
    }
    defaults.update(overrides)
    return defaults


def create_respond_payload(**overrides) -> dict:
    defaults = {
        "proposed_pepm_cents": 5200,
        "proposed_contribution_pct": 0.82,
        "justification": "Compensating response restoring proposal",
    }
    defaults.update(overrides)
    return defaults


def create_stop_loss_payload(**overrides) -> dict:
    defaults = {
        "specific_deductible_cents": DEFAULTS["SPECIFIC_DEDUCTIBLE"],
        "aggregate_attachment_pct": DEFAULTS["AGGREGATE_ATTACHMENT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_change_payload(quote_id, **overrides) -> dict:
    defaults = {
        "quote_id": quote_id,
        "event_type": "NEW_HIRE",
        "change_count": 40,
        "effective_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
