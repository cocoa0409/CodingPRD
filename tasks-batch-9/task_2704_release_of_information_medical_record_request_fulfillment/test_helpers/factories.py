"""Payload builders.  Every money field is an integral number of cents and every
per-page rate is an integral number of millicents, so no factory ever emits a
float or a numeric string."""

import itertools
from typing import Any, Dict, List, Optional

from .constants import CA_FEE_RULE, CANONICAL_FACILITY

_mrn_counter = itertools.count(1)
_email_counter = itertools.count(1)


def unique_mrn() -> str:
    return f"MRN-{1000 + next(_mrn_counter)}"


def unique_email() -> str:
    return f"party{next(_email_counter)}@firm.example"


# ---------------------------------------------------------------- state fee rule
def state_fee_rule_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(CA_FEE_RULE)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- facility
def facility_payload(state_fee_rule_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = dict(CANONICAL_FACILITY)
    payload["state_fee_rule_id"] = state_fee_rule_id
    payload.update(overrides)
    return payload


def facility_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- patient
def patient_payload(facility_id: str, mrn: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_id": facility_id,
        "mrn": mrn if mrn is not None else unique_mrn(),
        "full_name": "Dana Reyes",
        "date_of_birth": "1984-03-11",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- requester
def attorney_requester_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requester_type": "ATTORNEY",
        "contact_email": "counsel@firm.example",
        "organization_name": "Firm LLP",
        "credential_number": "BAR-55",
        "signature_on_file": True,
    }
    payload.update(overrides)
    return payload


def patient_requester_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requester_type": "PATIENT",
        "contact_email": "dana@example.com",
        "patient_id": patient_id,
        "signature_on_file": True,
    }
    payload.update(overrides)
    return payload


def insurer_requester_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requester_type": "INSURER",
        "contact_email": "claims@carrier.example",
        "organization_name": "Carrier Mutual",
        "signature_on_file": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- authorization
def authorization_payload(
    patient_id: str,
    requester_id: str,
    expected_patient_version: int,
    scope_categories: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "requester_id": requester_id,
        "expected_patient_version": expected_patient_version,
        "signed_at": "2026-08-01T00:00:00Z",
        "expires_at": "2026-12-31T00:00:00Z",
        "scope_categories": list(scope_categories or ["GENERAL_MEDICAL"]),
        "designated_recipient_endpoint": "counsel@firm.example",
        "signature_verified": True,
    }
    payload.update(overrides)
    return payload


def authorization_cure_payload(
    scope_categories: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "signed_at": "2026-08-01T00:00:00Z",
        "expires_at": "2026-12-31T00:00:00Z",
        "scope_categories": list(scope_categories or ["GENERAL_MEDICAL"]),
        "designated_recipient_endpoint": "counsel@firm.example",
        "signature_verified": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- request
def third_party_request_payload(
    facility_id: str,
    patient_id: str,
    requester_id: str,
    authorization_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_id": facility_id,
        "patient_id": patient_id,
        "requester_id": requester_id,
        "authorization_id": authorization_id,
        "access_basis": "THIRD_PARTY_AUTHORIZATION",
        "requested_categories": ["GENERAL_MEDICAL"],
        "date_range_start": "2024-01-01",
        "date_range_end": "2025-12-31",
        "delivery_format": "SECURE_PORTAL",
    }
    payload.update(overrides)
    return payload


def patient_access_request_payload(
    facility_id: str, patient_id: str, requester_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_id": facility_id,
        "patient_id": patient_id,
        "requester_id": requester_id,
        "access_basis": "PATIENT_RIGHT_OF_ACCESS",
        "requested_categories": ["GENERAL_MEDICAL"],
        "date_range_start": "2024-01-01",
        "date_range_end": "2025-12-31",
        "delivery_format": "SECURE_PORTAL",
    }
    payload.update(overrides)
    return payload


def intake_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- record segment
def record_segment_payload(
    request_id: str, category: str = "GENERAL_MEDICAL", source_system: str = "EHR_CURRENT", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "source_system": source_system,
        "category": category,
    }
    payload.update(overrides)
    return payload


def retrieved_payload(page_count: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": "RETRIEVED", "page_count": page_count}
    payload.update(overrides)
    return payload


def unavailable_payload(reason: str = "chart destroyed under the retention schedule", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": "UNAVAILABLE", "unavailable_reason": reason}
    payload.update(overrides)
    return payload


def withdrawn_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": "WITHDRAWN"}
    payload.update(overrides)
    return payload


def redaction_payload(redacted_page_count: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "redacted_page_count": redacted_page_count,
        "redaction_note": "third-party identifiers",
    }
    payload.update(overrides)
    return payload


def redaction_decision_payload(decision: str, note: str = "sufficient", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "note": note}
    payload.update(overrides)
    return payload


def include_decision(segment_id: str, redaction_required: bool = False) -> Dict[str, Any]:
    return {
        "record_segment_id": segment_id,
        "decision": "INCLUDE",
        "redaction_required": redaction_required,
    }


def withhold_decision(segment_id: str) -> Dict[str, Any]:
    return {"record_segment_id": segment_id, "decision": "WITHHOLD"}


def sensitive_review_payload(segment_decisions: Optional[List[Dict[str, Any]]] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"segment_decisions": list(segment_decisions or [])}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- invoice
def invoice_payload(request_id: str, expected_request_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "expected_request_version": expected_request_version,
    }
    payload.update(overrides)
    return payload


def pay_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "PAY", "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def waive_payload(reason: str = "indigency waiver on file", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "WAIVE", "reason": reason}
    payload.update(overrides)
    return payload


def void_payload(reason: str = "BILLING_CLERK_VOID", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "VOID", "reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- delivery
def delivery_payload(
    request_id: str,
    delivery_format: str = "SECURE_PORTAL",
    recipient_endpoint: str = "counsel@firm.example",
    encryption: str = "TLS",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "delivery_format": delivery_format,
        "recipient_endpoint": recipient_endpoint,
        "encryption": encryption,
    }
    payload.update(overrides)
    return payload


def transmission_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if outcome == "FAILED":
        payload["failure_reason"] = "the portal handle bounced"
    payload.update(overrides)
    return payload


def confirm_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- denial
def denial_payload(
    request_id: str, grounds: str, denial_type: str = "FULL", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "denial_type": denial_type,
        "grounds": grounds,
        "rationale": "statutory ground applies to this disclosure",
    }
    payload.update(overrides)
    return payload


def denial_review_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "rationale": "second officer review"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- amendment
def amendment_payload(
    request_id: str, patient_id: str, record_segment_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "patient_id": patient_id,
        "record_segment_id": record_segment_id,
        "requested_change": "correct the discharge date on page 4",
    }
    payload.update(overrides)
    return payload


def amendment_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "rationale": "reviewed against the source chart"}
    payload.update(overrides)
    return payload


def amendment_resubmission_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"additional_information": "attached the corrected discharge summary"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- request actions
def release_payload(note: str = "released after prepayment", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"release_note": note}
    payload.update(overrides)
    return payload


def extension_payload(note: str = "compilation across four source systems", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"notice_note": note}
    payload.update(overrides)
    return payload


def withdraw_payload(reason: str = "the matter settled", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"withdrawal_reason": reason}
    payload.update(overrides)
    return payload


def revoke_payload(reason: str = "the patient withdrew consent", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"revocation_reason": reason}
    payload.update(overrides)
    return payload
