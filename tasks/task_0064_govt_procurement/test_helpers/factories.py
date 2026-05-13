"""Payload factories — one per endpoint with structured input.

Each factory emits the exact field names declared in PRD §3 prose. PRD
field-name fidelity is load-bearing because the implementation reads
JSON keys directly; an abbreviation here would force the implementer to
drop a PRD-required check in order to pass the test.

All factories accept **overrides for tests that need to mutate one field
while keeping the rest at defaults.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


# ===========================================================================
# Clock / events (PRD §2.4)
# ===========================================================================
def clock_advance_payload(target_iso: str) -> Dict[str, Any]:
    """PRD §2.4: "an admin-only test-driving capability that accepts a
    target_iso parameter, moves current_time forward to that instant."""
    return {"target_iso": target_iso}


def emit_event_payload(system: str,
                       payload: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §2.4: "A separate test-driving capability emits external
    events from credit-information or regulatory systems given a system
    discriminator and an arbitrary payload."""
    return {"system": system, "payload": payload}


# ===========================================================================
# Supplier (PRD §3.3)
# ===========================================================================
def create_supplier_payload(
    legal_name: str = "Test Supplier Co.",
    tax_id: str = "TAX-001",
    qualifications: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: "A supplier registers itself ... by providing a
    legal_name (non-empty and unique across all suppliers) and a tax_id
    (non-empty and unique), and optionally a list of qualifications
    strings such as 'ISO9001' or 'CONSTRUCTION_GRADE_A'."""
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "tax_id": tax_id,
    }
    if qualifications is not None:
        payload["qualifications"] = list(qualifications)
    payload.update(overrides)
    return payload


def blacklist_supplier_payload(
    blacklist_until: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: "A regulator may at any point blacklist the supplier ...
    supplying a blacklist_until UTC timestamp until which the supplier
    is treated as blacklisted."""
    payload: Dict[str, Any] = {"blacklist_until": blacklist_until}
    payload.update(overrides)
    return payload


# ===========================================================================
# Procurement plan (PRD §3.1)
# ===========================================================================
def create_plan_payload(
    agency_id: str = "agency-001",
    fiscal_year: int = 2026,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "A government agency begins the procurement cycle by
    creating a procurement plan tied to the agency's identifier
    (agency_id) and a target fiscal year (fiscal_year, an integer that
    must lie between 2000 and 2100 inclusive)."""
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "fiscal_year": int(fiscal_year),
    }
    payload.update(overrides)
    return payload


def create_plan_item_payload(
    title: str = "Test Plan Item",
    category: str = "GOODS",
    budget_cents: int = 10_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "Each line item, a PlanItem, carries a title (non-empty),
    a category chosen from GOODS, SERVICES, or WORKS, and a budget_cents
    allocation in integer cents that must be strictly greater than zero."""
    payload: Dict[str, Any] = {
        "title": title,
        "category": category,
        "budget_cents": int(budget_cents),
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Project (PRD §3.4)
# ===========================================================================
def create_project_payload(
    plan_item_id: str,
    title: str = "Test Project",
    evaluation_method: str = "LOWEST_PRICE",
    bid_submission_deadline: str = "2026-03-01T00:00:00.000Z",
    query_window_close_at: str = "2026-02-15T00:00:00.000Z",
    bid_opening_at: str = "2026-03-02T00:00:00.000Z",
    estimated_value_cents: int = 10_000_000,
    required_qualifications: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: "The creation payload supplies the parent plan_item_id,
    a title, the chosen evaluation_method (one of LOWEST_PRICE or
    COMPREHENSIVE_SCORING), three UTC timestamps (bid_submission_deadline,
    query_window_close_at, and bid_opening_at), a strictly positive
    estimated_value_cents (the price ceiling), and a list of
    required_qualifications strings every bidder must hold."""
    payload: Dict[str, Any] = {
        "plan_item_id": plan_item_id,
        "title": title,
        "evaluation_method": evaluation_method,
        "bid_submission_deadline": bid_submission_deadline,
        "query_window_close_at": query_window_close_at,
        "bid_opening_at": bid_opening_at,
        "estimated_value_cents": int(estimated_value_cents),
        "required_qualifications": (
            list(required_qualifications) if required_qualifications else []
        ),
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Tender document (PRD §3.4, §3.5)
# ===========================================================================
def lowest_price_evaluation_criteria() -> Dict[str, Any]:
    """PRD §3.4: "For LOWEST_PRICE, the object takes the form
    { 'tie_break': 'earliest_bid' }."""
    return {"tie_break": "earliest_bid"}


def comprehensive_scoring_evaluation_criteria(
    weight_price: float = 0.40,
    weight_technical: float = 0.40,
    weight_qualification: float = 0.20,
    max_technical_score: int = 100,
    max_qualification_score: int = 100,
) -> Dict[str, Any]:
    """PRD §3.4: "For COMPREHENSIVE_SCORING, the object carries three
    weights — weight_price, weight_technical, weight_qualification —
    each strictly between 0 and 1, exclusive on both ends, and summing
    to one within a tolerance of EPSILON (1e-9); it also carries
    max_technical_score and max_qualification_score."""
    return {
        "weight_price": weight_price,
        "weight_technical": weight_technical,
        "weight_qualification": weight_qualification,
        "max_technical_score": int(max_technical_score),
        "max_qualification_score": int(max_qualification_score),
    }


def create_tender_document_payload(
    template_id: str = "tmpl-001",
    technical_spec: str = "Standard technical specification text.",
    commercial_spec: str = "Net 30 payment terms; CNY; FOB destination.",
    evaluation_criteria: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: "The officer supplies a template_id from the
    tender-template library, a non-empty technical_spec, a non-empty
    commercial_spec (which carries payment terms), and an
    evaluation_criteria object whose shape varies by evaluation method."""
    if evaluation_criteria is None:
        evaluation_criteria = lowest_price_evaluation_criteria()
    payload: Dict[str, Any] = {
        "template_id": template_id,
        "technical_spec": technical_spec,
        "commercial_spec": commercial_spec,
        "evaluation_criteria": evaluation_criteria,
    }
    payload.update(overrides)
    return payload


def clarify_tender_payload(
    clarification_note: str = "Section 3.2 clarified.",
) -> Dict[str, Any]:
    """PRD §3.5: "the procurement officer can move the tender from
    PUBLISHED → CLARIFYING, supplying a clarification_note payload."""
    return {"clarification_note": clarification_note}


# ===========================================================================
# Bid (PRD §3.6)
# ===========================================================================
def submit_bid_payload(
    supplier_id: str,
    tender_document_version: int = 1,
    bid_price_cents: int = 8_000_000,
    technical_score_raw: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: "The submission payload carries supplier_id, the integer
    tender_document_version the bid was prepared against, the bid's
    bid_price_cents (a strictly positive integer), and an optional
    technical_score_raw (a self-declared technical score that defaults
    to 0 and is bounded by zero and max_technical_score)."""
    payload: Dict[str, Any] = {
        "supplier_id": supplier_id,
        "tender_document_version": int(tender_document_version),
        "bid_price_cents": int(bid_price_cents),
    }
    if technical_score_raw is not None:
        payload["technical_score_raw"] = int(technical_score_raw)
    payload.update(overrides)
    return payload


def record_evaluation_payload(
    technical_score_raw: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.8: "The endpoint accepts an optional technical_score_raw
    override; if absent the bid's stored value is used."""
    payload: Dict[str, Any] = {}
    if technical_score_raw is not None:
        payload["technical_score_raw"] = int(technical_score_raw)
    return payload


# ===========================================================================
# Committee (PRD §3.7)
# ===========================================================================
def form_committee_payload(
    requested_size: int = 3,
    selection_seed: str = "seed-001",
) -> Dict[str, Any]:
    """PRD §3.7: "The form-committee payload supplies a requested_size
    and a caller-supplied opaque selection_seed."""
    return {
        "requested_size": int(requested_size),
        "selection_seed": selection_seed,
    }


# ===========================================================================
# Query (PRD §3.7)
# ===========================================================================
def submit_query_payload(
    supplier_id: str,
    question: str = "What is the warranty term?",
) -> Dict[str, Any]:
    """PRD §3.7: "The submission payload carries supplier_id and a
    non-empty question."""
    return {"supplier_id": supplier_id, "question": question}


def respond_query_payload(response: str = "12 months warranty.") -> Dict[str, Any]:
    """PRD §3.7: "the procurement officer answers it via a response
    payload."""
    return {"response": response}


# ===========================================================================
# Complaint (PRD §3.10)
# ===========================================================================
def file_complaint_payload(
    complainant_supplier_id: str,
    subject: str = "EVALUATION",
    narrative: str = "Scoring appears inconsistent.",
) -> Dict[str, Any]:
    """PRD §3.10: "The submission payload carries
    complainant_supplier_id, a subject chosen from PRESCREEN_RESULT,
    EVALUATION, AWARD, or CONTRACT, and a non-empty narrative."""
    return {
        "complainant_supplier_id": complainant_supplier_id,
        "subject": subject,
        "narrative": narrative,
    }


def uphold_complaint_payload(corrective_action: str) -> Dict[str, Any]:
    """PRD §3.10: "Upholding ... requires corrective_action to be
    non-null and one of REOPEN_PRESCREEN, REOPEN_EVALUATION,
    REVOKE_AWARD, or FREEZE_PROJECT."""
    return {"corrective_action": corrective_action}


# ===========================================================================
# Contract (PRD §3.11)
# ===========================================================================
def file_contract_payload(
    project_id: str,
    award_id: str,
    supplier_id: str,
    contract_amount_cents: int,
    payment_terms: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.11: "The filing payload supplies project_id, award_id,
    supplier_id, contract_amount_cents, and payment_terms."""
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "award_id": award_id,
        "supplier_id": supplier_id,
        "contract_amount_cents": int(contract_amount_cents),
        "payment_terms": payment_terms,
    }
    payload.update(overrides)
    return payload


def contract_amendment_payload(
    delta_amount_cents: int,
    reason: str = "Scope adjustment.",
) -> Dict[str, Any]:
    """PRD §3.11: "Filing the amendment ... supplies a signed
    delta_amount_cents (positive or negative) and a non-empty reason."""
    return {
        "delta_amount_cents": int(delta_amount_cents),
        "reason": reason,
    }


def record_payment_payload(amount_cents: int) -> Dict[str, Any]:
    """PRD §3.11: "Payments are mirrored from the external payment system
    onto the contract through a record-payment capability that accepts
    an amount_cents payload."""
    return {"amount_cents": int(amount_cents)}


def terminate_contract_payload(
    reason: str = "Material breach.",
) -> Dict[str, Any]:
    """PRD §3.11: "A regulator may terminate an ACTIVE contract with a
    reason payload."""
    return {"reason": reason}


__all__ = [
    "clock_advance_payload",
    "emit_event_payload",
    "create_supplier_payload",
    "blacklist_supplier_payload",
    "create_plan_payload",
    "create_plan_item_payload",
    "create_project_payload",
    "lowest_price_evaluation_criteria",
    "comprehensive_scoring_evaluation_criteria",
    "create_tender_document_payload",
    "clarify_tender_payload",
    "submit_bid_payload",
    "record_evaluation_payload",
    "form_committee_payload",
    "submit_query_payload",
    "respond_query_payload",
    "file_complaint_payload",
    "uphold_complaint_payload",
    "file_contract_payload",
    "contract_amendment_payload",
    "record_payment_payload",
    "terminate_contract_payload",
]
