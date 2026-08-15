"""Payload factories — one per creatable resource, input fields only.

Values that must be unique within a test (mrn, room_label, npi, names)
are suffixed with a process-wide counter; the harness restarts the server
before every test, so each test's database starts empty.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_patient_payload(mrn=None, full_name=None, date_of_birth="1970-01-01",
                           **overrides) -> dict:
    n = _seq()
    payload = {
        "mrn": mrn or f"MRN-{n:05d}",
        "full_name": full_name or f"Patient {n}",
        "date_of_birth": date_of_birth,
    }
    payload.update(overrides)
    return payload


def create_referral_order_payload(patient_id, ordering_provider_name="Dr Ref",
                                  requested_study_type="HST",
                                  icd10_primary=None, priority=None,
                                  **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "ordering_provider_name": ordering_provider_name,
        "requested_study_type": requested_study_type,
        "icd10_primary": icd10_primary or TEST_DEFAULTS["ICD10"],
    }
    if priority is not None:
        payload["priority"] = priority
    payload.update(overrides)
    return payload


def create_authorization_payload(order_version, payer_name=None,
                                 authorization_number=None, approved_nights=1,
                                 window_start=None, window_end=None,
                                 **overrides) -> dict:
    n = _seq()
    payload = {
        "payer_name": payer_name or TEST_DEFAULTS["PAYER"],
        "authorization_number": authorization_number or f"AU-{n:05d}",
        "approved_nights": approved_nights,
        "window_start": window_start or TEST_DEFAULTS["WINDOW_START"],
        "window_end": window_end or TEST_DEFAULTS["WINDOW_END"],
        "expected_referral_order_version": order_version,
    }
    payload.update(overrides)
    return payload


def create_bed_payload(room_label=None, titration_capable=None, is_active=None,
                       **overrides) -> dict:
    n = _seq()
    payload = {"room_label": room_label or f"B-{n:05d}"}
    if titration_capable is not None:
        payload["titration_capable"] = titration_capable
    if is_active is not None:
        payload["is_active"] = is_active
    payload.update(overrides)
    return payload


def create_technologist_payload(full_name=None, credential="RPSGT",
                                **overrides) -> dict:
    n = _seq()
    payload = {"full_name": full_name or f"Tech {n}", "credential": credential}
    payload.update(overrides)
    return payload


def create_scorer_payload(full_name=None, credential="RPSGT", npi=None,
                          reliability_pool=None, **overrides) -> dict:
    n = _seq()
    payload = {
        "full_name": full_name or f"Scorer {n}",
        "credential": credential,
        "npi": npi or f"NPI-S-{n:05d}",
    }
    if reliability_pool is not None:
        payload["reliability_pool"] = reliability_pool
    payload.update(overrides)
    return payload


def create_physician_payload(full_name=None, npi=None, board_certified=None,
                             **overrides) -> dict:
    n = _seq()
    payload = {
        "full_name": full_name or f"Doc {n}",
        "npi": npi or f"NPI-P-{n:05d}",
    }
    if board_certified is not None:
        payload["board_certified"] = board_certified
    payload.update(overrides)
    return payload


def create_staffing_assignment_payload(technologist_id, shift_date,
                                       patient_capacity=None,
                                       **overrides) -> dict:
    payload = {"technologist_id": technologist_id, "shift_date": shift_date}
    if patient_capacity is not None:
        payload["patient_capacity"] = patient_capacity
    payload.update(overrides)
    return payload


def create_sleep_study_payload(patient_id, order_id, study_type,
                               scheduled_date=None, bed_id=None,
                               **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "order_id": order_id,
        "study_type": study_type,
        "scheduled_date": scheduled_date or TEST_DEFAULTS["STUDY_DATE"],
    }
    if bed_id is not None:
        payload["bed_id"] = bed_id
    payload.update(overrides)
    return payload


def split_decision_payload(intended_outcome="CONVERT_TO_TITRATION",
                           diagnostic_minutes_observed=130,
                           partial_ahi_observed=45.0,
                           central_predominance_flag=False,
                           remaining_minutes_available=200,
                           override_reason=None, **overrides) -> dict:
    payload = {
        "intended_outcome": intended_outcome,
        "diagnostic_minutes_observed": diagnostic_minutes_observed,
        "partial_ahi_observed": partial_ahi_observed,
        "central_predominance_flag": central_predominance_flag,
        "remaining_minutes_available": remaining_minutes_available,
    }
    if override_reason is not None:
        payload["override_reason"] = override_reason
    payload.update(overrides)
    return payload


def complete_acquisition_payload(total_recording_time_minutes=480,
                                 titration_final_pressure_cm=None,
                                 leak_95th_l_min=None, **overrides) -> dict:
    payload = {"total_recording_time_minutes": total_recording_time_minutes}
    if titration_final_pressure_cm is not None:
        payload["titration_final_pressure_cm"] = titration_final_pressure_cm
    if leak_95th_l_min is not None:
        payload["leak_95th_l_min"] = leak_95th_l_min
    payload.update(overrides)
    return payload


def create_scoring_task_payload(study_id, scorer_id, assignment_kind="PRIMARY",
                                **overrides) -> dict:
    payload = {
        "study_id": study_id,
        "scorer_id": scorer_id,
        "assignment_kind": assignment_kind,
    }
    payload.update(overrides)
    return payload


def submit_scoring_task_payload(obstructive_apneas=20, central_apneas=0,
                                mixed_apneas=0, hypopneas=20, reras=0,
                                epochs_total=960, total_sleep_time_minutes=None,
                                total_recording_time_minutes=480,
                                **overrides) -> dict:
    """Default shape targets HST (recording-time base, no sleep time)."""
    payload = {
        "obstructive_apneas": obstructive_apneas,
        "central_apneas": central_apneas,
        "mixed_apneas": mixed_apneas,
        "hypopneas": hypopneas,
        "reras": reras,
        "epochs_total": epochs_total,
    }
    if total_sleep_time_minutes is not None:
        payload["total_sleep_time_minutes"] = total_sleep_time_minutes
    if total_recording_time_minutes is not None:
        payload["total_recording_time_minutes"] = total_recording_time_minutes
    payload.update(overrides)
    return payload


def create_interpretation_report_payload(study_id, primary_scoring_task_id,
                                         study_version,
                                         diagnosis_code=None,
                                         **overrides) -> dict:
    payload = {
        "study_id": study_id,
        "primary_scoring_task_id": primary_scoring_task_id,
        "diagnosis_code": diagnosis_code or TEST_DEFAULTS["ICD10"],
        "expected_sleep_study_version": study_version,
    }
    payload.update(overrides)
    return payload


def create_therapy_prescription_payload(report_id, report_version,
                                        device_type="CPAP", mask_type="NASAL",
                                        cpap_pressure_cm=9.0,
                                        apap_min_cm=None, apap_max_cm=None,
                                        bipap_ipap_cm=None, bipap_epap_cm=None,
                                        humidification=None,
                                        **overrides) -> dict:
    payload = {
        "report_id": report_id,
        "device_type": device_type,
        "mask_type": mask_type,
        "expected_interpretation_report_version": report_version,
    }
    if cpap_pressure_cm is not None:
        payload["cpap_pressure_cm"] = cpap_pressure_cm
    if apap_min_cm is not None:
        payload["apap_min_cm"] = apap_min_cm
    if apap_max_cm is not None:
        payload["apap_max_cm"] = apap_max_cm
    if bipap_ipap_cm is not None:
        payload["bipap_ipap_cm"] = bipap_ipap_cm
    if bipap_epap_cm is not None:
        payload["bipap_epap_cm"] = bipap_epap_cm
    if humidification is not None:
        payload["humidification"] = humidification
    payload.update(overrides)
    return payload


def create_dme_order_payload(prescription_id, vendor_name="DME Corp",
                             **overrides) -> dict:
    payload = {"prescription_id": prescription_id, "vendor_name": vendor_name}
    payload.update(overrides)
    return payload


def dme_follow_up_payload(usage_hours_avg=4.0, compliant_nights_percent=70.0,
                          **overrides) -> dict:
    payload = {
        "usage_hours_avg": usage_hours_avg,
        "compliant_nights_percent": compliant_nights_percent,
    }
    payload.update(overrides)
    return payload


def create_inter_rater_case_payload(study_id, primary_task_id, rescore_task_id,
                                    **overrides) -> dict:
    payload = {
        "study_id": study_id,
        "primary_task_id": primary_task_id,
        "rescore_task_id": rescore_task_id,
    }
    payload.update(overrides)
    return payload
