"""Payload factories — one per entity, input fields only (PRD 3).

Each factory provides sensible defaults and accepts **overrides so tests can
control exactly the values they assert on.
"""

DEFAULTS = {
    "CLINIC_NAME": "Test Fertility Clinic",
    "PATIENT_NAME": "Test Patient",
    "DOB": "1990-01-01T00:00:00.000Z",
    "PACKAGE_NAME": "Single IVF Cycle",
    "DRUG_NAME": "Gonal-F",
}


def create_clinic_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["CLINIC_NAME"]}
    payload.update(overrides)
    return payload


def create_package_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PACKAGE_NAME"],
        "base_price_cents": 500000,
        "coverage_pct": 0.8,
        "stim_med_covered": True,
        "cryo_storage_covered": False,
        "annual_cryo_storage_cents": 60000,
        "lifetime_coverage_cap_cents": 100000000,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {"full_name": DEFAULTS["PATIENT_NAME"], "date_of_birth": DEFAULTS["DOB"]}
    payload.update(overrides)
    return payload


def create_donor_payload(**overrides) -> dict:
    payload = {"code": "D-001", "donor_type": "EGG"}
    payload.update(overrides)
    return payload


def create_surrogate_payload(**overrides) -> dict:
    payload = {"full_name": "Test Surrogate"}
    payload.update(overrides)
    return payload


def create_consent_form_payload(**overrides) -> dict:
    payload = {
        "form_key": "IVF_GENERAL",
        "version_label": "v1",
        "required_for": ["CYCLE_START", "RETRIEVAL", "TRANSFER", "CRYO_STORE"],
    }
    payload.update(overrides)
    return payload


def create_patient_consent_payload(patient_id, consent_form_id, **overrides) -> dict:
    payload = {"patient_id": patient_id, "consent_form_id": consent_form_id}
    payload.update(overrides)
    return payload


def create_tank_payload(**overrides) -> dict:
    payload = {"label": "Tank-A", "capacity_slots": 5}
    payload.update(overrides)
    return payload


def create_cycle_payload(patient_id, **overrides) -> dict:
    payload = {"patient_id": patient_id}
    payload.update(overrides)
    return payload


def create_medication_payload(cycle_id, **overrides) -> dict:
    payload = {
        "treatment_cycle_id": cycle_id,
        "drug_name": DEFAULTS["DRUG_NAME"],
        "start_day_offset": 0,
        "end_day_offset": 4,
        "daily_dose_units": 300,
        "unit_price_cents": 100,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(cycle_id, start_utc, end_utc, **overrides) -> dict:
    payload = {
        "treatment_cycle_id": cycle_id,
        "appointment_type": "BLOODWORK",
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    payload.update(overrides)
    return payload


def create_specimen_payload(cycle_id, tank_id, **overrides) -> dict:
    payload = {
        "treatment_cycle_id": cycle_id,
        "cryo_tank_id": tank_id,
        "specimen_type": "EMBRYO",
    }
    payload.update(overrides)
    return payload


def create_outcome_payload(cycle_id, **overrides) -> dict:
    payload = {"treatment_cycle_id": cycle_id, "pregnancy_test_result": "POSITIVE"}
    payload.update(overrides)
    return payload


def set_clock_payload(clinic_id, to_iso8601) -> dict:
    return {"clinic_id": clinic_id, "to_iso8601": to_iso8601}
