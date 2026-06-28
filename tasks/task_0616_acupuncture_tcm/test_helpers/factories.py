"""Payload factories — one per entity, input fields only.

Each factory yields a sensible default payload and accepts **overrides for the
fields a test needs to control. Field names are PRD-exact.
"""


def create_practitioner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Acu",
        "license_number": "LIC-DEFAULT",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "room_name": "Room Default",
    }
    defaults.update(overrides)
    return defaults


def create_herb_item_payload(**overrides) -> dict:
    defaults = {
        "herb_name": "Bai Shao",
        "initial_grams": 500,
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(herb_item_id: str = None, grams_per_dose: int = 10,
                           **overrides) -> dict:
    defaults = {
        "formula_name": "Test Formula",
    }
    if "line_items" not in overrides:
        defaults["line_items"] = [
            {"herb_item_id": herb_item_id, "grams_per_dose": grams_per_dose}
        ]
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "chief_complaint": "back pain",
        "tongue_finding": "RED",
        "tongue_coating": "THIN_WHITE",
        "pulse_finding": "WIRY",
        "tcm_pattern": "QI_STAGNATION",
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(patient_id: str, practitioner_id: str,
                                  intake_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "practitioner_id": practitioner_id,
        "intake_id": intake_id,
        "acupoints": ["LI4", "ST36"],
        "planned_sessions": 4,
    }
    defaults.update(overrides)
    return defaults


def create_package_series_payload(patient_id: str, total_credits: int = 10,
                                  price_paid_cents: int = 90000, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "total_credits": total_credits,
        "price_paid_cents": price_paid_cents,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(patient_id: str, treatment_plan_id: str,
                               practitioner_id: str, room_id: str,
                               expected_treatment_plan_version: int,
                               **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "treatment_plan_id": treatment_plan_id,
        "practitioner_id": practitioner_id,
        "room_id": room_id,
        "charge_source": "PER_VISIT",
        "scheduled_start": "2026-06-01T10:00:00Z",
        "scheduled_end": "2026-06-01T10:45:00Z",
        "base_fee_cents": 12000,
        "expected_treatment_plan_version": expected_treatment_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {
        "modality": "CUPPING",
        "fee_cents": 3500,
    }
    defaults.update(overrides)
    return defaults


def create_dispense_payload(patient_id: str, treatment_plan_id: str,
                            herbal_formula_id: str,
                            expected_treatment_plan_version: int,
                            doses: int = 1, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "treatment_plan_id": treatment_plan_id,
        "herbal_formula_id": herbal_formula_id,
        "doses": doses,
        "expected_treatment_plan_version": expected_treatment_plan_version,
    }
    defaults.update(overrides)
    return defaults
