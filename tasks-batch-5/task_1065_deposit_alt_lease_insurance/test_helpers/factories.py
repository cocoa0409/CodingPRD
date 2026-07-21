"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}{next(_counter)}"


DEFAULTS = {
    "MONTHLY_RENT_CENTS": 200000,
    "COVERAGE_LIMIT_CENTS": 300000,
    "ANNUAL_INCOME_CENTS": 7200000,
    "CREDIT_PROXY_SCORE": 750,
    "MAX_MONTHLY_FEE_PCT": 0.10,
    "COOLING_OFF_BUFFER_DAYS": 30,
}


def create_landlord_payload(**overrides) -> dict:
    n = _unique("landlord")
    defaults = {
        "full_name": f"Landlord {n}",
        "email": f"{n}@example.com",
        "phone_number": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_renter_payload(**overrides) -> dict:
    n = _unique("renter")
    defaults = {
        "full_name": f"Renter {n}",
        "email": f"{n}@example.com",
        "phone_number": "555-0200",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(landlord_id: str, **overrides) -> dict:
    n = _unique("prop")
    defaults = {
        "landlord_id": landlord_id,
        "address_line1": f"{n} Main St",
        "city": "Los Angeles",
        "state_code": "CA",
        "monthly_rent_cents": DEFAULTS["MONTHLY_RENT_CENTS"],
        "property_type": "SINGLE_FAMILY",
    }
    defaults.update(overrides)
    return defaults


def create_state_compliance_rule_payload(state_code: str = "CA", **overrides) -> dict:
    defaults = {
        "state_code": state_code,
        "enrollment_allowed": True,
        "max_monthly_fee_pct_of_rent": DEFAULTS["MAX_MONTHLY_FEE_PCT"],
        "cooling_off_buffer_days": DEFAULTS["COOLING_OFF_BUFFER_DAYS"],
        "mandatory_alternative_offering": True,
    }
    defaults.update(overrides)
    return defaults


def create_renter_enrollment_payload(property_id: str, renter_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "renter_id": renter_id,
        "payment_plan": "MONTHLY",
        "requested_coverage_limit_cents": DEFAULTS["COVERAGE_LIMIT_CENTS"],
        "self_reported_annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
        "credit_proxy_score": DEFAULTS["CREDIT_PROXY_SCORE"],
        "prior_eviction_count": 0,
        "lease_start_date": "2026-07-01T00:00:00Z",
        "lease_end_date": "2027-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, claim_type: str = "PROPERTY_DAMAGE", line_items=None, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "claim_type": claim_type,
        "line_items": line_items if line_items is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_subrogation_case_payload(claim_id: str, original_demand_amount_cents: int, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "original_demand_amount_cents": original_demand_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_recovery_payment_payload(subrogation_case_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "subrogation_case_id": subrogation_case_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_limit_adjustment_payload(requested_coverage_limit_cents: int, expected_policy_version: int, **overrides) -> dict:
    defaults = {
        "requested_coverage_limit_cents": requested_coverage_limit_cents,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults
