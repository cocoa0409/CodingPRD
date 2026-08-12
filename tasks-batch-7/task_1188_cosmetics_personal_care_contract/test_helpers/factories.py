"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import LOT_EXPIRES_AT, RUN_DAY

# PRD §3.1: a lot's supplier `lot_code` must be unique per component, so the
# default code is generated unique per call (tests that exercise the
# uniqueness rule pass explicit duplicate codes).
_lot_code_seq = itertools.count(1)


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Beauty",
        "tier": "STANDARD",
        "minimum_run_units": 1000,
        "credit_limit_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {
        "name": "Water",
        "kind": "RAW_MATERIAL",
        "supply_mode": "MANUFACTURER_SUPPLIED",
        "standard_cost_per_kg_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_code": "LOT-%d" % next(_lot_code_seq),
        "quantity_received": 100,
        "expires_at": LOT_EXPIRES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(customer_id, ingredients, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "name": "Formula F",
        "ownership": "CUSTOMER_OWNED",
        "confidentiality": "STANDARD",
        "product_class": "SKIN",
        "allergen_flag": False,
        "bulk_mass_per_unit_kg": 0.05,
        "viscosity_target_cps": 4000,
        "viscosity_tolerance_pct": 10,
        "ph_target": 5.5,
        "ph_tolerance": 0.5,
        "ingredients": ingredients,
        "required_components": [],
    }
    defaults.update(overrides)
    return defaults


def single_ingredient(component_id, inci_name="AQUA") -> list:
    return [{"inci_name": inci_name, "component_id": component_id, "percentage": 100}]


def create_order_payload(formula_id, requested_units, **overrides) -> dict:
    defaults = {"formula_id": formula_id, "requested_units": requested_units}
    defaults.update(overrides)
    return defaults


def patch_order_payload(requested_units, expected_production_order_version) -> dict:
    return {
        "requested_units": requested_units,
        "expected_production_order_version": expected_production_order_version,
    }


def create_batch_payload(batch_size_kg, **overrides) -> dict:
    defaults = {"batch_size_kg": batch_size_kg}
    defaults.update(overrides)
    return defaults


def allocation_item(lot_id, quantity, batch_id=None) -> dict:
    item = {"lot_id": lot_id, "quantity": quantity}
    if batch_id is not None:
        item["batch_id"] = batch_id
    return item


def create_allocations_payload(items) -> dict:
    return {"items": items}


def ipc_check_payload(check_type, measured_value) -> dict:
    return {"check_type": check_type, "measured_value": measured_value}


def create_review_payload(review_scope="INCI_LIST") -> dict:
    return {"review_scope": review_scope}


def create_revision_payload(expected_formula_version, **overrides) -> dict:
    defaults = {"expected_formula_version": expected_formula_version}
    defaults.update(overrides)
    return defaults


def declare_shortfall_payload(component_id, required_quantity) -> dict:
    return {"component_id": component_id, "required_quantity": required_quantity}


def commit_shortfall_payload(committed_by_date="2026-06-01T00:00:00Z") -> dict:
    return {"committed_by_date": committed_by_date}


def escalate_shortfall_payload(resolution) -> dict:
    return {"resolution": resolution}


def waive_variant_payload(decision) -> dict:
    return {"decision": decision}


def create_chamber_payload(**overrides) -> dict:
    defaults = {"chamber_code": "CH1", "capacity_studies": 2}
    defaults.update(overrides)
    return defaults


def create_study_payload(chamber_id, study_type) -> dict:
    return {"chamber_id": chamber_id, "study_type": study_type}


def record_reading_payload(interval_index, result) -> dict:
    return {"interval_index": interval_index, "result": result}


def create_line_payload(**overrides) -> dict:
    defaults = {"line_code": "L1"}
    defaults.update(overrides)
    return defaults


def create_run_payload(line_id, batch_id, planned_units,
                       scheduled_start=f"{RUN_DAY}T08:00:00Z",
                       scheduled_end=f"{RUN_DAY}T09:00:00Z",
                       **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "batch_id": batch_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "planned_units": planned_units,
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(filled_units, **overrides) -> dict:
    defaults = {"filled_units": filled_units}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
