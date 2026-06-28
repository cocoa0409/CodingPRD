"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are exactly as named in the PRD.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["owns_components"], bool)
    assert isinstance(data["version"], int)


def assert_component(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["kind"] in ("INGREDIENT", "PACKAGING", "LABEL")
    assert isinstance(data["allergens"], list)
    assert isinstance(data["customer_owned"], bool)
    assert isinstance(data["version"], int)


def assert_component_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["component_id"])
    assert data["status"] in ("AVAILABLE", "DEPLETED", "QUARANTINED")
    assert float(data["remaining_qty"]) >= 0, "remaining_qty never below 0"


def assert_recipe(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "RETIRED",
    )
    assert isinstance(data["allergen_profile"], list)
    assert isinstance(data["version"], int)


def assert_bom_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["recipe_id"])
    assert is_valid_uuid(data["component_id"])
    assert isinstance(data["version"], int)


def assert_production_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["current_allergen_residue"], list)
    assert isinstance(data["version"], int)


def assert_crew(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int)


def assert_production_run(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in (
        "SCHEDULED", "RUNNING", "PENDING_QA", "RELEASED", "QUARANTINED", "CANCELLED",
    )
    assert isinstance(data["version"], int)


def assert_checkweigh_sample(data: dict):
    """Append-only record: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "CheckweighSample is append-only: no version"
    assert "updated_at" not in data, "CheckweighSample is append-only: no updated_at"
    assert data["verdict"] in ("PASS", "UNDER", "OVER")


def assert_cmr_ledger_entry(data: dict):
    """Append-only record: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "CmrLedgerEntry is append-only: no version"
    assert data["reason"] in ("CONSUME", "SCRAP_WASTE", "RETURN_ON_CANCEL")
