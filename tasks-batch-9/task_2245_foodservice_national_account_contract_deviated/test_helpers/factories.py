"""Request payload factories.

Each factory returns only the fields a client is allowed to send, with sane
defaults for the optional ones omitted, and accepts **overrides so a test can
pin any single field. Server-computed fields are never included.
"""
from typing import Any, Dict, List, Optional

from .constants import TERM_END, TERM_START


def _payload(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

def operator_payload(
    legal_name: str = "Harborline Grill Group",
    operator_code: str = "HLG",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {"legal_name": legal_name, "operator_code": operator_code}, overrides
    )


def manufacturer_payload(
    name: str = "Cascadia Poultry Co",
    manufacturer_code: str = "CPC",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"name": name, "manufacturer_code": manufacturer_code}, overrides)


def distribution_center_payload(
    dc_code: str = "DC-SEA",
    name: str = "Seattle DC",
    in_market_state_codes: Optional[List[str]] = None,
    out_of_market_fee_per_case_cents: int = 275,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "dc_code": dc_code,
            "name": name,
            "in_market_state_codes": (
                ["WA", "OR"] if in_market_state_codes is None else in_market_state_codes
            ),
            "out_of_market_fee_per_case_cents": out_of_market_fee_per_case_cents,
        },
        overrides,
    )


def product_payload(
    manufacturer_id: str,
    sku: str = "P-CHKN",
    description: str = "Chicken Breast 4/10#",
    product_class_code: str = "PROTEIN",
    pack_size: int = 4,
    last_cost_cents: int = 4200,
    avg_cost_cents: int = 4100,
    replacement_cost_cents: int = 4300,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "sku": sku,
            "description": description,
            "product_class_code": product_class_code,
            "manufacturer_id": manufacturer_id,
            "pack_size": pack_size,
            "last_cost_cents": last_cost_cents,
            "avg_cost_cents": avg_cost_cents,
            "replacement_cost_cents": replacement_cost_cents,
        },
        overrides,
    )


def availability_payload(
    stock_status: Optional[str] = None,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"stock_status": stock_status, "status": status}, overrides)


# --------------------------------------------------------------------------
# Contract construction
# --------------------------------------------------------------------------

def contract_payload(
    operator_id: str,
    rebate_funding_manufacturer_id: str,
    contract_code: str = "HLG-2026",
    effective_from: str = TERM_START,
    effective_to: str = TERM_END,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "operator_id": operator_id,
            "contract_code": contract_code,
            "rebate_funding_manufacturer_id": rebate_funding_manufacturer_id,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        overrides,
    )


def amendment_payload(
    contract_code: str = "HLG-2026-A1",
    effective_from: str = TERM_START,
    effective_to: str = TERM_END,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_code": contract_code,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        overrides,
    )


def contract_tier_payload(
    contract_id: str,
    product_class_code: str = "PROTEIN",
    cost_basis: str = "LAST_COST",
    markup_type: str = "PERCENT_OF_COST",
    markup_value: float = 12.50,
    min_case_volume: int = 0,
    max_case_volume: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_id": contract_id,
            "product_class_code": product_class_code,
            "cost_basis": cost_basis,
            "markup_type": markup_type,
            "markup_value": markup_value,
            "min_case_volume": min_case_volume,
            "max_case_volume": max_case_volume,
        },
        overrides,
    )


def dc_coverage_payload(
    contract_id: str,
    distribution_center_id: str,
    coverage_type: str = "IN_MARKET",
    coverage_from: str = TERM_START,
    coverage_to: str = TERM_END,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_id": contract_id,
            "distribution_center_id": distribution_center_id,
            "coverage_type": coverage_type,
            "coverage_from": coverage_from,
            "coverage_to": coverage_to,
        },
        overrides,
    )


def substitution_rule_payload(
    contract_id: str,
    primary_product_id: str,
    substitute_product_id: str,
    rank: int = 1,
    price_protection_mode: str = "HOLD_CONTRACT_PRICE",
    max_price_delta_pct: float = 5.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_id": contract_id,
            "primary_product_id": primary_product_id,
            "substitute_product_id": substitute_product_id,
            "rank": rank,
            "price_protection_mode": price_protection_mode,
            "max_price_delta_pct": max_price_delta_pct,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Deviated pricing
# --------------------------------------------------------------------------

def deviation_agreement_payload(
    contract_id: str,
    product_id: str,
    manufacturer_id: str,
    expected_contract_version: int,
    max_operator_price_cents: int,
    effective_from: str,
    effective_to: str,
    bill_back_basis: str = "FIXED_NET_PRICE",
    requested_net_price_cents: Optional[int] = None,
    protected_discount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_id": contract_id,
            "product_id": product_id,
            "manufacturer_id": manufacturer_id,
            "bill_back_basis": bill_back_basis,
            "requested_net_price_cents": requested_net_price_cents,
            "protected_discount_cents": protected_discount_cents,
            "max_operator_price_cents": max_operator_price_cents,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "expected_contract_version": expected_contract_version,
        },
        overrides,
    )


def manufacturer_decision_payload(
    decision: str = "APPROVE",
    decision_note: Optional[str] = "Approved per national program",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"decision": decision, "decision_note": decision_note}, overrides)


# --------------------------------------------------------------------------
# Cost change notices
# --------------------------------------------------------------------------

def price_change_notice_payload(
    contract_id: str,
    product_id: str,
    effective_at: str,
    cost_basis: str = "LAST_COST",
    proposed_cost_cents: Optional[int] = None,
    published_index_value: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_id": contract_id,
            "product_id": product_id,
            "cost_basis": cost_basis,
            "effective_at": effective_at,
            "proposed_cost_cents": proposed_cost_cents,
            "published_index_value": published_index_value,
        },
        overrides,
    )


def notice_revise_payload(
    effective_at: str,
    cost_basis: str = "LAST_COST",
    proposed_cost_cents: Optional[int] = None,
    published_index_value: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "cost_basis": cost_basis,
            "effective_at": effective_at,
            "proposed_cost_cents": proposed_cost_cents,
            "published_index_value": published_index_value,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Rebate periods, order lines and bill-back
# --------------------------------------------------------------------------

def rebate_period_payload(
    contract_id: str,
    period_start: str,
    period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_id": contract_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def order_line_payload(
    contract_id: str,
    product_id: str,
    distribution_center_id: str,
    quantity_cases: int = 300,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "contract_id": contract_id,
            "product_id": product_id,
            "distribution_center_id": distribution_center_id,
            "quantity_cases": quantity_cases,
        },
        overrides,
    )


def bill_back_claim_payload(
    deviation_agreement_id: str,
    claim_period_start: str,
    claim_period_end: str,
    expected_deviation_agreement_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "deviation_agreement_id": deviation_agreement_id,
            "claim_period_start": claim_period_start,
            "claim_period_end": claim_period_end,
            "expected_deviation_agreement_version": (
                expected_deviation_agreement_version
            ),
        },
        overrides,
    )


def bill_back_remittance_payload(
    manufacturer_id: str,
    remitted_amount_cents: int,
    remittance_reference: str = "CPC-WIRE-0001",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "manufacturer_id": manufacturer_id,
            "remitted_amount_cents": remitted_amount_cents,
            "remittance_reference": remittance_reference,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Pricing disputes
# --------------------------------------------------------------------------

def pricing_dispute_payload(
    order_line_id: str,
    claimed_correct_unit_price_cents: int,
    dispute_reason: str = "TIER_MISAPPLIED",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "order_line_id": order_line_id,
            "claimed_correct_unit_price_cents": claimed_correct_unit_price_cents,
            "dispute_reason": dispute_reason,
        },
        overrides,
    )


def dispute_resolution_payload(
    resolution: str = "UPHELD",
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"resolution": resolution, "note": note}, overrides)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    return _payload({"to_iso8601": to_iso8601}, overrides)
