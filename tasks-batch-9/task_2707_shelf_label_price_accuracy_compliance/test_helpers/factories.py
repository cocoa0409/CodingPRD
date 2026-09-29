"""Request payload builders.

Every monetary amount is an integer number of cents and is sent as a JSON
number, never as a string.  Percentage figures (``score_pct``,
``scanner_error_rate_threshold_pct``) are likewise plain JSON numbers.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import DEFAULT_CLOCK

_counter = itertools.count(1)


def next_seq() -> int:
    """A process-unique counter for generating distinct natural keys."""
    return next(_counter)


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Jurisdiction
# ---------------------------------------------------------------------------
def jurisdiction_payload(
    code: Optional[str] = None,
    name: str = "California",
    **rulebook: Any,
) -> Dict[str, Any]:
    """A jurisdiction create body.  Rulebook settings are opt-in keyword args."""
    payload: Dict[str, Any] = {
        "code": code if code is not None else f"US-C{next_seq():02d}",
        "name": name,
    }
    payload.update(rulebook)
    return payload


# ---------------------------------------------------------------------------
# Store, aisle, associate
# ---------------------------------------------------------------------------
def store_payload(
    jurisdiction_id: str,
    store_number: Optional[str] = None,
    name: str = "Bay Street",
) -> Dict[str, Any]:
    return {
        "store_number": store_number
        if store_number is not None
        else f"S{next_seq():03d}",
        "name": name,
        "jurisdiction_id": jurisdiction_id,
    }


def aisle_payload(
    aisle_code: str = "A01",
    category_code: str = "DAIRY",
    assigned_associate_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "aisle_code": aisle_code,
        "category_code": category_code,
    }
    if assigned_associate_id is not None:
        payload["assigned_associate_id"] = assigned_associate_id
    return payload


def associate_payload(
    role_code: str,
    employee_number: Optional[str] = None,
    full_name: str = "Alex Associate",
) -> Dict[str, Any]:
    return {
        "employee_number": employee_number
        if employee_number is not None
        else f"E-{next_seq():04d}",
        "full_name": full_name,
        "role_code": role_code,
    }


def training_payload(module_code: str = "LABEL_101", score_pct: float = 95) -> Dict[str, Any]:
    return {"module_code": module_code, "score_pct": score_pct}


def accountability_action_payload(
    action_type: str,
    trigger_code: str,
    source_ref: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "action_type": action_type,
            "trigger_code": trigger_code,
            "source_ref": source_ref,
        }
    )


def action_transition_payload(
    target_status: str, void_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_status": target_status}
    if void_reason is not None:
        payload["void_reason"] = void_reason
    return payload


def assign_associate_payload(associate_id: Optional[str]) -> Dict[str, Any]:
    """``None`` is a meaningful value here: it clears the assignment."""
    return {"assigned_associate_id": associate_id}


# ---------------------------------------------------------------------------
# Price change files and lines
# ---------------------------------------------------------------------------
def price_change_file_payload(
    jurisdiction_id: str,
    scope_store_ids: List[str],
    effective_date: str = "2026-08-03T00:00:00Z",
    file_number: Optional[str] = None,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "file_number": file_number
        if file_number is not None
        else f"PCF-{next_seq():04d}",
        "jurisdiction_id": jurisdiction_id,
        "effective_date": effective_date,
        "scope_store_ids": scope_store_ids,
    }
    if priority is not None:
        payload["priority"] = priority
    return payload


def price_change_line_payload(
    item_upc: str,
    new_retail_cents: int,
    old_retail_cents: int,
    net_content_qty: float,
    net_content_uom: str,
    item_description: str = "Milk 1gal",
    category_code: str = "DAIRY",
    promo_flag: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_upc": item_upc,
        "item_description": item_description,
        "category_code": category_code,
        "old_retail_cents": old_retail_cents,
        "new_retail_cents": new_retail_cents,
        "net_content_qty": net_content_qty,
        "net_content_uom": net_content_uom,
    }
    if promo_flag is not None:
        payload["promo_flag"] = promo_flag
    return payload


def supersede_payload(superseded_by_file_id: str) -> Dict[str, Any]:
    return {"superseded_by_file_id": superseded_by_file_id}


# ---------------------------------------------------------------------------
# Label tasks
# ---------------------------------------------------------------------------
def label_task_payload(
    store_id: str,
    price_change_line_id: str,
    aisle_id: str,
    assigned_associate_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    expected_price_change_file_version: int,
) -> Dict[str, Any]:
    return {
        "store_id": store_id,
        "price_change_line_id": price_change_line_id,
        "aisle_id": aisle_id,
        "assigned_associate_id": assigned_associate_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "expected_price_change_file_version": expected_price_change_file_version,
    }


def place_payload(observed_shelf_price_cents: int) -> Dict[str, Any]:
    return {"observed_shelf_price_cents": observed_shelf_price_cents}


def verify_payload(
    outcome: str, rejection_reason: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none({"outcome": outcome, "rejection_reason": rejection_reason})


# ---------------------------------------------------------------------------
# Scanner audits
# ---------------------------------------------------------------------------
def scanner_audit_payload(
    store_id: str,
    aisle_id: str,
    auditor_associate_id: str,
    scan_window_start: str,
    scan_window_end: str,
    audit_type: str = "ROUTINE",
) -> Dict[str, Any]:
    return {
        "store_id": store_id,
        "aisle_id": aisle_id,
        "auditor_associate_id": auditor_associate_id,
        "audit_type": audit_type,
        "scan_window_start": scan_window_start,
        "scan_window_end": scan_window_end,
    }


def scan_line_payload(
    item_upc: str, shelf_price_cents: int, register_price_cents: int
) -> Dict[str, Any]:
    return {
        "item_upc": item_upc,
        "shelf_price_cents": shelf_price_cents,
        "register_price_cents": register_price_cents,
    }


def close_audit_payload(rate_variant: Optional[str] = None) -> Dict[str, Any]:
    return _drop_none({"rate_variant": rate_variant})


def reopen_audit_payload(
    reopen_reason: str = "Register export was incomplete",
) -> Dict[str, Any]:
    return {"reopen_reason": reopen_reason}


# ---------------------------------------------------------------------------
# Promotional signage
# ---------------------------------------------------------------------------
def promo_signage_payload(
    store_id: str,
    aisle_id: str,
    disclosure_codes: List[str],
    promo_start_at: str = "2026-08-01T00:00:00Z",
    promo_end_at: str = "2026-08-20T00:00:00Z",
    sign_code: Optional[str] = None,
    price_change_line_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "aisle_id": aisle_id,
        "sign_code": sign_code if sign_code is not None else f"SG-{next_seq():03d}",
        "promo_start_at": promo_start_at,
        "promo_end_at": promo_end_at,
        "disclosure_codes": disclosure_codes,
    }
    if price_change_line_id is not None:
        payload["price_change_line_id"] = price_change_line_id
    return payload


def post_signage_payload(override_acknowledged: Optional[bool] = None) -> Dict[str, Any]:
    return _drop_none({"override_acknowledged": override_acknowledged})


# ---------------------------------------------------------------------------
# Regulatory inspections and findings
# ---------------------------------------------------------------------------
def inspection_payload(
    store_id: str,
    scanner_audit_id: str,
    inspector_ref: Optional[str] = None,
    inspection_date: str = DEFAULT_CLOCK,
) -> Dict[str, Any]:
    return {
        "store_id": store_id,
        "scanner_audit_id": scanner_audit_id,
        "inspector_ref": inspector_ref
        if inspector_ref is not None
        else f"INS-{next_seq():03d}",
        "inspection_date": inspection_date,
    }


def finding_input(
    finding_code: str,
    severity: str,
    affected_item_count: int,
    affected_aisle_code: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "finding_code": finding_code,
            "severity": severity,
            "affected_item_count": affected_item_count,
            "affected_aisle_code": affected_aisle_code,
        }
    )


def issue_findings_payload(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"findings": findings}


def finding_transition_payload(
    target_status: str,
    remediation_action_code: Optional[str] = None,
    remediation_evidence_ref: Optional[str] = None,
    waiver_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "target_status": target_status,
            "remediation_action_code": remediation_action_code,
            "remediation_evidence_ref": remediation_evidence_ref,
            "waiver_reason": waiver_reason,
        }
    )


def inspection_response_payload(
    remediation_summary: str,
    expected_regulatory_inspection_version: int,
) -> Dict[str, Any]:
    return {
        "remediation_summary": remediation_summary,
        "expected_regulatory_inspection_version": expected_regulatory_inspection_version,
    }


def adjudicate_payload(
    decision: str,
    assessed_penalty_cents: Optional[int] = None,
    rejection_note: Optional[str] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "decision": decision,
            "assessed_penalty_cents": assessed_penalty_cents,
            "rejection_note": rejection_note,
        }
    )


# ---------------------------------------------------------------------------
# Refund claims
# ---------------------------------------------------------------------------
def refund_claim_payload(
    scan_line_id: str,
    customer_ref: str,
    expected_scanner_audit_version: int,
) -> Dict[str, Any]:
    return {
        "scan_line_id": scan_line_id,
        "customer_ref": customer_ref,
        "expected_scanner_audit_version": expected_scanner_audit_version,
    }


def settle_claim_payload(
    target_status: str, denial_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_status": target_status}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


# ---------------------------------------------------------------------------
# Exception reports
# ---------------------------------------------------------------------------
def exception_report_payload(
    store_id: str, period_start_at: str, period_end_at: str
) -> Dict[str, Any]:
    return {
        "store_id": store_id,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
    }


def root_cause_payload(
    root_cause_code: str, remediation_owner_associate_id: str
) -> Dict[str, Any]:
    return {
        "root_cause_code": root_cause_code,
        "remediation_owner_associate_id": remediation_owner_associate_id,
    }


def close_report_payload(closure_note: str = "Retraining delivered") -> Dict[str, Any]:
    return {"closure_note": closure_note}
