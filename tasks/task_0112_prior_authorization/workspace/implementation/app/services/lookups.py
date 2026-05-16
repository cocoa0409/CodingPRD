"""Existence lookups used by validations (priority 3 / 4)."""
from ..errors import APIError
from ..store import get_store


def get_patient_or_404(patient_id: str) -> dict:
    rec = get_store().patients.get(patient_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"Patient {patient_id} not found")
    return rec


def get_provider_or_404(provider_id: str) -> dict:
    rec = get_store().providers.get(provider_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"Provider {provider_id} not found")
    return rec


def get_catalog_or_404(item_id: str) -> dict:
    rec = get_store().catalog_items.get(item_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"ServiceCatalogItem {item_id} not found")
    return rec


def get_authorization_or_404(auth_id: str) -> dict:
    rec = get_store().authorization_requests.get(auth_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"AuthorizationRequest {auth_id} not found")
    return rec


def get_evidence_or_404(evidence_id: str) -> dict:
    rec = get_store().clinical_evidence.get(evidence_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"ClinicalEvidence {evidence_id} not found")
    return rec


def get_peer_review_or_404(p2p_id: str) -> dict:
    rec = get_store().peer_to_peer_reviews.get(p2p_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"PeerToPeerReview {p2p_id} not found")
    return rec


def get_appeal_or_404(appeal_id: str) -> dict:
    rec = get_store().appeals.get(appeal_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"Appeal {appeal_id} not found")
    return rec


def reference_or_404(table: dict, ref_id: str, label: str) -> dict:
    """Generic 'foreign-key body reference must exist' check (validation #4)."""
    rec = table.get(ref_id)
    if rec is None:
        raise APIError("ERR_REFERENCE_NOT_FOUND", f"{label} {ref_id} not found")
    return rec
