"""Payload factories — one per creatable resource, input fields only."""
from .constants import INGREDIENT_PROFILES, TEST_DEFAULTS


def create_ingredient_payload(profile="CORN", **overrides) -> dict:
    defaults = dict(INGREDIENT_PROFILES[profile])
    defaults.update(overrides)
    return defaults


def create_price_tick_payload(ingredient_id, price_cents_per_ton=None,
                              effective_from=None, **overrides) -> dict:
    defaults = {
        "ingredient_id": ingredient_id,
        "price_cents_per_ton": price_cents_per_ton or TEST_DEFAULTS["CORN_PRICE_CENTS_PER_TON"],
        "effective_from": effective_from or TEST_DEFAULTS["TICK_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(ingredient_id, **overrides) -> dict:
    defaults = {
        "ingredient_id": ingredient_id,
        "supplier_ref": "SUP-1",
        "fixed_price_cents_per_ton": 29000,
        "total_tons": 50,
        "window_start_date": "2026-04-01",
        "window_end_date": "2026-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_bin_payload(code="BIN-1", capacity_tons=50, **overrides) -> dict:
    defaults = {"code": code, "capacity_tons": capacity_tons}
    defaults.update(overrides)
    return defaults


def create_customer_payload(name="Acme Farms", credit_limit_cents=None, **overrides) -> dict:
    defaults = {
        "name": name,
        "credit_limit_cents": credit_limit_cents if credit_limit_cents is not None
        else TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(full_name="Olly Operator", capability="OPERATOR", **overrides) -> dict:
    defaults = {"full_name": full_name, "capability": capability}
    defaults.update(overrides)
    return defaults


def create_formula_payload(code="F-GROW", min_protein_pct=19.5, max_fiber_pct=5.0,
                           min_energy_kcal_kg=3000, **overrides) -> dict:
    defaults = {
        "code": code,
        "min_protein_pct": min_protein_pct,
        "max_fiber_pct": max_fiber_pct,
        "min_energy_kcal_kg": min_energy_kcal_kg,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(formula_id, tons=10, expected_customer_version=1, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "tons": tons,
        "expected_customer_version": expected_customer_version,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(order_id, line_id, target_tons=10,
                         planned_start_at=None, planned_end_at=None, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "line_id": line_id,
        "target_tons": target_tons,
        "planned_start_at": planned_start_at or TEST_DEFAULTS["BATCH_WINDOW_START"],
        "planned_end_at": planned_end_at or TEST_DEFAULTS["BATCH_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_weighment_payload(ingredient_id, bin_id, actual_tons, **overrides) -> dict:
    defaults = {
        "ingredient_id": ingredient_id,
        "bin_id": bin_id,
        "actual_tons": actual_tons,
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(batch_id, sample_type="COMPOSITE", **overrides) -> dict:
    defaults = {"batch_id": batch_id, "sample_type": sample_type}
    defaults.update(overrides)
    return defaults


def create_sample_result_payload(protein_pct_actual=20.0, crude_fiber_pct_actual=4.0,
                                 moisture_pct=0, **overrides) -> dict:
    defaults = {
        "protein_pct_actual": protein_pct_actual,
        "crude_fiber_pct_actual": crude_fiber_pct_actual,
        "moisture_pct": moisture_pct,
    }
    defaults.update(overrides)
    return defaults


def create_flush_record_payload(line_id, flush_material_ingredient_id,
                                quantity_tons=0.5, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "flush_material_ingredient_id": flush_material_ingredient_id,
        "quantity_tons": quantity_tons,
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(code="L1", **overrides) -> dict:
    defaults = {"code": code}
    defaults.update(overrides)
    return defaults


def create_truck_payload(plate_no="TRK-01", cargo_class_capability="STANDARD_ONLY",
                         compartments=None, **overrides) -> dict:
    defaults = {
        "plate_no": plate_no,
        "cargo_class_capability": cargo_class_capability,
        "compartments": compartments if compartments is not None
        else [{"compartment_seq": 1, "capacity_tons": 12}],
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(truck_id, order_id, compartment_allocations=None,
                        planned_departure_at=None, planned_return_at=None, **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "order_id": order_id,
        "planned_departure_at": planned_departure_at or TEST_DEFAULTS["TRIP_DEPARTURE"],
        "planned_return_at": planned_return_at or TEST_DEFAULTS["TRIP_RETURN"],
        "compartment_allocations": compartment_allocations if compartment_allocations is not None
        else [{"compartment_seq": 1, "tons": 10, "cargo_class": "STANDARD"}],
    }
    defaults.update(overrides)
    return defaults
