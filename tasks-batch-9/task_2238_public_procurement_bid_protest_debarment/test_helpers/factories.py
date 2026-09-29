"""Payload factories.

Each factory returns a request body containing input fields only — never a
computed or server-owned field. Naturally unique inputs (a vendor's tax id, a
solicitation number, a requirement code, a document reference) are generated
from monotonic counters so that a test which needs two independent rows never
trips a duplicate-key rule by accident.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import DEFAULT_CLOCK_UTC

_tax_id_counter = itertools.count(100000001)
_solicitation_counter = itertools.count(1)
_requirement_counter = itertools.count(1)
_document_counter = itertools.count(1)
_question_counter = itertools.count(1)


def next_tax_id() -> str:
    return str(next(_tax_id_counter))


def next_solicitation_number() -> str:
    return "SOL-2238-{:05d}".format(next(_solicitation_counter))


def next_requirement_code() -> str:
    return "REQ-{:05d}".format(next(_requirement_counter))


def next_document_ref() -> str:
    return "DOC-{:05d}".format(next(_document_counter))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
def vendor_payload(
    legal_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    contact_email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    tid = tax_id if tax_id is not None else next_tax_id()
    payload: Dict[str, Any] = {
        "legal_name": legal_name or "Ridgeline Paving LLC {}".format(tid),
        "tax_id": tid,
        "contact_email": contact_email or "v{}@example.gov".format(tid),
    }
    payload.update(overrides)
    return payload


def fee_deposit_payload(amount_cents: int = 200000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Solicitations
# ---------------------------------------------------------------------------
def requirement_payload(
    requirement_code: Optional[str] = None,
    description: str = "five percent bid bond",
    materiality: str = "MATERIAL",
    is_waivable: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requirement_code": requirement_code or next_requirement_code(),
        "description": description,
        "materiality": materiality,
        "is_waivable": is_waivable,
    }
    payload.update(overrides)
    return payload


def solicitation_payload(
    solicitation_number: Optional[str] = None,
    title: str = "Roadway Resurfacing District 4",
    issuing_agency_code: str = "DOT",
    estimated_value_cents: int = 100000000,
    original_bid_due_utc: str = "2026-08-27T00:00:00Z",
    original_question_deadline_utc: str = "2026-08-20T00:00:00Z",
    mandatory_requirements: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "solicitation_number": solicitation_number or next_solicitation_number(),
        "title": title,
        "issuing_agency_code": issuing_agency_code,
        "estimated_value_cents": estimated_value_cents,
        "original_bid_due_utc": original_bid_due_utc,
        "original_question_deadline_utc": original_question_deadline_utc,
        "mandatory_requirements": (
            mandatory_requirements
            if mandatory_requirements is not None
            else [requirement_payload(requirement_code="REQ-BOND")]
        ),
    }
    payload.update(overrides)
    return payload


def addendum_payload(
    summary: str = "clarifies striping color",
    extends_bid_due_by_days: int = 0,
    acknowledgment_required: bool = True,
    new_requirement_codes: Optional[List[Dict[str, Any]]] = None,
    answers_question_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "summary": summary,
        "extends_bid_due_by_days": extends_bid_due_by_days,
        "acknowledgment_required": acknowledgment_required,
        "new_requirement_codes": (
            new_requirement_codes if new_requirement_codes is not None else []
        ),
    }
    if answers_question_ids is not None:
        payload["answers_question_ids"] = answers_question_ids
    payload.update(overrides)
    return payload


def question_payload(
    vendor_id: str, question_text: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "question_text": question_text
        or "is the inspector certification transferable? (q{})".format(
            next(_question_counter)
        ),
    }
    payload.update(overrides)
    return payload


def cancel_payload(
    cancellation_reason: str = "appropriation lapsed before award", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def resolicit_payload(
    new_solicitation_number: Optional[str] = None,
    original_bid_due_utc: str = "2026-10-01T00:00:00Z",
    original_question_deadline_utc: str = "2026-09-24T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "new_solicitation_number": new_solicitation_number
        or next_solicitation_number(),
        "original_bid_due_utc": original_bid_due_utc,
        "original_question_deadline_utc": original_question_deadline_utc,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bids, responsiveness, responsibility
# ---------------------------------------------------------------------------
def bid_payload(
    solicitation_id: str,
    vendor_id: str,
    total_price_cents: int = 12000000,
    acknowledged_addendum_sequences: Optional[List[int]] = None,
    expected_solicitation_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "solicitation_id": solicitation_id,
        "vendor_id": vendor_id,
        "total_price_cents": total_price_cents,
        "acknowledged_addendum_sequences": (
            acknowledged_addendum_sequences
            if acknowledged_addendum_sequences is not None
            else []
        ),
    }
    if expected_solicitation_version is not None:
        payload["expected_solicitation_version"] = expected_solicitation_version
    payload.update(overrides)
    return payload


def responsiveness_payload(
    determination: str = "RESPONSIVE",
    reason_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "determination": determination,
        "reason_codes": reason_codes if reason_codes is not None else [],
    }
    payload.update(overrides)
    return payload


def responsibility_review_payload(
    financial_capacity_score: int = 80,
    past_performance_score: int = 85,
    integrity_score: int = 90,
    determination: str = "RESPONSIBLE",
    notes: str = "audited statements and three comparable projects",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "financial_capacity_score": financial_capacity_score,
        "past_performance_score": past_performance_score,
        "integrity_score": integrity_score,
        "determination": determination,
        "notes": notes,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------
def award_payload(
    solicitation_id: str, winning_bid_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "solicitation_id": solicitation_id,
        "winning_bid_id": winning_bid_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Protests, the agency record, hearings and the decision
# ---------------------------------------------------------------------------
def protest_payload(
    solicitation_id: str,
    protester_vendor_id: str,
    grounds_code: str = "EVALUATION_ERROR",
    narrative: str = "the bid abstract mis-extended the unit prices",
    challenged_bid_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "solicitation_id": solicitation_id,
        "protester_vendor_id": protester_vendor_id,
        "grounds_code": grounds_code,
        "narrative": narrative,
    }
    if challenged_bid_id is not None:
        payload["challenged_bid_id"] = challenged_bid_id
    payload.update(overrides)
    return payload


def record_item_payload(
    item_type: str = "AGENCY_REPORT",
    document_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_type": item_type,
        "document_ref": document_ref or next_document_ref(),
    }
    payload.update(overrides)
    return payload


def hearing_payload(
    hearing_officer_user_id: str,
    scheduled_start_utc: str = "2026-08-28T09:00:00Z",
    scheduled_end_utc: str = "2026-08-28T11:00:00Z",
    room_code: str = "ROOM-A",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hearing_officer_user_id": hearing_officer_user_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "room_code": room_code,
    }
    payload.update(overrides)
    return payload


def continuance_payload(
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    room_code: str = "ROOM-A",
    continuance_reason: str = "protester counsel unavailable",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "room_code": room_code,
        "continuance_reason": continuance_reason,
    }
    payload.update(overrides)
    return payload


def protest_decision_payload(
    outcome: str = "DENIED",
    rationale: str = "the record supports the agency determination",
    remedy_code: str = "NONE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "rationale": rationale,
        "remedy_code": remedy_code,
    }
    payload.update(overrides)
    return payload


def withdraw_payload(
    withdrawal_reason: str = "resolved informally with the agency", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


def stay_override_payload(
    urgency_justification: str = (
        "the culvert failure presents an imminent hazard to the travelling public"
    ),
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"urgency_justification": urgency_justification}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Debarment proceedings, responses, hearings, decisions, petitions
# ---------------------------------------------------------------------------
def proceeding_payload(
    vendor_id: str,
    cause_code: str = "FRAUD",
    aggravating_factor_codes: Optional[List[str]] = None,
    mitigating_factor_codes: Optional[List[str]] = None,
    interim_suspension: bool = False,
    source_protest_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "cause_code": cause_code,
        "aggravating_factor_codes": (
            aggravating_factor_codes
            if aggravating_factor_codes is not None
            else [cause_code]
        ),
        "mitigating_factor_codes": (
            mitigating_factor_codes if mitigating_factor_codes is not None else []
        ),
        "interim_suspension": interim_suspension,
    }
    if source_protest_id is not None:
        payload["source_protest_id"] = source_protest_id
    payload.update(overrides)
    return payload


def debarment_response_payload(
    response_narrative: str = "self-reported the invoice error and cooperated",
    mitigating_factor_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "response_narrative": response_narrative,
        "mitigating_factor_codes": (
            mitigating_factor_codes if mitigating_factor_codes is not None else []
        ),
    }
    payload.update(overrides)
    return payload


def debarment_hearing_payload(
    hearing_summary: str = "respondent appeared and was heard on the merits",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"hearing_summary": hearing_summary}
    payload.update(overrides)
    return payload


def debarment_decision_payload(
    outcome: str = "DEBARRED",
    rationale: str = "cause established by a preponderance of the evidence",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "rationale": rationale}
    payload.update(overrides)
    return payload


def petition_payload(
    remediation_evidence_codes: Optional[List[str]] = None,
    narrative: str = "field supervisors retrained and an independent audit passed",
    expected_proceeding_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "remediation_evidence_codes": (
            remediation_evidence_codes
            if remediation_evidence_codes is not None
            else ["TRAINING_COMPLETED"]
        ),
        "narrative": narrative,
    }
    if expected_proceeding_version is not None:
        payload["expected_proceeding_version"] = expected_proceeding_version
    payload.update(overrides)
    return payload


def petition_decision_payload(
    outcome: str = "GRANTED",
    decision_rationale: str = "remediation is documented and the period served",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "decision_rationale": decision_rationale,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Subcontractor screenings
# ---------------------------------------------------------------------------
def screening_payload(
    solicitation_id: str,
    prime_vendor_id: str,
    sub_vendor_id: str,
    tier: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "solicitation_id": solicitation_id,
        "prime_vendor_id": prime_vendor_id,
        "sub_vendor_id": sub_vendor_id,
        "tier": tier,
    }
    payload.update(overrides)
    return payload
