"""Payload factories — one per entity, only ``source: input`` fields.

Field names are PRD-exact (PRD §3 prose plus §4 endpoint inputs). Each
factory accepts ``**overrides`` so individual tests can pin specific
values for boundary or precondition behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def unique_bar_number(prefix: str = "BAR") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def unique_template_code(prefix: str = "TPL") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_court_room(prefix: str = "ROOM") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def unique_hash(prefix: str = "hash") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def unique_email() -> str:
    return f"party-{uuid.uuid4().hex[:8]}@example.com"


def unique_phone() -> str:
    """Generates a phone string within PRD §3.2 length constraints (7..20)."""
    return "+1" + uuid.uuid4().int.__str__()[:10]


def unique_intake_doc_id() -> str:
    return f"intake-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Lawyer
# ---------------------------------------------------------------------------
def create_lawyer_payload(
    *,
    full_name: Optional[str] = None,
    bar_number: Optional[str] = None,
    role: str = "PARTNER",
    hourly_rate_cents: int = 30_000,
    client_history: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Lawyer {uuid.uuid4().hex[:6]}",
        "bar_number": bar_number or unique_bar_number(),
        "role": role,
        "hourly_rate_cents": hourly_rate_cents,
    }
    if client_history is not None:
        payload["client_history"] = client_history
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------
def create_case_payload(
    *,
    lead_lawyer_id: str,
    case_type: str = "CIVIL",
    title: Optional[str] = None,
    claim_amount_cents: int = 5_000_000,
    client_identity_hash: Optional[str] = None,
    opposing_identity_hash: Optional[str] = None,
    intake_document_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_type": case_type,
        "title": title or f"Case {uuid.uuid4().hex[:6]}",
        "claim_amount_cents": claim_amount_cents,
        "lead_lawyer_id": lead_lawyer_id,
        "client_identity_hash": client_identity_hash or unique_hash("client"),
        "opposing_identity_hash": (
            opposing_identity_hash or unique_hash("opposing")
        ),
        "intake_document_id": intake_document_id or unique_intake_doc_id(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Party
# ---------------------------------------------------------------------------
def create_party_payload(
    *,
    party_role: str = "PLAINTIFF",
    full_name: Optional[str] = None,
    id_document_number: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    agency_lawyer_id: Optional[str] = None,
    access_level: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "party_role": party_role,
        "full_name": full_name or f"Party {uuid.uuid4().hex[:6]}",
        "id_document_number": (
            id_document_number or f"ID-{uuid.uuid4().hex[:10].upper()}"
        ),
        "contact_email": contact_email or unique_email(),
        "contact_phone": contact_phone or unique_phone(),
    }
    if agency_lawyer_id is not None:
        payload["agency_lawyer_id"] = agency_lawyer_id
    if access_level is not None:
        payload["access_level"] = access_level
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DocumentTemplate
# ---------------------------------------------------------------------------
def create_template_payload(
    *,
    template_code: Optional[str] = None,
    case_type: str = "CIVIL",
    name: Optional[str] = None,
    variables: Optional[List[str]] = None,
    body_template: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "template_code": template_code or unique_template_code(),
        "case_type": case_type,
        "name": name or f"Template {uuid.uuid4().hex[:6]}",
        "variables": (
            variables if variables is not None else ["{{case_number}}"]
        ),
        "body_template": (
            body_template
            or "Case: {{case_number}} — auto-generated draft body."
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DocumentDraft
# ---------------------------------------------------------------------------
def create_draft_payload(
    *,
    case_id: str,
    template_id: str,
    drafter_lawyer_id: str,
    variable_overrides: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "template_id": template_id,
        "drafter_lawyer_id": drafter_lawyer_id,
    }
    if variable_overrides is not None:
        payload["variable_overrides"] = variable_overrides
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Hearing
# ---------------------------------------------------------------------------
def create_hearing_payload(
    *,
    case_id: str,
    court_room: Optional[str] = None,
    scheduled_start: str,
    scheduled_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "court_room": court_room or unique_court_room(),
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def reschedule_hearing_payload(
    *,
    court_room: Optional[str] = None,
    scheduled_start: str,
    scheduled_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "court_room": court_room or unique_court_room(),
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------
def create_evidence_payload(
    *,
    case_id: str,
    evidence_type: str = "DOCUMENTARY",
    collected_at: str,
    collected_by_lawyer_id: str,
    case_fact_refs: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "evidence_type": evidence_type,
        "collected_at": collected_at,
        "collected_by_lawyer_id": collected_by_lawyer_id,
    }
    if case_fact_refs is not None:
        payload["case_fact_refs"] = case_fact_refs
    payload.update(overrides)
    return payload


def create_custody_event_payload(
    *,
    actor_lawyer_id: str,
    action: str,
    occurred_at: str,
    location: str = "Office Storage",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "actor_lawyer_id": actor_lawyer_id,
        "action": action,
        "occurred_at": occurred_at,
        "location": location,
    }
    payload.update(overrides)
    return payload


def create_rebuttal_payload(
    *,
    filed_by_lawyer_id: str,
    ground: str = "Hearsay objection — generated for test",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "filed_by_lawyer_id": filed_by_lawyer_id,
        "ground": ground,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TimeEntry / Bill
# ---------------------------------------------------------------------------
def create_time_entry_payload(
    *,
    lawyer_id: str,
    task_label: str = "Draft motion",
    minutes: int = 60,
    billable: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lawyer_id": lawyer_id,
        "task_label": task_label,
        "minutes": minutes,
        "billable": billable,
    }
    payload.update(overrides)
    return payload


def adjust_time_entry_payload(
    *,
    adjustment_minutes: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"adjustment_minutes": adjustment_minutes}
    payload.update(overrides)
    return payload


def create_bill_payload(
    *,
    billing_mode: str = "FIXED",
    fixed_fee_cents: Optional[int] = None,
    contingent_rate_bps: Optional[int] = None,
    recovered_amount_cents: Optional[int] = None,
    expense_reimbursement_cents: Optional[int] = None,
    cost_recovery_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"billing_mode": billing_mode}
    if fixed_fee_cents is not None:
        payload["fixed_fee_cents"] = fixed_fee_cents
    if contingent_rate_bps is not None:
        payload["contingent_rate_bps"] = contingent_rate_bps
    if recovered_amount_cents is not None:
        payload["recovered_amount_cents"] = recovered_amount_cents
    if expense_reimbursement_cents is not None:
        payload["expense_reimbursement_cents"] = expense_reimbursement_cents
    if cost_recovery_cents is not None:
        payload["cost_recovery_cents"] = cost_recovery_cents
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# External event payloads
# ---------------------------------------------------------------------------
def payment_event_payload(
    *,
    bill_id: str,
    amount_cents: int,
    external_payment_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "bill_id": bill_id,
        "amount_cents": amount_cents,
        "external_payment_id": (
            external_payment_id or f"pay-{uuid.uuid4().hex[:10]}"
        ),
    }
    payload.update(overrides)
    return payload


def signature_event_payload(
    *,
    draft_id: str,
    signature_kind: str = "DRAFT_LOCKED",
    external_signature_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "draft_id": draft_id,
        "signature_kind": signature_kind,
        "external_signature_id": (
            external_signature_id or f"sig-{uuid.uuid4().hex[:10]}"
        ),
    }
    payload.update(overrides)
    return payload


def court_filing_event_payload(
    *,
    evidence_id: str,
    court_filing_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_id": evidence_id,
        "court_filing_id": (
            court_filing_id or f"court-{uuid.uuid4().hex[:10]}"
        ),
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_bar_number",
    "unique_template_code",
    "unique_court_room",
    "unique_hash",
    "unique_email",
    "unique_phone",
    "unique_intake_doc_id",
    "create_lawyer_payload",
    "create_case_payload",
    "create_party_payload",
    "create_template_payload",
    "create_draft_payload",
    "create_hearing_payload",
    "reschedule_hearing_payload",
    "create_evidence_payload",
    "create_custody_event_payload",
    "create_rebuttal_payload",
    "create_time_entry_payload",
    "adjust_time_entry_payload",
    "create_bill_payload",
    "payment_event_payload",
    "signature_event_payload",
    "court_filing_event_payload",
]
