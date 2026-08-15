"""Payload factories — one per entity, input fields only.

Every factory accepts **overrides so tests can control exactly the knobs the
claim under test needs. Unique-ish suffixes keep naic_code / license_number
from colliding inside a single test's database.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_carrier_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "name": f"Carrier {n}",
        "naic_code": f"NAIC-{n:06d}",
        "contact_email": f"uw{n}@carrier.example.com",
    }
    defaults.update(overrides)
    return defaults


def create_tpa_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "name": f"TPA {n}",
        "license_number": f"LIC-{n:06d}",
        "contact_email": f"ops{n}@tpa.example.com",
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(carrier_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "carrier_id": carrier_id,
        "name": f"Program {n}",
        "line_of_business": "GENERAL_LIABILITY",
        "states_covered": ["CA"],
        "inception_date": "2026-08-01T00:00:00Z",
        "aggregate_limit_cents": TEST_DEFAULTS["AGGREGATE_LIMIT_CENTS"],
        "commission_rate_pct": TEST_DEFAULTS["COMMISSION_RATE_PCT"],
        "corrective_threshold_pct": TEST_DEFAULTS["CORRECTIVE_THRESHOLD_PCT"],
        "termination_threshold_pct": TEST_DEFAULTS["TERMINATION_THRESHOLD_PCT"],
        "min_trust_balance_cents": TEST_DEFAULTS["MIN_TRUST_BALANCE_CENTS"],
        "min_earned_premium_for_ratio_cents": TEST_DEFAULTS["MIN_EARNED_PREMIUM_FOR_RATIO_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_guideline_payload(expected_program_version: int, **overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "class_code": "ARTISAN",
        "max_policy_premium_cents": TEST_DEFAULTS["GUIDELINE_MAX_PREMIUM_CENTS"],
        "max_policy_limit_cents": TEST_DEFAULTS["GUIDELINE_MAX_LIMIT_CENTS"],
        "min_policy_premium_cents": TEST_DEFAULTS["GUIDELINE_MIN_PREMIUM_CENTS"],
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(expected_program_version: int, **overrides) -> dict:
    defaults = {
        "period_label": "2026-Q3",
        "allocated_cents": TEST_DEFAULTS["TRANCHE_ALLOCATED_CENTS"],
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_rate_filing_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "filing_type": "RATE",
        "base_rates": {"ARTISAN": TEST_DEFAULTS["BASE_RATE_CENTS"]},
        "policy_fee_cents": TEST_DEFAULTS["POLICY_FEE_CENTS"],
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "insured_name": f"Insured {n}",
        "state_code": "CA",
        "class_code": "ARTISAN",
        "exposure_units": 100,
        "coverage_limit_cents": 500000,
        "experience_mod": 1.0,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "LIABILITY",
        "occurrence_date": "2026-08-10T00:00:00Z",
        "amount_claimed_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(tpa_id: str, **overrides) -> dict:
    defaults = {
        "tpa_id": tpa_id,
        "claim_type": "LIABILITY",
        "authority_limit_cents": TEST_DEFAULTS["APPOINTMENT_AUTHORITY_LIMIT_CENTS"],
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bordereau_payload(**overrides) -> dict:
    defaults = {
        "bordereau_type": "PREMIUM",
        "period_label": "2026-08",
        "due_date": "2026-09-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "scope": "FULL",
        "scheduled_start": "2026-09-01T00:00:00Z",
        "scheduled_end": "2026-09-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
