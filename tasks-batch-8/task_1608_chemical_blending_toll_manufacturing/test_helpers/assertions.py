"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Every resource carries ``id``, ``created_at``,
``updated_at`` and ``version`` (PRD §2.4).
"""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer >= 1"


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_pricing_agreement(data: dict):
    _assert_common(data, "PricingAgreement")
    assert data["pricing_mode"] in ["TOLLING_FEE", "FORMULATED_PRICE"]
    assert isinstance(data["tolling_base_fee_cents"], int)
    assert isinstance(data["tolling_per_kg_cents"], int)
    assert isinstance(data["formulated_price_per_kg_cents"], int)
    assert isinstance(data["over_yield_split_pct"], int)
    assert 0 <= data["over_yield_split_pct"] <= 100
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "TERMINATED"]


def assert_lot(data: dict):
    _assert_common(data, "RawMaterialLot")
    assert isinstance(data["material_code"], str) and data["material_code"]
    assert data["ghS_class"] in ["FLAMMABLE", "OXIDIZER", "ACID", "BASE", "TOXIN", "NON_HAZ"]
    for field in ("quantity_kg_received", "quantity_kg_on_hand",
                  "quantity_kg_committed", "quantity_kg_available"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert data[field] >= 0, f"{field} must be >= 0"
    assert data["storage_zone"] in ["Z_FLAM", "Z_OXID", "Z_ACID", "Z_BASE", "Z_TOXIC", "Z_GENERAL"]
    assert is_iso8601_timestamp(data["received_at"])


def assert_lot_balances(data: dict, on_hand, committed, available):
    """The three derived lot balances (PRD §3.4) reconcile exactly."""
    assert data["quantity_kg_on_hand"] == pytest.approx(on_hand, abs=1e-3), \
        f"quantity_kg_on_hand: expected {on_hand}, got {data['quantity_kg_on_hand']}"
    assert data["quantity_kg_committed"] == pytest.approx(committed, abs=1e-3), \
        f"quantity_kg_committed: expected {committed}, got {data['quantity_kg_committed']}"
    assert data["quantity_kg_available"] == pytest.approx(available, abs=1e-3), \
        f"quantity_kg_available: expected {available}, got {data['quantity_kg_available']}"


def assert_recipe(data: dict):
    _assert_common(data, "Recipe")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["target_density_kg_per_l"] > 0
    assert 0 < data["theoretical_yield_pct"] <= 100
    assert isinstance(data["components"], list) and len(data["components"]) >= 1
    for comp in data["components"]:
        assert isinstance(comp["material_code"], str)
        assert isinstance(comp["charge_order"], int) and comp["charge_order"] >= 1
    assert data["highest_component_ghs"] in \
        ["FLAMMABLE", "OXIDIZER", "ACID", "BASE", "TOXIN", "NON_HAZ"]
    assert data["status"] in ["DRAFT", "APPROVED", "RETIRED"]


def assert_tank(data: dict):
    _assert_common(data, "Tank")
    assert isinstance(data["tank_code"], str) and data["tank_code"]
    assert isinstance(data["capacity_l"], int) and data["capacity_l"] > 0
    assert isinstance(data["working_capacity_l"], int)
    assert 0 < data["working_capacity_l"] <= data["capacity_l"]
    assert data["current_zone"] in ["Z_FLAM", "Z_OXID", "Z_ACID", "Z_BASE", "Z_TOXIC", "Z_GENERAL"]
    assert data["occupied_by_batch_id"] is None or is_valid_uuid(data["occupied_by_batch_id"])
    assert data["last_product_ghs"] is None or data["last_product_ghs"] in \
        ["FLAMMABLE", "OXIDIZER", "ACID", "BASE", "TOXIN", "NON_HAZ"]
    assert data["cleaning_state"] in \
        ["DIRTY", "CLEANING_IN_PROGRESS", "CLEAN_PENDING_VALIDATION", "CLEAN_VALIDATED"]
    assert data["operational_state"] in ["AVAILABLE", "RESERVED", "IN_USE", "OUT_OF_SERVICE"]


def assert_cleaning_record(data: dict):
    _assert_common(data, "CleaningRecord")
    assert data["method"] in ["SOLVENT_FLUSH", "CAUSTIC_CIP", "STEAM", "DRY_PURGE"]
    assert is_iso8601_timestamp(data["started_at"])
    assert is_iso8601_timestamp(data["completed_at"])
    assert isinstance(data["residue_ppm"], int) and data["residue_ppm"] >= 0
    assert data["validation_outcome"] in ["PENDING", "PASSED", "FAILED"]


def assert_batch_job(data: dict):
    _assert_common(data, "BatchJob")
    for fk in ("customer_id", "recipe_id", "pricing_agreement_id", "tank_id"):
        assert is_valid_uuid(data[fk]), f"BatchJob.{fk} must be a valid UUID"
    assert isinstance(data["batch_size_l"], int) and data["batch_size_l"] > 0
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["theoretical_output_kg"], (int, float))
    assert data["highest_component_ghs_snapshot"] in \
        ["FLAMMABLE", "OXIDIZER", "ACID", "BASE", "TOXIN", "NON_HAZ"]
    assert data["status"] in ["INTAKE", "RELEASED", "CHARGING", "MIXING", "HOLD_QA",
                              "COMPLETED", "CANCELLED", "REJECTED_QA"]


def assert_batch_charge(data: dict):
    _assert_common(data, "BatchCharge")
    assert is_valid_uuid(data["batch_job_id"])
    assert is_valid_uuid(data["raw_material_lot_id"])
    assert isinstance(data["charge_order"], int) and data["charge_order"] >= 1
    assert isinstance(data["charged_qty_kg"], (int, float)) and data["charged_qty_kg"] > 0
    assert data["status"] in ["COMMITTED", "CONSUMED", "RELEASED"]


def assert_sds_document(data: dict):
    _assert_common(data, "SDSDocument")
    assert is_valid_uuid(data["batch_job_id"])
    assert isinstance(data["authoring_revision"], int) and data["authoring_revision"] >= 1
    assert data["ghs_classification"] in \
        ["FLAMMABLE", "OXIDIZER", "ACID", "BASE", "TOXIN", "NON_HAZ"]
    assert data["signal_word"] in ["DANGER", "WARNING", "NONE"]
    assert isinstance(data["hazard_statements"], list)
    assert isinstance(data["authoring_consistency_flag"], bool)
    assert data["status"] in ["DRAFT", "ISSUED", "SUPERSEDED"]


def assert_package_config(data: dict):
    _assert_common(data, "PackageConfig")
    assert is_valid_uuid(data["batch_job_id"])
    assert data["package_type"] in ["DRUM_205L", "IBC_1000L", "TOTE_500L", "PAIL_20L"]
    assert isinstance(data["un_rated"], bool)
    assert isinstance(data["package_count"], int) and data["package_count"] > 0
    assert isinstance(data["total_volume_l"], int) and data["total_volume_l"] > 0
    assert isinstance(data["placard_required"], bool)
    assert data["placard_class"] is None or data["placard_class"] in \
        ["CLASS_3_FLAMMABLE", "CLASS_5_1_OXIDIZER", "CLASS_8_CORROSIVE", "CLASS_6_1_TOXIC"]


def assert_shipment(data: dict):
    _assert_common(data, "Shipment")
    assert is_valid_uuid(data["batch_job_id"])
    assert isinstance(data["carrier_name"], str)
    assert isinstance(data["vehicle_placards"], list)
    assert is_iso8601_timestamp(data["departure_at"])
    assert data["shipped_volume_l"] is None or isinstance(data["shipped_volume_l"], int)
    assert data["status"] in ["PLANNED", "LOADING", "DISPATCHED", "CANCELLED"]


def assert_heel_disposal(data: dict):
    _assert_common(data, "HeelDisposalRecord")
    assert is_valid_uuid(data["batch_job_id"])
    assert is_valid_uuid(data["raw_material_lot_id"])
    assert isinstance(data["heel_returned_kg"], (int, float)) and data["heel_returned_kg"] >= 0
    assert isinstance(data["heel_disposed_kg"], (int, float)) and data["heel_disposed_kg"] >= 0
    assert data["disposal_method"] is None or data["disposal_method"] in \
        ["INCINERATION", "FUEL_BLENDING", "HAZARDOUS_LANDFILL"]
    assert is_iso8601_timestamp(data["disposed_at"])
    assert data["status"] in ["PENDING", "POSTED"]
