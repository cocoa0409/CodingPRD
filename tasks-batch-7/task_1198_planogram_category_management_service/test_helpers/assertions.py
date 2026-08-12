"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_retailer(data: dict):
    assert isinstance(data, dict), "retailer payload must be a dict"
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert isinstance(data.get("name"), str) and data["name"], "name must be non-empty string"
    assert data.get("status") in ("ACTIVE", "SUSPENDED"), f"unexpected retailer status {data.get('status')!r}"
    assert isinstance(data.get("compliance_threshold_pct"), int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_category(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("retailer_id", "")), "retailer_id must be UUID"
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("role") in ("DESTINATION", "ROUTINE", "CONVENIENCE", "SEASONAL")
    assert isinstance(data.get("annual_sales_cents"), int)
    assert isinstance(data.get("total_linear_feet"), int)
    assert data.get("status") in ("OPEN", "LOCKED", "ARCHIVED")
    assert "active_planogram_id" in data
    assert isinstance(data.get("version"), int)


def assert_supplier(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("retailer_id", "")), "retailer_id must be UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("is_captain"), bool)
    assert "captain_category_id" in data
    assert isinstance(data.get("version"), int)


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("retailer_id", "")), "retailer_id must be UUID"
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be UUID"
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be UUID"
    assert isinstance(data.get("sku"), str) and data["sku"]
    assert isinstance(data.get("width_in"), (int, float))
    assert isinstance(data.get("unit_cost_cents"), int)
    assert isinstance(data.get("weekly_demand_units"), int)
    assert data.get("status") in ("CANDIDATE", "LISTED", "DISCONTINUING", "DELISTED")
    assert isinstance(data.get("version"), int)


def assert_planogram(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("variant") in ("BASE", "CLUSTER_A", "CLUSTER_B")
    assert data.get("status") in ("DRAFT", "IN_REVIEW", "APPROVED", "ACTIVE", "SUPERSEDED", "REJECTED")
    assert isinstance(data.get("total_facings"), int)
    assert isinstance(data.get("total_capacity_units"), int)
    assert isinstance(data.get("shelf_utilization_pct"), (int, float))
    assert isinstance(data.get("version"), int)


def assert_planogram_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("planogram_id", "")), "planogram_id must be UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be UUID"
    assert isinstance(data.get("position_index"), int)
    assert isinstance(data.get("facings"), int)
    assert isinstance(data.get("capacity_units"), int)
    assert isinstance(data.get("days_of_supply"), (int, float))
    assert data.get("dos_flag") in ("UNDERSTOCK", "OK", "OVERSTOCK")
    assert isinstance(data.get("version"), int)


def assert_store(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("retailer_id", ""))
    assert isinstance(data.get("store_code"), str) and data["store_code"]
    assert data.get("cluster") in ("BASE", "CLUSTER_A", "CLUSTER_B")
    assert isinstance(data.get("version"), int)


def assert_audit_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be UUID"
    assert is_valid_uuid(data.get("planogram_id", "")), "planogram_id must be UUID"
    assert isinstance(data.get("photo_url"), str) and data["photo_url"]
    assert data.get("status") in ("SUBMITTED", "SCORED", "REJECTED")
    assert isinstance(data.get("version"), int)


def assert_funding_deal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("retailer_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in ("PROPOSED", "APPROVED", "ACTIVE", "CLOSED", "REJECTED")
    assert data.get("coi_flag") in ("NONE", "CAPTAIN_SELF_DEALING", "CAPTAIN_BLOCKING_RIVAL")
    assert isinstance(data.get("version"), int)


def assert_reset_project(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("category_id", ""))
    assert is_valid_uuid(data.get("planogram_id", ""))
    assert is_valid_uuid(data.get("store_id", ""))
    assert data.get("status") in ("PROPOSED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data.get("labor_hours_estimated"), (int, float))
    assert isinstance(data.get("version"), int)


def assert_reset_crew(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("retailer_id", ""))
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("max_concurrent_projects"), int)
    assert isinstance(data.get("version"), int)


def assert_reset_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_valid_uuid(data.get("reset_project_id", ""))
    assert is_valid_uuid(data.get("crew_id", ""))
    assert data.get("status") in ("ASSIGNED", "RELEASED")
    assert isinstance(data.get("version"), int)
