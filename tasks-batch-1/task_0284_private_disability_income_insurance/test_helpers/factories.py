"""Payload factories — one per entity, input fields only.

Field names mirror the PRD exactly. Each factory provides sensible defaults
and accepts **overrides. Optional fields (those with PRD-declared defaults) are
omitted from the base payload unless overridden.
"""
from .constants import TEST_DEFAULTS


def create_insurer_payload(**overrides) -> dict:
    defaults = {"name": "Test Insurer"}
    defaults.update(overrides)
    return defaults


def advance_clock_payload(by_months: int = 5, **overrides) -> dict:
    defaults = {"by_months": by_months}
    defaults.update(overrides)
    return defaults


def create_occupation_class_payload(insurer_id: str, **overrides) -> dict:
    defaults = {
        "insurer_id": insurer_id,
        "code": "MED",
        "risk_tier": "MEDIUM",
        "max_benefit_months": TEST_DEFAULTS["MAX_BENEFIT_MONTHS"],
        "min_elimination_days": 0,
        "own_occ_window_months_cap": 60,
    }
    defaults.update(overrides)
    return defaults


def create_policyholder_payload(insurer_id: str, **overrides) -> dict:
    defaults = {
        "insurer_id": insurer_id,
        "full_name": "Test Policyholder",
        "pre_disability_monthly_income_cents": TEST_DEFAULTS["PRE_DISABILITY_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(insurer_id: str, policyholder_id: str,
                          occupation_class_id: str, **overrides) -> dict:
    """Required Policy input fields. Optional fields (own_occ_window_months,
    cola_rider, cola_annual_rate) are added only via overrides."""
    defaults = {
        "insurer_id": insurer_id,
        "policyholder_id": policyholder_id,
        "occupation_class_id": occupation_class_id,
        "monthly_benefit_cents": TEST_DEFAULTS["MONTHLY_BENEFIT_CENTS"],
        "benefit_period_months": TEST_DEFAULTS["BENEFIT_PERIOD_MONTHS"],
        "elimination_period_days": TEST_DEFAULTS["ELIMINATION_PERIOD_DAYS"],
        "occupation_definition": "ANY_OCC",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(insurer_id: str, policy_id: str, **overrides) -> dict:
    defaults = {
        "insurer_id": insurer_id,
        "policy_id": policy_id,
        "disability_onset_month": 0,
        "claimed_disability_type": "TOTAL",
    }
    defaults.update(overrides)
    return defaults


def create_income_report_payload(effective_month: int, current_monthly_income_cents: int,
                                 expected_claim_version: int, **overrides) -> dict:
    defaults = {
        "effective_month": effective_month,
        "current_monthly_income_cents": current_monthly_income_cents,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def create_disability_proof_payload(attestation_month: int, still_disabled: bool = True,
                                    **overrides) -> dict:
    defaults = {
        "attestation_month": attestation_month,
        "still_disabled": still_disabled,
    }
    defaults.update(overrides)
    return defaults


def create_benefit_period_payload(coverage_month: int, **overrides) -> dict:
    defaults = {"coverage_month": coverage_month}
    defaults.update(overrides)
    return defaults


def create_offset_award_payload(offset_source: str, monthly_offset_cents: int,
                                start_month: int, end_month: int, **overrides) -> dict:
    defaults = {
        "offset_source": offset_source,
        "monthly_offset_cents": monthly_offset_cents,
        "start_month": start_month,
        "end_month": end_month,
    }
    defaults.update(overrides)
    return defaults


def finalize_offset_award_payload(**overrides) -> dict:
    """final_monthly_offset_cents is optional; omitted unless overridden."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults
