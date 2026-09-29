"""Request-body factories for the pulmonary function laboratory API.

Each factory produces the body the corresponding endpoint declares, with the
laboratory's standard roster values as defaults so a scenario only has to state
what it actually varies.
"""

from typing import Any, Dict, List, Optional, Sequence

ALL_MODALITIES: Sequence[str] = ("SPIROMETRY", "DLCO", "PLETHYSMOGRAPHY")


# --------------------------------------------------------------------- devices
def device_payload(device_code: str, modality: str = "SPIROMETRY") -> Dict[str, Any]:
    return {"device_code": device_code, "modality": modality}


# ----------------------------------------------------------------------- staff
def technologist_payload(
    employee_code: str = "T-001",
    full_name: str = "Tessa Ng",
    credential: str = "RPFT",
    competency_expires_on: str = "2027-06-30",
    credentialed_modalities: Optional[Sequence[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employee_code": employee_code,
        "full_name": full_name,
        "role_type": "TECHNOLOGIST",
        "credential": credential,
        "competency_expires_on": competency_expires_on,
        "credentialed_modalities": list(
            credentialed_modalities if credentialed_modalities is not None
            else ALL_MODALITIES
        ),
    }
    payload.update(extra)
    return payload


def biologic_control_subject_payload(
    employee_code: str = "T-090",
    full_name: str = "Cal Mensah",
    baseline_fev1_l: float = 4.000,
    baseline_fvc_l: float = 5.200,
    baseline_established_on: str = "2026-05-01",
    credential: str = "CPFT",
    credentialed_modalities: Optional[Sequence[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employee_code": employee_code,
        "full_name": full_name,
        "role_type": "TECHNOLOGIST",
        "credential": credential,
        "competency_expires_on": "2027-06-30",
        "credentialed_modalities": list(
            credentialed_modalities if credentialed_modalities is not None
            else ("SPIROMETRY",)
        ),
        "is_biologic_control": True,
        "baseline_fev1_l": baseline_fev1_l,
        "baseline_fvc_l": baseline_fvc_l,
        "baseline_established_on": baseline_established_on,
    }
    payload.update(extra)
    return payload


def ordering_physician_payload(
    employee_code: str = "D-001",
    full_name: str = "Dana Okafor",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employee_code": employee_code,
        "full_name": full_name,
        "role_type": "ORDERING_PHYSICIAN",
        "credential": "MD",
        "competency_expires_on": "2027-06-30",
        "credentialed_modalities": list(ALL_MODALITIES),
    }
    payload.update(extra)
    return payload


def interpreting_physician_payload(
    employee_code: str = "R-001",
    full_name: str = "Rhea Lund",
    max_concurrent_reports: int = 1,
    credentialed_modalities: Optional[Sequence[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employee_code": employee_code,
        "full_name": full_name,
        "role_type": "INTERPRETING_PHYSICIAN",
        "credential": "MD",
        "competency_expires_on": "2027-06-30",
        "credentialed_modalities": list(
            credentialed_modalities if credentialed_modalities is not None
            else ("SPIROMETRY",)
        ),
        "max_concurrent_reports": max_concurrent_reports,
    }
    payload.update(extra)
    return payload


# -------------------------------------------------------------------- patients
def patient_payload(
    mrn: str = "MRN-7001",
    full_name: str = "Alan Ruiz",
    birth_date: str = "1981-03-15",
    sex: str = "MALE",
    height_cm: float = 175.0,
    weight_kg: float = 80.0,
    smoking_status: str = "FORMER",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mrn": mrn,
        "full_name": full_name,
        "birth_date": birth_date,
        "sex": sex,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "smoking_status": smoking_status,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------- reference equations
def reference_equation_payload(
    equation_code: str = "GLI-M-2005",
    modality_scope: Optional[Sequence[str]] = None,
    sex_scope: str = "MALE",
    applicable_age_min: int = 40,
    applicable_age_max: int = 60,
    lln_percentile: float = 5.0,
    ratio_lln: float = 0.700,
    a_fev1: float = 2.300,
    b_fev1: float = 0.020,
    c_fev1: float = 0.400,
    a_fvc: float = 1.350,
    b_fvc: float = 0.030,
    c_fvc: float = 0.400,
    rsd_frac: float = 0.130,
    bd_criterion: str = "PCT_BASELINE_2005",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "equation_code": equation_code,
        "modality_scope": list(
            modality_scope if modality_scope is not None else ("SPIROMETRY",)
        ),
        "sex_scope": sex_scope,
        "applicable_age_min": applicable_age_min,
        "applicable_age_max": applicable_age_max,
        "lln_percentile": lln_percentile,
        "ratio_lln": ratio_lln,
        "a_fev1": a_fev1,
        "b_fev1": b_fev1,
        "c_fev1": c_fev1,
        "a_fvc": a_fvc,
        "b_fvc": b_fvc,
        "c_fvc": c_fvc,
        "rsd_frac": rsd_frac,
        "bd_criterion": bd_criterion,
    }
    payload.update(extra)
    return payload


# ------------------------------------------------------------- rescue lots
def rescue_lot_payload(
    lot_number: str = "L-2026-08",
    drug: str = "ALBUTEROL_MDI",
    doses_at_receipt: int = 10,
    expires_on: str = "2026-12-31",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_number": lot_number,
        "drug": drug,
        "doses_at_receipt": doses_at_receipt,
        "expires_on": expires_on,
    }
    payload.update(extra)
    return payload


# ------------------------------------------------------------- quality events
def calibration_event_payload(
    measured_volume_l: float = 2.764,
    ambient_temp_c: int = 23,
    barometric_pressure_kpa: float = 101.30,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "VOLUME_CALIBRATION",
        "measured_volume_l": measured_volume_l,
        "ambient_temp_c": ambient_temp_c,
        "barometric_pressure_kpa": barometric_pressure_kpa,
    }
    payload.update(extra)
    return payload


def leak_check_event_payload(
    ambient_temp_c: int = 23,
    barometric_pressure_kpa: float = 101.30,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "LEAK_CHECK",
        "ambient_temp_c": ambient_temp_c,
        "barometric_pressure_kpa": barometric_pressure_kpa,
    }
    payload.update(extra)
    return payload


def biologic_control_event_payload(
    subject_staff_id: str,
    measured_fev1_l: float = 3.850,
    measured_fvc_l: float = 5.100,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "BIOLOGIC_CONTROL",
        "subject_staff_id": subject_staff_id,
        "measured_fev1_l": measured_fev1_l,
        "measured_fvc_l": measured_fvc_l,
    }
    payload.update(extra)
    return payload


def filter_replacement_event_payload(
    filter_serial: str = "F-1001", **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "FILTER_REPLACEMENT",
        "filter_serial": filter_serial,
    }
    payload.update(extra)
    return payload


def disinfection_event_payload(dwell_minutes: int = 25, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "HIGH_LEVEL_DISINFECT",
        "dwell_minutes": dwell_minutes,
    }
    payload.update(extra)
    return payload


def return_to_service_payload(
    clearance_note: str = "Cleared after independent calibration and biologic control.",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"clearance_note": clearance_note}
    payload.update(extra)
    return payload


# ----------------------------------------------------------------- test orders
def test_order_payload(
    patient_id: str,
    indication_code: str = "DYSPNEA_EVALUATION",
    requested_modalities: Optional[Sequence[str]] = None,
    test_context: str = "ROUTINE_CLINICAL",
    bronchodilator_requested: bool = False,
    current_medication_classes: Optional[Sequence[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "indication_code": indication_code,
        "requested_modalities": list(
            requested_modalities if requested_modalities is not None
            else ("SPIROMETRY",)
        ),
        "test_context": test_context,
        "bronchodilator_requested": bronchodilator_requested,
        "current_medication_classes": list(
            current_medication_classes if current_medication_classes is not None else ()
        ),
    }
    payload.update(extra)
    return payload


def cancel_order_payload(
    cancellation_reason: str = "Patient withdrew from the referral.",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancellation_reason": cancellation_reason}
    payload.update(extra)
    return payload


def medication_hold_payload(
    medication_class: str, expected_order_version: int, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "medication_class": medication_class,
        "expected_order_version": expected_order_version,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------- test sessions
def test_session_payload(
    order_id: str,
    device_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "device_id": device_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(extra)
    return payload


def maneuver_payload(
    fvc_l: float,
    fev1_l: float,
    pef_l_s: float = 6.00,
    back_extrapolated_volume_ml: int = 100,
    expiratory_time_s: float = 15.0,
    phase: str = "PRE_BD",
    plateau_reached: bool = False,
    cough_in_first_second: bool = False,
    glottic_closure: bool = False,
    coaching_note: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "phase": phase,
        "fvc_l": fvc_l,
        "fev1_l": fev1_l,
        "pef_l_s": pef_l_s,
        "back_extrapolated_volume_ml": back_extrapolated_volume_ml,
        "expiratory_time_s": expiratory_time_s,
        "plateau_reached": plateau_reached,
        "cough_in_first_second": cough_in_first_second,
        "glottic_closure": glottic_closure,
    }
    if coaching_note is not None:
        payload["coaching_note"] = coaching_note
    payload.update(extra)
    return payload


# The laboratory's standard three-effort spirometry series: best FEV1 2.400 L,
# best FVC 3.200 L, an FEV1 repeatability delta of 150 mL and grade A.
STANDARD_MANEUVER_SERIES: List[Dict[str, Any]] = [
    maneuver_payload(3.200, 2.400, pef_l_s=6.00, back_extrapolated_volume_ml=100,
                     expiratory_time_s=15.0),
    maneuver_payload(3.150, 2.250, pef_l_s=5.80, back_extrapolated_volume_ml=120,
                     expiratory_time_s=16.0),
    maneuver_payload(3.100, 2.200, pef_l_s=5.60, back_extrapolated_volume_ml=110,
                     expiratory_time_s=15.5),
]


def post_bronchodilator_maneuver_payload(
    fvc_l: float = 3.300,
    fev1_l: float = 2.720,
    **extra: Any,
) -> Dict[str, Any]:
    return maneuver_payload(
        fvc_l,
        fev1_l,
        pef_l_s=extra.pop("pef_l_s", 6.40),
        back_extrapolated_volume_ml=extra.pop("back_extrapolated_volume_ml", 120),
        expiratory_time_s=extra.pop("expiratory_time_s", 16.0),
        phase="POST_BD",
        **extra,
    )


def finalize_quality_payload(
    technologist_comment: str = "Three acceptable efforts, good coaching response.",
) -> Dict[str, Any]:
    return {"technologist_comment": technologist_comment}


# -------------------------------------------------------------- custody events
def custody_event_payload(event_type: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(extra)
    return payload


def id_verified_payload(id_document_type: str = "PHOTO_ID") -> Dict[str, Any]:
    return {"event_type": "ID_VERIFIED", "id_document_type": id_document_type}


def seal_applied_payload(seal_serial: str = "SEAL-9001") -> Dict[str, Any]:
    return {"event_type": "SEAL_APPLIED", "seal_serial": seal_serial}


def seal_broken_payload(seal_serial: str = "SEAL-9001") -> Dict[str, Any]:
    return {"event_type": "SEAL_BROKEN", "seal_serial": seal_serial}


def witness_signed_payload(note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": "WITNESS_SIGNED"}
    if note is not None:
        payload["note"] = note
    return payload


# -------------------------------------------------------------- challenge runs
def challenge_run_payload(
    rescue_lot_id: str, agent: str = "METHACHOLINE", **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"agent": agent, "rescue_lot_id": rescue_lot_id}
    payload.update(extra)
    return payload


def challenge_step_payload(
    dose_units: float, post_step_fev1_l: float, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dose_units": dose_units,
        "post_step_fev1_l": post_step_fev1_l,
    }
    payload.update(extra)
    return payload


def abort_challenge_run_payload(abort_reason: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"abort_reason": abort_reason}
    payload.update(extra)
    return payload


# ------------------------------------------------------ interpretation reports
def report_assignment_payload(expected_session_version: int, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_session_version": expected_session_version}
    payload.update(extra)
    return payload


def sign_report_payload(
    clinical_comment: str = "Restrictive pattern, moderate severity.",
) -> Dict[str, Any]:
    return {"clinical_comment": clinical_comment}


def amend_report_payload(amendment_reason: str) -> Dict[str, Any]:
    return {"amendment_reason": amendment_reason}
