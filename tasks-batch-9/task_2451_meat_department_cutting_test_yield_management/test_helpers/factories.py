"""Payload factories — one per write operation, input fields only."""

from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


def department_payload(**overrides) -> Dict[str, Any]:
    """Only `name` and `store_code` are required; every other field defaults."""
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["DEPARTMENT_NAME"],
        "store_code": TEST_DEFAULTS["STORE_CODE"],
    }
    payload.update(overrides)
    return payload


def primal_purchase_payload(department_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "primal_code": TEST_DEFAULTS["P1_PRIMAL_CODE"],
        "product_class": "WHOLE_MUSCLE",
        "country_of_origin": "USA",
        "vendor_name": TEST_DEFAULTS["VENDOR_NAME"],
        "gross_weight_lb": TEST_DEFAULTS["P1_GROSS_WEIGHT_LB"],
        "invoice_cost_cents": TEST_DEFAULTS["P1_INVOICE_COST_CENTS"],
        "freight_cost_cents": TEST_DEFAULTS["P1_FREIGHT_COST_CENTS"],
        "vendor_allowance_cents": TEST_DEFAULTS["P1_VENDOR_ALLOWANCE_CENTS"],
        "receiving_shrink_lb": TEST_DEFAULTS["P1_RECEIVING_SHRINK_LB"],
        "received_at": TEST_DEFAULTS["P1_RECEIVED_AT"],
    }
    payload.update(overrides)
    return payload


def retail_item_payload(department_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "item_code": TEST_DEFAULTS["RIB01_ITEM_CODE"],
        "subprimal_code": TEST_DEFAULTS["RIB01_SUBPRIMAL_CODE"],
        "product_class": "WHOLE_MUSCLE",
    }
    payload.update(overrides)
    return payload


def cutting_test_payload(
    primal_purchase_id: str, test_weight_lb: float, expected_primal_purchase_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "primal_purchase_id": primal_purchase_id,
        "test_weight_lb": test_weight_lb,
        "expected_primal_purchase_version": expected_primal_purchase_version,
    }
    payload.update(overrides)
    return payload


def cutting_test_line_payload(
    line_seq: int,
    subprimal_code: str,
    disposition: str,
    yield_weight_lb: float,
    market_value_per_lb_cents: int,
    lean_pct: Optional[float] = None,
    retail_item_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "line_seq": line_seq,
        "subprimal_code": subprimal_code,
        "disposition": disposition,
        "yield_weight_lb": yield_weight_lb,
        "market_value_per_lb_cents": market_value_per_lb_cents,
    }
    if lean_pct is not None:
        payload["lean_pct"] = lean_pct
    if retail_item_id is not None:
        payload["retail_item_id"] = retail_item_id
    payload.update(overrides)
    return payload


def transition_payload(action: str, **fields) -> Dict[str, Any]:
    """Every transition endpoint takes an `action` field naming the transition
    plus whatever fields that action requires."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def price_proposal_payload(primal_purchase_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"primal_purchase_id": primal_purchase_id}
    payload.update(overrides)
    return payload


def price_activation_payload(
    expected_retail_item_version: int,
    cutting_test_id: Optional[str] = None,
    grind_run_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_retail_item_version": expected_retail_item_version
    }
    if cutting_test_id is not None:
        payload["cutting_test_id"] = cutting_test_id
    if grind_run_id is not None:
        payload["grind_run_id"] = grind_run_id
    payload.update(overrides)
    return payload


def case_plan_payload(department_id: str, service_date: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "service_date": service_date,
    }
    payload.update(overrides)
    return payload


def case_plan_line_payload(
    retail_item_id: str,
    line_seq: int,
    facings: int,
    expected_movement_lb: float,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "retail_item_id": retail_item_id,
        "line_seq": line_seq,
        "facings": facings,
        "expected_movement_lb": expected_movement_lb,
    }
    payload.update(overrides)
    return payload


def fill_payload(filled_lb: float, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"filled_lb": filled_lb}
    payload.update(overrides)
    return payload


def markdown_payload(
    markdown_lb: float, markdown_price_per_lb_cents: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "markdown_lb": markdown_lb,
        "markdown_price_per_lb_cents": markdown_price_per_lb_cents,
    }
    payload.update(overrides)
    return payload


def shrink_event_payload(shrink_lb: float, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"shrink_lb": shrink_lb}
    payload.update(overrides)
    return payload


def trim_lot_payload(
    department_id: str,
    lot_code: str,
    received_lb: float,
    pack_date: str,
    cutting_test_line_id: Optional[str] = None,
    source_trim_lot_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "lot_code": lot_code,
        "received_lb": received_lb,
        "pack_date": pack_date,
    }
    if cutting_test_line_id is not None:
        payload["cutting_test_line_id"] = cutting_test_line_id
    if source_trim_lot_id is not None:
        payload["source_trim_lot_id"] = source_trim_lot_id
    payload.update(overrides)
    return payload


def grind_run_payload(
    department_id: str,
    target_retail_item_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    declared_coo: str = "USA",
    target_lean_pct: float = 85.0,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "target_retail_item_id": target_retail_item_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "declared_coo": declared_coo,
        "target_lean_pct": target_lean_pct,
    }
    payload.update(overrides)
    return payload


def grind_input_payload(
    trim_lot_id: str, input_seq: int, weight_lb: float, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "trim_lot_id": trim_lot_id,
        "input_seq": input_seq,
        "weight_lb": weight_lb,
    }
    payload.update(overrides)
    return payload


def temperature_log_payload(
    department_id: str, case_code: str, reading_c: float, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "case_code": case_code,
        "reading_c": reading_c,
    }
    payload.update(overrides)
    return payload


def pre_order_payload(
    department_id: str,
    retail_item_id: str,
    requested_weight_lb: float,
    pickup_window_start_at: str,
    pickup_window_end_at: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "retail_item_id": retail_item_id,
        "customer_name": TEST_DEFAULTS["CUSTOMER_NAME"],
        "customer_phone": TEST_DEFAULTS["CUSTOMER_PHONE"],
        "requested_weight_lb": requested_weight_lb,
        "pickup_window_start_at": pickup_window_start_at,
        "pickup_window_end_at": pickup_window_end_at,
    }
    payload.update(overrides)
    return payload


def shrink_reconciliation_payload(
    department_id: str,
    period_start_date: str,
    period_end_date: str,
    basis: str = "YIELD_MODEL",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "basis": basis,
    }
    payload.update(overrides)
    return payload
