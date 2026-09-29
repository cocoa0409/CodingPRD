"""Payload factories — one per request body, carrying only client-supplied inputs."""

from typing import Any, Dict, Optional

from .constants import DEFAULT_CLOCK, TEST_DEFAULTS


def clock_payload(current_utc: str = DEFAULT_CLOCK) -> Dict[str, Any]:
    return {"current_utc": current_utc}


def property_room_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["ROOM_NAME"],
        "agency_code": TEST_DEFAULTS["AGENCY_CODE"],
    }
    payload.update(overrides)
    return payload


def offense_statute_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "offense_code": "TH-3",
        "description": "Grand theft third degree",
        "preservation_class": "STANDARD",
        "statutory_retention_days": 365,
        "appeal_window_days": 30,
        "destruction_requires_court_order": False,
    }
    payload.update(overrides)
    return payload


def storage_location_payload(property_room_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "property_room_id": property_room_id,
        "code": "G-01",
        "category": "GENERAL",
        "capacity_slots": 2,
    }
    payload.update(overrides)
    return payload


def custodian_payload(property_room_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "property_room_id": property_room_id,
        "badge_number": "T-100",
        "full_name": "Tara Ng",
        "role_type": "EVIDENCE_TECH",
        "certification_expires_at": TEST_DEFAULTS["CERTIFICATION_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def suspend_payload(reason: str = "Pending internal review") -> Dict[str, Any]:
    return {"reason": reason}


def case_payload(property_room_id: str, offense_statute_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "property_room_id": property_room_id,
        "case_number": "26-00001",
        "offense_statute_id": offense_statute_id,
    }
    payload.update(overrides)
    return payload


def evidence_item_payload(case_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "item_description": "Pawn ticket folder",
        "category": "GENERAL",
        "packaging_type": "RIGID_BOX",
        "appraised_value_cents": 120000,
        "seized_at": TEST_DEFAULTS["SEIZED_AT"],
    }
    payload.update(overrides)
    return payload


def storage_assignment_payload(storage_location_id: Optional[str] = None) -> Dict[str, Any]:
    """Naming a bin is optional; omitting it asks the service to auto-select."""
    if storage_location_id is None:
        return {}
    return {"storage_location_id": storage_location_id}


def retention_determination_payload(
    evidence_item_id: str, basis: str, expected_evidence_item_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "evidence_item_id": evidence_item_id,
        "basis": basis,
        "expected_evidence_item_version": expected_evidence_item_version,
    }
    payload.update(overrides)
    return payload


def custody_transfer_payload(
    evidence_item_id: str,
    to_custodian_id: str,
    purpose: str,
    released_at: str,
    due_back_at: str,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "evidence_item_id": evidence_item_id,
        "to_custodian_id": to_custodian_id,
        "purpose": purpose,
        "released_at": released_at,
        "due_back_at": due_back_at,
    }
    payload.update(overrides)
    return payload


def release_payload(released_signature: str, witness_signature: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"released_signature": released_signature}
    if witness_signature is not None:
        payload["witness_signature"] = witness_signature
    return payload


def return_payload(receipt_signature: str) -> Dict[str, Any]:
    return {"receipt_signature": receipt_signature}


def report_lost_payload(reason: str = "Item not produced at the laboratory bench") -> Dict[str, Any]:
    return {"reason": reason}


def disposition_order_payload(
    evidence_item_id: str,
    order_type: str,
    requested_by_custodian_id: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_item_id": evidence_item_id,
        "type": order_type,
        "requested_by_custodian_id": requested_by_custodian_id,
    }
    payload.update(overrides)
    return payload


def authorize_payload(court_order_number: str) -> Dict[str, Any]:
    return {"court_order_number": court_order_number}


def reject_payload(reason: str = "Court refused the disposition") -> Dict[str, Any]:
    return {"reason": reason}


def execute_payload(executed_by_custodian_id: str, witness_custodian_id: str) -> Dict[str, Any]:
    return {
        "executed_by_custodian_id": executed_by_custodian_id,
        "witness_custodian_id": witness_custodian_id,
    }


def settle_payload(gross_sale_cents: int) -> Dict[str, Any]:
    return {"gross_sale_cents": gross_sale_cents}


def disburse_payload(payee_reference: str) -> Dict[str, Any]:
    return {"payee_reference": payee_reference}


def owner_claim_payload(evidence_item_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "evidence_item_id": evidence_item_id,
        "claimant_name": "Dana Whitlock",
        "claimant_contact": "22 Alder Street, Riverbend",
        "notice_method": "CERTIFIED_MAIL",
    }
    payload.update(overrides)
    return payload


def file_claim_payload(proof_document_ref: str = "PROOF-2026-3311") -> Dict[str, Any]:
    return {"proof_document_ref": proof_document_ref}


def audit_session_payload(
    storage_location_id: str,
    auditor_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    expected_storage_location_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "storage_location_id": storage_location_id,
        "auditor_id": auditor_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "expected_storage_location_version": expected_storage_location_version,
    }
    payload.update(overrides)
    return payload


def scan_payload(barcode: str) -> Dict[str, Any]:
    return {"barcode": barcode}


def resolve_discrepancy_payload(resolution: str, resolution_note: str) -> Dict[str, Any]:
    return {"resolution": resolution, "resolution_note": resolution_note}
