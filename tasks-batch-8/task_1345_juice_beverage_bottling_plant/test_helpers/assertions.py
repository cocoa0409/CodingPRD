"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §2.9)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

CUSTOMER_STATUSES = ["PENDING_CREDIT", "ACTIVE", "SUSPENDED", "CLOSED"]
FORMULA_STATUSES = ["DRAFT", "LABEL_REVIEW", "APPROVED", "REVISION_REQUIRED", "RETIRED"]
REVIEW_STATUSES = ["PENDING", "APPROVED", "REJECTED", "SUPERSEDED"]
TANK_POSTURES = ["AVAILABLE", "OCCUPIED", "AWAITING_CIP", "IN_CIP"]
BATCH_STATUSES = [
    "PLANNED", "BLENDING", "AWAITING_QA", "QA_PASSED", "QA_FAILED",
    "PROCESSING", "PROCESSED", "RELEASED", "CONDEMNED", "CONSUMED",
]
PROCESS_RUN_STATUSES = [
    "SCHEDULED", "RUNNING", "VALIDATED", "DEVIATED", "ABORTED",
    "DISPOSITION_RELEASED", "DISPOSITION_REJECTED",
]
CONTAINER_LOT_STATUSES = ["RECEIVED", "QC_PASSED", "QC_FAILED", "RETURNED", "DEPLETED"]
LINE_STATUSES = ["ACTIVE", "MAINTENANCE"]
PRODUCTION_STATUSES = [
    "QUOTED", "CONFIRMED", "SCHEDULED", "IN_PRODUCTION", "COMPLETED",
    "BLOCKED_SUPPLY", "BLOCKED_LABEL", "CANCELLED",
]
INVOICE_STATUSES = ["NOT_INVOICED", "PROVISIONAL", "FINAL"]
LOT_STATUSES = ["AVAILABLE", "DEPLETED", "EXPIRED", "RECALLED"]
ORDER_STATUSES = ["PLACED", "ALLOCATED", "PICKED", "SHIPPED", "BACKORDERED", "CANCELLED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-less UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_customer_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["minimum_run_units"], int)
    assert isinstance(data["pallet_deposit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in CUSTOMER_STATUSES


def assert_formula(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["formula_code"], str) and data["formula_code"]
    assert isinstance(data["target_brix"], (int, float))
    assert isinstance(data["brix_tolerance"], (int, float))
    assert data["process_type"] in ["PASTEURIZATION", "HPP"]
    assert isinstance(data["container_fill_ml"], int)
    assert isinstance(data["concentrate_brix"], (int, float))
    assert data["allergen_group"] in ["NONE", "SULFITE", "TREE_NUT", "MILK"]
    assert isinstance(data["shelf_life_days"], int)
    assert isinstance(data["claims"], list)
    assert isinstance(data["label_version"], int) and data["label_version"] >= 0
    assert data["status"] in FORMULA_STATUSES


def assert_label_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["claims_snapshot"], list)
    assert data["status"] in REVIEW_STATUSES


def assert_tank(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tank_code"], str) and data["tank_code"]
    assert isinstance(data["capacity_liters"], int)
    assert data["allergen_group"] in ["NONE", "SULFITE", "TREE_NUT", "MILK"]
    assert data["posture"] in TANK_POSTURES


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("tank_id", ""))
    assert isinstance(data["quantity_liters"], (int, float))
    assert isinstance(data["initial_quantity_liters"], (int, float))
    assert isinstance(data["added_water_liters"], (int, float))
    assert isinstance(data["added_concentrate_liters"], (int, float))
    assert isinstance(data["adjustment_count"], int)
    assert data["status"] in BATCH_STATUSES


def assert_process_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["process_type"] in ["PASTEURIZATION", "HPP"]
    assert data["status"] in PROCESS_RUN_STATUSES


def assert_container_lot(data: dict):
    _assert_common_fields(data)
    assert data["container_type"] in ["GLASS_355", "PET_473", "PET_1000", "CAN_330"]
    assert isinstance(data["quantity_received"], int)
    assert isinstance(data["quantity_available"], int)
    assert isinstance(data["quantity_reserved"], int)
    assert isinstance(data["quantity_consumed"], int)
    assert data["status"] in CONTAINER_LOT_STATUSES


def assert_container_lot_conservation(data: dict):
    """PRD §2.9: quantity_received == available + reserved + consumed, always."""
    assert data["quantity_received"] == (
        data["quantity_available"] + data["quantity_reserved"] + data["quantity_consumed"]
    ), (
        f"container lot conservation broken: {data['quantity_received']} != "
        f"{data['quantity_available']} + {data['quantity_reserved']} + {data['quantity_consumed']}"
    )


def assert_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["supported_container_types"], list) and data["supported_container_types"]
    assert isinstance(data["nominal_cpm"], int)
    assert data["status"] in LINE_STATUSES


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("formula_id", ""))
    assert data["container_type"] in ["GLASS_355", "PET_473", "PET_1000", "CAN_330"]
    assert isinstance(data["planned_units"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert data["production_status"] in PRODUCTION_STATUSES
    assert data["invoice_status"] in INVOICE_STATUSES


def assert_finished_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("production_run_id", ""))
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("warehouse_zone_id", ""))
    assert isinstance(data["lot_code"], str) and data["lot_code"].startswith("FG-")
    assert isinstance(data["units_total"], int)
    assert isinstance(data["units_available"], int)
    assert isinstance(data["units_allocated"], int)
    assert isinstance(data["units_shipped"], int)
    assert isinstance(data["pallet_count"], int)
    assert isinstance(data["production_date"], str)
    assert isinstance(data["expiry_label_date"], str)
    assert isinstance(data["expiry_stability_date"], str)
    assert data["status"] in LOT_STATUSES


def assert_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert data["temperature_class"] in ["AMBIENT", "CHILLED", "FROZEN"]
    assert isinstance(data["pallet_capacity"], int)
    assert isinstance(data["pallets_stored"], int)


def assert_shipment_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("formula_id", ""))
    assert data["channel"] in ["DIRECT_RETAIL", "CLUB", "FOODSERVICE", "EXPORT"]
    assert isinstance(data["requested_delivery_date"], str)
    assert isinstance(data["units_requested"], int)
    assert isinstance(data["min_shelf_life_days"], int)
    assert isinstance(data["allocations"], list)
    assert isinstance(data["allocated_units"], int)
    assert data["status"] in ORDER_STATUSES


def assert_pallet_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["pallets_out_total"], int)
    assert isinstance(data["pallets_returned_total"], int)
    assert isinstance(data["pallets_converted_total"], int)
    assert isinstance(data["pallets_outstanding"], int)
    assert isinstance(data["escrow_balance_cents"], int)


def assert_pallet_account_invariants(data: dict, pallet_deposit_cents: int):
    """PRD §2.9: outstanding == out - returned - converted; escrow == outstanding * deposit."""
    expected_outstanding = (
        data["pallets_out_total"] - data["pallets_returned_total"] - data["pallets_converted_total"]
    )
    assert data["pallets_outstanding"] == expected_outstanding, (
        f"pallets_outstanding {data['pallets_outstanding']} != {expected_outstanding}"
    )
    assert data["pallets_outstanding"] >= 0, "pallets_outstanding must never go negative"
    assert data["escrow_balance_cents"] == data["pallets_outstanding"] * pallet_deposit_cents, (
        f"escrow {data['escrow_balance_cents']} != {data['pallets_outstanding']} * {pallet_deposit_cents}"
    )


def assert_pallet_entry(data: dict):
    """Append-only ledger entry: carries id and created_at but NO updated_at / version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "append-only pallet entry must not carry updated_at"
    assert "version" not in data, "append-only pallet entry must not carry version"
    assert is_valid_uuid(data.get("pallet_account_id", ""))
    assert data["entry_type"] in ["SHIP", "RETURN", "CONVERSION"]
    assert isinstance(data["pallet_count"], int) and data["pallet_count"] > 0
    assert isinstance(data["entry_date"], str)
    assert isinstance(data["running_balance"], int)


def assert_batch_mass_balance(data: dict):
    """PRD §2.9: quantity_liters == initial + added_water + added_concentrate."""
    total = round(
        data["initial_quantity_liters"] + data["added_water_liters"] + data["added_concentrate_liters"], 1
    )
    assert round(data["quantity_liters"], 1) == total, (
        f"batch mass balance broken: {data['quantity_liters']} != {total}"
    )
