"""Payload factories — one per entity, input fields only (per PRD endpoint definitions)."""

_COUNTER = {"n": 0}


def _next() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


# --- growers / buyers ---

def create_grower_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Test Ranch {n}",
        "ranch_code": f"RC-{n:04d}",
        "base_price_cents_per_lb": 250,
    }
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Test Buyer {n}",
        "buyer_code": f"BC-{n:04d}",
    }
    defaults.update(overrides)
    return defaults


# --- lots / lab tests ---

def create_lot_payload(**overrides) -> dict:
    defaults = {
        "variety": "Nonpareil",
        "gross_weight_lbs": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_moisture_kernel_test_payload(**overrides) -> dict:
    defaults = {
        "test_type": "MOISTURE_KERNEL",
        "moisture_pct": 6.0,
        "kernel_pct": 0.50,
        "foreign_material_pct": 0.01,
    }
    defaults.update(overrides)
    return defaults


def create_aflatoxin_test_payload(**overrides) -> dict:
    defaults = {
        "test_type": "AFLATOXIN",
        "aflatoxin_ppb": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_kernel_grade_test_payload(**overrides) -> dict:
    defaults = {
        "test_type": "KERNEL_GRADE",
        "edible_kernel_pct": 0.80,
        "size_spec": "SPEC_23_25",
    }
    defaults.update(overrides)
    return defaults


# --- processing runs ---

def create_processing_run_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def complete_run_payload(**overrides) -> dict:
    defaults = {
        "kernel_out_lbs": 2400,
        "shell_out_lbs": 1300,
        "hull_out_lbs": 900,
    }
    defaults.update(overrides)
    return defaults


# --- dryers / drying batches ---

def create_dryer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "dryer_code": f"D-{n:04d}",
        "capacity_lbs": 60000,
    }
    defaults.update(overrides)
    return defaults


def create_drying_batch_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-05-02T00:00:00Z",
        "end_at": "2026-05-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- bins / placements / withdrawals ---

def create_bin_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "bin_code": f"B-{n:04d}",
        "capacity_lbs": 5000,
        "allowed_product_forms": ["KERNEL"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(**overrides) -> dict:
    defaults = {
        "product_form": "KERNEL",
        "quantity_lbs": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_payload(**overrides) -> dict:
    defaults = {
        "product_form": "KERNEL",
        "quantity_lbs": 100,
    }
    defaults.update(overrides)
    return defaults


# --- fumigations ---

def create_fumigation_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-05-10T00:00:00Z",
        "aeration_hours": 48,
    }
    defaults.update(overrides)
    return defaults


# --- contracts / shipments ---

def create_contract_payload(**overrides) -> dict:
    defaults = {
        "product_form": "KERNEL",
        "size_spec": "SPEC_23_25",
        "max_defects_pct": 0.05,
        "price_cents_per_lb": 300,
        "required_qty_lbs": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "quantity_lbs": 1000,
    }
    defaults.update(overrides)
    return defaults


# --- settlements ---

def create_settlement_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


# --- byproduct sales ---

def create_byproduct_sale_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "product_form": "HULL",
        "quantity_lbs": 100,
        "price_cents_per_lb": 3,
        "buyer_name": f"Byproduct Buyer {n}",
    }
    defaults.update(overrides)
    return defaults
