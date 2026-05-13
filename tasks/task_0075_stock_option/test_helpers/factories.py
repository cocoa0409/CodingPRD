"""Payload factories — one per endpoint that takes a body.

Only fields from PRD §3 / §4 input columns. Each factory accepts
**overrides so individual tests can vary specific values without
re-typing the whole payload.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# OptionPlan
# ---------------------------------------------------------------------------
def create_option_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'A PlanAdministrator creates it by submitting a name,
    a positive integer pool_total_options, and a jurisdiction_code.'"""
    defaults: Dict[str, Any] = {
        "name": f"{TEST_DEFAULTS['PLAN_NAME']}-{uuid.uuid4().hex[:8]}",
        "pool_total_options": TEST_DEFAULTS["POOL_TOTAL"],
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_US"],
    }
    defaults.update(overrides)
    return defaults


def activate_option_plan_payload(now_iso: Optional[str] = None,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Activation may optionally accept an initial now_iso
    instant which becomes the plan's starting current_clock_ts.'"""
    payload: Dict[str, Any] = {}
    if now_iso is not None:
        payload["now_iso"] = now_iso
    payload.update(overrides)
    return payload


def clock_advance_payload(by_seconds: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'the administrator-only clock-advance capability, which
    adds a supplied by_seconds integer to current_clock_ts.'"""
    payload: Dict[str, Any] = {"by_seconds": by_seconds}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# GrantBatch
# ---------------------------------------------------------------------------
def create_grant_batch_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input set:
    batch_label, cliff_months, vesting_total_months, vesting_period_months,
    vesting_algorithm, performance_condition_required?, initial_price_per_option_cents.
    """
    defaults: Dict[str, Any] = {
        "batch_label": f"{TEST_DEFAULTS['BATCH_LABEL']}-{uuid.uuid4().hex[:6]}",
        "cliff_months": TEST_DEFAULTS["CLIFF_MONTHS"],
        "vesting_total_months": TEST_DEFAULTS["VESTING_TOTAL_MONTHS"],
        "vesting_period_months": TEST_DEFAULTS["VESTING_PERIOD_MONTHS"],
        "vesting_algorithm": TEST_DEFAULTS["VESTING_ALGORITHM_ANNIVERSARY"],
        "performance_condition_required": False,
        "initial_price_per_option_cents": TEST_DEFAULTS["INITIAL_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Grantee
# ---------------------------------------------------------------------------
def create_grantee_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 input set: hr_employee_id, full_name, tax_residency."""
    defaults: Dict[str, Any] = {
        "hr_employee_id": f"hr-{uuid.uuid4().hex[:10]}",
        "full_name": "Grantee Alpha",
        "tax_residency": TEST_DEFAULTS["JURISDICTION_US"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------
def create_grant_payload(grantee_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'submitted by a PlanAdministrator against an
    OPEN_FOR_GRANTS batch, naming the recipient grantee_id, the positive
    integer quantity, and the per-option grant_date_fair_value_cents.'"""
    defaults: Dict[str, Any] = {
        "grantee_id": grantee_id,
        "quantity": TEST_DEFAULTS["GRANT_QUANTITY"],
        "grant_date_fair_value_cents": TEST_DEFAULTS["GRANT_FAIR_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def sign_agreement_payload(require_live: Optional[bool] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'The signing request may include an optional require_live flag.'"""
    payload: Dict[str, Any] = {}
    if require_live is not None:
        payload["require_live"] = require_live
    payload.update(overrides)
    return payload


def accelerate_vesting_payload(corporate_event_id: str,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'takes a corporate_event_id referencing an existing event
    of type CHANGE_OF_CONTROL or IPO.'"""
    payload: Dict[str, Any] = {"corporate_event_id": corporate_event_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ExerciseWindow
# ---------------------------------------------------------------------------
def create_exercise_window_payload(open_ts: str, close_ts: str,
                                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6 input set: label, open_ts, close_ts."""
    defaults: Dict[str, Any] = {
        "label": f"window-{uuid.uuid4().hex[:6]}",
        "open_ts": open_ts,
        "close_ts": close_ts,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CorporateEvent
# ---------------------------------------------------------------------------
def create_blackout_event_payload(event_type: str, effective_ts: str,
                                  blackout_end_ts: str,
                                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: blackout events carry effective_ts and blackout_end_ts."""
    defaults: Dict[str, Any] = {
        "event_type": event_type,
        "effective_ts": effective_ts,
        "blackout_end_ts": blackout_end_ts,
    }
    defaults.update(overrides)
    return defaults


def create_stock_split_payload(effective_ts: str,
                               numerator: int = 2,
                               denominator: int = 1,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7 STOCK_SPLIT: split_ratio_numerator / split_ratio_denominator."""
    defaults: Dict[str, Any] = {
        "event_type": "STOCK_SPLIT",
        "effective_ts": effective_ts,
        "split_ratio_numerator": numerator,
        "split_ratio_denominator": denominator,
    }
    defaults.update(overrides)
    return defaults


def create_cash_dividend_payload(effective_ts: str,
                                 dividend_cents: int,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7 CASH_DIVIDEND: dividend_amount_cents per share."""
    defaults: Dict[str, Any] = {
        "event_type": "CASH_DIVIDEND",
        "effective_ts": effective_ts,
        "dividend_amount_cents": dividend_cents,
    }
    defaults.update(overrides)
    return defaults


def create_restructuring_payload(effective_ts: str,
                                 restructure_factor_bps: int,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7 RESTRUCTURING: restructure_factor_bps (100..100000)."""
    defaults: Dict[str, Any] = {
        "event_type": "RESTRUCTURING",
        "effective_ts": effective_ts,
        "restructure_factor_bps": restructure_factor_bps,
    }
    defaults.update(overrides)
    return defaults


def create_change_of_control_payload(effective_ts: str,
                                     **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: CHANGE_OF_CONTROL events serve as the acceleration referent."""
    defaults: Dict[str, Any] = {
        "event_type": "CHANGE_OF_CONTROL",
        "effective_ts": effective_ts,
    }
    defaults.update(overrides)
    return defaults


def create_ipo_payload(effective_ts: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: IPO events serve as the acceleration referent."""
    defaults: Dict[str, Any] = {
        "event_type": "IPO",
        "effective_ts": effective_ts,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ExerciseApplication
# ---------------------------------------------------------------------------
def create_exercise_application_payload(window_id: str,
                                        pinned_price_version_id: str,
                                        requested_quantity: int,
                                        settlement_mode: str,
                                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'specifying a window_id, a positive integer
    requested_quantity, a settlement_mode of SHARE_ISSUANCE or
    CASH_SETTLEMENT, and the pinned_price_version_id they intend to use.'"""
    defaults: Dict[str, Any] = {
        "window_id": window_id,
        "pinned_price_version_id": pinned_price_version_id,
        "requested_quantity": requested_quantity,
        "settlement_mode": settlement_mode,
    }
    defaults.update(overrides)
    return defaults


def pay_application_payload(payment_reference: str,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: '/pay requires a non-empty payment_reference.'"""
    payload: Dict[str, Any] = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


def settle_application_share_payload(share_registry_reference: str,
                                     **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'For SHARE_ISSUANCE, the settlement request must carry
    a share_registry_reference.'"""
    payload: Dict[str, Any] = {
        "share_registry_reference": share_registry_reference,
    }
    payload.update(overrides)
    return payload


def settle_application_cash_payload(payment_reference: str,
                                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'For CASH_SETTLEMENT, it must carry a payment_reference.'"""
    payload: Dict[str, Any] = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


def reject_application_payload(reason: Optional[str] = None,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'an administrator may reject a SUBMITTED or
    ELIGIBILITY_VERIFIED application with an optional reason field.'"""
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TaxEventRecord (out-of-band sale events)
# ---------------------------------------------------------------------------
def create_sale_tax_event_payload(sale_proceeds_cents: int,
                                  cost_basis_cents: int,
                                  sold_quantity: int,
                                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9 SALE: 'an administrator submitting a sale event with
    sale_proceeds_cents, cost_basis_cents, and sold_quantity.'"""
    defaults: Dict[str, Any] = {
        "event_type": "SALE",
        "sale_proceeds_cents": sale_proceeds_cents,
        "cost_basis_cents": cost_basis_cents,
        "sold_quantity": sold_quantity,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# DepartureRecord
# ---------------------------------------------------------------------------
def create_departure_record_payload(departure_type: str,
                                    departed_ts: str,
                                    leaver_class: Optional[str] = None,
                                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.10: 'naming a departure_type ..., an effective departed_ts,
    and (only when departure_type is TERMINATION) a leaver_class.'"""
    defaults: Dict[str, Any] = {
        "departure_type": departure_type,
        "departed_ts": departed_ts,
    }
    if leaver_class is not None:
        defaults["leaver_class"] = leaver_class
    defaults.update(overrides)
    return defaults


__all__ = [
    "create_option_plan_payload",
    "activate_option_plan_payload",
    "clock_advance_payload",
    "create_grant_batch_payload",
    "create_grantee_payload",
    "create_grant_payload",
    "sign_agreement_payload",
    "accelerate_vesting_payload",
    "create_exercise_window_payload",
    "create_blackout_event_payload",
    "create_stock_split_payload",
    "create_cash_dividend_payload",
    "create_restructuring_payload",
    "create_change_of_control_payload",
    "create_ipo_payload",
    "create_exercise_application_payload",
    "pay_application_payload",
    "settle_application_share_payload",
    "settle_application_cash_payload",
    "reject_application_payload",
    "create_sale_tax_event_payload",
    "create_departure_record_payload",
]
