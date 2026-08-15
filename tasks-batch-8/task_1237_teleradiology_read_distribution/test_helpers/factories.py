"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "HOSPITAL_NAME": "Test Hospital",
    "STATE_CODE": "CA",
    "RAD_NAME": "Test Radiologist",
    "GRANT_VALID_FROM": "2026-01-01",
    "GRANT_VALID_UNTIL": "2026-12-31",
    "SHIFT_START": "2026-05-09T00:00:00Z",
    "SHIFT_END": "2026-05-12T00:00:00Z",
    "PERIOD_START": "2026-05-01",
    "PERIOD_END": "2026-05-31",
}


def create_hospital_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["HOSPITAL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_radiologist_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["RAD_NAME"],
        "subspecialties": ["NEURORAD"],
        "license_states": ["CA"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(radiologist_id, **overrides) -> dict:
    defaults = {
        "radiologist_id": radiologist_id,
        "starts_at": DEFAULTS["SHIFT_START"],
        "ends_at": DEFAULTS["SHIFT_END"],
        "modalities": ["CT"],
    }
    defaults.update(overrides)
    return defaults


def create_routing_policy_payload(hospital_id, expected_hospital_version, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "modality": "CT",
        "body_part_group": "NEURO",
        "priority": "ROUTINE",
        "required_subspecialty": "NEURORAD",
        "prelim_required": False,
        "expected_hospital_version": expected_hospital_version,
    }
    defaults.update(overrides)
    return defaults


def create_credential_grant_payload(radiologist_id, hospital_id, **overrides) -> dict:
    defaults = {
        "radiologist_id": radiologist_id,
        "hospital_id": hospital_id,
        "grant_type": "BY_PROXY",
        "valid_from": DEFAULTS["GRANT_VALID_FROM"],
        "valid_until": DEFAULTS["GRANT_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_study_payload(hospital_id, accession_number, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "accession_number": accession_number,
        "modality": "CT",
        "body_part_group": "NEURO",
        "priority": "ROUTINE",
        "patient_ref": "MRN-1",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(study_id, expected_study_version, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "expected_study_version": expected_study_version,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(assignment_id, report_type, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "report_type": report_type,
        "findings_text": "findings",
        "impression_text": "impression",
    }
    defaults.update(overrides)
    return defaults


def create_discrepancy_case_payload(prelim_report_id, final_report_id, **overrides) -> dict:
    defaults = {
        "prelim_report_id": prelim_report_id,
        "final_report_id": final_report_id,
    }
    defaults.update(overrides)
    return defaults


def create_billing_period_payload(hospital_id, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def seed_finalized_studies_payload(hospital_id, count, received_at, final_signed_at, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "count": count,
        "received_at": received_at,
        "final_signed_at": final_signed_at,
    }
    defaults.update(overrides)
    return defaults
