"""Domain assertion helpers for the fire protection hydraulic design API."""
from typing import Any, Dict, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CLOCK_DEFAULT_UTC

# --------------------------------------------------------------------------
# Common field shapes
# --------------------------------------------------------------------------


def assert_identity_fields(row: Dict[str, Any]) -> None:
    """Every resource carries a server-minted UUID id and a created_at stamp."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]


def assert_versioned_row(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Most resources additionally carry updated_at and an integer version."""
    assert_identity_fields(row)
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int)
    assert row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_row(row: Dict[str, Any]) -> None:
    """Append-only rows carry only id and created_at: no updated_at, no version."""
    assert_identity_fields(row)
    assert "updated_at" not in row, "append-only row exposed updated_at"
    assert "version" not in row, "append-only row exposed version"


def assert_money(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=0.005)


def assert_flow(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=0.05)


def assert_pressure(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=0.005)


def assert_density(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=0.0005)


def assert_percentage(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=0.05)


def assert_clock_default(value: Any) -> None:
    """The logical clock reads 2026-08-01T00:00:00Z at startup."""
    assert value is not None
    assert str(value).startswith("2026-08-01T00:00:00"), value
    assert str(CLOCK_DEFAULT_UTC).startswith("2026-08-01T00:00:00")


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------


def assert_engineer_shape(row: Dict[str, Any]) -> None:
    assert_append_only_row(row)
    for field in ("full_name", "license_state", "license_number", "license_status", "discipline"):
        assert field in row, f"engineer is missing {field}"
    assert len(row["license_state"]) == 2
    assert row["license_state"].isupper()


def assert_ahj_reviewer_shape(row: Dict[str, Any]) -> None:
    assert_append_only_row(row)
    for field in ("full_name", "jurisdiction_code", "discipline"):
        assert field in row, f"reviewer is missing {field}"


def assert_flow_test_shape(row: Dict[str, Any]) -> None:
    assert_append_only_row(row)
    for field in ("project_id", "hydrant_tag", "static_psi", "residual_psi", "flow_gpm", "tested_at"):
        assert field in row, f"flow test is missing {field}"
    assert row["residual_psi"] < row["static_psi"]


def assert_iteration_shape(row: Dict[str, Any]) -> None:
    assert_append_only_row(row)
    for field in (
        "iteration_index",
        "pipe_size_in",
        "length_ft",
        "fitting_equivalent_ft",
        "flow_gpm",
        "elevation_change_ft",
        "friction_loss_psi",
        "elevation_loss_psi",
        "velocity_fps",
        "cumulative_psi_after",
        "in_active_chain",
        "is_supply_connection",
    ):
        assert field in row, f"iteration is missing {field}"


def assert_project_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_number",
        "building_name",
        "jurisdiction_code",
        "jurisdiction_state",
        "occupancy_type",
        "building_height_ft",
        "underground_lead_in_loss_psi",
        "lead_engineer_id",
        "ahj_reviewer_id",
        "status",
        "design_posture",
        "governing_hydraulic_calculation_id",
        "governing_demand_gpm",
        "auxiliary_demand_gpm",
        "total_system_demand_gpm",
        "sealed_calculation_count",
        "open_major_comment_count",
        "submittal_cycle_count",
        "review_fee_balance_usd",
        "pump_required_flag",
    ):
        assert field in row, f"project is missing {field}"


def assert_hazard_area_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "label",
        "hazard_class",
        "commodity_class",
        "storage_height_ft",
        "ceiling_height_ft",
        "area_sqft",
        "sprinkler_system_type",
        "ceiling_slope_pct",
        "effective_hazard_class",
        "design_density",
        "design_area_sqft",
        "hose_allowance_gpm",
        "reclassification_count",
    ):
        assert field in row, f"hazard area is missing {field}"


def assert_calculation_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "hazard_area_id",
        "method",
        "k_factor",
        "authored_by_engineer_id",
        "state",
        "design_flow_gpm",
        "hose_allowance_gpm",
        "room_design_penalty_gpm",
        "hazard_total_demand_gpm",
        "chain_start_index",
        "iteration_count",
        "end_head_psi",
        "required_psi_at_base_of_riser",
    ):
        assert field in row, f"calculation is missing {field}"


def assert_evaluation_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "flow_test_id",
        "governing_hydraulic_calculation_id",
        "evaluation_basis",
        "basis_static_psi",
        "basis_residual_psi",
        "basis_test_flow_gpm",
        "design_demand_gpm",
        "required_psi_at_demand",
        "available_psi_at_demand",
        "safety_margin_psi",
        "safety_margin_pct",
        "margin_verdict",
        "pinned_calculation_iteration_count",
        "pump_sized",
        "state",
    ):
        assert field in row, f"evaluation is missing {field}"


def assert_fire_pump_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "water_supply_evaluation_id",
        "model_tag",
        "rated_flow_gpm",
        "suction_psi_at_rated",
        "required_discharge_psi",
        "rated_pressure_psi",
        "churn_discharge_psi",
        "flow_150_pct_gpm",
        "suction_psi_at_150_pct",
        "available_psi_at_150_pct",
        "sizing_verdict",
        "state",
    ):
        assert field in row, f"fire pump is missing {field}"
    assert row["rated_pressure_psi"] % 5 == 0
    assert row["rated_pressure_psi"] >= 40


def assert_auxiliary_system_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "label",
        "system_type",
        "agent_type",
        "demand_gpm",
        "interlock_required",
        "interlock_verified",
        "status",
        "outage_start_at",
        "outage_end_at",
    ):
        assert field in row, f"auxiliary system is missing {field}"


def assert_shop_drawing_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "hydraulic_calculation_id",
        "sheet_number",
        "state",
        "required_trade_count",
        "cleared_trade_count",
    ):
        assert field in row, f"shop drawing is missing {field}"


def assert_trade_clearance_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "shop_drawing_id",
        "trade",
        "elevation_low_in",
        "elevation_high_in",
        "state",
        "conflict_severity",
        "note",
    ):
        assert field in row, f"trade clearance is missing {field}"
    assert row["elevation_high_in"] > row["elevation_low_in"]


def assert_submittal_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "included_calculation_ids",
        "cycle_number",
        "submitted_at",
        "state",
        "review_fee_usd",
        "open_comment_count",
        "major_comment_count",
        "reviewed_by_ahj_reviewer_id",
        "supersedes_submittal_id",
    ):
        assert field in row, f"submittal is missing {field}"


def assert_review_comment_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "submittal_id",
        "code_section",
        "severity",
        "description",
        "assigned_engineer_id",
        "raised_by_ahj_reviewer_id",
        "state",
        "response_note",
        "close_note",
        "disposition",
    ):
        assert field in row, f"review comment is missing {field}"


def assert_acceptance_test_shape(row: Dict[str, Any]) -> None:
    assert_versioned_row(row)
    for field in (
        "project_id",
        "test_type",
        "required_flow_gpm",
        "required_residual_psi",
        "witness_status",
        "documentation_status",
        "retest_count",
        "witness_reviewer_id",
        "measured_flow_gpm",
        "measured_residual_psi",
        "witness_window_start",
        "witness_window_end",
        "as_built_document_ref",
    ):
        assert field in row, f"acceptance test is missing {field}"


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------


def assert_demand_ledger(
    project: Dict[str, Any],
    governing_calculation_id: Optional[str],
    governing_demand_gpm: float,
    auxiliary_demand_gpm: float,
    total_system_demand_gpm: float,
) -> None:
    """total_system_demand_gpm is governing_demand_gpm plus auxiliary_demand_gpm."""
    assert project["governing_hydraulic_calculation_id"] == governing_calculation_id
    assert_flow(project["governing_demand_gpm"], governing_demand_gpm)
    assert_flow(project["auxiliary_demand_gpm"], auxiliary_demand_gpm)
    assert_flow(project["total_system_demand_gpm"], total_system_demand_gpm)


def assert_empty_ledger(project: Dict[str, Any]) -> None:
    """When the eligible set is empty the governing id is null and the demand is 0.0."""
    assert project["governing_hydraulic_calculation_id"] is None
    assert_flow(project["governing_demand_gpm"], 0.0)


def assert_posture(project: Dict[str, Any], expected: str) -> None:
    """The posture is derived from status and open_major_comment_count, never supplied."""
    assert project["design_posture"] == expected, (
        f"expected posture {expected}, got {project['design_posture']} "
        f"(status={project['status']}, "
        f"open_major_comment_count={project['open_major_comment_count']})"
    )


def assert_posture_derivation(project: Dict[str, Any]) -> None:
    if project["status"] in ("CORRECTIVE_ACTION", "CLOSED_OUT"):
        expected = "FROZEN"
    elif project["open_major_comment_count"] > 0:
        expected = "GATED"
    else:
        expected = "OPEN"
    assert_posture(project, expected)


def assert_calculation_demand_snapshot(
    calculation: Dict[str, Any],
    design_flow_gpm: float,
    hose_allowance_gpm: float,
    hazard_total_demand_gpm: float,
    room_design_penalty_gpm: float = 0.0,
) -> None:
    assert_flow(calculation["design_flow_gpm"], design_flow_gpm)
    assert_flow(calculation["hose_allowance_gpm"], hose_allowance_gpm)
    assert_flow(calculation["room_design_penalty_gpm"], room_design_penalty_gpm)
    assert_flow(calculation["hazard_total_demand_gpm"], hazard_total_demand_gpm)


def assert_classification(
    hazard_area: Dict[str, Any],
    effective_hazard_class: str,
    design_density: float,
    design_area_sqft: float,
    hose_allowance_gpm: float,
) -> None:
    assert hazard_area["effective_hazard_class"] == effective_hazard_class
    assert_density(hazard_area["design_density"], design_density)
    assert hazard_area["design_area_sqft"] == pytest.approx(design_area_sqft, abs=0.5)
    assert_flow(hazard_area["hose_allowance_gpm"], hose_allowance_gpm)


def assert_margin(
    evaluation: Dict[str, Any],
    available_psi_at_demand: float,
    safety_margin_psi: float,
    safety_margin_pct: float,
    margin_verdict: str,
) -> None:
    assert_pressure(evaluation["available_psi_at_demand"], available_psi_at_demand)
    assert_pressure(evaluation["safety_margin_psi"], safety_margin_psi)
    assert_percentage(evaluation["safety_margin_pct"], safety_margin_pct)
    assert evaluation["margin_verdict"] == margin_verdict


def assert_sheet_counters(
    shop_drawing: Dict[str, Any], state: str, cleared_trade_count: int
) -> None:
    assert shop_drawing["state"] == state
    assert shop_drawing["required_trade_count"] == 3
    assert shop_drawing["cleared_trade_count"] == cleared_trade_count


def assert_seal_metadata_cleared(calculation: Dict[str, Any]) -> None:
    assert calculation["sealed_by_engineer_id"] is None
    assert calculation["sealed_at"] is None


def assert_reopened(calculation: Dict[str, Any], stale_reason: str) -> None:
    assert calculation["state"] == "REOPENED"
    assert calculation["stale_reason"] == stale_reason
