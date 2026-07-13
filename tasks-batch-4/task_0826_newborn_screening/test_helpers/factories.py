"""Payload factories — one per entity, input fields only (Newborn Screening PRD)."""

DEFAULTS = {
    "BIRTH_DATETIME": "2026-02-27T06:00:00Z",
    "GEST_WEEKS": 39,
    "BIRTH_WEIGHT": 3200,
    "COLLECTION_DATETIME": "2026-02-28T12:00:00Z",
    "RECEIVED_DATETIME": "2026-03-01T06:00:00Z",
    "BLOOD_SPOT_COUNT": 5,
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "General Hospital",
        "facility_type": "HOSPITAL",
        "state_region": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_infant_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "birth_datetime": DEFAULTS["BIRTH_DATETIME"],
        "gestational_age_weeks": DEFAULTS["GEST_WEEKS"],
        "birth_weight_grams": DEFAULTS["BIRTH_WEIGHT"],
        "sex": "F",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision, "recorded_by": "parent"}
    defaults.update(overrides)
    return defaults


def create_specimen_payload(infant_id: str, expected_infant_version: int, **overrides) -> dict:
    defaults = {
        "infant_id": infant_id,
        "specimen_type": "INITIAL",
        "collection_datetime": DEFAULTS["COLLECTION_DATETIME"],
        "expected_infant_version": expected_infant_version,
    }
    defaults.update(overrides)
    return defaults


def create_receive_payload(**overrides) -> dict:
    defaults = {
        "received_datetime": DEFAULTS["RECEIVED_DATETIME"],
        "blood_spot_count": DEFAULTS["BLOOD_SPOT_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_screen_payload(specimen_id: str, **overrides) -> dict:
    defaults = {"specimen_id": specimen_id}
    defaults.update(overrides)
    return defaults


def report_metabolic_payload(metabolic_result: str, **overrides) -> dict:
    defaults = {"metabolic_result": metabolic_result}
    defaults.update(overrides)
    return defaults


def point_of_care_hearing_payload(hearing_result: str, **overrides) -> dict:
    defaults = {"component": "HEARING", "hearing_result": hearing_result}
    defaults.update(overrides)
    return defaults


def point_of_care_cchd_payload(spo2_right_hand: int, spo2_foot: int, **overrides) -> dict:
    defaults = {
        "component": "CCHD",
        "spo2_right_hand": spo2_right_hand,
        "spo2_foot": spo2_foot,
    }
    defaults.update(overrides)
    return defaults


def create_specialty_clinic_payload(**overrides) -> dict:
    defaults = {
        "name": "Metabolic Genetics Clinic",
        "specialty": "METABOLIC_GENETICS",
        "concurrent_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(follow_up_case_id: str, specialty_clinic_id: str,
                            referral_reason: str, **overrides) -> dict:
    defaults = {
        "follow_up_case_id": follow_up_case_id,
        "specialty_clinic_id": specialty_clinic_id,
        "referral_reason": referral_reason,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(referral_id: str, start_datetime: str,
                               end_datetime: str, **overrides) -> dict:
    defaults = {
        "referral_id": referral_id,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
    }
    defaults.update(overrides)
    return defaults


def create_assay_run_payload(facility_id: str, instrument_code: str,
                             start_datetime: str, end_datetime: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "instrument_code": instrument_code,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
    }
    defaults.update(overrides)
    return defaults
