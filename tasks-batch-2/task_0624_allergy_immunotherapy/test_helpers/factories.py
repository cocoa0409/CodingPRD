"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only fields with source: input appear here.
"""

DEFAULTS = {
    "PATIENT_NAME": "Test Patient",
    "DATE_OF_BIRTH": "1990-01-01",
    "PANEL_NAME": "Test Panel",
    "CONTROL_WHEAL_MM": 3,
    "ALLERGEN_CODE": "DUST",
    "POTENCY": 10000,
    "RECEIVED_AT": "2026-01-01T00:00:00Z",
    "PREPARED_VOLUME_ML": 5.0,
}


def create_patient_payload(**overrides) -> dict:
    """POST /patients body. epinephrine_on_file is optional (defaults false)."""
    defaults = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    defaults.update(overrides)
    return defaults


def create_panel_payload(**overrides) -> dict:
    """POST /patients/{id}/panels body. control_wheal_mm optional (default 3)."""
    defaults = {
        "panel_name": DEFAULTS["PANEL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_skin_test_payload(wheal_mm, clinically_relevant=False, **overrides) -> dict:
    """SKIN allergen test: carries wheal_mm, never specific_ige_ku."""
    defaults = {
        "allergen_code": DEFAULTS["ALLERGEN_CODE"],
        "method": "SKIN",
        "wheal_mm": wheal_mm,
        "clinically_relevant": clinically_relevant,
    }
    defaults.update(overrides)
    return defaults


def create_blood_test_payload(specific_ige_ku, clinically_relevant=False, **overrides) -> dict:
    """BLOOD allergen test: carries specific_ige_ku, never wheal_mm."""
    defaults = {
        "allergen_code": DEFAULTS["ALLERGEN_CODE"],
        "method": "BLOOD",
        "specific_ige_ku": specific_ige_ku,
        "clinically_relevant": clinically_relevant,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(patient_id, panel_id, **overrides) -> dict:
    """POST /immunotherapy-plans body."""
    defaults = {
        "patient_id": patient_id,
        "panel_id": panel_id,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(vial_color, lot_number, **overrides) -> dict:
    """POST /serum-lots body."""
    defaults = {
        "vial_color": vial_color,
        "lot_number": lot_number,
        "concentrate_potency_pnu_per_ml": DEFAULTS["POTENCY"],
        "received_at_iso": DEFAULTS["RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def mix_vial_payload(lot_id, expected_plan_version, prepared_volume_ml=None, **overrides) -> dict:
    """POST /immunotherapy-plans/{id}/vials body."""
    defaults = {
        "lot_id": lot_id,
        "prepared_volume_ml": (
            prepared_volume_ml
            if prepared_volume_ml is not None
            else DEFAULTS["PREPARED_VOLUME_ML"]
        ),
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults


def administer_shot_payload(vial_id, expected_plan_version, injection_count=None, **overrides) -> dict:
    """POST /immunotherapy-plans/{id}/shot-visits body. injection_count optional (default 1)."""
    defaults = {
        "vial_id": vial_id,
        "expected_plan_version": expected_plan_version,
    }
    if injection_count is not None:
        defaults["injection_count"] = injection_count
    defaults.update(overrides)
    return defaults


def release_payload(released_at_iso, reaction_grade=None, **overrides) -> dict:
    """POST /shot-visits/{id}/release body. reaction_grade optional."""
    defaults = {
        "released_at_iso": released_at_iso,
    }
    if reaction_grade is not None:
        defaults["reaction_grade"] = reaction_grade
    defaults.update(overrides)
    return defaults


def record_reaction_payload(reaction_grade, epinephrine_administered=None, **overrides) -> dict:
    """POST /shot-visits/{id}/record-reaction body."""
    defaults = {
        "reaction_grade": reaction_grade,
    }
    if epinephrine_administered is not None:
        defaults["epinephrine_administered"] = epinephrine_administered
    defaults.update(overrides)
    return defaults


def resume_payload(expected_plan_version, **overrides) -> dict:
    """POST /immunotherapy-plans/{id}/resume body."""
    defaults = {
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults
