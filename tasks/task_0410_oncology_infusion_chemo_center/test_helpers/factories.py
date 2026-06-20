"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only source=input fields appear here; computed and
system fields (bsa_m2, ordered_dose_mg, status, snapshots, etc.) are omitted.
"""

DEFAULTS = {
    "HEIGHT_CM": 170,
    "WEIGHT_KG": 70,
    "GFR_ML_MIN": 80,
    "CYCLE_LENGTH_DAYS": 21,
    "TOTAL_CYCLES": 1,
    "VIAL_SIZE_MG": 150,
    "FLAT_DOSE_MG": 600,
    "PAYER": "Acme",
    "TREATMENT_START_DATE": "2026-07-01",
}


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": "MRN-DEFAULT",
        "full_name": "Test Patient",
        "height_cm": DEFAULTS["HEIGHT_CM"],
        "weight_kg": DEFAULTS["WEIGHT_KG"],
        "gfr_ml_min": DEFAULTS["GFR_ML_MIN"],
    }
    defaults.update(overrides)
    return defaults


def create_regimen_protocol_payload(**overrides) -> dict:
    defaults = {
        "code": "PROTO-DEFAULT",
        "name": "Test Protocol",
        "cycle_length_days": DEFAULTS["CYCLE_LENGTH_DAYS"],
        "total_cycles": DEFAULTS["TOTAL_CYCLES"],
    }
    defaults.update(overrides)
    return defaults


def create_order_set_item_payload(regimen_protocol_id, **overrides) -> dict:
    """Defaults to a FLAT CHEMO item. Override dosing_method + dose fields for
    BSA (dose_per_m2) or AUC (target_auc)."""
    defaults = {
        "regimen_protocol_id": regimen_protocol_id,
        "drug_name": "DrugC",
        "role": "CHEMO",
        "dosing_method": "FLAT",
        "flat_dose_mg": DEFAULTS["FLAT_DOSE_MG"],
        "vial_size_mg": DEFAULTS["VIAL_SIZE_MG"],
        "day_offset": 1,
        "sequence_index": 1,
    }
    defaults.update(overrides)
    return defaults


def create_chair_payload(**overrides) -> dict:
    defaults = {"label": "CHAIR-DEFAULT"}
    defaults.update(overrides)
    return defaults


def create_nurse_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Nurse",
        "is_chemo_certified": True,
        "max_acuity_load": 6,
    }
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "drug_name": "SpecialtyX",
        "payer": DEFAULTS["PAYER"],
    }
    defaults.update(overrides)
    return defaults


def decide_prior_authorization_payload(decision, **overrides) -> dict:
    """decision is 'APPROVE' or 'DENY'. Pass authorized_units_mg for APPROVE."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_treatment_cycle_payload(patient_id, regimen_protocol_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "regimen_protocol_id": regimen_protocol_id,
        "treatment_start_date": DEFAULTS["TREATMENT_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_drug_order_payload(treatment_cycle_id, order_set_item_id, **overrides) -> dict:
    defaults = {
        "treatment_cycle_id": treatment_cycle_id,
        "order_set_item_id": order_set_item_id,
    }
    defaults.update(overrides)
    return defaults


def verify_drug_order_payload(recomputed_dose_mg) -> dict:
    return {"recomputed_dose_mg": recomputed_dose_mg}


def create_infusion_appointment_payload(treatment_cycle_id, chair_id, nurse_id,
                                        start_at, end_at, acuity,
                                        expected_treatment_cycle_version, **overrides) -> dict:
    defaults = {
        "treatment_cycle_id": treatment_cycle_id,
        "chair_id": chair_id,
        "nurse_id": nurse_id,
        "start_at": start_at,
        "end_at": end_at,
        "acuity": acuity,
        "expected_treatment_cycle_version": expected_treatment_cycle_version,
    }
    defaults.update(overrides)
    return defaults


def create_toxicity_event_payload(treatment_cycle_id, ctcae_grade, description, **overrides) -> dict:
    defaults = {
        "treatment_cycle_id": treatment_cycle_id,
        "ctcae_grade": ctcae_grade,
        "description": description,
    }
    defaults.update(overrides)
    return defaults
