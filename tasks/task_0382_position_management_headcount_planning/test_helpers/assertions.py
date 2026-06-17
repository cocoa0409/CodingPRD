"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_EMPLOYEE_STATUSES = ["AVAILABLE", "ASSIGNED"]
_POSITION_LIFECYCLE = ["DRAFT", "REQUISITIONED", "FUNDED", "FROZEN", "ABOLISHED"]
_POSITION_OCCUPANCY = ["VACANT", "FILLED"]
_POSTURE = ["OPEN", "FROZEN"]
_INCUMBENT_STATUSES = ["ACTIVE", "VACATED"]
_FREEZE_STATUSES = ["ACTIVE", "LIFTED"]
_REQ_TYPES = ["NEW_HIRE", "BACKFILL"]
_REQ_STATUSES = ["OPEN", "SUSPENDED", "APPROVED", "CLOSED", "CANCELLED"]
_RECLASS_DIRECTIONS = ["UPGRADE", "DOWNGRADE", "LATERAL"]
_RECLASS_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"]
_FORECAST_STATUSES = ["DRAFT", "SNAPSHOTTED"]


def _assert_full_triple(data: dict):
    """common_fields:true entities carry id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be int >= 1"


def _assert_config_pair(data: dict):
    """common_fields:false entities carry ONLY id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_employee(data: dict):
    _assert_full_triple(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["annual_salary_cents"], int) and data["annual_salary_cents"] >= 0
    assert data["status"] in _EMPLOYEE_STATUSES, f"bad employee status {data['status']}"


def assert_grade(data: dict):
    _assert_config_pair(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    for f in ("band_min_cents", "band_mid_cents", "band_max_cents", "rank"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["band_mid_cents"] >= data["band_min_cents"], "mid >= min"
    assert data["band_max_cents"] >= data["band_mid_cents"], "max >= mid"
    assert data["rank"] >= 1, "rank >= 1"
    # Immutable config: must NOT carry updated_at/version.
    assert "version" not in data, "Grade is immutable config — must not carry version"
    assert "updated_at" not in data, "Grade is immutable config — must not carry updated_at"


def assert_cost_center(data: dict):
    _assert_full_triple(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    for f in ("annual_budget_cents", "adjusted_budget_cents", "committed_cost_cents",
              "available_budget_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    for f in ("fte_cap", "committed_fte", "filled_fte"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric FTE"
    assert data["posture"] in _POSTURE, f"bad posture {data['posture']}"


def assert_cost_center_invariants(data: dict):
    """Derived-field invariants that must hold after any operation (PRD §2.8)."""
    # available_budget_cents = adjusted_budget_cents - committed_cost_cents.
    assert data["available_budget_cents"] == data["adjusted_budget_cents"] - data["committed_cost_cents"], \
        "available_budget_cents must equal adjusted_budget_cents - committed_cost_cents"
    assert data["committed_fte"] >= 0, "committed_fte must be non-negative"
    assert data["filled_fte"] >= 0, "filled_fte must be non-negative"


def assert_position(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("cost_center_id", "")), "cost_center_id must be UUID"
    assert is_valid_uuid(data.get("grade_id", "")), "grade_id must be UUID"
    assert data["manager_position_id"] is None or is_valid_uuid(data["manager_position_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["fte"], (int, float)) and 0 < data["fte"] <= 1.0
    assert data["lifecycle_status"] in _POSITION_LIFECYCLE, f"bad lifecycle {data['lifecycle_status']}"
    assert data["occupancy_status"] in _POSITION_OCCUPANCY, f"bad occupancy {data['occupancy_status']}"
    assert isinstance(data["span_of_control"], int) and data["span_of_control"] >= 0
    assert isinstance(data["planned_cost_cents"], int)
    assert isinstance(data["actual_cost_cents"], int)


def assert_incumbent(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("position_id", "")), "position_id must be UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be UUID"
    assert data["status"] in _INCUMBENT_STATUSES, f"bad incumbent status {data['status']}"


def assert_freeze_order(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("cost_center_id", "")), "cost_center_id must be UUID"
    assert isinstance(data["reason"], str)
    assert data["status"] in _FREEZE_STATUSES, f"bad freeze status {data['status']}"


def assert_requisition(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("position_id", "")), "position_id must be UUID"
    assert data["req_type"] in _REQ_TYPES, f"bad req_type {data['req_type']}"
    assert data["status"] in _REQ_STATUSES, f"bad requisition status {data['status']}"


def assert_reclass_request(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("position_id", "")), "position_id must be UUID"
    assert is_valid_uuid(data.get("target_grade_id", "")), "target_grade_id must be UUID"
    assert isinstance(data["from_grade_rank"], int)
    assert isinstance(data["target_grade_rank"], int)
    assert data["direction"] in _RECLASS_DIRECTIONS, f"bad direction {data['direction']}"
    assert data["status"] in _RECLASS_STATUSES, f"bad reclass status {data['status']}"


def assert_forecast_period(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("cost_center_id", "")), "cost_center_id must be UUID"
    assert isinstance(data["fiscal_label"], str) and len(data["fiscal_label"]) > 0
    assert isinstance(data["planned_fte"], (int, float))
    assert data["status"] in _FORECAST_STATUSES, f"bad forecast status {data['status']}"


def assert_budget_adjustment(data: dict):
    _assert_config_pair(data)
    assert is_valid_uuid(data.get("cost_center_id", "")), "cost_center_id must be UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["status"] == "APPLIED", "budget adjustment is born APPLIED"
    # Append-only event: must NOT carry updated_at/version.
    assert "version" not in data, "BudgetAdjustment is append-only — must not carry version"
    assert "updated_at" not in data, "BudgetAdjustment is append-only — must not carry updated_at"
