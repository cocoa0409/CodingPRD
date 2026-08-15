"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DOB": "1970-01-01",
    "DIAGNOSIS": "C61",
    "INTENT": "CURATIVE",
    "TECHNIQUE": "IMRT",
    "TOTAL_DOSE": 2000,
    "FRACTIONS": 10,
    "SIM_START": "2026-07-30T09:00:00Z",
    "SIM_END": "2026-07-30T09:30:00Z",
    "IMMOBILIZATION": "THERMOPLASTIC_MASK",
    "WEIGHT": 80.0,
    "CONTOUR_LABEL": "CT1",
    "TARGET_VOLUMES": ["PTV"],
    "CONSTRAINT_STRUCTURE": "Cord",
    "CONSTRAINT_TYPE": "MAX_DOSE",
}

_mrn_counter = {"n": 0}


def _next_mrn() -> str:
    _mrn_counter["n"] += 1
    return f"MRN-GEN-{_mrn_counter['n']:04d}"


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": _next_mrn(),
        "full_name": "Generated Patient",
        "date_of_birth": DEFAULTS["DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    defaults = {
        "diagnosis_code": DEFAULTS["DIAGNOSIS"],
        "intent": DEFAULTS["INTENT"],
        "technique": DEFAULTS["TECHNIQUE"],
        "prescribed_total_dose_cGy": DEFAULTS["TOTAL_DOSE"],
        "planned_fractions": DEFAULTS["FRACTIONS"],
    }
    defaults.update(overrides)
    return defaults


def create_simulation_payload(**overrides) -> dict:
    defaults = {
        "machine_id": None,  # caller supplies
        "start_time": DEFAULTS["SIM_START"],
        "end_time": DEFAULTS["SIM_END"],
        "immobilization_device": DEFAULTS["IMMOBILIZATION"],
    }
    defaults.update(overrides)
    return defaults


def complete_simulation_payload(**overrides) -> dict:
    defaults = {"patient_weight_kg": DEFAULTS["WEIGHT"]}
    defaults.update(overrides)
    return defaults


def create_contour_set_payload(**overrides) -> dict:
    defaults = {
        "set_label": DEFAULTS["CONTOUR_LABEL"],
        "target_volumes": list(DEFAULTS["TARGET_VOLUMES"]),
        "oar_structures": [],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "contour_set_id": None,  # caller supplies
        "target_total_dose_cGy": DEFAULTS["TOTAL_DOSE"],
        "planned_fractions": DEFAULTS["FRACTIONS"],
        "expected_course_version": None,  # caller supplies
    }
    defaults.update(overrides)
    return defaults


def create_dose_constraint_payload(**overrides) -> dict:
    defaults = {
        "structure_name": DEFAULTS["CONSTRAINT_STRUCTURE"],
        "constraint_type": DEFAULTS["CONSTRAINT_TYPE"],
        "limit_cGy": 2000,
        "evaluated_value_cGy": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_physics_check_payload(**overrides) -> dict:
    defaults = {"check_type": "PRIMARY", "outcome": "PASS"}
    defaults.update(overrides)
    return defaults


def create_fraction_session_payload(**overrides) -> dict:
    defaults = {
        "plan_id": None,     # caller supplies
        "machine_id": None,  # caller supplies
        "start_time": "2026-08-03T09:00:00Z",
        "end_time": "2026-08-03T09:20:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(**overrides) -> dict:
    defaults = {"name": "Machine", "machine_type": "LINAC", "room": "TX1"}
    defaults.update(overrides)
    return defaults


def create_interruption_payload(**overrides) -> dict:
    defaults = {
        "reason": "PATIENT_ILLNESS",
        "missed_count": 1,
        "start_date": "2026-08-04",
        "end_date": "2026-08-04",
    }
    defaults.update(overrides)
    return defaults


def create_chart_review_payload(**overrides) -> dict:
    defaults = {"outcome": "PASS"}
    defaults.update(overrides)
    return defaults
