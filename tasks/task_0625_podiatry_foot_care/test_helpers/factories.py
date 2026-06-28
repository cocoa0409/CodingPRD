"""Payload factories — one per entity, input fields only."""


def create_practice_payload(**overrides) -> dict:
    defaults = {"name": "Foot Clinic", "npi": "1234567890"}
    defaults.update(overrides)
    return defaults


def create_provider_payload(practice_id: str, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "full_name": "Dr Sole",
        "role_type": "PODIATRIST",
    }
    defaults.update(overrides)
    return defaults


def create_modality_payload(practice_id: str, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "name": "X-Ray 1",
        "modality_type": "XRAY",
        "cleanup_buffer_minutes": 15,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(practice_id: str, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "full_name": "Test Patient",
        "date_of_birth": "1960-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "service_category": "DME",
        "hcpcs_code": "L4360",
        "authorized_units": 2,
        "valid_from_date": "2026-01-01",
        "valid_through_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(patient_id: str, provider_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "scheduled_start": "2026-06-01T09:00:00Z",
        "scheduled_end": "2026-06-01T09:30:00Z",
        "exam_billed_cents": 12000,
        "exam_fee_cap_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_procedure_payload(encounter_id: str, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
        "service_date": "2026-06-01",
        "billed_cents": 8000,
        "fee_cap_cents": 7000,
    }
    defaults.update(overrides)
    return defaults


def create_orthotic_rx_payload(encounter_id: str, prior_authorization_id: str, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "prior_authorization_id": prior_authorization_id,
        "l_code": "L3000",
        "foot_side": "LEFT",
    }
    defaults.update(overrides)
    return defaults


def create_lab_order_payload(orthotic_rx_id: str, **overrides) -> dict:
    defaults = {
        "orthotic_rx_id": orthotic_rx_id,
        "lab_name": "OrthoLab",
        "line_items": [
            {"description": "shell", "l_code": "L3000",
             "unit_price_cents": 24999, "quantity": 1, "discount_pct": 0.0},
        ],
        "units_drawn": 1,
    }
    defaults.update(overrides)
    return defaults


def create_dme_dispense_payload(prior_authorization_id: str, encounter_id: str,
                                expected_prior_authorization_version: int, **overrides) -> dict:
    defaults = {
        "prior_authorization_id": prior_authorization_id,
        "encounter_id": encounter_id,
        "hcpcs_code": "L4360",
        "acquisition_mode": "PURCHASE",
        "units": 1,
        "purchase_price_cents": 15000,
        "expected_prior_authorization_version": expected_prior_authorization_version,
    }
    defaults.update(overrides)
    return defaults


def create_imaging_order_payload(encounter_id: str, modality_id: str,
                                 expected_modality_version: int, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "modality_id": modality_id,
        "study_start": "2026-06-02T10:00:00Z",
        "study_end": "2026-06-02T10:30:00Z",
        "expected_modality_version": expected_modality_version,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(encounter_id: str, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "specialty": "VASCULAR",
        "reason": "PAD evaluation",
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "anchor_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults
