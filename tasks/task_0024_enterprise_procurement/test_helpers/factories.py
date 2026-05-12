"""Payload factories — one factory per entity, input fields only.

Field names match the PRD verbatim (PRD §3). All factories accept
**overrides so individual tests can pin values they need to exercise
boundary or precondition behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_budget_code(department: str = "IT", purpose: str = "CAPEX") -> str:
    """PRD §3.1 budget code pattern: BA-NNNN-LETTERS-LETTERS.

    Random four-digit number + uppercase department & purpose tokens.
    Append a random uppercase A-Z suffix to the purpose group so
    collisions across the ~hundred budgets created during a full test
    run are effectively impossible (4 digits alone would collide every
    ~150 accounts via the birthday bound). The suffix uses only A-Z so
    the code still matches the implementation's "BA-NNNN-UPPER-UPPER"
    pattern (no digits in the letter groups).
    """
    import random
    n = uuid.uuid4().int % 10000
    rng = random.Random(uuid.uuid4().int)
    suffix = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(8))
    return f"BA-{n:04d}-{department.upper()}-{purpose.upper()}{suffix}"


def unique_legal_name(prefix: str = "Supplier") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_tax_id() -> str:
    return f"TAX-{uuid.uuid4().hex[:12].upper()}"


def unique_clause_code(prefix: str = "CL") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_invoice_no(prefix: str = "INV") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def unique_delivery_note_no(prefix: str = "DN") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# ---------------------------------------------------------------------------
# BudgetAccount payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_budget_account_payload(
    *,
    code: Optional[str] = None,
    department: str = "IT",
    fiscal_year: int = 2030,
    total_amount_cents: int = 100_000_000,  # $1,000,000
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_budget_code(department=department, purpose="CAPEX"),
        "department": department,
        "fiscal_year": fiscal_year,
        "total_amount_cents": total_amount_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Supplier payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_supplier_payload(
    *,
    legal_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    qualification_categories: Optional[List[str]] = None,
    qualification_expires_at: str = "2099-12-31T23:59:59.000Z",
    bank_account_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or unique_legal_name(),
        "tax_id": tax_id or unique_tax_id(),
        "qualification_categories": qualification_categories or ["IT_HARDWARE"],
        "qualification_expires_at": qualification_expires_at,
        "bank_account_id": bank_account_id or f"bank-{uuid.uuid4().hex[:12]}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Requirement payload (PRD §3.2)
# ---------------------------------------------------------------------------
def create_requirement_payload(
    *,
    category: str = "IT_HARDWARE",
    specification: str = "Standard issue laptop, 16GB RAM, 512GB SSD",
    quantity: int = 10,
    unit: str = "unit",
    expected_delivery_date: str = "2030-06-01T00:00:00.000Z",
    budget_account_id: Optional[str] = None,
    estimated_unit_price_cents: int = 100_000,
    attachment_uri: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category": category,
        "specification": specification,
        "quantity": quantity,
        "unit": unit,
        "expected_delivery_date": expected_delivery_date,
        "budget_account_id": budget_account_id,
        "estimated_unit_price_cents": estimated_unit_price_cents,
    }
    if attachment_uri is not None:
        payload["attachment_uri"] = attachment_uri
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Quote payload (PRD §3.2)
# ---------------------------------------------------------------------------
def add_quote_payload(
    *,
    supplier_id: str,
    unit_price_cents: int = 100_000,
    lead_time_days: int = 14,
    technical_score: float = 80.00,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supplier_id": supplier_id,
        "unit_price_cents": unit_price_cents,
        "lead_time_days": lead_time_days,
        "technical_score": technical_score,
    }
    payload.update(overrides)
    return payload


def shortlist_payload(*, quote_ids: List[str], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quote_ids": list(quote_ids)}
    payload.update(overrides)
    return payload


def award_payload(
    *,
    awarded_quote_id: str,
    justification: str = "Best score in pool-relative composite ranking.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "awarded_quote_id": awarded_quote_id,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contract / Clause payloads (PRD §3.6)
# ---------------------------------------------------------------------------
def create_clause_template_payload(
    *,
    code: Optional[str] = None,
    title: str = "Standard payment clause",
    body: str = "Payment shall be made per attached schedule.",
    category: str = "PAYMENT",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_clause_code(),
        "title": title,
        "body": body,
        "category": category,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(
    *,
    purchase_order_id: str,
    clause_template_ids: List[str],
    payment_terms_type: str = "ON_DELIVERY",
    payment_terms_params: Optional[Dict[str, Any]] = None,
    parties_required: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "purchase_order_id": purchase_order_id,
        "clause_template_ids": list(clause_template_ids),
        "payment_terms_type": payment_terms_type,
        "payment_terms_params": (
            payment_terms_params if payment_terms_params is not None else {}
        ),
        "parties_required": parties_required or ["Buyer", "Supplier"],
    }
    payload.update(overrides)
    return payload


def amend_contract_payload(
    *, change_reason: str = "Editorial revision", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"change_reason": change_reason}
    payload.update(overrides)
    return payload


def sign_contract_payload(
    *, role: str, signature_ref: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "role": role,
        "signature_ref": signature_ref or f"sig-{uuid.uuid4().hex[:12]}",
    }
    payload.update(overrides)
    return payload


def terminate_contract_payload(
    *, reason: str = "Supplier non-performance", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Receipt payload (PRD §3.8)
# ---------------------------------------------------------------------------
def create_receipt_payload(
    *,
    delivery_note_no: Optional[str] = None,
    received_quantity: int = 10,
    accepted_quantity: int = 10,
    quality_rating: float = 90.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delivery_note_no": delivery_note_no or unique_delivery_note_no(),
        "received_quantity": received_quantity,
        "accepted_quantity": accepted_quantity,
        "quality_rating": quality_rating,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invoice payload (PRD §3.9)
# ---------------------------------------------------------------------------
def create_invoice_payload(
    *,
    purchase_order_id: str,
    supplier_id: str,
    invoice_no: Optional[str] = None,
    invoice_date: str = "2030-04-01T00:00:00.000Z",
    invoiced_quantity: int = 10,
    invoiced_amount_cents: int = 100_000,
    tax_amount_cents: int = 11_504,
    tax_rate_declared: float = 0.13,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "purchase_order_id": purchase_order_id,
        "supplier_id": supplier_id,
        "invoice_no": invoice_no or unique_invoice_no(),
        "invoice_date": invoice_date,
        "invoiced_quantity": invoiced_quantity,
        "invoiced_amount_cents": invoiced_amount_cents,
        "tax_amount_cents": tax_amount_cents,
        "tax_rate_declared": tax_rate_declared,
    }
    payload.update(overrides)
    return payload


def reject_invoice_payload(
    *, reason: str = "Mismatch beyond tolerance", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def override_invoice_payload(
    *, justification: str = "GM override after vendor reconciliation", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"justification": justification}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payment payloads (PRD §3.10)
# ---------------------------------------------------------------------------
def apply_payment_payload(
    *, payment_schedule_id: str, invoice_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "payment_schedule_id": payment_schedule_id,
        "invoice_id": invoice_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Approval / delegation payloads (PRD §3.4)
# ---------------------------------------------------------------------------
def delegate_step_payload(*, target_user_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_user_id": target_user_id}
    payload.update(overrides)
    return payload


def approve_step_payload(
    *, decision_comment: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if decision_comment is not None:
        payload["decision_comment"] = decision_comment
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driving payloads (PRD §3.11)
# ---------------------------------------------------------------------------
def supplier_delivery_payload(
    *,
    purchase_order_id: str,
    delivery_note_no: Optional[str] = None,
    declared_quantity: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "purchase_order_id": purchase_order_id,
        "delivery_note_no": delivery_note_no or unique_delivery_note_no(),
        "declared_quantity": declared_quantity,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_budget_code",
    "unique_legal_name",
    "unique_tax_id",
    "unique_clause_code",
    "unique_invoice_no",
    "unique_delivery_note_no",
    "create_budget_account_payload",
    "create_supplier_payload",
    "create_requirement_payload",
    "add_quote_payload",
    "shortlist_payload",
    "award_payload",
    "create_clause_template_payload",
    "create_contract_payload",
    "amend_contract_payload",
    "sign_contract_payload",
    "terminate_contract_payload",
    "create_receipt_payload",
    "create_invoice_payload",
    "reject_invoice_payload",
    "override_invoice_payload",
    "apply_payment_payload",
    "delegate_step_payload",
    "approve_step_payload",
    "supplier_delivery_payload",
]
