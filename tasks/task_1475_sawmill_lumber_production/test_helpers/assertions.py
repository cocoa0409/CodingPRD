"""Entity assertions and domain invariant checkers for the sawmill API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

SPECIES = ["DOUGLAS_FIR", "PONDEROSA_PINE", "HEMLOCK_FIR", "CEDAR"]
LOG_GRADES = ["PEELER", "SAWLOG_1", "SAWLOG_2", "UTILITY"]
STAMPED_GRADES = ["SELECT_STRUCT", "NO_2", "NO_3", "ECONOMY"]
LOAD_STATUSES = ["RECEIVED", "SCALED", "DISPUTED", "DECKED", "CONSUMED"]
RUN_STATUSES = ["PLANNED", "COMPLETED"]
CHARGE_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED"]
PACKAGE_STATUSES = ["GREEN", "IN_KILN", "DRY", "STAMPED", "ALLOCATED", "SHIPPED"]
CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "CLOSED", "EXPIRED"]
ORDER_STATUSES = ["PLACED", "ALLOCATED", "SHIPPED", "CANCELLED"]


def _assert_tracked(data: dict):
    """Fields carried by every fully-tracked resource (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only ledger rows carry id + created_at only (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_log_load(data: dict):
    _assert_tracked(data)
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert data["species"] in SPECIES
    assert data["log_grade"] in LOG_GRADES
    assert data["status"] in LOAD_STATUSES
    if data.get("scaled_mbf") is not None:
        assert isinstance(data["scaled_mbf"], (int, float))
    if data.get("price_per_mbf_cents") is not None:
        assert isinstance(data["price_per_mbf_cents"], int)
    if data.get("purchase_cost_cents") is not None:
        assert isinstance(data["purchase_cost_cents"], int)
    assert isinstance(data["days_in_deck"], int)
    assert isinstance(data["degrade_pct"], (int, float))


def assert_sawing_run(data: dict):
    _assert_tracked(data)
    assert data["saw_line"] in ["LINE_A", "LINE_B"]
    assert isinstance(data["scheduled_date"], str)
    assert data["sawing_pattern"] in ["DIMENSION_2X4", "STUD_MIX", "TIMBER_4X4"]
    assert isinstance(data["log_load_ids"], list)
    assert data["status"] in RUN_STATUSES
    if data["status"] == "COMPLETED":
        assert isinstance(data["input_mbf"], (int, float))
        assert isinstance(data["output_green_mbf"], (int, float))
        assert isinstance(data["recovery_pct_provisional"], (int, float))
        assert is_iso8601_timestamp(data.get("completed_at", ""))


def assert_kiln_charge(data: dict):
    _assert_tracked(data)
    assert data["chamber"] in ["KILN_1", "KILN_2", "KILN_3"]
    assert data["species"] in SPECIES
    assert isinstance(data["package_ids"], list)
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert isinstance(data["target_moisture_pct"], (int, float))
    assert data["status"] in CHARGE_STATUSES


def assert_lumber_package(data: dict):
    _assert_tracked(data)
    assert is_valid_uuid(data.get("sawing_run_id", ""))
    assert data["species"] in SPECIES
    assert data["dimension"] in ["2X4", "2X6", "4X4"]
    assert data["length_ft"] in [8, 10, 12, 16]
    assert isinstance(data["pieces"], int)
    assert isinstance(data["green_mbf"], (int, float))
    assert isinstance(data["estimated_dry_mbf"], (int, float))
    if data.get("actual_dry_mbf") is not None:
        assert isinstance(data["actual_dry_mbf"], (int, float))
    assert isinstance(data["dry_mbf"], (int, float))
    assert data["status"] in PACKAGE_STATUSES
    if data.get("stamped_grade") is not None:
        assert data["stamped_grade"] in STAMPED_GRADES


def assert_grade_inspection(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data.get("package_id", ""))
    assert data["inspector_grade"] in STAMPED_GRADES
    assert data["action"] in ["STAMP", "RESTAMP"]


def assert_sales_contract(data: dict):
    _assert_tracked(data)
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert data["species"] in SPECIES
    assert data["grade"] in STAMPED_GRADES
    assert isinstance(data["committed_mbf"], (int, float))
    assert isinstance(data["contract_price_per_mbf_cents"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in CONTRACT_STATUSES
    assert isinstance(data["reserved_mbf"], (int, float))
    assert isinstance(data["shipped_mbf"], (int, float))
    assert isinstance(data["remaining_mbf"], (int, float))


def assert_sales_order(data: dict):
    _assert_tracked(data)
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert data["species"] in SPECIES
    assert data["grade"] in STAMPED_GRADES
    assert data["length_spec"] == "RL" or data["length_spec"] in [8, 10, 12, 16]
    assert isinstance(data["volume_mbf"], (int, float))
    assert data["pricing_mode"] in ["CONTRACT", "SPOT"]
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["allocated_mbf"], (int, float))
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ORDER_STATUSES


def assert_price_list(data: dict):
    _assert_append_only(data)
    assert data["species"] in SPECIES
    assert data["grade"] in STAMPED_GRADES
    assert isinstance(data["base_price_per_mbf_cents"], int)
    assert isinstance(data["effective_from"], str)


def assert_byproduct_sale(data: dict):
    _assert_append_only(data)
    assert data["product"] in ["CHIP", "SAWDUST", "BARK"]
    assert isinstance(data["volume_tons"], (int, float))
    assert isinstance(data["price_per_ton_cents"], int)
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert isinstance(data["total_cents"], int)
