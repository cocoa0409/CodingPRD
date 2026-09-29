"""Payload factories — one per write operation, input fields only."""
from typing import Any, Dict, List, Optional

# Canonical reference values used across the suite.
DEFAULTS = {
    "PLAN_CODE": "P1",
    "PAYER_NAME": "Meridian Health",
    "ENDOSCOPIST_NPI": "1000000001",
    "ENDOSCOPIST_NAME": "Dr Ada Ng",
    "ANESTHESIA_NPI": "2000000001",
    "ANESTHESIA_NAME": "Dr Bo Reyes",
    "MRN": "MRN-0001",
    "BIRTH_DATE": "1975-04-10",
    "ROOM_CODE": "ENDO-1",
    "SESSION_DATE": "2026-09-15",
    "WINDOW_START_UTC": "2026-09-15T13:00:00Z",
    "WINDOW_END_UTC": "2026-09-15T21:00:00Z",
    "SLOT_START_UTC": "2026-09-15T13:00:00Z",
    "DURATION_MINUTES": 45,
    "REFERRING_PROVIDER_NPI": "9000000001",
    "ACCESSION_NUMBER": "ACC-0001",
    "CLOCK_ISO": "2026-09-01T00:00:00Z",
}


def create_insurance_plan_payload(**overrides) -> Dict[str, Any]:
    """`plan_code` and `payer_name` are required; every cost-sharing term has a default."""
    payload: Dict[str, Any] = {
        "plan_code": DEFAULTS["PLAN_CODE"],
        "payer_name": DEFAULTS["PAYER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_clinician_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "npi": DEFAULTS["ENDOSCOPIST_NPI"],
        "full_name": DEFAULTS["ENDOSCOPIST_NAME"],
        "clinician_type": "ENDOSCOPIST",
    }
    payload.update(overrides)
    return payload


def create_anesthesia_clinician_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "npi": DEFAULTS["ANESTHESIA_NPI"],
        "full_name": DEFAULTS["ANESTHESIA_NAME"],
        "clinician_type": "ANESTHESIA",
    }
    payload.update(overrides)
    return payload


def create_patient_payload(insurance_plan_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mrn": DEFAULTS["MRN"],
        "birth_date": DEFAULTS["BIRTH_DATE"],
        "insurance_plan_id": insurance_plan_id,
        "asa_class": 2,
    }
    payload.update(overrides)
    return payload


def create_endoscopy_session_payload(lead_endoscopist_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "room_code": DEFAULTS["ROOM_CODE"],
        "session_date": DEFAULTS["SESSION_DATE"],
        "window_start_utc": DEFAULTS["WINDOW_START_UTC"],
        "window_end_utc": DEFAULTS["WINDOW_END_UTC"],
        "lead_endoscopist_id": lead_endoscopist_id,
    }
    payload.update(overrides)
    return payload


def session_status_action_payload(action: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return payload


def create_anesthesia_coverage_payload(anesthesia_clinician_id: str,
                                       coverage_start_utc: str = DEFAULTS["WINDOW_START_UTC"],
                                       coverage_end_utc: str = DEFAULTS["WINDOW_END_UTC"],
                                       **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "anesthesia_clinician_id": anesthesia_clinician_id,
        "coverage_start_utc": coverage_start_utc,
        "coverage_end_utc": coverage_end_utc,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "referring_provider_npi": DEFAULTS["REFERRING_PROVIDER_NPI"],
        "reason": "AVERAGE_RISK_SCREENING",
        "asa_class_reported": 2,
    }
    payload.update(overrides)
    return payload


def triage_action_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def create_screening_episode_payload(patient_id: str,
                                     indication: str = "SCREENING_AVERAGE_RISK",
                                     **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"patient_id": patient_id, "indication": indication}
    payload.update(overrides)
    return payload


def close_episode_payload(reason: str) -> Dict[str, Any]:
    return {"reason": reason}


def outreach_payload(channel: str, acknowledged: Optional[bool] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"channel": channel}
    if acknowledged is not None:
        payload["acknowledged"] = acknowledged
    return payload


def prep_attestation_payload(regimen_completed: bool) -> Dict[str, Any]:
    return {"regimen_completed": regimen_completed}


def create_noninvasive_test_payload(test_type: str = "FIT",
                                    collected_date: str = "2026-09-01") -> Dict[str, Any]:
    return {"test_type": test_type, "collected_date": collected_date}


def noninvasive_test_result_payload(result: str) -> Dict[str, Any]:
    return {"result": result}


def create_procedure_booking_payload(episode_id: str, performing_endoscopist_id: str,
                                     expected_session_version: int,
                                     slot_start_utc: str = DEFAULTS["SLOT_START_UTC"],
                                     duration_minutes: int = DEFAULTS["DURATION_MINUTES"],
                                     **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_id": episode_id,
        "performing_endoscopist_id": performing_endoscopist_id,
        "slot_start_utc": slot_start_utc,
        "duration_minutes": duration_minutes,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def complete_procedure_payload(prep_quality_bbps: int, polyps_removed_count: int,
                               largest_polyp_mm: int, specimen_count: int) -> Dict[str, Any]:
    return {
        "prep_quality_bbps": prep_quality_bbps,
        "polyps_removed_count": polyps_removed_count,
        "largest_polyp_mm": largest_polyp_mm,
        "specimen_count": specimen_count,
    }


def abort_procedure_payload(prep_quality_bbps: int,
                            cancellation_reason: str = "INADEQUATE_PREP") -> Dict[str, Any]:
    return {
        "prep_quality_bbps": prep_quality_bbps,
        "cancellation_reason": cancellation_reason,
    }


def cancel_booking_payload(cancellation_reason: str = "PATIENT_RESCHEDULED") -> Dict[str, Any]:
    return {"cancellation_reason": cancellation_reason}


def specimen(label: str, histology: str, size_mm: int) -> Dict[str, Any]:
    return {"label": label, "histology": histology, "size_mm": size_mm}


def create_pathology_report_payload(specimens: List[Dict[str, Any]],
                                    accession_number: str = DEFAULTS["ACCESSION_NUMBER"],
                                    **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "accession_number": accession_number,
        "specimens": specimens,
    }
    payload.update(overrides)
    return payload


def amend_pathology_report_payload(specimens: List[Dict[str, Any]],
                                   amendment_reason: str,
                                   **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "specimens": specimens,
        "amendment_reason": amendment_reason,
    }
    payload.update(overrides)
    return payload


def create_surveillance_recommendation_payload(expected_episode_version: int,
                                               **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_episode_version": expected_episode_version}
    payload.update(overrides)
    return payload


def dispute_claim_payload(dispute_reason: str = "PATIENT_APPEAL") -> Dict[str, Any]:
    return {"dispute_reason": dispute_reason}


def create_quality_period_payload(endoscopist_id: str, period_start_date: str,
                                  period_end_date: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "endoscopist_id": endoscopist_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload


def attest_quality_period_payload(remediation_plan: str) -> Dict[str, Any]:
    return {"remediation_plan": remediation_plan}
