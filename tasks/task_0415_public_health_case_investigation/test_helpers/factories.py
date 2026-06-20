"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults for required input fields and accepts
**overrides for the values a test needs to control.
"""

DEFAULTS = {
    "PROGRAM_NAME": "State PH",
    "JURISDICTION_NAME": "County 1",
    "FIPS_CODE": "06001",
    "PATIENT_REFERENCE": "PT-1",
    "CONTACT_REFERENCE": "K-1",
    "SYMPTOM_ONSET_DATE": "2026-03-10T00:00:00.000Z",
    "LAST_EXPOSURE_DATE": "2026-03-15T00:00:00.000Z",
    "SPECIMEN_DATE": "2026-03-11T00:00:00.000Z",
}


def create_program_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["PROGRAM_NAME"]}
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": DEFAULTS["JURISDICTION_NAME"],
        "fips_code": DEFAULTS["FIPS_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_condition_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "condition_code": "COVID19",
        "display_name": "COVID-19",
        "presymptomatic_days": 2,
        "infectious_tail_days": 10,
        "quarantine_days": 14,
        "test_based_release_days": 7,
        "isolation_min_days": 5,
        "fever_free_days": 1,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(program_id, jurisdiction_id, condition_code="COVID19", **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "jurisdiction_id": jurisdiction_id,
        "condition_code": condition_code,
        "patient_reference": DEFAULTS["PATIENT_REFERENCE"],
        "symptom_onset_date": DEFAULTS["SYMPTOM_ONSET_DATE"],
        "is_symptomatic": True,
    }
    defaults.update(overrides)
    return defaults


def create_lab_result_payload(program_id, jurisdiction_id, condition_code="COVID19",
                              patient_reference="PT-1", **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "jurisdiction_id": jurisdiction_id,
        "condition_code": condition_code,
        "patient_reference": patient_reference,
        "result_value": "POSITIVE",
        "specimen_collection_date": DEFAULTS["SPECIMEN_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_contact_payload(program_id, source_case_id, monitoring_jurisdiction_id,
                           **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "source_case_id": source_case_id,
        "monitoring_jurisdiction_id": monitoring_jurisdiction_id,
        "contact_reference": DEFAULTS["CONTACT_REFERENCE"],
        "exposure_setting": "HOUSEHOLD",
        "proximity_meters": 0.5,
        "cumulative_exposure_minutes": 30,
        "last_exposure_date": DEFAULTS["LAST_EXPOSURE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_period_payload(start_date, end_date,
                                     monitoring_type="QUARANTINE", **overrides) -> dict:
    defaults = {
        "monitoring_type": monitoring_type,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(program_id, case_id, to_jurisdiction_id,
                            expected_case_version, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "case_id": case_id,
        "to_jurisdiction_id": to_jurisdiction_id,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_export_payload(program_id, case_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "case_id": case_id,
    }
    defaults.update(overrides)
    return defaults
