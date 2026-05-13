"""Payload factories for the Travel Reimburse API.

One factory per create/mutate endpoint. Only `source: input` fields are
emitted; computed/system fields (status, totals, etc.) are NEVER included
in factory output because PRD §2.4 forbids client-supplied id/version.

Factory keys mirror PRD field names exactly. Tests pass overrides via
keyword arguments.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def unique_invoice_number(prefix: str = "INV") -> str:
    """Generate a unique invoice serial for tests."""
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def unique_invoice_code(prefix: str = "CODE") -> str:
    """Generate a unique invoice code for tests."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_option_code(prefix: str = "OPT") -> str:
    """Generate a unique policy option code for tests."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ---------------------------------------------------------------------------
# Employee  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_employee_payload(
    full_name: str = "Test Employee",
    employee_level: str = "STAFF",
    department_id: Optional[str] = None,
    supervisor_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /employees."""
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "employee_level": employee_level,
        "department_id": department_id or f"dept-{uuid.uuid4().hex[:8]}",
        "supervisor_id": supervisor_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ExpenseStandard  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_expense_standard_payload(
    version: int = 1,
    effective_from: str = "2024-01-01T00:00:00.000Z",
    effective_to: Optional[str] = None,
    city_tier: str = "TIER_2",
    employee_level: str = "STAFF",
    lodging_daily_cap: float = 400.00,
    per_diem_amount: float = 80.00,
    transportation_daily_cap: float = 120.00,
    holiday_multiplier: float = 1.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /expense-standards.

    PRD §3.1: every row is keyed by (version, city_tier, employee_level).
    holiday_multiplier defaults to 1.00 per PRD §3.1.
    """
    payload: Dict[str, Any] = {
        "version": version,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "city_tier": city_tier,
        "employee_level": employee_level,
        "lodging_daily_cap": lodging_daily_cap,
        "per_diem_amount": per_diem_amount,
        "transportation_daily_cap": transportation_daily_cap,
        "holiday_multiplier": holiday_multiplier,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TravelApplication  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_travel_application_payload(
    destination_city: str = "Shanghai",
    destination_tier: str = "TIER_2",
    travel_scope: str = "DOMESTIC",
    purpose: str = "Customer onboarding visit",
    planned_start: str = "2025-06-01T09:00:00.000Z",
    planned_end: str = "2025-06-04T18:00:00.000Z",
    estimated_budget: float = 2_000.00,
    urgent: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /travel-applications.

    PRD §3.2: applicant_id is INFERRED from X-User-ID, not the body;
    `urgent` is optional with default false (we let server default unless
    explicitly set).
    """
    payload: Dict[str, Any] = {
        "destination_city": destination_city,
        "destination_tier": destination_tier,
        "travel_scope": travel_scope,
        "purpose": purpose,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "estimated_budget": estimated_budget,
    }
    if urgent is not None:
        payload["urgent"] = urgent
    payload.update(overrides)
    return payload


def patch_travel_application_payload(version: int,
                                     **overrides: Any) -> Dict[str, Any]:
    """Inputs to PATCH /travel-applications/{id}. Only `version` is
    required (per PRD §2.5 OCC); other fields are optional partial updates."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


def reject_payload(rejection_reason: str = "Needs more justification",
                   **overrides: Any) -> Dict[str, Any]:
    """Inputs to POST /travel-applications/{id}/reject and
    POST /reimbursement-forms/{id}/reject (without correction flag)."""
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def reject_form_payload(rejection_reason: str = "Need additional receipts",
                        correction: bool = True,
                        **overrides: Any) -> Dict[str, Any]:
    """Inputs to POST /reimbursement-forms/{id}/reject.

    PRD §3.7: correction=true returns the form to DRAFT and increments
    correction_round; correction=false terminates as REJECTED.
    """
    payload: Dict[str, Any] = {
        "rejection_reason": rejection_reason,
        "correction": correction,
    }
    payload.update(overrides)
    return payload


def approval_payload(comment: Optional[str] = None,
                     **overrides: Any) -> Dict[str, Any]:
    """Inputs to /approve endpoints. comment is optional per PRD §3.2."""
    payload: Dict[str, Any] = {}
    if comment is not None:
        payload["comment"] = comment
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ItinerarySegment  (PRD §3.3)
# ---------------------------------------------------------------------------
def book_segment_payload(
    segment_type: str = "FLIGHT",
    option_code: str = "OPT-FLIGHT-001",
    start_at: str = "2025-06-01T10:00:00.000Z",
    end_at: str = "2025-06-01T13:00:00.000Z",
    cost: float = 500.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /travel-applications/{id}/itineraries and the
    /change endpoint."""
    payload: Dict[str, Any] = {
        "segment_type": segment_type,
        "option_code": option_code,
        "start_at": start_at,
        "end_at": end_at,
        "cost": cost,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invoice  (PRD §3.6)
# ---------------------------------------------------------------------------
def upload_invoice_payload(
    applicant_id: str,
    invoice_number: Optional[str] = None,
    invoice_code: Optional[str] = None,
    category: str = "LODGING",
    amount: Optional[float] = None,
    invoice_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /invoices.

    PRD §3.6: 'optionally the amount and invoice_date if those are
    already known'. amount/invoice_date are optional in the upload step.
    """
    payload: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "invoice_number": invoice_number or unique_invoice_number(),
        "invoice_code": invoice_code or unique_invoice_code(),
        "category": category,
    }
    if amount is not None:
        payload["amount"] = amount
    if invoice_date is not None:
        payload["invoice_date"] = invoice_date
    payload.update(overrides)
    return payload


def tax_verify_pin_payload(invoice_id: str,
                           verdict: str = "VALID",
                           **overrides: Any) -> Dict[str, Any]:
    """Inputs to POST /_external/invoice-verify-result.

    PRD §3.10: 'pins the outcome of the next tax-authority verification on
    a specific invoice, taking an invoice_id and a verdict of either
    VALID or INVALID.'
    """
    payload: Dict[str, Any] = {"invoice_id": invoice_id, "verdict": verdict}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReimbursementForm + Item  (PRD §3.7)
# ---------------------------------------------------------------------------
def create_form_payload(application_id: str,
                        **overrides: Any) -> Dict[str, Any]:
    """Inputs to POST /reimbursement-forms.

    PRD §3.7: 'Creating the form requires only the parent application_id;
    the form is created in DRAFT with applicant_id mirrored from the
    application.'
    """
    payload: Dict[str, Any] = {"application_id": application_id}
    payload.update(overrides)
    return payload


def add_item_payload(
    invoice_id: str,
    category: str,
    covered_days: int = 1,
    claimed_amount: float = 100.00,
    matched_segment_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /reimbursement-forms/{id}/items.

    PRD §3.7: matched_segment_id is required for LODGING and TRANSPORTATION
    items; nullable for PER_DIEM and OTHER.
    """
    payload: Dict[str, Any] = {
        "invoice_id": invoice_id,
        "category": category,
        "covered_days": covered_days,
        "claimed_amount": claimed_amount,
    }
    if matched_segment_id is not None:
        payload["matched_segment_id"] = matched_segment_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payment  (PRD §3.9)
# ---------------------------------------------------------------------------
def payment_batch_payload(
    form_ids: List[str],
    channel: str = "BANK_TRANSFER",
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /payments/batches."""
    payload: Dict[str, Any] = {
        "form_ids": list(form_ids),
        "channel": channel,
    }
    payload.update(overrides)
    return payload


def payment_result_payload(
    outcome: str = "SUCCESS",
    external_ref: Optional[str] = None,
    failure_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inputs to POST /payments/{id}/result.

    PRD §3.9: 'outcome (SUCCESS or FAILED), an optional external_ref
    (populated on success), and an optional failure_reason (populated on
    failure).'
    """
    payload: Dict[str, Any] = {"outcome": outcome}
    if outcome == "SUCCESS":
        payload["external_ref"] = (
            external_ref or f"BANK-REF-{uuid.uuid4().hex[:8].upper()}"
        )
    elif outcome == "FAILED":
        payload["failure_reason"] = (
            failure_reason or "Insufficient funds at originating account"
        )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-harness payloads (PRD §3.10)
# ---------------------------------------------------------------------------
def clock_payload(seconds: int) -> Dict[str, Any]:
    """Inputs to POST /_clock/advance."""
    return {"seconds": int(seconds)}


def booking_options_payload(segment_type: str,
                            employee_level: str,
                            option_codes: List[str]) -> Dict[str, Any]:
    """Inputs to POST /_external/booking-options."""
    return {
        "segment_type": segment_type,
        "employee_level": employee_level,
        "option_codes": list(option_codes),
    }


__all__ = [
    "unique_invoice_number",
    "unique_invoice_code",
    "unique_option_code",
    "create_employee_payload",
    "create_expense_standard_payload",
    "create_travel_application_payload",
    "patch_travel_application_payload",
    "reject_payload",
    "reject_form_payload",
    "approval_payload",
    "book_segment_payload",
    "upload_invoice_payload",
    "tax_verify_pin_payload",
    "create_form_payload",
    "add_item_payload",
    "payment_batch_payload",
    "payment_result_payload",
    "clock_payload",
    "booking_options_payload",
]
