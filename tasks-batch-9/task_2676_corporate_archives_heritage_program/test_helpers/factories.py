"""Payload factories: valid-by-default request bodies with overridable fields.

Each factory returns a dict containing exactly the required input fields of one
endpoint, with realistic archives-domain values. Optional fields are omitted
unless the caller passes them, so that a factory never silently supplies a
value the API is supposed to default for itself. Numbers stay numbers — money
is an integer count of cents and never a string.
"""

from itertools import count
from typing import Any, Dict, List, Optional

_SEQ = count(1)


def _next() -> int:
    """A per-process counter used to keep unique business keys distinct."""
    return next(_SEQ)


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override of ``None`` removes the field entirely."""
    for key, value in overrides.items():
        if value is None and key in payload:
            del payload[key]
        else:
            payload[key] = value
    return payload


# ─── RetentionSchedule ────────────────────────────────────────────────────

def retention_schedule_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    payload = {
        "code": f"SCH-{n:04d}",
        "retention_years": 7,
        "disposition_action": "DESTROY",
        "legal_citation": "Corporate Records Policy 4.2",
        "min_appraisal_score_for_permanent": 80.00,
    }
    return _apply(payload, overrides)


# ─── RecordSeries ─────────────────────────────────────────────────────────

def record_series_payload(retention_schedule_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "title": "Board Minutes",
        "business_unit": "Corporate Secretary",
        "retention_schedule_id": retention_schedule_id,
        "sensitivity_ceiling": "INTERNAL",
        "annual_volume_linear_feet": 20,
        "earliest_record_year": 1960,
        "latest_record_year": 2000,
    }
    return _apply(payload, overrides)


def dispose_payload(certificate_reference: str, **overrides) -> Dict[str, Any]:
    payload = {"disposition_certificate_reference": certificate_reference}
    return _apply(payload, overrides)


# ─── LegalHold ────────────────────────────────────────────────────────────

def legal_hold_payload(record_series_id: str, **overrides) -> Dict[str, Any]:
    n = _next()
    payload = {
        "matter_number": f"MAT-{n:04d}",
        "record_series_id": record_series_id,
        "effective_from": "2026-08-01T00:00:00Z",
    }
    return _apply(payload, overrides)


def release_payload(note: str = "Matter closed; hold lifted.", **overrides):
    payload = {"release_note": note}
    return _apply(payload, overrides)


# ─── AppraisalRecord ──────────────────────────────────────────────────────

def appraisal_payload(
    record_series_id: str,
    expected_series_version: int,
    informational_value: int = 8,
    evidential_value: int = 7,
    brand_heritage_value: int = 6,
    uniqueness_factor: int = 5,
    provenance_verified: bool = True,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "record_series_id": record_series_id,
        "informational_value": informational_value,
        "evidential_value": evidential_value,
        "brand_heritage_value": brand_heritage_value,
        "uniqueness_factor": uniqueness_factor,
        "provenance_verified": provenance_verified,
        "expected_series_version": expected_series_version,
    }
    return _apply(payload, overrides)


# ─── Accession ────────────────────────────────────────────────────────────

def accession_payload(
    record_series_id: str, declared_unit_count: int = 2, **overrides
) -> Dict[str, Any]:
    payload = {
        "record_series_id": record_series_id,
        "donor_name": "Corporate Records Centre",
        "transfer_instrument": "INTERNAL_TRANSFER",
        "declared_unit_count": declared_unit_count,
    }
    return _apply(payload, overrides)


def verify_provenance_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    payload = {
        "provenance_statement": "Chain of custody confirmed against the transfer list.",
        "transfer_instrument_reference": f"IT-2026-{n:04d}",
    }
    return _apply(payload, overrides)


def reject_accession_payload(
    reason: str = "Duplicates of records already held; no archival value.", **overrides
) -> Dict[str, Any]:
    payload = {"rejection_reason": reason}
    return _apply(payload, overrides)


# ─── ArchivalItem ─────────────────────────────────────────────────────────

def archival_item_payload(
    accession_id: str,
    storage_zone_id: str,
    unit_count: int = 2,
    condition_grade: str = "GOOD",
    original_format: str = "PAPER",
    sensitivity_level: str = "INTERNAL",
    brand_use_year: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    n = _next()
    payload = {
        "accession_id": accession_id,
        "storage_zone_id": storage_zone_id,
        "item_label": f"BOX-{n:04d}",
        "unit_count": unit_count,
        "condition_grade": condition_grade,
        "original_format": original_format,
        "sensitivity_level": sensitivity_level,
    }
    if brand_use_year is not None:
        payload["brand_use_year"] = brand_use_year
    return _apply(payload, overrides)


# ─── StorageZone ──────────────────────────────────────────────────────────

def storage_zone_payload(
    temperature_c: float = 16.0,
    relative_humidity_pct: float = 42.0,
    max_overlapping_migration_jobs: int = 1,
    **overrides,
) -> Dict[str, Any]:
    n = _next()
    payload = {
        "zone_code": f"Z-{n:04d}",
        "temperature_c": temperature_c,
        "relative_humidity_pct": relative_humidity_pct,
        "max_overlapping_migration_jobs": max_overlapping_migration_jobs,
    }
    return _apply(payload, overrides)


def environment_reading_payload(
    temperature_c: float, relative_humidity_pct: float, **overrides
) -> Dict[str, Any]:
    payload = {
        "temperature_c": temperature_c,
        "relative_humidity_pct": relative_humidity_pct,
    }
    return _apply(payload, overrides)


# ─── FindingAid ───────────────────────────────────────────────────────────

def finding_aid_payload(accession_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "accession_id": accession_id,
        "title": "Guide to the Records",
        "arrangement_level": "SERIES",
        "version_label": "v1",
    }
    return _apply(payload, overrides)


# ─── PreservationPlan ─────────────────────────────────────────────────────

def preservation_plan_payload(
    storage_zone_id: str, budget_cents: int = 500000, **overrides
) -> Dict[str, Any]:
    payload = {
        "storage_zone_id": storage_zone_id,
        "plan_name": "Magnetic Media Rescue",
        "budget_cents": budget_cents,
    }
    return _apply(payload, overrides)


# ─── MigrationJob ─────────────────────────────────────────────────────────

def migration_job_payload(
    preservation_plan_id: str,
    archival_item_id: str,
    units: int = 10,
    window_start: str = "2026-09-01T00:00:00Z",
    window_end: str = "2026-09-30T00:00:00Z",
    target_format: str = "PRESERVATION_TIFF",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "preservation_plan_id": preservation_plan_id,
        "archival_item_id": archival_item_id,
        "target_format": target_format,
        "units": units,
        "window_start": window_start,
        "window_end": window_end,
    }
    return _apply(payload, overrides)


# ─── Requester ────────────────────────────────────────────────────────────

def requester_payload(
    requester_class: str = "EXTERNAL_RESEARCHER",
    nda_on_file: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    n = _next()
    payload = {
        "display_name": f"Researcher {n}",
        "requester_class": requester_class,
        "affiliation": "School of Business History",
    }
    if nda_on_file is not None:
        payload["nda_on_file"] = nda_on_file
    return _apply(payload, overrides)


def suspend_requester_payload(
    reason: str = "Breach of reading-room rules.", **overrides
) -> Dict[str, Any]:
    payload = {"suspend_reason": reason}
    return _apply(payload, overrides)


# ─── AccessRequest ────────────────────────────────────────────────────────

def access_request_payload(
    requester_id: str,
    record_series_id: str,
    requested_item_ids: List[str],
    finding_aid_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "requester_id": requester_id,
        "record_series_id": record_series_id,
        "purpose": "Research into the company's post-war expansion.",
        "requested_item_ids": list(requested_item_ids),
    }
    if finding_aid_id is not None:
        payload["finding_aid_id"] = finding_aid_id
    return _apply(payload, overrides)


def revise_payload(
    requested_item_ids: List[str], purpose: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload = {"requested_item_ids": list(requested_item_ids)}
    if purpose is not None:
        payload["purpose"] = purpose
    return _apply(payload, overrides)


def approve_request_payload(approval_scope: str = "FULL", **overrides) -> Dict[str, Any]:
    payload = {"approval_scope": approval_scope}
    return _apply(payload, overrides)


def deny_request_payload(
    reason: str = "Confidential personnel content.", **overrides
) -> Dict[str, Any]:
    payload = {"deny_reason": reason}
    return _apply(payload, overrides)


# ─── ConfidentialityScreening ─────────────────────────────────────────────

def screening_payload(
    access_request_id: str, expected_access_request_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "access_request_id": access_request_id,
        "expected_access_request_version": expected_access_request_version,
    }
    return _apply(payload, overrides)


def complete_screening_payload(
    decision: str = "GRANT_FULL",
    redaction_required: Optional[bool] = None,
    screening_note: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if redaction_required is not None:
        payload["redaction_required"] = redaction_required
    if screening_note is not None:
        payload["screening_note"] = screening_note
    return _apply(payload, overrides)


# ─── OralHistoryInterview ─────────────────────────────────────────────────

def interview_payload(
    accession_id: str,
    interview_date: str = "2026-07-15T14:00:00Z",
    embargo_until: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "accession_id": accession_id,
        "narrator_name": "H. Vogel",
        "interview_date": interview_date,
    }
    if embargo_until is not None:
        payload["embargo_until"] = embargo_until
    return _apply(payload, overrides)


def consent_payload(consent_action: str, **overrides) -> Dict[str, Any]:
    payload = {"consent_action": consent_action}
    return _apply(payload, overrides)


def transcription_payload(transcription_action: str, **overrides) -> Dict[str, Any]:
    payload = {"transcription_action": transcription_action}
    return _apply(payload, overrides)


# ─── TrademarkEvidencePackage ─────────────────────────────────────────────

def evidence_package_payload(
    record_series_id: str,
    claimed_first_use_year: int,
    evidence_item_ids: List[str],
    mark_name: str = "HERITAGE BLUE",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "record_series_id": record_series_id,
        "mark_name": mark_name,
        "claimed_first_use_year": claimed_first_use_year,
        "evidence_item_ids": list(evidence_item_ids),
    }
    return _apply(payload, overrides)


# ─── ExhibitLoan ──────────────────────────────────────────────────────────

def exhibit_loan_payload(
    archival_item_id: str,
    window_start: str,
    window_end: str,
    units: int = 2,
    exhibit_name: str = "Centenary Hall",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "archival_item_id": archival_item_id,
        "exhibit_name": exhibit_name,
        "units": units,
        "window_start": window_start,
        "window_end": window_end,
    }
    return _apply(payload, overrides)


def return_loan_payload(returned_condition_grade: str = "GOOD", **overrides):
    payload = {"returned_condition_grade": returned_condition_grade}
    return _apply(payload, overrides)


# ─── DeaccessionProposal ──────────────────────────────────────────────────

def deaccession_proposal_payload(
    archival_item_id: str,
    units: int = 2,
    route: str = "DESTRUCTION",
    recipient_repository: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "archival_item_id": archival_item_id,
        "rationale": "Duplicate of the master file held elsewhere.",
        "route": route,
        "units": units,
    }
    if recipient_repository is not None:
        payload["recipient_repository"] = recipient_repository
    return _apply(payload, overrides)


def clearance_payload(note: Optional[str] = None, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if note is not None:
        payload["clearance_note"] = note
    return _apply(payload, overrides)


def execute_payload(transfer_reference: str, **overrides) -> Dict[str, Any]:
    payload = {"transfer_reference": transfer_reference}
    return _apply(payload, overrides)


# ─── Trailing action payloads ─────────────────────────────────────────────

def cancel_job_payload(
    reason: str = "Vendor withdrew the quotation.", **overrides
) -> Dict[str, Any]:
    payload = {"cancel_reason": reason}
    return _apply(payload, overrides)


def submit_review_payload(version_label: Optional[str] = None, **overrides):
    payload: Dict[str, Any] = {}
    if version_label is not None:
        payload["version_label"] = version_label
    return _apply(payload, overrides)


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
