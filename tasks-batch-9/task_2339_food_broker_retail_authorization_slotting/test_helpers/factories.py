"""Payload factories: one per write endpoint, input fields only.

Each factory returns a minimal-but-valid body and accepts `**overrides` so a test
can perturb exactly the field under examination.  Optional fields are only
emitted when explicitly supplied, so the PRD's declared defaults stay observable.
"""

from typing import Any, Dict, List

from . import constants as C
from .types import (
    AmortizationMethod,
    CatalogDecision,
    ConflictScope,
    DeductionReasonCode,
    PromotionEventType,
    VoidRateBasis,
)

_UNSET = object()


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not _UNSET}


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def clock_payload(current_utc: str = C.CLOCK_DEFAULT_UTC) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# --------------------------------------------------------------------------- #
# Retailer
# --------------------------------------------------------------------------- #
def retailer_payload(
    name: str = "Bigmart",
    chain_code: str = "BIGMART",
    total_store_count: int = 1200,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "chain_code": chain_code,
        "total_store_count": total_store_count,
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #
def principal_payload(
    name: str = "Northwind Foods",
    code: str = "NWF",
    slotting_budget_cents: int = 20000000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "code": code,
        "slotting_budget_cents": slotting_budget_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def principal_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return _prune(payload)


def principal_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return _prune(dict(overrides))


# --------------------------------------------------------------------------- #
# Commission agreement
# --------------------------------------------------------------------------- #
def agreement_payload(
    principal_id: str,
    retailer_id: str,
    category_code: str = C.PRIMARY_CATEGORY,
    effective_start_date: str = "2026-01-01",
    effective_end_date: str = "2027-01-01",
    base_commission_bps: int = 500,
    tier_threshold_cents: int = 3000000,
    tier_commission_bps: int = 300,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "principal_id": principal_id,
        "retailer_id": retailer_id,
        "category_code": category_code,
        "effective_start_date": effective_start_date,
        "effective_end_date": effective_end_date,
        "base_commission_bps": base_commission_bps,
        "tier_threshold_cents": tier_threshold_cents,
        "tier_commission_bps": tier_commission_bps,
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Conflict rule
# --------------------------------------------------------------------------- #
def conflict_rule_payload(
    principal_a_id: str,
    principal_b_id: str,
    category_code: str = C.PRIMARY_CATEGORY,
    scope: str = ConflictScope.NATIONAL,
    retailer_id: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category_code": category_code,
        "principal_a_id": principal_a_id,
        "principal_b_id": principal_b_id,
        "scope": scope,
        "retailer_id": retailer_id,
    }
    payload.update(overrides)
    return _prune(payload)


def waive_payload(waiver_reason: str = "Competitive overlap resolved", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"waiver_reason": waiver_reason}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Item and catalog
# --------------------------------------------------------------------------- #
def item_payload(
    principal_id: str,
    upc: str = C.UPC_1,
    description: str = "Mini Tacos 12ct",
    case_pack_units: int = 12,
    list_price_cents: int = 2010,
    unit_cost_cents: int = 1200,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "principal_id": principal_id,
        "upc": upc,
        "description": description,
        "case_pack_units": case_pack_units,
        "list_price_cents": list_price_cents,
        "unit_cost_cents": unit_cost_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def catalog_submission_payload(
    upc: str = C.UPC_1,
    dimensions_cm: str = "20x15x8",
    gross_weight_g: int = 900,
    nutrition_panel_url: str = "https://cdn.example/n1.pdf",
    shelf_life_days: int = 365,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "gtin14": C.gtin14_for(upc),
        "dimensions_cm": dimensions_cm,
        "gross_weight_g": gross_weight_g,
        "nutrition_panel_url": nutrition_panel_url,
        "shelf_life_days": shelf_life_days,
    }
    payload.update(overrides)
    return _prune(payload)


def catalog_decision_payload(
    decision: str = CatalogDecision.VALIDATED,
    reject_reason: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "reject_reason": reject_reason}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Category review
# --------------------------------------------------------------------------- #
def review_payload(
    retailer_id: str,
    category_code: str = C.PRIMARY_CATEGORY,
    review_window_start: str = "2026-09-01",
    review_window_end: str = "2026-09-15",
    submission_deadline: str = "2026-08-20T00:00:00Z",
    new_item_slots: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "retailer_id": retailer_id,
        "category_code": category_code,
        "review_window_start": review_window_start,
        "review_window_end": review_window_end,
        "submission_deadline": submission_deadline,
        "new_item_slots": new_item_slots,
    }
    payload.update(overrides)
    return _prune(payload)


def reopen_payload(new_submission_deadline: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_submission_deadline": new_submission_deadline}
    payload.update(overrides)
    return _prune(payload)


def decide_payload(
    expected_review_version: int,
    authorized_item_ids: List[str],
    default_store_count: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_review_version": expected_review_version,
        "authorized_item_ids": authorized_item_ids,
        "default_store_count": default_store_count,
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #
def presentation_payload(
    review_id: str,
    principal_id: str,
    item_ids: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "review_id": review_id,
        "principal_id": principal_id,
        "item_ids": list(item_ids),
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Slotting deal
# --------------------------------------------------------------------------- #
def deal_payload(
    presentation_id: str,
    requested_fee_per_store_cents: int = 50000,
    store_count_in_scope: int = 100,
    item_count_in_scope: int = 1,
    forecast_annual_units: int = 0,
    amortization_periods: int = 6,
    amortization_method: Any = AmortizationMethod.FORECAST_STRAIGHT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "presentation_id": presentation_id,
        "requested_fee_per_store_cents": requested_fee_per_store_cents,
        "store_count_in_scope": store_count_in_scope,
        "item_count_in_scope": item_count_in_scope,
        "forecast_annual_units": forecast_annual_units,
        "amortization_periods": amortization_periods,
        "amortization_method": amortization_method,
    }
    payload.update(overrides)
    return _prune(payload)


def propose_payload(proposed_fee_per_store_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"proposed_fee_per_store_cents": proposed_fee_per_store_cents}
    payload.update(overrides)
    return _prune(payload)


def counter_payload(
    counter_fee_per_store_cents: int,
    counter_forecast_annual_units: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "counter_fee_per_store_cents": counter_fee_per_store_cents,
        "counter_forecast_annual_units": counter_forecast_annual_units,
    }
    payload.update(overrides)
    return _prune(payload)


def accept_payload(expected_principal_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_principal_version": expected_principal_version}
    payload.update(overrides)
    return _prune(payload)


def reject_deal_payload(reject_reason: str = "Fee above plan", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reject_reason": reject_reason}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #
def discontinue_payload(discontinue_reason: str = "SLOW_TURNS", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"discontinue_reason": discontinue_reason}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Distribution ledger
# --------------------------------------------------------------------------- #
def snapshot_payload(
    authorization_id: str,
    expected_authorization_version: int,
    period_index: int = 1,
    reported_store_count: int = 400,
    distributed_store_count: int = 380,
    reported_case_volume: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "authorization_id": authorization_id,
        "expected_authorization_version": expected_authorization_version,
        "period_index": period_index,
        "reported_store_count": reported_store_count,
        "distributed_store_count": distributed_store_count,
        "reported_case_volume": reported_case_volume,
    }
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Promotion event
# --------------------------------------------------------------------------- #
def promotion_payload(
    authorization_id: str,
    event_type: str = PromotionEventType.PRICE_FEATURE,
    window_start: str = "2026-09-10T10:00:00Z",
    window_end: str = "2026-09-10T14:00:00Z",
    planned_funding_cents: int = 320000,
    store_code: Any = _UNSET,
    sample_units_requested: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "authorization_id": authorization_id,
        "event_type": event_type,
        "window_start": window_start,
        "window_end": window_end,
        "planned_funding_cents": planned_funding_cents,
        "store_code": store_code,
        "sample_units_requested": sample_units_requested,
    }
    payload.update(overrides)
    return _prune(payload)


def demo_payload(
    authorization_id: str,
    window_start: str,
    window_end: str,
    store_code: str = "S001",
    sample_units_requested: int = 300,
    planned_funding_cents: int = 40000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "authorization_id": authorization_id,
        "event_type": PromotionEventType.DEMO_SAMPLING,
        "window_start": window_start,
        "window_end": window_end,
        "planned_funding_cents": planned_funding_cents,
        "store_code": store_code,
        "sample_units_requested": sample_units_requested,
    }
    payload.update(overrides)
    return _prune(payload)


def execute_promotion_payload(actual_funding_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_funding_cents": actual_funding_cents}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Deduction
# --------------------------------------------------------------------------- #
def deduction_payload(
    retailer_id: str,
    principal_id: str,
    reason_code: str = DeductionReasonCode.SHORTAGE,
    amount_cents: int = 90000,
    deduction_date: str = "2026-08-01",
    promotion_event_id: Any = _UNSET,
    original_deduction_id: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "retailer_id": retailer_id,
        "principal_id": principal_id,
        "reason_code": reason_code,
        "amount_cents": amount_cents,
        "deduction_date": deduction_date,
        "promotion_event_id": promotion_event_id,
        "original_deduction_id": original_deduction_id,
    }
    payload.update(overrides)
    return _prune(payload)


def dispute_payload(claim_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"claim_amount_cents": claim_amount_cents}
    payload.update(overrides)
    return _prune(payload)


def substantiate_payload(document_ref: str = "POD-1001", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"document_ref": document_ref}
    payload.update(overrides)
    return _prune(payload)


def deny_payload(denial_reason: str = "Not evidenced at store level", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"denial_reason": denial_reason}
    payload.update(overrides)
    return _prune(payload)


# --------------------------------------------------------------------------- #
# Retailer policy shorthands used by several scenarios
# --------------------------------------------------------------------------- #
def store_count_basis_retailer(**overrides: Any) -> Dict[str, Any]:
    return retailer_payload(
        void_rate_basis_default=VoidRateBasis.STORE_COUNT_BASIS,
        at_risk_void_rate_bps=C.DEFAULT_AT_RISK_VOID_RATE_BPS,
        **overrides,
    )


def reported_basis_retailer(**overrides: Any) -> Dict[str, Any]:
    return retailer_payload(
        name="Valufresh",
        chain_code="VALUFRESH",
        void_rate_basis_default=VoidRateBasis.REPORTED_BASIS,
        at_risk_void_rate_bps=C.DEFAULT_AT_RISK_VOID_RATE_BPS,
        **overrides,
    )
