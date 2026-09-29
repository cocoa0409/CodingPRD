"""Payload factories — one per resource, input fields only."""

from .constants import TEST_DEFAULTS


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["FACILITY_NAME"],
        "cms_ccn": TEST_DEFAULTS["CMS_CCN"],
        "review_period_start": TEST_DEFAULTS["REVIEW_PERIOD_START"],
        "review_period_end": TEST_DEFAULTS["REVIEW_PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def create_clinician_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "full_name": "Dana Whitfield",
        "credential": "NURSE",
        "npi": "1000000001",
    }
    payload.update(overrides)
    return payload


def create_patient_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "mrn": "MRN-A",
        "full_name": "Alma Reyes",
        "birth_date": TEST_DEFAULTS["PATIENT_BIRTH_DATE"],
        "impairment_group_code": TEST_DEFAULTS["IMPAIRMENT_GROUP_CODE"],
        "etiologic_diagnosis_code": TEST_DEFAULTS["ETIOLOGIC_DIAGNOSIS_CODE"],
        "comorbidity_tier": "NONE",
    }
    payload.update(overrides)
    return payload


def create_screening_payload(patient_id: str, conducted_by_clinician_id: str,
                             **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "conducted_by_clinician_id": conducted_by_clinician_id,
        "expected_admission_at": TEST_DEFAULTS["EXPECTED_ADMISSION_AT"],
        "intensive_therapy_documented": True,
        "expected_functional_improvement_documented": True,
        "prior_functional_level_documented": True,
        "medical_supervision_documented": True,
    }
    payload.update(overrides)
    return payload


def review_screening_payload(decision: str = "CONCUR", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_admission_payload(patient_id: str, screening_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "screening_id": screening_id,
    }
    payload.update(overrides)
    return payload


def admit_admission_payload(admitted_at: str = None, **overrides) -> dict:
    payload = {"admitted_at": admitted_at or TEST_DEFAULTS["ADMITTED_AT"]}
    payload.update(overrides)
    return payload


def deny_admission_payload(denial_reason: str = "Patient is not a rehabilitation "
                                                "candidate at this time",
                           **overrides) -> dict:
    payload = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


def discharge_admission_payload(discharged_at: str,
                                discharge_destination: str = "COMMUNITY",
                                discharge_planned: bool = True,
                                **overrides) -> dict:
    payload = {
        "discharged_at": discharged_at,
        "discharge_destination": discharge_destination,
        "discharge_planned": discharge_planned,
    }
    payload.update(overrides)
    return payload


def rescind_interruption_payload(rescind_reason: str = "Readmission coded to the "
                                                       "wrong predecessor stay",
                                 **overrides) -> dict:
    payload = {"rescind_reason": rescind_reason}
    payload.update(overrides)
    return payload


def create_plan_of_care_payload(admission_id: str, expected_admission_version: int,
                                **overrides) -> dict:
    payload = {
        "admission_id": admission_id,
        "expected_admission_version": expected_admission_version,
        "target_los_days": TEST_DEFAULTS["TARGET_LOS_DAYS"],
        "weekly_minutes_target": TEST_DEFAULTS["WEEKLY_MINUTES_TARGET"],
        "disciplines": ["PT"],
    }
    payload.update(overrides)
    return payload


def create_therapy_week_payload(admission_id: str, week_index: int = 1,
                                week_start_date: str = None, **overrides) -> dict:
    payload = {
        "admission_id": admission_id,
        "week_index": week_index,
        "week_start_date": week_start_date or TEST_DEFAULTS["WEEK_START_DATE"],
    }
    payload.update(overrides)
    return payload


def grant_week_exception_payload(exception_reason: str = "Patient medically unable to "
                                                        "tolerate therapy for three "
                                                        "days",
                                 **overrides) -> dict:
    payload = {"exception_reason": exception_reason}
    payload.update(overrides)
    return payload


def create_therapy_session_payload(admission_id: str, clinician_id: str,
                                   start_at: str, end_at: str,
                                   discipline: str = "PT",
                                   modality: str = "INDIVIDUAL",
                                   **overrides) -> dict:
    payload = {
        "admission_id": admission_id,
        "clinician_id": clinician_id,
        "discipline": discipline,
        "modality": modality,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def void_session_payload(void_reason: str = "Documented in error — patient refused",
                         **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


def create_team_conference_payload(admission_id: str, therapy_week_id: str,
                                   led_by_clinician_id: str,
                                   participant_clinician_ids: list,
                                   held_at: str, **overrides) -> dict:
    payload = {
        "admission_id": admission_id,
        "therapy_week_id": therapy_week_id,
        "led_by_clinician_id": led_by_clinician_id,
        "participant_clinician_ids": list(participant_clinician_ids),
        "held_at": held_at,
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(admission_id: str, coder_clinician_id: str,
                              assessment_type: str = "ADMISSION",
                              **overrides) -> dict:
    payload = {
        "admission_id": admission_id,
        "coder_clinician_id": coder_clinician_id,
        "assessment_type": assessment_type,
    }
    payload.update(overrides)
    return payload


def complete_assessment_payload(item_set_complete: bool = True, **overrides) -> dict:
    payload = {"item_set_complete": item_set_complete}
    payload.update(overrides)
    return payload


def create_compliance_review_payload(facility_id: str,
                                     expected_facility_version: int,
                                     method: str = "MEDICAL_REVIEW",
                                     period_start: str = None,
                                     period_end: str = None,
                                     **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "expected_facility_version": expected_facility_version,
        "method": method,
        "period_start": period_start or TEST_DEFAULTS["REVIEW_PERIOD_START"],
        "period_end": period_end or TEST_DEFAULTS["REVIEW_PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def create_qrp_assessment_payload(facility_id: str, fiscal_year: int = 2027,
                                  reporting_period_start: str = None,
                                  reporting_period_end: str = None,
                                  **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "fiscal_year": fiscal_year,
        "reporting_period_start": (reporting_period_start
                                   or TEST_DEFAULTS["REVIEW_PERIOD_START"]),
        "reporting_period_end": (reporting_period_end
                                 or TEST_DEFAULTS["REVIEW_PERIOD_END"]),
    }
    payload.update(overrides)
    return payload
