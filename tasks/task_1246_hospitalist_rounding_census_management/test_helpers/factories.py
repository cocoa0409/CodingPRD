"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FULL_NAME": "Test Hospitalist",
    "SPECIALTY": "INTERNAL_MEDICINE",
    "MRN": "M000",
    "ACUITY": "MEDIUM",
    "ADMIT_SOURCE": "ED",
    "STAY_TYPE": "INPATIENT",
    "SHIFT_TYPE": "DAY",
    "SHIFT_START": "2026-05-01T06:00:00Z",
    "SHIFT_END": "2026-05-01T18:00:00Z",
    "TARGET_DISCHARGE_AT": "2026-05-02T15:00:00Z",
    "CONSULT_SPECIALTY": "CARDIOLOGY",
    "CONSULT_PRIORITY": "ROUTINE",
    "CONSULT_REASON": "clinical question",
    "ENCOUNTER_TYPE": "SUBSEQUENT_VISIT",
    "OCCURRED_ON": "2026-05-04",
    "WRVU_VALUE": 1.2,
    "PERIOD_START": "2026-05-01",
    "PERIOD_END": "2026-05-31",
    "WINDOW_DATE": "2026-05-01",
    "WINDOW_TYPE": "NIGHT_PRIMARY",
    "WINDOW_START": "2026-05-01T19:00:00Z",
    "WINDOW_END": "2026-05-02T07:00:00Z",
    "WINDOW_CAPACITY": 2,
    "RETURN_REASON": "needs more detail",
}


def create_hospitalist_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "specialty": DEFAULTS["SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": DEFAULTS["MRN"],
        "acuity": DEFAULTS["ACUITY"],
        "admit_source": DEFAULTS["ADMIT_SOURCE"],
        "stay_type": DEFAULTS["STAY_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_type": DEFAULTS["SHIFT_TYPE"],
        "start_at": DEFAULTS["SHIFT_START"],
        "end_at": DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_admission_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_transfer_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_discharge_order_payload(**overrides) -> dict:
    defaults = {
        "target_discharge_at": DEFAULTS["TARGET_DISCHARGE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_handoff_payload(**overrides) -> dict:
    defaults = {
        "receiving_hospitalist_id": None,
        "patient_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_consult_request_payload(**overrides) -> dict:
    defaults = {
        "specialty": DEFAULTS["CONSULT_SPECIALTY"],
        "priority": DEFAULTS["CONSULT_PRIORITY"],
        "reason": DEFAULTS["CONSULT_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(**overrides) -> dict:
    defaults = {
        "encounter_type": DEFAULTS["ENCOUNTER_TYPE"],
        "occurred_on": DEFAULTS["OCCURRED_ON"],
        "wrvu_value": DEFAULTS["WRVU_VALUE"],
    }
    defaults.update(overrides)
    return defaults


def create_productivity_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_coverage_window_payload(**overrides) -> dict:
    defaults = {
        "window_date": DEFAULTS["WINDOW_DATE"],
        "window_type": DEFAULTS["WINDOW_TYPE"],
        "start_at": DEFAULTS["WINDOW_START"],
        "end_at": DEFAULTS["WINDOW_END"],
        "capacity": DEFAULTS["WINDOW_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults
