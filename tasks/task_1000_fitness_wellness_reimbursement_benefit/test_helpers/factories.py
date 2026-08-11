"""Payload factories — one per entity, input fields only."""
from .constants import STANDARD_TIER, TEST_DEFAULTS


def create_employer_payload(**overrides) -> dict:
    defaults = {"name": "ACME", "funding_model": "PREFUNDED"}
    defaults.update(overrides)
    return defaults


def create_plan_payload(employer_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "name": "2026 Standard",
        "benefit_year": TEST_DEFAULTS["BENEFIT_YEAR"],
        "period_start": TEST_DEFAULTS["PLAN_PERIOD_START"],
        "period_end": TEST_DEFAULTS["PLAN_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def tier_payload(**overrides) -> dict:
    defaults = dict(STANDARD_TIER)
    defaults.update(overrides)
    return defaults


def put_tiers_payload(tiers, expected_plan_version) -> dict:
    return {"tiers": tiers, "expected_plan_version": expected_plan_version}


def create_member_payload(employer_id, plan_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "plan_id": plan_id,
        "external_ref": "E1",
        "full_name": "Mem One",
        "tier_code": "INDIVIDUAL",
        "hire_date": TEST_DEFAULTS["MEMBER_HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_dependent_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dep One",
        "relationship": "SPOUSE",
        "birth_date": "1990-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "GymIn",
        "modality": "GYM",
        "network_tier": "IN_NETWORK",
        "contract_start": TEST_DEFAULTS["PROVIDER_CONTRACT_START"],
        "contract_end": TEST_DEFAULTS["PROVIDER_CONTRACT_END"],
        "visit_rate_cents": TEST_DEFAULTS["VISIT_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def put_contract_payload(expected_provider_version, **overrides) -> dict:
    defaults = {
        "contract_start": TEST_DEFAULTS["PROVIDER_CONTRACT_START"],
        "contract_end": "2026-06-30T23:59:59Z",
        "visit_rate_cents": 1600,
        "expected_provider_version": expected_provider_version,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(member_id, plan_id, **overrides) -> dict:
    defaults = {"member_id": member_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def create_visit_payload(enrollment_id, member_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "member_id": member_id,
        "check_in_at": "2026-05-02T08:00:00Z",
        "check_out_at": "2026-05-02T09:00:00Z",
        "verification_method": "GEO_FENCE",
    }
    defaults.update(overrides)
    return defaults


def line_item(unit_amount_cents, quantity=1, tax_pct=0.0, description="gym") -> dict:
    return {
        "description": description,
        "unit_amount_cents": unit_amount_cents,
        "quantity": quantity,
        "tax_pct": tax_pct,
    }


def create_claim_payload(enrollment_id, receipt_ref, amount_cents=1000, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "claim_type": "REIMBURSEMENT",
        "service_date": "2026-05-02T10:00:00Z",
        "receipt_ref": receipt_ref,
        "line_items": [line_item(amount_cents)],
    }
    defaults.update(overrides)
    return defaults


def create_funding_account_payload(employer_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "benefit_year": TEST_DEFAULTS["BENEFIT_YEAR"],
        "initial_deposit_cents": TEST_DEFAULTS["FUNDING_OPENING_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(member_id, period_yyyymm="2026-05", **overrides) -> dict:
    defaults = {"member_id": member_id, "period_yyyymm": period_yyyymm}
    defaults.update(overrides)
    return defaults
