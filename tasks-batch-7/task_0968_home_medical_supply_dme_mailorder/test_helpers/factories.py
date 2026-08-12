"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def payer_plan_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Test Plan {n}",
        "plan_type": "MEDICARE_DMEPOS",
        "coinsurance_pct": 0.20,
        "cycle_months": 3,
        "is_active": True,
    }
    defaults.update(overrides)
    return defaults


def formulary_item_payload(covered_plan_ids, **overrides) -> dict:
    n = _seq()
    defaults = {
        "hcpcs_code": "A4419",
        "name": f"Test Item {n}",
        "category": "OSTOMY",
        "covered_plan_ids": list(covered_plan_ids),
        "pack_fee_cents": 1850,
        "pack_size": 10,
        "retail_price_cents": 300,
        "max_units_per_cycle": 60,
        "requires_pa": False,
        "size_codes": ["45MM"],
    }
    defaults.update(overrides)
    return defaults


def patient_payload(payer_plan_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Test Patient {n}",
        "date_of_birth": "1960-01-01",
        "payer_plan_id": payer_plan_id,
        "hsa_initial_credit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def prescription_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "hcpcs_code": "A4419",
        "prescriber_npi": "1234567890",
        "diagnosis_codes": ["N39.3"],
        "monthly_quantity": 20,
        "effective_date": "2026-05-01",
        "expiration_date": "2026-11-01",
    }
    defaults.update(overrides)
    return defaults


def fit_profile_payload(patient_id, expected_patient_version, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "category": "OSTOMY",
        "size_code": "45MM",
        "measured_on": "2026-04-20",
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def resupply_program_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "category": "OSTOMY",
        "frequency_days": 30,
        "start_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def order_payload(patient_id, **overrides) -> dict:
    defaults = {"patient_id": patient_id}
    defaults.update(overrides)
    return defaults


def order_line_payload(formulary_item_id, expected_order_version, **overrides) -> dict:
    defaults = {
        "formulary_item_id": formulary_item_id,
        "size_code": "45MM",
        "quantity": 1,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def prior_authorization_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "hcpcs_code": "A6250",
        "approved_units": 45,
        "valid_from": "2026-05-01",
        "valid_to": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def stock_level_payload(formulary_item_id, **overrides) -> dict:
    defaults = {"formulary_item_id": formulary_item_id, "on_hand_qty": 500}
    defaults.update(overrides)
    return defaults


def fitting_sample_payload(patient_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "patient_id": patient_id,
        "category": "OSTOMY",
        "size_code": "45MM",
        "item_name": f"Sample {n}",
    }
    defaults.update(overrides)
    return defaults


def hsa_debit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": "test debit"}
    defaults.update(overrides)
    return defaults


def hsa_credit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": "test credit"}
    defaults.update(overrides)
    return defaults
