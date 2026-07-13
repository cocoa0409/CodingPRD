"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "SUBSTANCE_NAME": "acetaminophen",
    "SUBSTANCE_TOXIC_DOSE": 150,
    "SUBSTANCE_ONSET": 4,
    "FACILITY_NAME": "Metro ED",
    "SPECIALIST_NAME": "Sam SPI",
}


def create_substance_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SUBSTANCE_NAME"],
        "category": "ANALGESIC",
        "toxic_dose_mg_per_kg": DEFAULTS["SUBSTANCE_TOXIC_DOSE"],
        "onset_hours": DEFAULTS["SUBSTANCE_ONSET"],
        "reference_route": "INGESTION",
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["FACILITY_NAME"],
        "facility_type": "ED",
        "status": "ACCEPTING",
        "consult_capacity": 2,
    }
    payload.update(overrides)
    return payload


def create_protocol_payload(**overrides) -> dict:
    payload = {
        "risk_tier": "MODERATE",
        "management_setting": "HOME",
        "followup_count": 1,
        "followup_interval_hours": 24,
        "requires_toxicologist": False,
    }
    payload.update(overrides)
    return payload


def create_specialist_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["SPECIALIST_NAME"],
        "credential": "SPI",
    }
    payload.update(overrides)
    return payload


def create_case_payload(**overrides) -> dict:
    payload = {
        "patient_age_years": 6,
        "patient_weight_kg": 20,
        "patient_sex": "MALE",
        "chief_complaint": "ingestion",
    }
    payload.update(overrides)
    return payload


def create_exposure_payload(substance_id, **overrides) -> dict:
    payload = {
        "substance_id": substance_id,
        "route": "INGESTION",
        "dose_range_low_mg": 1200,
        "dose_range_high_mg": 1500,
        "time_since_exposure_hours": 2,
    }
    payload.update(overrides)
    return payload


def create_risk_assessment_payload(expected_case_version, **overrides) -> dict:
    payload = {"expected_case_version": expected_case_version}
    payload.update(overrides)
    return payload


def create_disposition_payload(risk_assessment_id, disposition_type, **overrides) -> dict:
    payload = {
        "risk_assessment_id": risk_assessment_id,
        "disposition_type": disposition_type,
    }
    payload.update(overrides)
    return payload


def create_follow_up_call_payload(assigned_specialist_id, sequence_index,
                                  scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "assigned_specialist_id": assigned_specialist_id,
        "sequence_index": sequence_index,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_facility_consult_payload(case_id, facility_id, consult_duration_minutes, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "facility_id": facility_id,
        "consult_duration_minutes": consult_duration_minutes,
    }
    payload.update(overrides)
    return payload


def create_npds_report_payload(case_id, primary_substance_id, **overrides) -> dict:
    payload = {"case_id": case_id, "primary_substance_id": primary_substance_id}
    payload.update(overrides)
    return payload


def create_note_payload(note_type="INTAKE", body="Documentation note.", **overrides) -> dict:
    payload = {"note_type": note_type, "body": body}
    payload.update(overrides)
    return payload
