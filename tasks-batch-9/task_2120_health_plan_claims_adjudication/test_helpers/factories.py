"""Payload factories — one per write endpoint, client-supplied fields only."""
from typing import List, Optional

from .constants import TEST_DEFAULTS


def create_benefit_plan_payload(**overrides) -> dict:
    """The five fields a benefit plan always requires; the other five are optional."""
    defaults = {
        "plan_code": "PLAN-1",
        "name": "Test Benefit Plan",
        "deductible_individual_cents": TEST_DEFAULTS["DEDUCTIBLE_CENTS"],
        "oop_max_individual_cents": TEST_DEFAULTS["OOP_MAX_CENTS"],
        "coinsurance_member_pct": TEST_DEFAULTS["COINSURANCE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_rate_payload(**overrides) -> dict:
    defaults = {
        "procedure_code": "73721",
        "allowed_amount_cents": TEST_DEFAULTS["RATE_IMAGING_CENTS"],
        "effective_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "member_number": "M-1",
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(**overrides) -> dict:
    """member_id is taken from the URL and is never read from the body."""
    defaults = {
        "effective_date": "2026-01-01",
        "cob_order": "PRIMARY",
    }
    defaults.update(overrides)
    return defaults


def terminate_coverage_payload(term_date: str) -> dict:
    return {"term_date": term_date}


def create_accumulator_adjustment_payload(
    expected_accumulator_version: int,
    deductible_delta_cents: int = 0,
    oop_delta_cents: int = 0,
    **overrides,
) -> dict:
    defaults = {
        "expected_accumulator_version": expected_accumulator_version,
        "deductible_delta_cents": deductible_delta_cents,
        "oop_delta_cents": oop_delta_cents,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": "1000000001",
        "name": "Test Provider",
        "network_status": "IN_NETWORK",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(provider_id: str, plan_id: str, **overrides) -> dict:
    """The companion field follows pricing_method: a percent-of-fee-schedule contract
    carries contract_pct, a case-rate contract carries case_rate_cents. Pass either
    explicitly as None to omit it from the body."""
    defaults = {
        "provider_id": provider_id,
        "plan_id": plan_id,
        "effective_date": "2026-01-01",
        "term_date": "2026-12-31",
        "pricing_method": "PCT_OF_FEE_SCHEDULE",
    }
    defaults.update(overrides)
    if defaults["pricing_method"] == "CASE_RATE":
        if "contract_pct" not in overrides:
            defaults.setdefault("case_rate_cents", 50000)
    else:
        if "case_rate_cents" not in overrides:
            defaults.setdefault("contract_pct", 0.900)
    return {key: value for key, value in defaults.items() if value is not None}


def terminate_contract_payload(term_date: str) -> dict:
    return {"term_date": term_date}


def create_edit_rule_payload(**overrides) -> dict:
    defaults = {
        "rule_code": "RULE-1",
        "edit_type": "AUTH_REQUIRED",
        "primary_code": "73721",
        "severity": "PEND",
        "precedence_rank": 30,
        "reason_code": "PEND_AUTH_MISSING",
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(member_id: str, provider_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "provider_id": provider_id,
        "procedure_code": "73721",
        "authorized_units": 4,
        "valid_from": "2026-01-01",
        "valid_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def claim_line_payload(
    line_number: int,
    procedure_code: str = "73721",
    units: int = 1,
    billed_amount_cents: int = 60000,
    service_date: str = "2026-02-10",
    modifier_code: Optional[str] = None,
) -> dict:
    """One element of a claim's lines array."""
    line = {
        "line_number": line_number,
        "procedure_code": procedure_code,
        "units": units,
        "billed_amount_cents": billed_amount_cents,
        "service_date": service_date,
    }
    if modifier_code is not None:
        line["modifier_code"] = modifier_code
    return line


def create_claim_payload(
    member_id: str,
    provider_id: str,
    lines: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    defaults = {
        "claim_number": "CLM-1",
        "member_id": member_id,
        "provider_id": provider_id,
        "lines": lines if lines is not None else [claim_line_payload(1)],
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(
    claim_number: str, lines: List[dict], **overrides
) -> dict:
    defaults = {
        "claim_number": claim_number,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def override_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def other_payer_payment_payload(
    other_payer_paid_cents: int, expected_claim_version: int
) -> dict:
    return {
        "other_payer_paid_cents": other_payer_paid_cents,
        "expected_claim_version": expected_claim_version,
    }


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
