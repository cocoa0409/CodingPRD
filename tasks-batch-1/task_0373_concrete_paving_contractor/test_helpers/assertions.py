"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)

PROJECT_STATES = [
    "DRAFT", "ESTIMATING", "APPROVED", "REJECTED", "SCHEDULED",
    "POURED", "CURING", "COMPLETED", "ON_HOLD",
]


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_project(data: dict):
    assert_common_fields(data)
    assert isinstance(data["site_name"], str)
    assert isinstance(data["client_name"], str)
    assert data["status"] in PROJECT_STATES, f"unexpected status {data['status']}"
    assert isinstance(data["base_contract_amount"], (int, float))
    assert isinstance(data["provisional_contract_value"], (int, float))
    assert isinstance(data["committed_contract_value"], (int, float))
    assert isinstance(data["total_drawn_amount"], (int, float))
    assert isinstance(data["warranty_risk_score"], int)


def assert_project_invariants(data: dict):
    """Invariants that hold after any operation (§2.9, §3.7)."""
    assert 0 <= data["warranty_risk_score"] <= 100, "warranty_risk_score clamps to [0,100]"
    assert data["total_drawn_amount"] >= 0
    assert_cost_precision(data["base_contract_amount"])
    assert_cost_precision(data["provisional_contract_value"])
    assert_cost_precision(data["committed_contract_value"])
    assert_cost_precision(data["total_drawn_amount"])


def assert_segment(data: dict):
    assert_common_fields(data)
    assert data["area_sqft"] > 0, "area_sqft must be > 0"
    assert data["thickness_in"] > 0, "thickness_in must be > 0"
    assert data["finish_grade"] in ["BROOM", "EXPOSED_AGGREGATE", "STAMPED"]
    assert data["reinforcement"] in ["NONE", "MESH", "REBAR"]


def assert_estimate(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED"]
    assert isinstance(data["provisional_cubic_yards"], int)
    assert isinstance(data["estimate_total"], (int, float))
    assert_cost_precision(data["labor_subtotal"])
    assert_cost_precision(data["material_subtotal"])
    assert_cost_precision(data["estimate_total"])


def assert_permit(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["APPLIED", "ISSUED", "CLOSED", "REVOKED"]


def assert_material_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ORDERED", "POURING", "POURED", "CANCELLED"]
    assert data["mix_type"] in ["STANDARD", "HIGH_EARLY", "FIBER"]
    assert isinstance(data["order_cubic_yards"], int)


def assert_weather_reading(data: dict):
    """common_fields:false — only id + created_at; no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "WeatherReading must not carry a version field"
    assert "updated_at" not in data, "WeatherReading must not carry updated_at"


def assert_crew(data: dict):
    assert_common_fields(data)
    assert data["skill"] in ["FLATWORK", "FINISHING", "PAVING"]
    assert data["headcount"] >= 1


def assert_equipment(data: dict):
    assert_common_fields(data)
    assert data["asset_type"] in ["PUMP_TRUCK", "POWER_TROWEL", "SCREED", "MIXER"]


def assert_crew_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["BOOKED", "RELEASED"]


def assert_change_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "REJECTED"]


def assert_draw(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["REQUESTED", "RELEASED", "VOIDED"]
    assert data["draw_type"] in ["DEPOSIT", "PROGRESS", "FINAL"]


def assert_warranty(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "CLAIM_OPEN", "VOID"]
    assert isinstance(data["defect_claims_count"], int)
