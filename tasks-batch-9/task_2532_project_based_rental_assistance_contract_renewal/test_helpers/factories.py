"""Request-payload factories. Every factory produces only input fields."""
from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "owner": {
        "legal_name": "Cedar Ridge Housing Partners LP",
        "tin": "27-3310011",
        "contact_email": "agent@cedarridge.example",
    },
    "property": {
        "project_name": "Cedar Ridge Apartments",
        "state_code": "IL",
        "total_units": 24,
        "assisted_unit_count": 20,
        "published_fmr_cents": 126000,
        "baseline_utility_allowance_cents": 11500,
        "has_fha_insured_mortgage": False,
    },
    "hap_contract": {
        "contract_type": "NEW_CONSTRUCTION",
        "expiration_date": "2027-12-31",
        "term_months": 12,
        "contract_rent_per_unit_cents": 118000,
        "monthly_debt_service_per_unit_cents": 32000,
        "operating_expense_per_unit_cents": 61000,
        "reserve_deposit_per_unit_cents": 4500,
        "authorized_hap_budget_cents": 30000000,
    },
    "study": {
        "appraiser_name": "Hollis Appraisal Group",
    },
    "comparable": {
        "address_label": "88 Alder Court",
        "raw_rent_cents": 125000,
        "adjustment_total_cents": 4650,
        "utility_adjustment_cents": 1500,
        "weight": 3,
    },
    "utility_allowance_analysis": {
        "method": "FACTOR_BASED",
        "utility_rate_change_pct": 0.09,
        "effective_date": "2026-09-01",
    },
    "tenant_household": {
        "unit_number": "101",
        "household_name": "Alvarez",
        "annual_adjusted_income_cents": 1800000,
        "annual_gross_income_cents": 1920000,
        "family_size": 3,
    },
    "tenant_certification": {
        "cert_type": "INITIAL",
        "effective_date": "2026-07-01",
    },
    "tenant_notice": {
        "notice_type": "RENEWAL_INTENT",
        "effective_date": "2027-12-31",
    },
    "voucher_submission": {
        "period_month": "2026-07",
    },
    "special_claim": {
        "claim_type": "VACANCY",
        "unit_number": "101",
        "claim_period_month": "2027-01",
        "vacancy_start_date": "2027-01-20",
    },
}


def create_owner_payload(**overrides: Any) -> dict[str, Any]:
    """Payload for owner registration: `legal_name`, `tin`, `contact_email`."""
    payload = dict(DEFAULTS["owner"])
    payload.update(overrides)
    return payload


def create_property_payload(owner_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload for property registration under `owner_id`."""
    payload = dict(DEFAULTS["property"])
    payload["owner_id"] = owner_id
    payload.update(overrides)
    return payload


def create_hap_contract_payload(property_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload recording a HAP contract on `property_id`."""
    payload = dict(DEFAULTS["hap_contract"])
    payload["property_id"] = property_id
    payload.update(overrides)
    return payload


def create_renewal_case_payload(contract_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload opening a renewal case; only `contract_id` is supplied."""
    payload: dict[str, Any] = {"contract_id": contract_id}
    payload.update(overrides)
    return payload


def select_option_payload(renewal_option: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"renewal_option": renewal_option}
    payload.update(overrides)
    return payload


def elect_adjustment_payload(adjustment_method: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"adjustment_method": adjustment_method}
    payload.update(overrides)
    return payload


def execute_renewal_payload(expected_contract_version: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"expected_contract_version": expected_contract_version}
    payload.update(overrides)
    return payload


def create_study_payload(renewal_case_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload commissioning a comparability study on `renewal_case_id`."""
    payload = dict(DEFAULTS["study"])
    payload["renewal_case_id"] = renewal_case_id
    payload.update(overrides)
    return payload


def create_comparable_payload(study_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload adding one comparable unit to a draft study."""
    payload = dict(DEFAULTS["comparable"])
    payload["study_id"] = study_id
    payload.update(overrides)
    return payload


def challenge_study_payload(
    reason: str, struck_comparable_ids: list[str], **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reason": reason,
        "struck_comparable_ids": struck_comparable_ids,
    }
    payload.update(overrides)
    return payload


def decide_study_payload(decision: str, reason: str | None = None, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def create_utility_allowance_analysis_payload(
    property_id: str, **overrides: Any
) -> dict[str, Any]:
    """Payload opening a factor-based utility allowance analysis by default."""
    payload = dict(DEFAULTS["utility_allowance_analysis"])
    payload["property_id"] = property_id
    payload.update(overrides)
    if payload.get("method") == "ENGINEERING_BASED":
        payload.pop("utility_rate_change_pct", None)
    elif payload.get("method") == "FACTOR_BASED":
        payload.pop("engineering_estimate_cents", None)
    return payload


def decide_utility_allowance_payload(
    decision: str, reason: str | None = None, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def apply_utility_allowance_payload(
    expected_property_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"expected_property_version": expected_property_version}
    payload.update(overrides)
    return payload


def create_tenant_household_payload(property_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload adding an assisted household to `property_id`."""
    payload = dict(DEFAULTS["tenant_household"])
    payload["property_id"] = property_id
    payload.update(overrides)
    return payload


def move_out_payload(move_out_date: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"move_out_date": move_out_date}
    payload.update(overrides)
    return payload


def create_tenant_certification_payload(
    tenant_id: str, expected_tenant_version: int, **overrides: Any
) -> dict[str, Any]:
    """Payload certifying a household; `expected_tenant_version` is required."""
    payload = dict(DEFAULTS["tenant_certification"])
    payload["tenant_id"] = tenant_id
    payload["expected_tenant_version"] = expected_tenant_version
    payload.update(overrides)
    return payload


def create_tenant_notice_payload(renewal_case_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload issuing a statutory notice under `renewal_case_id`."""
    payload = dict(DEFAULTS["tenant_notice"])
    payload["renewal_case_id"] = renewal_case_id
    payload.update(overrides)
    return payload


def rescind_payload(reason: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def create_restructuring_determination_payload(
    renewal_case_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"renewal_case_id": renewal_case_id}
    payload.update(overrides)
    return payload


def create_voucher_submission_payload(
    contract_id: str, expected_contract_version: int, **overrides: Any
) -> dict[str, Any]:
    """Payload opening a monthly voucher for one billing period."""
    payload = dict(DEFAULTS["voucher_submission"])
    payload["contract_id"] = contract_id
    payload["expected_contract_version"] = expected_contract_version
    payload.update(overrides)
    return payload


def reverse_voucher_payload(reason: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def create_special_claim_payload(contract_id: str, **overrides: Any) -> dict[str, Any]:
    """Payload filing a special claim; defaults to a vacancy claim."""
    payload = dict(DEFAULTS["special_claim"])
    payload["contract_id"] = contract_id
    payload.update(overrides)
    return payload


def create_vacancy_claim_payload(
    contract_id: str,
    unit_number: str,
    claim_period_month: str,
    vacancy_start_date: str,
    vacancy_end_date: str | None = None,
    estimated_vacancy_days: int | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Payload for a vacancy claim on either valuation branch."""
    payload: dict[str, Any] = {
        "contract_id": contract_id,
        "claim_type": "VACANCY",
        "unit_number": unit_number,
        "claim_period_month": claim_period_month,
        "vacancy_start_date": vacancy_start_date,
    }
    if vacancy_end_date is not None:
        payload["vacancy_end_date"] = vacancy_end_date
    if estimated_vacancy_days is not None:
        payload["estimated_vacancy_days"] = estimated_vacancy_days
    payload.update(overrides)
    return payload


def create_direct_ledger_claim_payload(
    contract_id: str,
    claim_type: str,
    unit_number: str,
    claim_period_month: str,
    claimed_amount_cents: int,
    security_deposit_balance_cents: int | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Payload for an `UNPAID_RENT` or `TENANT_DAMAGES` claim."""
    payload: dict[str, Any] = {
        "contract_id": contract_id,
        "claim_type": claim_type,
        "unit_number": unit_number,
        "claim_period_month": claim_period_month,
        "claimed_amount_cents": claimed_amount_cents,
    }
    if security_deposit_balance_cents is not None:
        payload["security_deposit_balance_cents"] = security_deposit_balance_cents
    payload.update(overrides)
    return payload


def decide_claim_payload(decision: str, reason: str | None = None, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload
