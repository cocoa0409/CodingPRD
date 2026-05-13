"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 / §4 declare as input for the
relevant endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-name helpers
# ---------------------------------------------------------------------------
def unique_suffix(length: int = 10) -> str:
    return uuid.uuid4().hex[:length]


def unique_sponsor_name(prefix: str = "ACME") -> str:
    return f"{prefix}-{unique_suffix(6).upper()}"


def unique_drug_name(prefix: str = "Drug") -> str:
    return f"{prefix}-{unique_suffix(6).upper()}"


def unique_full_name(prefix: str = "Member") -> str:
    return f"{prefix} {unique_suffix(6)}"


def unique_uri(prefix: str = "https://docs.example.com/file") -> str:
    return f"{prefix}/{unique_suffix(10)}.pdf"


def unique_applicant_id(prefix: str = "applicant") -> str:
    """An opaque PI identifier used as X-User-ID for Applicant calls and
    recorded as Application.applicant_id."""
    return f"{prefix}-{unique_suffix(8)}"


# ---------------------------------------------------------------------------
# Application  POST /ethics/applications  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_application_payload(
    *,
    sponsor_name: Optional[str] = None,
    drug_name: Optional[str] = None,
    indication: Optional[str] = None,
    phase: str = "PHASE_II",
    review_track: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1 application input fields: sponsor_name (1..200),
    drug_name (1..200), indication (1..500), phase, optional
    review_track (defaults to STANDARD when omitted)."""
    payload: Dict[str, Any] = {
        "sponsor_name": sponsor_name or unique_sponsor_name(),
        "drug_name": drug_name or unique_drug_name(),
        "indication": indication or "Type 2 Diabetes Mellitus",
        "phase": phase,
    }
    if review_track is not None:
        payload["review_track"] = review_track
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Submission  POST /ethics/applications/{id}/submissions  (PRD §3.1)
# ---------------------------------------------------------------------------
_SUBMISSION_URI_SENTINEL = object()


def create_submission_payload(
    *,
    protocol_doc_uri: Any = _SUBMISSION_URI_SENTINEL,
    investigator_brochure_uri: Any = _SUBMISSION_URI_SENTINEL,
    informed_consent_uri: Any = _SUBMISSION_URI_SENTINEL,
    cv_doc_uri: Any = _SUBMISSION_URI_SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1 submission inputs: four URI fields. Defaults supply
    non-null, non-empty strings so checklist_complete will be true; tests
    override individual URIs (e.g., to null/'') to probe incompleteness.

    A sentinel default is used (rather than ``None`` + ``or``) so that
    callers can explicitly pass ``None`` or ``""`` to probe the
    incomplete-checklist branch in PRD §3.1 without the helper silently
    substituting a non-empty default.
    """
    def _pick(value: Any, default_prefix: str) -> Any:
        if value is _SUBMISSION_URI_SENTINEL:
            return unique_uri(default_prefix)
        return value

    payload: Dict[str, Any] = {
        "protocol_doc_uri": _pick(protocol_doc_uri,
                                  "https://docs.example.com/protocol"),
        "investigator_brochure_uri": _pick(investigator_brochure_uri,
                                           "https://docs.example.com/ib"),
        "informed_consent_uri": _pick(informed_consent_uri,
                                      "https://docs.example.com/icf"),
        "cv_doc_uri": _pick(cv_doc_uri,
                            "https://docs.example.com/cv"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Submit application  POST /ethics/applications/{id}/submit  (PRD §3.1)
# ---------------------------------------------------------------------------
def submit_application_payload(
    *,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: optional 'version' field for optimistic concurrency."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Prescreen  POST /ethics/applications/{id}/prescreen  (PRD §3.1)
# ---------------------------------------------------------------------------
def prescreen_payload(
    *,
    decision: str,
    prescreen_notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'decision field — either PASS or REJECT — and an
    optional prescreen_notes rationale.'"""
    payload: Dict[str, Any] = {"decision": decision}
    if prescreen_notes is not None:
        payload["prescreen_notes"] = prescreen_notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CommitteeMember  POST /ethics/members  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_member_payload(
    *,
    full_name: Optional[str] = None,
    qualification: str = "MEDICAL_EXPERT",
    term_start: str = "2025-01-01T00:00:00.000Z",
    term_end: str = "2030-01-01T00:00:00.000Z",
    affiliated_sponsors: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: full_name, qualification, term_start, term_end, and
    optional affiliated_sponsors array (default empty)."""
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_full_name(),
        "qualification": qualification,
        "term_start": term_start,
        "term_end": term_end,
    }
    if affiliated_sponsors is not None:
        payload["affiliated_sponsors"] = affiliated_sponsors
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ConflictDeclaration  POST /ethics/members/{id}/conflicts  (PRD §3.2)
# ---------------------------------------------------------------------------
def declare_conflict_payload(
    *,
    application_id: str,
    conflict_type: str = "SPONSOR_RELATION",
    details: str = "Member is employed by trial sponsor.",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: '(member_id, application_id) pair, naming a
    conflict_type of SPONSOR_RELATION, CO_AUTHOR, or ECONOMIC_INTEREST
    together with free-text details.'"""
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "conflict_type": conflict_type,
        "details": details,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Meeting  POST /ethics/meetings  (PRD §3.3)
# ---------------------------------------------------------------------------
def create_meeting_payload(
    *,
    meeting_type: str = "STANDARD",
    scheduled_at: str,
    convener_member_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'meeting_type (either STANDARD for periodic review or
    EXPEDITED for an urgent-review session), an ISO 8601 UTC
    scheduled_at timestamp, and the convener_member_id of the committee
    member who will chair the session.'"""
    payload: Dict[str, Any] = {
        "meeting_type": meeting_type,
        "scheduled_at": scheduled_at,
        "convener_member_id": convener_member_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AgendaItem  POST /ethics/meetings/{id}/agenda-items  (PRD §3.3)
# ---------------------------------------------------------------------------
def create_agenda_item_payload(
    *,
    application_id: str,
    review_kind: str = "INITIAL_REVIEW",
    annual_report_id: Optional[str] = None,
    rectification_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'application_id to be reviewed, a review_kind from the
    closed set INITIAL_REVIEW, SECONDARY_REVIEW, ANNUAL_REVIEW,
    AMENDMENT_REVIEW, and FINAL_REPORT_REVIEW, and optionally either an
    annual_report_id ... or a rectification_id ...'"""
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "review_kind": review_kind,
    }
    if annual_report_id is not None:
        payload["annual_report_id"] = annual_report_id
    if rectification_id is not None:
        payload["rectification_id"] = rectification_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vote  POST /ethics/agenda-items/{id}/votes  (PRD §3.4)
# ---------------------------------------------------------------------------
def cast_vote_payload(
    *,
    vote_mode: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'supplying a vote_mode of APPROVE,
    APPROVE_WITH_MODIFICATION, REJECT, or DEFER.'"""
    payload: Dict[str, Any] = {"vote_mode": vote_mode}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rectification respond  (PRD §3.6)
# ---------------------------------------------------------------------------
def respond_rectification_payload(
    *,
    applicant_response_uri: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'applicant_response_uri that points to the response
    document'."""
    payload: Dict[str, Any] = {
        "applicant_response_uri": applicant_response_uri or unique_uri(
            "https://docs.example.com/response",
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AnnualReport  POST /ethics/applications/{aid}/annual-reports  (PRD §3.7)
# ---------------------------------------------------------------------------
def create_annual_report_payload(
    *,
    report_period_start: str = "2026-01-01T00:00:00.000Z",
    report_period_end: str = "2026-12-31T00:00:00.000Z",
    report_kind: str = "ANNUAL_PROGRESS",
    serious_adverse_event_count: int = 0,
    total_adverse_event_count: int = 0,
    enrollment_count: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'report_period_start and report_period_end ...,
    report_kind from ANNUAL_PROGRESS, PROTOCOL_AMENDMENT, or FINAL_REPORT,
    a serious_adverse_event_count ..., a total_adverse_event_count ...,
    and an enrollment_count ...'"""
    payload: Dict[str, Any] = {
        "report_period_start": report_period_start,
        "report_period_end": report_period_end,
        "report_kind": report_kind,
        "serious_adverse_event_count": serious_adverse_event_count,
        "total_adverse_event_count": total_adverse_event_count,
        "enrollment_count": enrollment_count,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock-advance  (PRD §4)
# ---------------------------------------------------------------------------
def clock_payload(
    *,
    target_timestamp: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: 'Advance the server's logical clock to a future ISO 8601
    UTC timestamp.'"""
    payload: Dict[str, Any] = {"target_timestamp": target_timestamp}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix",
    "unique_sponsor_name",
    "unique_drug_name",
    "unique_full_name",
    "unique_uri",
    "unique_applicant_id",
    "create_application_payload",
    "create_submission_payload",
    "submit_application_payload",
    "prescreen_payload",
    "create_member_payload",
    "declare_conflict_payload",
    "create_meeting_payload",
    "create_agenda_item_payload",
    "cast_vote_payload",
    "respond_rectification_payload",
    "create_annual_report_payload",
    "clock_payload",
]
