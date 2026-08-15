"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_FIBER_TYPES = {"COTTON", "POLYESTER", "RAYON", "WOOL", "NYLON"}
_FIBER_LOT_STATUSES = {"RECEIVED", "BLENDED", "EXHAUSTED"}
_RECIPE_STATUSES = {"DRAFT", "APPROVED", "REJECTED", "SUPERSEDED"}
_MACHINE_STATUSES = {"ACTIVE", "DOWN", "DECOMMISSIONED"}
_YARN_LOT_STATUSES = {"GREIGE", "DYEING", "FINISHED", "ALLOCATED", "REJECTED"}
_ASSIGNMENT_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
_DYE_LOT_STATUSES = {"SUBMITTED", "DYEING", "SHADE_PENDING", "APPROVED", "REJECTED"}
_SHADE_BAND_STATUSES = {"ACTIVE", "ARCHIVED"}
_LAB_DIP_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
_GRADES = {"FIRST_QUALITY", "SECOND_QUALITY", "REJECTED"}
_ROLL_STATUSES = {"AVAILABLE", "ALLOCATED", "SHIPPED", "CLOSE_OUT"}
_ORDER_STATUSES = {
    "OPEN", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED", "SHIPPED", "CANCELLED",
}


def _assert_common_fields(data: dict):
    """PRD §2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_fiber_lot(data: dict):
    _assert_common_fields(data)
    assert data["fiber_type"] in _FIBER_TYPES
    assert data["received_weight_lbs"] > 0
    assert data["unit_cost_per_lb"] >= 0
    # PRD §3.1: available weight can never fall below zero nor exceed received.
    assert 0 <= data["available_weight_lbs"] <= data["received_weight_lbs"]
    assert data["status"] in _FIBER_LOT_STATUSES


def assert_blend_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["recipe_code"], str) and len(data["recipe_code"]) > 0
    assert data["target_yarn_count_ne"] > 0
    assert data["status"] in _RECIPE_STATUSES
    assert "total_component_weight_lbs" in data
    # approved_at is null until the recipe is approved (PRD §3.1).
    if data["status"] == "APPROVED":
        assert data.get("approved_at") is not None
        assert data.get("projected_cost_per_lb") is not None


def assert_blend_component(data: dict):
    """Components carry ONLY id + created_at as system fields (PRD §2.4):
    updated_at and version are absent from the resource entirely."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "blend components must not carry updated_at"
    assert "version" not in data, "blend components must not carry version"
    assert data["component_weight_lbs"] > 0
    assert "proportion_pct" in data


def assert_spinning_machine(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_code"], str) and len(data["machine_code"]) > 0
    assert data["supported_count_min_ne"] > 0
    assert data["supported_count_max_ne"] > data["supported_count_min_ne"]
    assert data["status"] in _MACHINE_STATUSES


def assert_yarn_lot(data: dict):
    _assert_common_fields(data)
    assert data["spun_weight_lbs"] > 0
    assert data["actual_yarn_count_ne"] > 0
    assert data["greige_yards_available"] >= 0
    assert data["status"] in _YARN_LOT_STATUSES


def assert_machine_assignment(data: dict):
    _assert_common_fields(data)
    assert data["window_end"] > data["window_start"]
    assert data["status"] in _ASSIGNMENT_STATUSES


def assert_dye_lot(data: dict):
    _assert_common_fields(data)
    assert data["requested_yards"] > 0
    assert isinstance(data["vat_id"], str) and len(data["vat_id"]) > 0
    assert data["status"] in _DYE_LOT_STATUSES


def assert_shade_band(data: dict):
    _assert_common_fields(data)
    assert data["delta_e_tolerance"] > 0
    assert data["status"] in _SHADE_BAND_STATUSES


def assert_lab_dip(data: dict):
    _assert_common_fields(data)
    assert data["measured_delta_e"] >= 0
    assert data["status"] in _LAB_DIP_STATUSES


def assert_quality_test(data: dict):
    _assert_common_fields(data)
    assert 0 <= data["shrinkage_pct_provisional"] <= 100
    assert data["hand_score"] in (1, 2, 3, 4, 5)
    assert data["grade"] in _GRADES


def assert_finished_roll(data: dict):
    _assert_common_fields(data)
    assert data["put_up_yards"] > 0
    assert data["actual_yards"] > 0
    assert "yardage_deviation_pct" in data
    assert isinstance(data["is_second_quality"], bool)
    assert data["status"] in _ROLL_STATUSES


def assert_customer_order(data: dict):
    _assert_common_fields(data)
    assert data["requested_yards"] > 0
    assert data["allocated_yards"] >= 0
    assert 0 <= data["yardage_tolerance_pct"] <= 10
    assert data["status"] in _ORDER_STATUSES


def assert_fiber_weight_conservation(fiber_lot: dict, consumed_lbs: float):
    """Domain invariant: received == available + consumed (PRD §3.1)."""
    assert fiber_lot["received_weight_lbs"] == (
        fiber_lot["available_weight_lbs"] + consumed_lbs
    ), (
        f"Weight not conserved: received={fiber_lot['received_weight_lbs']}, "
        f"available={fiber_lot['available_weight_lbs']}, consumed={consumed_lbs}"
    )
