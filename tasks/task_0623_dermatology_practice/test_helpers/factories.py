"""Payload factories — one per entity, input fields only."""

_npi_counter = [0]


def _next_npi() -> str:
    _npi_counter[0] += 1
    return f"NPI-{_npi_counter[0]:06d}"


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Test Provider",
        "npi": _next_npi(),
        "can_perform_mohs": False,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": "Procedure Suite A",
        "room_kind": "STANDARD",
        "turnover_buffer_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(patient_id, provider_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "visit_type": "MEDICAL",
        "scheduled_at": "2026-01-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_skin_exam_photo_payload(encounter_id, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "body_site": "left-shoulder",
        "mole_map_x": 0.5,
        "mole_map_y": 0.5,
        "image_ref": "img-ref-1",
    }
    defaults.update(overrides)
    return defaults


def create_biopsy_payload(encounter_id, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "body_site": "back",
    }
    defaults.update(overrides)
    return defaults


def create_procedure_booking_payload(room_id, provider_id, encounter_id,
                                     expected_room_version, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "provider_id": provider_id,
        "encounter_id": encounter_id,
        "procedure_kind": "EXCISION",
        "start_at": "2026-01-08T10:00:00Z",
        "end_at": "2026-01-08T11:00:00Z",
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "drug_name": "biologic-X",
        "required_step_count": 0,
        "list_price_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_step_therapy_trial_payload(**overrides) -> dict:
    defaults = {
        "drug_name": "prior-step-drug",
        "outcome": "FAILED",
    }
    defaults.update(overrides)
    return defaults


def create_cosmetic_membership_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "tier": "SILVER",
        "purchased_unit_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_cosmetic_treatment_payload(encounter_id, membership_id,
                                      expected_membership_version, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "membership_id": membership_id,
        "service_name": "filler",
        "list_price_cents": 20000,
        "expected_membership_version": expected_membership_version,
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(patient_id, encounter_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "source_kind": "ENCOUNTER",
        "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_recall_reminder_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "reason": "ROUTINE_SKIN_CHECK",
        "due_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
