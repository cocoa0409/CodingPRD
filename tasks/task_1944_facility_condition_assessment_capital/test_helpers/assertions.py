"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import SYSTEM_CATEGORIES


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer: {data.get('version')!r}"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str)
    assert isinstance(data["gross_square_feet"], int)
    assert data["gross_square_feet"] > 0
    assert isinstance(data["current_replacement_value_cents"], int)
    assert data["current_replacement_value_cents"] >= 0
    assert isinstance(data["backlog_cost_cents"], int)
    assert data["backlog_cost_cents"] >= 0
    assert isinstance(data["facility_condition_index"], (int, float))
    assert data["facility_condition_index"] >= 0
    assert isinstance(data["assessment_epoch"], int)
    assert data["assessment_epoch"] >= 0


def assert_asset_system(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["system_category"] in SYSTEM_CATEGORIES
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["install_year"], int)
    assert 1900 <= data["install_year"] <= 2100
    assert isinstance(data["design_life_years"], int)
    assert data["design_life_years"] > 0
    assert isinstance(data["replacement_cost_cents"], int)
    assert data["replacement_cost_cents"] >= 0
    assert isinstance(data["condition_rating"], int)
    assert 1 <= data["condition_rating"] <= 5
    assert isinstance(data["remaining_useful_life_years"], int)
    assert data["remaining_useful_life_years"] >= 0
    assert data["status"] in ("ACTIVE", "REASSESSED", "RETIRED")
    assert isinstance(data["last_assessed_epoch"], int)
    assert data["last_assessed_epoch"] >= 0


def assert_deficiency(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("asset_system_id", ""))
    assert isinstance(data["description"], str)
    assert isinstance(data["cost_estimate_cents"], int)
    assert data["cost_estimate_cents"] > 0
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    assert isinstance(data["urgency"], int) and 1 <= data["urgency"] <= 5
    assert isinstance(data["is_code_violation"], bool)
    assert isinstance(data["is_accessibility_violation"], bool)
    assert isinstance(data["recommended_year"], int)
    assert isinstance(data["priority_score"], (int, float))
    assert data["remediation_status"] in (
        "OPEN", "IN_PROGRESS", "CORRECTED", "DEFERRED")
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "REJECTED")


def assert_capital_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["start_year"], int)
    assert isinstance(data["horizon_years"], int)
    assert 1 <= data["horizon_years"] <= 10
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "ARCHIVED")
    assert isinstance(data["total_programmed_cents"], int)
    assert data["total_programmed_cents"] >= 0


def assert_funding_scenario(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("capital_plan_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["annual_budget_cents"], int)
    assert data["annual_budget_cents"] > 0
    assert isinstance(data["escalation_rate"], (int, float))
    assert 0 <= data["escalation_rate"] <= 0.25
    assert data["status"] in ("CONFIGURED", "RUN", "SUPERSEDED")


def assert_plan_line_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("capital_plan_id", ""))
    assert is_valid_uuid(data.get("deficiency_id", ""))
    assert is_valid_uuid(data.get("funding_scenario_id", ""))
    assert isinstance(data["planned_year"], int)
    assert isinstance(data["escalated_cost_cents"], int)
    assert data["escalated_cost_cents"] >= 0
    assert data["funding_status"] in ("FUNDED", "UNFUNDED", "REMOVED")
    assert data.get("project_bundle_id") is None or \
        is_valid_uuid(data["project_bundle_id"])


def assert_project_bundle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("capital_plan_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["phase_number"], int)
    assert data["phase_number"] >= 1
    assert isinstance(data["bundled_cost_cents"], int)
    assert data["bundled_cost_cents"] >= 0


def assert_refresh_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["epoch"], int) and data["epoch"] >= 1
    assert data["status"] in ("OPEN", "CLOSED")
    assert is_iso8601_timestamp(data.get("opened_at", "")), \
        f"opened_at must be ISO 8601: {data.get('opened_at')!r}"


def assert_condition_snapshot(data: dict):
    """Append-only audit record: carries id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert "updated_at" not in data, "ConditionSnapshot must not expose updated_at"
    assert "version" not in data, "ConditionSnapshot must not expose version"
    assert is_valid_uuid(data.get("asset_system_id", ""))
    assert isinstance(data["condition_rating"], int)
    assert 1 <= data["condition_rating"] <= 5
    assert isinstance(data["remaining_useful_life_years"], int)
    assert isinstance(data["epoch"], int) and data["epoch"] >= 1


def assert_refresh_health(data: dict):
    assert data["health"] in ("NO_DATA", "STALE", "CRITICAL", "WATCH", "GOOD")
    assert isinstance(data["stale_systems"], int) and data["stale_systems"] >= 0
    assert isinstance(data["total_systems"], int) and data["total_systems"] >= 0
    assert isinstance(data["stressed_backlog_cents"], int)
    assert data["stressed_backlog_cents"] >= 0


def assert_facility_invariants(data: dict):
    """Facility aggregate invariants that must hold after any operation."""
    assert_facility(data)
    assert data["backlog_cost_cents"] >= 0
    assert data["current_replacement_value_cents"] >= 0
    if data["current_replacement_value_cents"] == 0:
        assert data["facility_condition_index"] == 0, \
            "FCI is defined as 0 when the facility has no live systems"
