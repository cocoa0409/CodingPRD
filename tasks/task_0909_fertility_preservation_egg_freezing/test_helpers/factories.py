"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PATIENT_NAME": "Test Patient",
    "DOB": "1990-01-01T00:00:00Z",
    "EMAIL": "patient@example.com",
    "PROVIDER_NAME": "Dr Test",
    "ROOM_NAME": "OR-Test",
    "TANK_NAME": "Tank-Test",
    "EMPLOYER": "Acme",
}


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "email": DEFAULTS["EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_provider_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "provider_role": "PHYSICIAN",
    }
    payload.update(overrides)
    return payload


def create_procedure_room_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ROOM_NAME"],
        "room_kind": "RETRIEVAL_OR",
    }
    payload.update(overrides)
    return payload


def create_storage_tank_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TANK_NAME"],
        "capacity_slots": 10,
    }
    payload.update(overrides)
    return payload


def create_consultation_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "patient_age_years": 30,
        "amh_level": 4.0,
        "antral_follicle_count": 20,
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(patient_id, consultation_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "consultation_id": consultation_id,
    }
    payload.update(overrides)
    return payload


def create_monitoring_appointment_payload(cycle_id, provider_id, scheduled_start,
                                          scheduled_end, **overrides) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "provider_id": provider_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def retrieve_payload(retrieval_room_id, tank_id, mature_oocyte_count=2,
                     oocytes_retrieved=12, retrieval_start="2026-05-10T08:00:00Z",
                     retrieval_end="2026-05-10T09:00:00Z", specimen_type="VIAL",
                     **overrides) -> dict:
    payload = {
        "retrieval_room_id": retrieval_room_id,
        "retrieval_start": retrieval_start,
        "retrieval_end": retrieval_end,
        "oocytes_retrieved": oocytes_retrieved,
        "mature_oocyte_count": mature_oocyte_count,
        "tank_id": tank_id,
        "specimen_type": specimen_type,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(patient_id, **overrides) -> dict:
    payload = {"patient_id": patient_id}
    payload.update(overrides)
    return payload


def create_benefit_coverage_payload(patient_id, annual_cap_cents=40000,
                                    covered_pct=0.5, covered_service_types=None,
                                    employer_name="Acme", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "employer_name": employer_name,
        "annual_cap_cents": annual_cap_cents,
        "covered_pct": covered_pct,
        "covered_service_types": covered_service_types or ["CYCLE"],
    }
    payload.update(overrides)
    return payload


def create_directive_payload(patient_id, expected_patient_version, directive_type="CONSENT",
                             disposition_action=None, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "directive_type": directive_type,
        "expected_patient_version": expected_patient_version,
    }
    if disposition_action is not None:
        payload["disposition_action"] = disposition_action
    payload.update(overrides)
    return payload


def create_thaw_authorization_payload(patient_id, specimen_ids,
                                      transfer_type="THAW_TO_TRANSFER", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "specimen_ids": specimen_ids,
        "transfer_type": transfer_type,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(patient_id, service_type="CYCLE", line_items=None, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "service_type": service_type,
        "line_items": line_items if line_items is not None else [{"description": "line", "amount_cents": 100000}],
    }
    payload.update(overrides)
    return payload
