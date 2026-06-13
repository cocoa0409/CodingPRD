"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr OD",
        "role": "OPTOMETRIST",
        "npi": "1234567890",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1990-01-01",
        "plan_carrier": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(patient_id: str, provider_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "encounter_type": "ROUTINE_VISION",
        "exam_fee_cents": 12000,
        "refraction_fee_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(encounter_id: str, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
        "rx_type": "EYEGLASS",
        "sphere_od": -1.25,
        "sphere_os": -1.00,
        "issue_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "carrier": "VSP",
        "benefit_period_start": "2026-01-01",
        "exam_copay_cents": 2500,
        "materials_allowance_cents": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_lab_order_payload(prescription_id: str, **overrides) -> dict:
    defaults = {
        "prescription_id": prescription_id,
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(encounter_id: str, **overrides) -> dict:
    defaults = {
        "encounter_id": encounter_id,
    }
    defaults.update(overrides)
    return defaults


def create_recall_reminder_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "channel": "EMAIL",
    }
    defaults.update(overrides)
    return defaults
