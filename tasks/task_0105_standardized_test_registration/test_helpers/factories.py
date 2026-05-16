"""Payload factories — one per entity, INPUT fields only.

PRD-required input fields per §3 entity descriptions. Computed fields
(status, balances, version, created_at, etc.) are never accepted from
input and never appear here.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Stable, unique string helpers
# ---------------------------------------------------------------------------
def unique_form_code(prefix: str = "FORM") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def unique_email(prefix: str = "candidate") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def unique_legal_name(prefix: str = "Candidate") -> str:
    return f"{prefix} {uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# TestEvent (PRD §3.1)
# ---------------------------------------------------------------------------
def create_test_event_payload(**overrides) -> Dict[str, Any]:
    """Default payload for POST /test-events.

    PRD §3.1 required: test_type, form_code, test_date,
    registration_deadline, late_registration_deadline,
    score_release_date, base_fee_cents, late_fee_cents. Subject is
    required for AP/CLEP and null for SAT/ACT.
    """
    defaults: Dict[str, Any] = {
        "test_type": "SAT",
        "form_code": unique_form_code("SAT"),
        "subject": None,
        "test_date": "2026-06-08T09:00:00.000Z",
        "registration_deadline": "2026-05-25T00:00:00.000Z",
        "late_registration_deadline": "2026-06-04T00:00:00.000Z",
        "score_release_date": "2026-06-15T00:00:00.000Z",
        "base_fee_cents": TEST_DEFAULTS["DEFAULT_BASE_FEE_CENTS"],
        "late_fee_cents": TEST_DEFAULTS["DEFAULT_LATE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def extend_deadline_payload(new_late_registration_deadline: str,
                            **overrides) -> Dict[str, Any]:
    """POST /test-events/{id}/extend-deadline payload."""
    defaults: Dict[str, Any] = {
        "new_late_registration_deadline": new_late_registration_deadline,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# TestCenter (PRD §3.2)
# ---------------------------------------------------------------------------
def create_test_center_payload(**overrides) -> Dict[str, Any]:
    """Default payload for POST /test-centers.

    PRD §3.2 required: name, address, state_code, timezone.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    defaults: Dict[str, Any] = {
        "name": f"Center {suffix}",
        "address": f"{suffix} Main St",
        "state_code": TEST_DEFAULTS["DEFAULT_STATE_CODE"],
        "timezone": TEST_DEFAULTS["DEFAULT_TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# TestCenterCapacity (PRD §3.2)
# ---------------------------------------------------------------------------
def create_capacity_payload(test_center_id: str,
                            total_capacity: int = 10,
                            accommodation_capacity: int = 2,
                            **overrides) -> Dict[str, Any]:
    """POST /test-events/{id}/test-center-capacities payload.

    PRD §3.2 required: test_center_id, total_capacity,
    accommodation_capacity (must not exceed total_capacity).
    """
    defaults: Dict[str, Any] = {
        "test_center_id": test_center_id,
        "total_capacity": total_capacity,
        "accommodation_capacity": accommodation_capacity,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Candidate (PRD §3.3)
# ---------------------------------------------------------------------------
def create_candidate_payload(**overrides) -> Dict[str, Any]:
    """Default payload for POST /candidates.

    PRD §3.3 required: legal_name, email, date_of_birth,
    home_state_code. has_iep_or_504 defaults to false.
    """
    defaults: Dict[str, Any] = {
        "legal_name": unique_legal_name(),
        "email": unique_email(),
        "date_of_birth": "2008-03-15",
        "home_state_code": TEST_DEFAULTS["DEFAULT_STATE_CODE"],
        "has_iep_or_504": False,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Registration (PRD §3.4)
# ---------------------------------------------------------------------------
def create_registration_payload(candidate_id: str,
                                test_center_id: str,
                                **overrides) -> Dict[str, Any]:
    """POST /test-events/{id}/registrations payload.

    PRD §3.4 required: candidate_id, test_center_id;
    force_confirmed optional (default false).
    """
    defaults: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "test_center_id": test_center_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# IDVerification (PRD §3.5)
# ---------------------------------------------------------------------------
def submit_id_payload(id_document_type: str = "DRIVERS_LICENSE",
                      issuing_state_code: Optional[str] = "CA",
                      id_expires_on: str = "2030-01-01",
                      **overrides) -> Dict[str, Any]:
    """POST .../id-verification/submit payload.

    PRD §3.5 required: id_document_type, id_expires_on;
    issuing_state_code optional (ignored when type=PASSPORT).
    """
    defaults: Dict[str, Any] = {
        "id_document_type": id_document_type,
        "issuing_state_code": issuing_state_code,
        "id_expires_on": id_expires_on,
    }
    defaults.update(overrides)
    # PRD §3.5: "an optional `issuing_state_code` (ignored when
    # `id_document_type` is `PASSPORT`)". Tests that pass PASSPORT
    # without a state must be able to drop the key entirely.
    if defaults.get("issuing_state_code") is None and id_document_type == "PASSPORT":
        defaults.pop("issuing_state_code", None)
    return defaults


def reject_id_payload(rejection_reason: str = "blurry photo",
                      **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


def clear_id_payload(**overrides) -> Dict[str, Any]:
    """POST .../id-verification/clear — only optional override flag."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# AccommodationRequest (PRD §3.6)
# ---------------------------------------------------------------------------
def create_accommodation_request_payload(candidate_id: str,
                                         test_event_id: str,
                                         requested_accommodations: Optional[List[str]] = None,
                                         supporting_documents: Optional[List[str]] = None,
                                         **overrides) -> Dict[str, Any]:
    """POST /accommodation-requests payload.

    PRD §3.6 required: candidate_id, test_event_id,
    requested_accommodations (enum array), supporting_documents
    (list of URIs / identifiers, at least one required to leave
    SUBMITTED).
    """
    defaults: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "test_event_id": test_event_id,
        "requested_accommodations": requested_accommodations or ["EXTENDED_TIME_50"],
        "supporting_documents": supporting_documents or [
            f"https://docs.example.com/{uuid.uuid4().hex[:10]}.pdf"
        ],
    }
    defaults.update(overrides)
    return defaults


def resubmit_accommodation_payload(supporting_documents: List[str],
                                   **overrides) -> Dict[str, Any]:
    """PATCH /accommodation-requests/{id}/resubmit payload.

    PRD §3.6: "the candidate who owns the request may re-submit by
    appending new entries to `supporting_documents` (the length must
    strictly increase) and providing the updated array".
    """
    defaults: Dict[str, Any] = {
        "supporting_documents": supporting_documents,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ScoreReport (PRD §3.9)
# ---------------------------------------------------------------------------
def create_score_report_payload(section_scores: Dict[str, int],
                                total_score: int,
                                report_type: str = "OFFICIAL",
                                **overrides) -> Dict[str, Any]:
    """POST /test-events/{id}/registrations/{id}/score-reports payload.

    PRD §3.9 required: section_scores (test_type-specific keys),
    total_score (range depends on program), report_type optional
    (default OFFICIAL).
    """
    defaults: Dict[str, Any] = {
        "section_scores": section_scores,
        "total_score": total_score,
        "report_type": report_type,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Cancellation payloads — optional version for OCC.
# ---------------------------------------------------------------------------
def cancel_payload(**overrides) -> Dict[str, Any]:
    """Body for DELETE .../registrations/{id} and
    POST .../admin-cancel — only optional version field per PRD §2.7."""
    return dict(overrides)


__all__ = [
    "unique_form_code",
    "unique_email",
    "unique_legal_name",
    "create_test_event_payload",
    "extend_deadline_payload",
    "create_test_center_payload",
    "create_capacity_payload",
    "create_candidate_payload",
    "create_registration_payload",
    "submit_id_payload",
    "reject_id_payload",
    "clear_id_payload",
    "create_accommodation_request_payload",
    "resubmit_accommodation_payload",
    "create_score_report_payload",
    "cancel_payload",
]
