"""Payload factories — one per entity, input fields only."""


DEFAULTS = {
    "MODEL_LIST_PRICE": 200_000,
    "MODEL_RESTOCK_FEE": 10_000,
    "MODEL_FIRMWARE": "1.0.0",
    "MODEL_WARRANTY_MONTHS": 24,
    "MODEL_MIN_SEVERITY": "MILD",
    "BENEFIT_TOTAL": 500_000,
    "BENEFIT_CAP": 250_000,
    "BENEFIT_COINS": 0.20,
    "BENEFIT_PERIOD_END": "2026-12-31",
    "UNIT_PRICE": 5_000,
    "CADENCE_DAYS": 30,
}


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1960-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_device_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": "DV-TEST-1",
        "name": "Test Model",
        "list_price_cents": DEFAULTS["MODEL_LIST_PRICE"],
        "restock_fee_cents": DEFAULTS["MODEL_RESTOCK_FEE"],
        "min_severity": DEFAULTS["MODEL_MIN_SEVERITY"],
        "firmware_version": DEFAULTS["MODEL_FIRMWARE"],
        "warranty_months": DEFAULTS["MODEL_WARRANTY_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_allowance_benefit_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "plan_name": "Test Plan",
        "total_allowance_cents": DEFAULTS["BENEFIT_TOTAL"],
        "per_device_cap_cents": DEFAULTS["BENEFIT_CAP"],
        "coinsurance_pct": DEFAULTS["BENEFIT_COINS"],
        "period_end": DEFAULTS["BENEFIT_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "audiologist_user_id": "aud-1",
        "pure_tone_avg_db": 50,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(patient_id, evaluation_id, device_model_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "evaluation_id": evaluation_id,
        "device_model_id": device_model_id,
        "ear_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {
        "audiologist_user_id": "aud-1",
        "reason": "COMFORT",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "DEFECT",
        "incident_date": "2026-04-10",
        "assessed_value_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(patient_id, fitting_order_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "fitting_order_id": fitting_order_id,
        "cadence_days": DEFAULTS["CADENCE_DAYS"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(device_model_id, **overrides) -> dict:
    defaults = {
        "device_model_id": device_model_id,
        "affected_firmware_version": "1.0.0",
        "target_firmware_version": "1.0.1",
        "severity_level": "MANDATORY",
    }
    defaults.update(overrides)
    return defaults
