"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_program_period_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PERIOD_NAME"],
        "starts_on": TEST_DEFAULTS["PERIOD_STARTS_ON"],
        "ends_on": TEST_DEFAULTS["PERIOD_ENDS_ON"],
    }
    payload.update(overrides)
    return payload


def create_site_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SCHOOL_NAME"],
        "site_type": "SCHOOL",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_site_hold_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "hold_type": "OUTBREAK_LOCKDOWN",
        "starts_at": "2026-05-11T00:00:00Z",
        "ends_at": "2026-05-18T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_patient_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "patient_type": "STUDENT",
        "external_ref": "S-001",
        "first_name": "Mia",
        "last_name": "Lopez",
        "date_of_birth": "2016-03-04",
        "household_size": 4,
    }
    payload.update(overrides)
    return payload


def create_resident_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "patient_type": "RESIDENT",
        "external_ref": "R-001",
        "first_name": "Alma",
        "last_name": "Reyes",
        "date_of_birth": "1941-09-12",
        "room_number": "214B",
        "household_size": 1,
    }
    payload.update(overrides)
    return payload


def create_school_consent_payload(patient_id: str, site_id: str, program_period_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "site_id": site_id,
        "program_period_id": program_period_id,
        "regime": "SCHOOL_GUARDIAN",
        "scope_tier": "SCREENING_FLUORIDE",
        "signed_at": TEST_DEFAULTS["CONSENT_SIGNED_AT"],
        "guardian_name": "Rosa Lopez",
        "guardian_relationship": "MOTHER",
    }
    payload.update(overrides)
    return payload


def create_snf_consent_payload(patient_id: str, site_id: str, program_period_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "site_id": site_id,
        "program_period_id": program_period_id,
        "regime": "SNF_RESPONSIBLE_PARTY",
        "scope_tier": "SCREENING_FLUORIDE",
        "signed_at": TEST_DEFAULTS["CONSENT_SIGNED_AT"],
        "responsible_party_name": "Tomas Reyes",
        "responsible_party_authority": "DURABLE_POA",
        "poa_document_ref": "POA-2019-118",
    }
    payload.update(overrides)
    return payload


def create_portable_unit_payload(**overrides) -> dict:
    payload = {"unit_code": "PU-01"}
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Reyes",
        "staff_role": "DENTIST",
        "license_number": "D-1001",
        "license_state": TEST_DEFAULTS["STATE_CODE"],
        "supervision_level": "SELF",
    }
    payload.update(overrides)
    return payload


def create_sterilization_load_payload(portable_unit_id: str, loaded_by_staff_id: str, **overrides) -> dict:
    payload = {
        "portable_unit_id": portable_unit_id,
        "loaded_by_staff_id": loaded_by_staff_id,
        "load_number": "L-1",
        "cycle_completed_at": TEST_DEFAULTS["LOAD_CYCLE_COMPLETED_AT"],
    }
    payload.update(overrides)
    return payload


def create_site_visit_payload(site_id, program_period_id, portable_unit_id, lead_staff_id, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "program_period_id": program_period_id,
        "portable_unit_id": portable_unit_id,
        "lead_staff_id": lead_staff_id,
        "scheduled_start_at": TEST_DEFAULTS["VISIT_START"],
        "scheduled_end_at": TEST_DEFAULTS["VISIT_END"],
        "chair_count": 2,
    }
    payload.update(overrides)
    return payload


def create_coverage_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "payer_type": "MEDICAID_MCO",
        "payer_name": "GoldenState Dental MCO",
        "member_id": "M-77001",
    }
    payload.update(overrides)
    return payload


def create_encounter_payload(site_visit_id, patient_id, consent_id, expected_site_visit_version, **overrides) -> dict:
    payload = {
        "site_visit_id": site_visit_id,
        "patient_id": patient_id,
        "consent_id": consent_id,
        "expected_site_visit_version": expected_site_visit_version,
    }
    payload.update(overrides)
    return payload


def screening_payload(performing_staff_id: str, **overrides) -> dict:
    payload = {
        "performing_staff_id": performing_staff_id,
        "cavitated_lesion_count": 1,
        "pain_reported": False,
        "abscess_or_swelling": False,
        "untreated_decay_present": True,
    }
    payload.update(overrides)
    return payload


def exam_payload(performing_staff_id: str, **overrides) -> dict:
    payload = {"performing_staff_id": performing_staff_id, "exam_modality": "ONSITE"}
    payload.update(overrides)
    return payload


def create_procedure_payload(encounter_id, procedure_code, expected_encounter_version, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "procedure_code": procedure_code,
        "expected_encounter_version": expected_encounter_version,
    }
    payload.update(overrides)
    return payload


def perform_procedure_payload(performing_staff_id, sterilization_load_id, **overrides) -> dict:
    payload = {
        "performing_staff_id": performing_staff_id,
        "sterilization_load_id": sterilization_load_id,
    }
    payload.update(overrides)
    return payload


def create_treatment_plan_payload(encounter_id, patient_id, authoring_staff_id, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "authoring_staff_id": authoring_staff_id,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(treatment_plan_id, patient_id, **overrides) -> dict:
    payload = {
        "treatment_plan_id": treatment_plan_id,
        "patient_id": patient_id,
        "dental_home_name": "Riverside Family Dental",
    }
    payload.update(overrides)
    return payload


def create_report_payload(program_period_id, report_type, **overrides) -> dict:
    payload = {"program_period_id": program_period_id, "report_type": report_type}
    payload.update(overrides)
    return payload
