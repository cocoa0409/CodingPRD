"""Request payload factories.

Each factory returns a payload carrying every required field the PRD declares
for that operation, with `**overrides` for whatever a test needs to control.
Optional fields are omitted unless overridden, so the server's declared
defaults stay observable.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CANONICAL_AGREEMENT_LOOKBACK_END,
    CANONICAL_AGREEMENT_LOOKBACK_START,
    CANONICAL_BASE_INTEREST_WAIVER_PCT,
    CANONICAL_BASE_PENALTY_WAIVER_PCT,
    CANONICAL_LOOKBACK_MONTHS,
    CANONICAL_POST_PROGRAM_MULTIPLIER,
    CANONICAL_RETURN_ORIGINAL_DUE_DATE,
    CANONICAL_RETURN_PERIOD_END,
    CANONICAL_RETURN_PERIOD_START,
    CANONICAL_RETURN_REPORTED_TAX_CENTS,
    CANONICAL_REVENUE_FORECAST_CENTS,
    CANONICAL_TERM_ELIGIBLE_END,
    CANONICAL_TERM_ELIGIBLE_START,
    CANONICAL_TERM_MIN_LIABILITY_CENTS,
    CANONICAL_WINDOW_CLOSE_AT,
    CANONICAL_WINDOW_OPEN_AT,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key explicitly overridden with ``None``
    unless the PRD declares that field nullable in the request body."""
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Programs and terms (PRD §3.1)
# ---------------------------------------------------------------------------


def program_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/programs` — required fields only, optionals omitted."""
    return _merge(
        {
            "name": "FY27 Amnesty",
            "window_open_at": CANONICAL_WINDOW_OPEN_AT,
            "window_close_at": CANONICAL_WINDOW_CLOSE_AT,
            "lookback_months": CANONICAL_LOOKBACK_MONTHS,
            "base_penalty_waiver_pct": CANONICAL_BASE_PENALTY_WAIVER_PCT,
            "base_interest_waiver_pct": CANONICAL_BASE_INTEREST_WAIVER_PCT,
            "post_program_penalty_multiplier": CANONICAL_POST_PROGRAM_MULTIPLIER,
            "revenue_forecast_cents": CANONICAL_REVENUE_FORECAST_CENTS,
        },
        overrides,
    )


def tax_type_term_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/programs/{id}/tax-type-terms`."""
    return _merge(
        {
            "tax_type": "SALES_USE",
            "eligible_period_start": CANONICAL_TERM_ELIGIBLE_START,
            "eligible_period_end": CANONICAL_TERM_ELIGIBLE_END,
            "min_liability_cents": CANONICAL_TERM_MIN_LIABILITY_CENTS,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Registries (PRD §3.2)
# ---------------------------------------------------------------------------


def taxpayer_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/taxpayers`."""
    return _merge(
        {
            "legal_name": "Pinnacle Grocers LLC",
            "taxpayer_type": "BUSINESS",
            "tin_last4": "4417",
        },
        overrides,
    )


def representative_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/representatives`."""
    return _merge(
        {"firm_name": "Halloran Tax Counsel", "bar_number": "BAR-55120"},
        overrides,
    )


def enforcement_case_payload(taxpayer_id: str, **overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/enforcement-cases`."""
    return _merge(
        {
            "taxpayer_id": taxpayer_id,
            "case_type": "FIELD_AUDIT",
            "tax_type": "SALES_USE",
            "opened_at": "2026-06-01",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Pre-clearance and negotiation (PRD §3.3)
# ---------------------------------------------------------------------------


def pre_clearance_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/pre-clearances`."""
    return _merge(
        {
            "program_id": program_id,
            "tax_type": "SALES_USE",
            "anonymous_alias": "CLIENT-ORION",
            "estimated_liability_cents": 1000000,
            "self_reported_under_audit": False,
            "earliest_unfiled_period_start": "2024-01-01",
        },
        overrides,
    )


def offer_terms_payload(
    expected_pre_clearance_version: int, **overrides: Any
) -> Dict[str, Any]:
    """`POST /amnesty/pre-clearances/{id}/offer-terms`."""
    return _merge(
        {
            "expected_pre_clearance_version": expected_pre_clearance_version,
            "offered_lookback_months": 30,
            "offered_penalty_waiver_pct": 0.60,
            "offered_interest_waiver_pct": 0.30,
        },
        overrides,
    )


def counter_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/pre-clearances/{id}/counter`."""
    return _merge(
        {
            "counter_lookback_months": 24,
            "counter_penalty_waiver_pct": 1.00,
            "counter_interest_waiver_pct": 0.75,
        },
        overrides,
    )


def disclose_identity_payload(taxpayer_id: str, **overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/pre-clearances/{id}/disclose-identity`."""
    return _merge({"taxpayer_id": taxpayer_id}, overrides)


def reject_pre_clearance_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/pre-clearances/{id}/reject`."""
    return _merge({"rejection_reason": "OFFICER_CLOSED_FILE"}, overrides)


# ---------------------------------------------------------------------------
# Agreements (PRD §3.4, §3.7)
# ---------------------------------------------------------------------------


def agreement_payload(
    program_id: str,
    taxpayer_id: str,
    tax_types: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """`POST /amnesty/agreements` — `pre_clearance_id` omitted, so the draft is
    the walk-in `AMNESTY_STATUTORY` variant unless a test supplies one."""
    return _merge(
        {
            "program_id": program_id,
            "taxpayer_id": taxpayer_id,
            "tax_types": list(tax_types) if tax_types else ["SALES_USE"],
            "lookback_start_date": CANONICAL_AGREEMENT_LOOKBACK_START,
            "lookback_end_date": CANONICAL_AGREEMENT_LOOKBACK_END,
        },
        overrides,
    )


def amend_payload(expected_agreement_version: int, **overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/agreements/{id}/amend`."""
    return _merge(
        {
            "expected_agreement_version": expected_agreement_version,
            "lookback_start_date": "2024-01-01",
            "lookback_end_date": CANONICAL_AGREEMENT_LOOKBACK_END,
        },
        overrides,
    )


def declare_breach_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/agreements/{id}/declare-breach`."""
    return _merge({"breach_reason": "PROSPECTIVE_FILING_MISSED"}, overrides)


def rescind_breach_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/agreements/{id}/rescind-breach`."""
    return _merge({"rescind_reason": "BREACH_DECLARED_IN_ERROR"}, overrides)


# ---------------------------------------------------------------------------
# Returns (PRD §3.5)
# ---------------------------------------------------------------------------


def disclosure_return_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/agreements/{id}/returns`."""
    return _merge(
        {
            "tax_type": "SALES_USE",
            "period_start_date": CANONICAL_RETURN_PERIOD_START,
            "period_end_date": CANONICAL_RETURN_PERIOD_END,
            "original_due_date": CANONICAL_RETURN_ORIGINAL_DUE_DATE,
            "reported_tax_cents": CANONICAL_RETURN_REPORTED_TAX_CENTS,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Payment plans, payments (PRD §3.6)
# ---------------------------------------------------------------------------


def payment_plan_payload(
    agreement_id: str,
    expected_agreement_version: int,
    installment_count: int,
    down_payment_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """`POST /amnesty/payment-plans`."""
    return _merge(
        {
            "agreement_id": agreement_id,
            "plan_type": "INSTALLMENT" if installment_count != 1 else "LUMP_SUM",
            "installment_count": installment_count,
            "down_payment_cents": down_payment_cents,
            "expected_agreement_version": expected_agreement_version,
        },
        overrides,
    )


def reject_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/payment-plans/{id}/reject`."""
    return _merge({"rejection_reason": "SCHEDULE_TOO_LONG"}, overrides)


def default_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/payment-plans/{id}/default`."""
    return _merge({"default_reason": "TAXPAYER_STOPPED_REMITTING"}, overrides)


def payment_payload(agreement_id: str, amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/payments`."""
    return _merge(
        {"agreement_id": agreement_id, "amount_cents": amount_cents}, overrides
    )


def reverse_payment_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/payments/{id}/reverse`."""
    return _merge({"reversal_reason": "ACH_RETURNED_INSUFFICIENT_FUNDS"}, overrides)


# ---------------------------------------------------------------------------
# Enforcement actions (PRD §3.9)
# ---------------------------------------------------------------------------


def enforcement_action_payload(
    taxpayer_id: str, program_id: str, base_tax_cents: int, **overrides: Any
) -> Dict[str, Any]:
    """`POST /amnesty/enforcement-actions`."""
    return _merge(
        {
            "taxpayer_id": taxpayer_id,
            "program_id": program_id,
            "action_type": "ASSESSMENT",
            "base_tax_cents": base_tax_cents,
        },
        overrides,
    )


def abate_action_payload(**overrides: Any) -> Dict[str, Any]:
    """`POST /amnesty/enforcement-actions/{id}/abate`."""
    return _merge({"abatement_reason": "TAXPAYER_PRODUCED_FILED_RETURNS"}, overrides)
