"""Payload builders.

Every builder returns a plain dict with sensible defaults that any test may
override through keyword arguments. Numeric fields — durations in milliseconds,
clip offsets, labour minutes, monetary amounts in cents and the optimistic
concurrency version — are always emitted as JSON numbers, never as strings.
"""

from typing import Any, Dict, List, Optional

from .constants import CITATION_FOR_CODE, INITIAL_CLOCK


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is the sentinel."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel: passing OMIT for a field removes it from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------- clock
def clock_payload(current_utc: str = INITIAL_CLOCK, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ---------------------------------------------------------------- staff
def staff_payload(
    full_name: str = "Dana Counsel",
    role_type: str = "COUNSEL",
    redaction_certification_level: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": full_name,
            "role_type": role_type,
            "redaction_certification_level": int(redaction_certification_level),
        },
        overrides,
    )


def counsel_payload(full_name: str = "Dana Counsel", level: int = 3, **overrides: Any) -> Dict[str, Any]:
    return staff_payload(full_name, "COUNSEL", level, **overrides)


def technician_payload(full_name: str = "Tess Tech", level: int = 3, **overrides: Any) -> Dict[str, Any]:
    return staff_payload(full_name, "TECHNICIAN", level, **overrides)


def reviewer_payload(full_name: str = "Quinn Review", level: int = 3, **overrides: Any) -> Dict[str, Any]:
    return staff_payload(full_name, "REVIEWER", level, **overrides)


# ------------------------------------------------------------ requesters
def requester_payload(
    full_name: str = "Pat Public",
    email: str = "pat@example.org",
    requester_type: str = "GENERAL_PUBLIC",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"full_name": full_name, "email": email, "requester_type": requester_type},
        overrides,
    )


# ----------------------------------------------------------- video assets
def video_asset_payload(
    incident_number: str = "INC-2026-0001",
    device_serial: str = "AXON-0001",
    officer_badge: str = "B-1000",
    recorded_start_at: str = "2026-07-30T01:00:00Z",
    duration_ms: int = 600000,
    classification: str = "ROUTINE",
    retention_category: str = "INVESTIGATIVE_3Y",
    scheduled_purge_at: str = "2029-07-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "incident_number": incident_number,
            "device_serial": device_serial,
            "officer_badge": officer_badge,
            "recorded_start_at": recorded_start_at,
            "duration_ms": int(duration_ms),
            "classification": classification,
            "retention_category": retention_category,
            "scheduled_purge_at": scheduled_purge_at,
        },
        overrides,
    )


def depicted_individual_payload(
    display_label: str = "SUBJECT-1", relationship: str = "BYSTANDER", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"display_label": display_label, "relationship": relationship}, overrides)


def purge_payload(destruction_note: str = "Retention schedule elapsed", **overrides: Any) -> Dict[str, Any]:
    return _merge({"destruction_note": destruction_note}, overrides)


# --------------------------------------------------------------- requests
def request_payload(
    requester_id: str,
    received_at: str = INITIAL_CLOCK,
    subject_incident_number: str = "INC-2026-0001",
    requested_date_from: str = "2026-07-30T00:00:00Z",
    requested_date_to: str = "2026-07-31T00:00:00Z",
    scope_narrative: str = "All BWC recordings for the incident",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "requester_id": requester_id,
            "received_at": received_at,
            "subject_incident_number": subject_incident_number,
            "requested_date_from": requested_date_from,
            "requested_date_to": requested_date_to,
            "scope_narrative": scope_narrative,
        },
        overrides,
    )


def scope_clarification_payload(
    expected_request_version: int,
    scope_narrative: str = "Narrowed to the contact itself",
    requested_date_from: str = "2026-07-30T00:00:00Z",
    requested_date_to: str = "2026-07-30T23:59:59Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "scope_narrative": scope_narrative,
            "requested_date_from": requested_date_from,
            "requested_date_to": requested_date_to,
            "expected_request_version": int(expected_request_version),
        },
        overrides,
    )


# ----------------------------------------------------- responsive records
def responsive_record_payload(video_asset_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"video_asset_id": video_asset_id}, overrides)


def inclusion_payload(inclusion_status: str = "RESPONSIVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"inclusion_status": inclusion_status}, overrides)


# ------------------------------------------------------- exemption claims
def exemption_claim_payload(
    exemption_code: str = "PERSONAL_PRIVACY",
    asserted_scope: str = "PARTIAL_REDACT",
    statutory_citation: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    citation = statutory_citation or CITATION_FOR_CODE[exemption_code]
    return _merge(
        {
            "exemption_code": exemption_code,
            "statutory_citation": citation,
            "asserted_scope": asserted_scope,
        },
        overrides,
    )


def adjudication_payload(
    disposition: str = "SUSTAINED",
    adjudication_note: str = "Statutory exemption confirmed",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"disposition": disposition, "adjudication_note": adjudication_note}, overrides)


# -------------------------------------------------------- redaction tasks
def redaction_task_payload(
    assigned_technician_id: str,
    target_type: str = "FACE",
    clip_start_ms: int = 0,
    clip_end_ms: int = 30000,
    exemption_claim_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_type": target_type,
        "clip_start_ms": int(clip_start_ms),
        "clip_end_ms": int(clip_end_ms),
        "assigned_technician_id": assigned_technician_id,
    }
    if exemption_claim_id is not None:
        payload["exemption_claim_id"] = exemption_claim_id
    return _merge(payload, overrides)


def submit_qa_payload(
    qa_reviewer_id: str,
    logged_labor_minutes: int = 5,
    qa_window_start_at: str = "2026-08-01T13:00:00Z",
    qa_window_end_at: str = "2026-08-01T14:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "logged_labor_minutes": int(logged_labor_minutes),
            "qa_reviewer_id": qa_reviewer_id,
            "qa_window_start_at": qa_window_start_at,
            "qa_window_end_at": qa_window_end_at,
        },
        overrides,
    )


def qa_outcome_payload(
    outcome: str = "PASS", defect_codes: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if defect_codes is not None:
        payload["defect_codes"] = list(defect_codes)
    return _merge(payload, overrides)


# ----------------------------------------------------- notification chain
def notification_payload(notice_method: str = "FIRST_CLASS_MAIL", **overrides: Any) -> Dict[str, Any]:
    return _merge({"notice_method": notice_method}, overrides)


def objection_payload(
    responsive_record_id: str, objection_basis: str = "PRIVACY", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"objection_basis": objection_basis, "responsive_record_id": responsive_record_id},
        overrides,
    )


# ---------------------------------------------------------- cost recovery
def fee_estimate_payload(
    expected_request_version: int,
    basis: str = "PRESUMPTIVE",
    media_type: str = "DIGITAL_DOWNLOAD",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "basis": basis,
            "media_type": media_type,
            "expected_request_version": int(expected_request_version),
        },
        overrides,
    )


def payment_payload(amount_cents: int, memo: str = "Payment posted", **overrides: Any) -> Dict[str, Any]:
    return _merge({"amount_cents": int(amount_cents), "memo": memo}, overrides)


def invoice_payload(memo: str = "Final cost-recovery invoice", **overrides: Any) -> Dict[str, Any]:
    return _merge({"memo": memo}, overrides)


def reversal_payload(memo: str = "Correction posted", **overrides: Any) -> Dict[str, Any]:
    return _merge({"memo": memo}, overrides)


# ---------------------------------------------------------------- endgame
def release_package_payload(media_type: str = "DIGITAL_DOWNLOAD", **overrides: Any) -> Dict[str, Any]:
    return _merge({"media_type": media_type}, overrides)


def denial_letter_payload(
    denial_type: str = "FULL",
    appeal_pathway_note: str = "Appeal in writing within thirty days.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"denial_type": denial_type, "appeal_pathway_note": appeal_pathway_note}, overrides
    )


def appeal_payload(appeal_grounds: str = "The exemptions do not cover this footage.", **overrides: Any) -> Dict[str, Any]:
    return _merge({"appeal_grounds": appeal_grounds}, overrides)


def appeal_decision_payload(decision: str = "UPHELD", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ------------------------------------------------------- litigation holds
def litigation_hold_payload(
    matter_number: str = "LIT-2026-0001",
    scope_incident_number: str = "INC-2026-0001",
    hold_type: str = "SUBPOENA",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "matter_number": matter_number,
            "scope_incident_number": scope_incident_number,
            "hold_type": hold_type,
        },
        overrides,
    )


def hold_release_payload(release_note: str = "Matter closed", **overrides: Any) -> Dict[str, Any]:
    return _merge({"release_note": release_note}, overrides)
