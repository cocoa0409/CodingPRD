"""Entity assertions and domain invariant checkers.

Each assert_* validates the response shape promised by PRD §2.4 (id,
created_at, updated_at, version on every resource) plus the per-entity
fields the PRD narratives commit to.
"""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["utility_name"], str) and data["utility_name"]
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert isinstance(data["retainage_pct"], (int, float))
    assert 0 <= data["retainage_pct"] < 1
    assert isinstance(data["overrun_threshold_pct"], (int, float))
    assert isinstance(data["quantity_cap_pct"], (int, float))
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")


def assert_bid_item(data: dict):
    _assert_common(data)
    assert isinstance(data["item_code"], str) and data["item_code"]
    assert data["unit"] in ("EACH", "LF", "CY", "HR")
    assert data["unit_price"] > 0
    assert data["estimated_quantity"] > 0
    assert data.get("overrun_rate") is None or data["overrun_rate"] > 0
    # A read of a single bid item always includes both running totals.
    assert isinstance(data["accepted_quantity"], (int, float))
    assert isinstance(data["billed_quantity"], (int, float))


def assert_work_package(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["location"], str)
    assert isinstance(data["requires_outage"], bool)
    assert data["status"] in ("PLANNED", "MOBILIZED", "IN_PROGRESS", "PUNCH",
                              "COMPLETED", "CANCELLED")
    # The two counters ride on the package and appear on every read.
    assert isinstance(data["rework_open_count"], int)
    assert isinstance(data["open_material_issue_count"], int)


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert data["crew_type"] in ("OVERHEAD", "UNDERGROUND", "STORM")
    assert data["base_rate_per_hour"] > 0
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "STANDBY", "CALLOUT")


def assert_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["equipment_code"], str) and data["equipment_code"]
    assert data["kind"] in ("BUCKET_TRUCK", "DIGGER_DERRICK", "TRENCHER", "REEL_TRAILER")
    assert data["daily_rate"] > 0
    assert isinstance(data["maintenance_flag"], bool)
    assert data["status"] in ("AVAILABLE", "IN_USE")


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_package_id", ""))
    assert is_valid_uuid(data.get("crew_id", ""))
    assert is_valid_uuid(data.get("equipment_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_production_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("bid_item_id", ""))
    assert isinstance(data["work_date"], str)
    assert data["quantity_reported"] > 0
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REWORK_REQUIRED", "VOID")


def assert_stock_item(data: dict):
    _assert_common(data)
    assert isinstance(data["material_code"], str) and data["material_code"]
    assert isinstance(data["uom"], str) and data["uom"]
    assert isinstance(data["initial_on_hand"], (int, float))
    assert data["initial_on_hand"] >= 0
    assert isinstance(data["on_hand"], (int, float))


def assert_material_issue(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_package_id", ""))
    assert is_valid_uuid(data.get("stock_item_id", ""))
    assert data["quantity_issued"] > 0
    assert isinstance(data["quantity_returned"], (int, float))
    assert data["quantity_returned"] >= 0
    assert data.get("quantity_installed") is None or data["quantity_installed"] >= 0
    assert data.get("variance") is None or isinstance(data["variance"], (int, float))
    assert data["status"] in ("OPEN", "RECONCILED", "VARIANCE_RECONCILED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_package_id", ""))
    assert is_valid_uuid(data.get("production_entry_id", ""))
    assert isinstance(data["standard_code"], str) and data["standard_code"]
    assert data.get("result") is None or data["result"] in ("PASS", "FAIL")
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED")


def assert_outage_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_package_id", ""))
    assert isinstance(data["circuit_id"], str) and data["circuit_id"]
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "CHANGE_REQUESTED",
                              "IN_EFFECT", "RELEASED", "DENIED", "CANCELLED")


def assert_storm_activation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("crew_id", ""))
    assert data["kind"] in ("STANDBY", "CALLOUT")
    assert isinstance(data["activation_date"], str)
    assert isinstance(data["converted"], bool)
    assert data["status"] in ("ACTIVE", "CLOSED", "CANCELLED")
    if data.get("premium_pay") is not None:
        assert_cost_precision(data["premium_pay"])


def assert_safety_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_package_id", ""))
    assert data["kind"] in ("OBSERVATION", "INCIDENT")
    assert data["severity"] in ("POSITIVE", "AT_RISK", "OSHA_RECORDABLE", "FATAL")
    assert isinstance(data["description"], str)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "CLOSED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_package_id", ""))
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line.get("bid_item_id", ""))
        assert isinstance(line["item_code"], str)
        assert isinstance(line["in_schedule_units"], (int, float))
        assert isinstance(line["overrun_units"], (int, float))
        assert isinstance(line["in_schedule_rate"], (int, float))
        assert isinstance(line["overrun_rate_applied"], (int, float))
        assert_cost_precision(line["extension_amount"])
    assert_cost_precision(data["subtotal"])
    assert_cost_precision(data["retainage_amount"])
    assert_cost_precision(data["amount_due"])
    assert data.get("hold_reason") is None or data["hold_reason"] == "OPEN_REWORK"
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "PAID",
                              "REJECTED", "VOID")
