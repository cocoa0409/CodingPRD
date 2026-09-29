"""Payload builders.

Each builder returns a valid request body with sensible defaults that any
test can override with keyword arguments.  Values that must be unique across
rows (profile codes, physical credential numbers, certificate serials) are
suffixed with a monotonic counter so a single test can create several rows.
"""

from itertools import count
from typing import Any, Dict, List, Optional

_counter = count(1)


def _next() -> int:
    return next(_counter)


# --------------------------------------------------------------------------
# Interoperability profile
# --------------------------------------------------------------------------
def interop_profile_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "profile_code": f"AAMVA-MDL-{_next():04d}",
        "standard_version": "ISO_18013_5_2021",
    }
    payload.update(overrides)
    return payload


def trust_list_snapshot_payload(
    interop_profile_id: str,
    expected_interop_profile_version: int,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_until: str = "2026-12-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "interop_profile_id": interop_profile_id,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "expected_interop_profile_version": expected_interop_profile_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Holder
# --------------------------------------------------------------------------
def holder_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Rosa Ibarra",
        "date_of_birth": "1990-04-11",
        "address_line1": "18 Cedar Row",
        "city": "Waverly",
        "state_code": "NE",
        "postal_code": "68462",
        "physical_credential_number": f"NE-44178{_next():03d}",
        "physical_credential_expires_on": "2030-06-30",
    }
    payload.update(overrides)
    return payload


def address_change_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "address_line1": "402 Birch Lane",
        "city": "Waverly",
        "state_code": "NE",
        "postal_code": "68462",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Identity proofing
# --------------------------------------------------------------------------
def proofing_session_payload(holder_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_id": holder_id,
        "requested_assurance_level": "IAL2",
    }
    payload.update(overrides)
    return payload


def evidence_payload(
    evidence_type: str = "DOCUMENT_SCAN",
    quality: str = "STRONG",
    captured_at: str = "2026-07-20T09:00:00Z",
    source_reference: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_type": evidence_type,
        "quality": quality,
        "captured_at": captured_at,
        "source_reference": source_reference or f"src-{_next()}",
    }
    payload.update(overrides)
    return payload


def adjudication_payload(decision: str = "VERIFY", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Device
# --------------------------------------------------------------------------
def device_payload(holder_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_id": holder_id,
        "platform": "ANDROID",
        "model_name": "Pixel 9",
        "hardware_attestation_token": f"att-tok-{_next()}",
        "protection_method": "BIOMETRIC",
    }
    payload.update(overrides)
    return payload


def attestation_payload(
    attestation_result: str = "PASS",
    secure_element_grade: str = "HARDWARE_STRONGBOX",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "attestation_result": attestation_result,
        "secure_element_grade": secure_element_grade,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Digital credential
# --------------------------------------------------------------------------
def credential_payload(
    holder_id: str,
    device_id: str,
    proofing_session_id: str,
    expected_device_version: int,
    valid_from: str = "2026-08-01T00:00:00Z",
    valid_until: str = "2031-07-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_id": holder_id,
        "device_id": device_id,
        "proofing_session_id": proofing_session_id,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "expected_device_version": expected_device_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Verifier and reader application
# --------------------------------------------------------------------------
def verifier_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_name": "Prairie Cellars",
        "category": "AGE_RESTRICTED_RETAIL",
        "purpose_scope": ["family_name", "age_over_21"],
        "retention_ceiling_days": 30,
    }
    payload.update(overrides)
    return payload


def reader_app_payload(
    verifier_id: str,
    requested_elements: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "verifier_id": verifier_id,
        "app_identifier": f"till-{_next()}",
        "certificate_serial": f"SER-{_next():04d}",
        "cert_not_before": "2026-07-01T00:00:00Z",
        "cert_not_after": "2027-07-01T00:00:00Z",
        "requested_elements": requested_elements
        if requested_elements is not None
        else ["family_name", "age_over_21"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Presentation session
# --------------------------------------------------------------------------
def presentation_session_payload(
    credential_id: str,
    reader_app_id: str,
    requested_elements: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "credential_id": credential_id,
        "reader_app_id": reader_app_id,
        "context": "ROUTINE",
        "purpose": "age check at point of sale",
        "requested_elements": requested_elements
        if requested_elements is not None
        else ["family_name", "age_over_21"],
        "handset_handling": "TAP_TO_READ",
        "retention_days": 5,
    }
    payload.update(overrides)
    return payload


def consent_payload(
    consent_decision: str = "APPROVE",
    unlock_method: Optional[str] = "BIOMETRIC",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"consent_decision": consent_decision}
    if unlock_method is not None:
        payload["unlock_method"] = unlock_method
    payload.update(overrides)
    return payload
