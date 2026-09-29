"""Payload builders with valid defaults and keyword overrides.

Every factory produces a body that the API accepts as-is; individual tests
override only the field under examination. ``None`` is never injected
automatically - to probe a missing required field, pop the key.
"""

from __future__ import annotations

import itertools
from typing import Any

from .constants import (
    STANDARD_AVERAGE_TICKET_CENTS,
    STANDARD_COUNTRY_CODE,
    STANDARD_CREDIT_SCORE,
    STANDARD_MCC_CODE,
    STANDARD_MONTHLY_VOLUME_CENTS,
    STANDARD_PRIOR_HISTORY_MONTHS,
)

_tax_id_counter = itertools.count(1)


def next_tax_id() -> str:
    """A fresh well-formed tax id (``^[0-9]{2}-[0-9]{7}$``)."""
    return f"88-{next(_tax_id_counter):07d}"


def application_payload(**overrides: Any) -> dict[str, Any]:
    """A complete, acceptable merchant application body."""
    payload: dict[str, Any] = {
        "legal_business_name": "Harborline Goods",
        "tax_id": next_tax_id(),
        "mcc_code": STANDARD_MCC_CODE,
        "country_code": STANDARD_COUNTRY_CODE,
        "requested_monthly_volume_cents": STANDARD_MONTHLY_VOLUME_CENTS,
        "average_ticket_cents": STANDARD_AVERAGE_TICKET_CENTS,
        "avg_delivery_lag_days": 0,
        "declared_chargeback_ratio_bps": 0,
        "prior_processing_history_months": STANDARD_PRIOR_HISTORY_MONTHS,
        "credit_score": STANDARD_CREDIT_SCORE,
    }
    payload.update(overrides)
    return payload


def beneficial_owner_payload(application_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "application_id": application_id,
        "full_name": "Dana Reyes",
        "ownership_pct": 100.00,
        "country_code": "US",
        "date_of_birth": "1980-05-05",
        "government_id_last4": "1234",
    }
    payload.update(overrides)
    return payload


def screening_payload(**overrides: Any) -> dict[str, Any]:
    """A clean screening result: no sanctions hit, no PEP flag, id verified."""
    payload: dict[str, Any] = {"sanctions_hit": False, "pep_flag": False, "id_verified": True}
    payload.update(overrides)
    return payload


def verification_payload(application_id: str, **overrides: Any) -> dict[str, Any]:
    """All four KYB checks matching."""
    payload: dict[str, Any] = {
        "application_id": application_id,
        "registry_match": True,
        "address_match": True,
        "tax_id_match": True,
        "bank_account_match": True,
    }
    payload.update(overrides)
    return payload


def credit_assessment_payload(
    application_id: str, expected_application_version: int, method: str = "LAG_WEIGHTED", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "application_id": application_id,
        "method": method,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def category_rule_payload(mcc_code: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mcc_code": mcc_code,
        "category": "GAMBLING",
        "disposition": "PROHIBITED",
    }
    payload.update(overrides)
    return payload


def day_activity_payload(merchant_id: str, business_date: str, **overrides: Any) -> dict[str, Any]:
    """A clean trading day: 1000 transactions, 1 000 000 cents, no chargebacks."""
    payload: dict[str, Any] = {
        "merchant_id": merchant_id,
        "business_date": business_date,
        "txn_count": 1000,
        "volume_cents": 1_000_000,
        "decline_count": 10,
        "distinct_card_count": 950,
        "cross_border_count": 0,
        "refund_cents": 0,
        "unique_bin_count": 300,
        "chargeback_count": 0,
        "chargeback_amount_cents": 0,
    }
    payload.update(overrides)
    return payload


def settlement_batch_payload(
    merchant_id: str, period_start_date: str, period_end_date: str, gross_volume_cents: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "merchant_id": merchant_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "gross_volume_cents": gross_volume_cents,
    }
    payload.update(overrides)
    return payload


def release_request_payload(
    amount_cents: int,
    tranche_start_date: str,
    tranche_end_date: str,
    expected_reserve_account_version: int,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "amount_cents": amount_cents,
        "tranche_start_date": tranche_start_date,
        "tranche_end_date": tranche_end_date,
        "expected_reserve_account_version": expected_reserve_account_version,
    }
    payload.update(overrides)
    return payload


def remediation_program_payload(
    merchant_id: str,
    window_start_date: str,
    window_end_date: str,
    target_ratio_bps: int = 80,
    monitoring_month_count: int = 3,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "merchant_id": merchant_id,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "target_ratio_bps": target_ratio_bps,
        "monitoring_month_count": monitoring_month_count,
    }
    payload.update(overrides)
    return payload


def termination_decision_payload(
    merchant_id: str, reason_code: str = "EXCESSIVE_CHARGEBACKS", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"merchant_id": merchant_id, "reason_code": reason_code}
    payload.update(overrides)
    return payload


def appeal_payload(
    merchant_id: str,
    termination_decision_id: str,
    evidence_summary: str = "Chargebacks were driven by a courier outage now resolved.",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "merchant_id": merchant_id,
        "termination_decision_id": termination_decision_id,
        "evidence_summary": evidence_summary,
    }
    payload.update(overrides)
    return payload


def portfolio_forecast_payload(
    as_of_date: str, method: str = "EXPECTED_LOSS", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"as_of_date": as_of_date, "method": method}
    payload.update(overrides)
    return payload
