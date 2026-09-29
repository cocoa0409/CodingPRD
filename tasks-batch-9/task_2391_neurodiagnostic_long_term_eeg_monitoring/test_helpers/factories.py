"""
Request-payload builders.

Each builder produces a valid payload for one creating or transitioning
endpoint, with the field names spelled exactly as the contract spells them.
Keyword overrides let a test vary one field while every other field stays
valid, and passing `None` for an optional field omits it entirely so that
default-value behaviour can be exercised.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    ALERT_SOURCE_ALGORITHM,
    CLASSIFICATION_CLINICAL,
    DISPOSITION_ROUTINE,
    EVENT_CLINICAL_SEIZURE,
    INTERVENTION_POSITIONING,
    INTERVENTION_SEIZURE_TESTING,
    OUTCOME_APPROVE,
    RISK_MODERATE,
    SETTING_INPATIENT,
    SPECIALTY_EPILEPTOLOGY,
    T_ADMIT,
    VOTE_CANDIDATE,
)
from .test_users import TECHNOLOGIST_ID

_mrn_counter = itertools.count(1)
_label_counter = itertools.count(1)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the omission sentinel `None`."""
    return {key: value for key, value in payload.items() if value is not None}


def next_mrn(prefix: str = "MRN-2391") -> str:
    return f"{prefix}-{next(_mrn_counter):04d}"


def next_bed_label(prefix: str = "EMU") -> str:
    return f"{prefix}-{next(_label_counter)}"


# ---------------------------------------------------------------------------
# Unit inventory
# ---------------------------------------------------------------------------


def unit_payload(
    name: str = "EMU A",
    bed_count: int = 2,
    storage_quota_gb: float = 500.00,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "bed_count": bed_count,
        "storage_quota_gb": storage_quota_gb,
    }
    payload.update(overrides)
    return _prune(payload)


def bed_payload(
    unit_id: str, label: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {"unit_id": unit_id, "label": label or next_bed_label()}
    payload.update(overrides)
    return _prune(payload)


def shift_payload(
    unit_id: str,
    technologist_user_id: str = TECHNOLOGIST_ID,
    starts_at: str = T_ADMIT,
    ends_at: str = "2026-08-10T00:00:00Z",
    max_concurrent_studies: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "technologist_user_id": technologist_user_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "max_concurrent_studies": max_concurrent_studies,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Patients and funding
# ---------------------------------------------------------------------------


def patient_payload(
    mrn: Optional[str] = None,
    display_name: str = "Pat Monitored",
    risk_tier: str = RISK_MODERATE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "mrn": mrn or next_mrn(),
        "display_name": display_name,
        "risk_tier": risk_tier,
    }
    payload.update(overrides)
    return _prune(payload)


def authorization_payload(
    patient_id: str,
    requested_setting: str = SETTING_INPATIENT,
    requested_days: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "patient_id": patient_id,
        "requested_setting": requested_setting,
        "requested_days": requested_days,
    }
    payload.update(overrides)
    return _prune(payload)


def payer_decision_payload(
    outcome: str = OUTCOME_APPROVE,
    authorized_days: Optional[int] = 5,
    authorized_setting: Optional[str] = SETTING_INPATIENT,
    payer_note: Optional[str] = "approved",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "outcome": outcome,
        "authorized_days": authorized_days,
        "authorized_setting": authorized_setting,
        "payer_note": payer_note,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Admissions and taper
# ---------------------------------------------------------------------------


def admission_payload(
    patient_id: str,
    authorization_id: str,
    unit_id: str,
    setting: str = SETTING_INPATIENT,
    scheduled_admit_at: str = T_ADMIT,
    target_event_count: int = 4,
    planned_days: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "patient_id": patient_id,
        "authorization_id": authorization_id,
        "unit_id": unit_id,
        "setting": setting,
        "scheduled_admit_at": scheduled_admit_at,
        "target_event_count": target_event_count,
        "planned_days": planned_days,
    }
    payload.update(overrides)
    return _prune(payload)


def admit_payload(bed_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"bed_id": bed_id}
    payload.update(overrides)
    return _prune(payload)


def extension_payload(expected_admission_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"expected_admission_version": expected_admission_version}
    payload.update(overrides)
    return _prune(payload)


def discharge_payload(
    disposition: str = DISPOSITION_ROUTINE, **overrides: Any
) -> Dict[str, Any]:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return _prune(payload)


def taper_plan_payload(
    admission_id: str, total_steps: int = 3, **overrides: Any
) -> Dict[str, Any]:
    payload = {"admission_id": admission_id, "total_steps": total_steps}
    payload.update(overrides)
    return _prune(payload)


def taper_hold_payload(
    hold_reason: str = "Rescue medication administered", **overrides: Any
) -> Dict[str, Any]:
    payload = {"hold_reason": hold_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Studies
# ---------------------------------------------------------------------------


def study_payload(
    admission_id: str,
    channel_count: int = 32,
    modality: str = SETTING_INPATIENT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "admission_id": admission_id,
        "channel_count": channel_count,
        "modality": modality,
    }
    payload.update(overrides)
    return _prune(payload)


def start_payload(shift_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"shift_id": shift_id}
    payload.update(overrides)
    return _prune(payload)


def pause_payload(
    reason: str = "ROUTINE_SEGMENT_CLOSE",
    maintenance_kind: Optional[str] = None,
    impedance_kohm: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "reason": reason,
        "maintenance_kind": maintenance_kind,
        "impedance_kohm": impedance_kohm,
    }
    payload.update(overrides)
    return _prune(payload)


def export_hold_payload(
    hold_reason: str = "LEGAL_HOLD", **overrides: Any
) -> Dict[str, Any]:
    payload = {"hold_reason": hold_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Alerts, interventions and markings
# ---------------------------------------------------------------------------


def alert_payload(
    source: str = ALERT_SOURCE_ALGORITHM, **overrides: Any
) -> Dict[str, Any]:
    payload = {"source": source}
    payload.update(overrides)
    return _prune(payload)


def intervention_payload(
    interventions: Optional[List[str]] = None,
    injury_observed: bool = False,
    rescue_med_given: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "interventions": (
            list(interventions)
            if interventions is not None
            else [INTERVENTION_POSITIONING, INTERVENTION_SEIZURE_TESTING]
        ),
        "injury_observed": injury_observed,
        "rescue_med_given": rescue_med_given,
    }
    payload.update(overrides)
    return _prune(payload)


def adjudicate_alert_payload(
    classification: str = CLASSIFICATION_CLINICAL, **overrides: Any
) -> Dict[str, Any]:
    payload = {"classification": classification}
    payload.update(overrides)
    return _prune(payload)


def marking_payload(
    study_id: str,
    onset_at: str,
    event_class: str = EVENT_CLINICAL_SEIZURE,
    duration_seconds: Optional[int] = None,
    alert_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "study_id": study_id,
        "onset_at": onset_at,
        "event_class": event_class,
        "duration_seconds": duration_seconds,
        "alert_id": alert_id,
    }
    payload.update(overrides)
    return _prune(payload)


def retract_marking_payload(
    retraction_reason: str = "Reviewed as movement artifact", **overrides: Any
) -> Dict[str, Any]:
    payload = {"retraction_reason": retraction_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def issue_prelim_payload(
    localization: str = "LEFT_TEMPORAL", **overrides: Any
) -> Dict[str, Any]:
    payload = {"localization": localization}
    payload.update(overrides)
    return _prune(payload)


def addendum_payload(
    addendum_reason: str = "Additional review of overnight segment", **overrides: Any
) -> Dict[str, Any]:
    payload = {"addendum_reason": addendum_reason}
    payload.update(overrides)
    return _prune(payload)


def issue_final_payload(
    localization: str = "LEFT_TEMPORAL", **overrides: Any
) -> Dict[str, Any]:
    payload = {"localization": localization}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Exports and conference
# ---------------------------------------------------------------------------


def export_payload(
    study_id: str,
    expected_study_version: int,
    include_video: bool = False,
    supersedes_export_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "study_id": study_id,
        "include_video": include_video,
        "expected_study_version": expected_study_version,
        "supersedes_export_id": supersedes_export_id,
    }
    payload.update(overrides)
    return _prune(payload)


def deliver_payload(
    recipient_center: str = "Regional Surgical Center", **overrides: Any
) -> Dict[str, Any]:
    payload = {"recipient_center": recipient_center}
    payload.update(overrides)
    return _prune(payload)


def revoke_payload(
    revocation_reason: str = "WRONG_RECIPIENT_CENTER", **overrides: Any
) -> Dict[str, Any]:
    payload = {"revocation_reason": revocation_reason}
    payload.update(overrides)
    return _prune(payload)


def conference_case_payload(
    admission_id: str, export_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {"admission_id": admission_id, "export_id": export_id}
    payload.update(overrides)
    return _prune(payload)


def vote_payload(
    specialty: str = SPECIALTY_EPILEPTOLOGY,
    vote: str = VOTE_CANDIDATE,
    rationale: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"specialty": specialty, "vote": vote, "rationale": rationale}
    payload.update(overrides)
    return _prune(payload)
