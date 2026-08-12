"""Payload factories — one per creatable resource, input fields only."""


def create_clinic_payload(**overrides) -> dict:
    payload = {"name": "Test Referring Vet", "address_zone": "Z0"}
    payload.update(overrides)
    return payload


def create_contract_payload(clinic_id: str, **overrides) -> dict:
    payload = {
        "clinic_id": clinic_id,
        "kind": "PER_STUDY_LIST",
        "valid_from": "2026-05-01T00:00:00Z",
        "valid_until": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_mobile_unit_payload(**overrides) -> dict:
    payload = {"name": "Test Van"}
    payload.update(overrides)
    return payload


def create_equipment_payload(**overrides) -> dict:
    payload = {"modality": "ULTRASOUND", "serial_label": "US-TEST"}
    payload.update(overrides)
    return payload


def calibrate_payload(**overrides) -> dict:
    payload = {
        "calibration_valid_from": "2026-05-01T00:00:00Z",
        "calibration_valid_until": "2026-05-29T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_technician_payload(**overrides) -> dict:
    payload = {"full_name": "Test Technician", "certified_modalities": ["ULTRASOUND"]}
    payload.update(overrides)
    return payload


def create_specialist_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Specialist",
        "modality_privileges": ["ULTRASOUND"],
        "species_privileges": ["CANINE"],
        "stat_eligible": False,
    }
    payload.update(overrides)
    return payload


def create_route_payload(mobile_unit_id: str, technician_id: str, **overrides) -> dict:
    payload = {
        "mobile_unit_id": mobile_unit_id,
        "technician_id": technician_id,
        "service_date": "2026-05-04",
        "shift_start_minute": 480,
        "shift_end_minute": 900,
    }
    payload.update(overrides)
    return payload


def create_route_stop_payload(clinic_id: str, expected_route_version: int, **overrides) -> dict:
    payload = {
        "clinic_id": clinic_id,
        "planned_arrival_minute": 540,
        "service_minutes": 45,
        "drive_minutes_from_prev": 20,
        "stop_priority": "ROUTINE",
        "expected_route_version": expected_route_version,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(clinic_id: str, **overrides) -> dict:
    payload = {
        "clinic_id": clinic_id,
        "patient_name": "Test Patient",
        "species": "CANINE",
        "study_kind": "TELERAD",
        "requested_modality": "ULTRASOUND",
        "priority": "ROUTINE",
        "clinical_history": "screening",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(referral_id: str, **overrides) -> dict:
    payload = {"referral_id": referral_id}
    payload.update(overrides)
    return payload


def create_study_payload(appointment_id: str, **overrides) -> dict:
    payload = {
        "appointment_id": appointment_id,
        "modality": "ULTRASOUND",
        "body_region": "ABDOMEN",
    }
    payload.update(overrides)
    return payload


def acquire_payload(equipment_id: str, technician_id: str, image_count: int = 5) -> dict:
    return {
        "equipment_id": equipment_id,
        "technician_id": technician_id,
        "image_count": image_count,
    }


def create_read_assignment_payload(study_id: str, specialist_id: str, expected_study_version: int) -> dict:
    return {
        "study_id": study_id,
        "specialist_id": specialist_id,
        "expected_study_version": expected_study_version,
    }


def create_report_payload(study_id: str, kind: str = "FINAL", findings: str = "normal") -> dict:
    return {"study_id": study_id, "kind": kind, "findings": findings}


def create_qc_check_payload(equipment_id: str, performed_by_technician_id: str, result: str, note=None) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "performed_by_technician_id": performed_by_technician_id,
        "result": result,
    }
    if note is not None:
        payload["note"] = note
    return payload


def create_peer_review_payload(report_id: str, reviewer_specialist_id: str) -> dict:
    return {"report_id": report_id, "reviewer_specialist_id": reviewer_specialist_id}


def create_invoice_payload(clinic_id: str, **overrides) -> dict:
    payload = {
        "clinic_id": clinic_id,
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
    }
    payload.update(overrides)
    return payload


def post_study_payload(study_id: str, expected_invoice_version: int) -> dict:
    return {"study_id": study_id, "expected_invoice_version": expected_invoice_version}
