"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _as_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected: str, label="timestamp"):
    """Compare a stored audit timestamp against the logical-clock instant it
    was stamped from, so that the three fractional digits every stored
    timestamp carries do not change the comparison."""
    assert actual is not None, f"{label} must be stamped"
    assert _as_instant(actual) == _as_instant(expected), (
        f"{label} should record the instant {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Shared audit-field helpers (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_versioned_row(data: dict):
    """Most rows expose id, created_at, updated_at, and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version begins at 1, got {data['version']}"


def assert_append_only_row(data: dict):
    """Leak tests and run tests hold only id and created_at alongside their
    own fields — neither updated_at nor version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert (
        "updated_at" not in data
    ), "an append-only record must not carry updated_at"
    assert "version" not in data, "an append-only record must not carry version"


def assert_two_decimals(value, label="value"):
    assert value is not None, f"{label} must be present"
    scaled = round(float(value) * 100)
    assert abs(float(value) * 100 - scaled) < 1e-6, (
        f"{label} must carry two decimal places, got {value}"
    )


def assert_four_decimals(value, label="value"):
    assert value is not None, f"{label} must be present"
    scaled = round(float(value) * 10000)
    assert abs(float(value) * 10000 - scaled) < 1e-6, (
        f"{label} must carry four decimal places, got {value}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_refrigerant_program(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["refrigerant_code"], str) and 1 <= len(
        data["refrigerant_code"]
    ) <= 32
    assert isinstance(data["gwp"], int) and data["gwp"] >= 1
    assert data["flammability_class"] in ("A1", "A2L")
    assert is_iso8601_timestamp(data["manufacture_cutoff_utc"])
    assert is_iso8601_timestamp(data["sell_through_deadline_utc"])
    assert data["sell_through_deadline_utc"] > data["manufacture_cutoff_utc"], (
        "sell_through_deadline_utc must fall strictly after manufacture_cutoff_utc"
    )
    assert data["status"] in ("ACTIVE", "SELL_THROUGH", "EXPIRED")
    assert isinstance(data["affected_platform_count"], int)
    assert data["affected_platform_count"] >= 0


def assert_regional_standard(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["region_code"], str) and 1 <= len(data["region_code"]) <= 32
    for field in ("min_seer2_standard", "min_seer2_high", "min_seer2_premium"):
        assert float(data[field]) > 0, f"{field} must be greater than zero"
        assert_two_decimals(data[field], field)
    assert isinstance(data["prohibits_flammable_refrigerant"], bool)
    assert is_iso8601_timestamp(data["effective_from_utc"])
    assert data["status"] == "ACTIVE", "a published standard is only ever ACTIVE"


def assert_product_platform(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["model_code"], str) and 1 <= len(data["model_code"]) <= 32
    assert data["efficiency_tier"] in ("STANDARD", "HIGH", "PREMIUM")
    assert is_valid_uuid(data["refrigerant_program_id"])
    assert isinstance(data["rated_capacity_btuh"], int)
    assert data["rated_capacity_btuh"] >= 6000
    assert float(data["rated_eer"]) > 0
    assert_two_decimals(data["rated_eer"], "rated_eer")
    assert float(data["rated_seer2"]) > 0
    assert_two_decimals(data["rated_seer2"], "rated_seer2")
    assert isinstance(data["compressor_part_number"], str)
    assert isinstance(data["control_board_part_number"], str)
    assert data["status"] in ("DRAFT", "ENG_REVIEW", "RELEASED", "RESTRICTED", "RETIRED")
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["blocked_region_codes"], list)
    assert data["blocked_region_codes"] == sorted(
        data["blocked_region_codes"]
    ), "blocked_region_codes is sorted ascending"
    assert len(data["blocked_region_codes"]) == len(
        set(data["blocked_region_codes"])
    ), "a region blocked by several conditions appears exactly once"
    assert isinstance(data["salable_region_count"], int)
    assert data["salable_region_count"] >= 0
    assert data["warranty_posture"] in ("OK", "CAPA_REQUIRED", "DESIGN_CHANGE_REQUIRED")
    assert_two_decimals(data["rolling_claim_rate_pct"], "rolling_claim_rate_pct")
    assert isinstance(data["units_built_released"], int)
    assert data["units_built_released"] >= 0
    assert isinstance(data["units_shipped_total"], int)
    assert data["units_shipped_total"] >= 0


def assert_certification_record(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["platform_id"])
    assert isinstance(data["region_code"], str)
    assert float(data["rated_seer2_submitted"]) > 0
    assert_two_decimals(data["rated_seer2_submitted"], "rated_seer2_submitted")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "CERTIFIED",
        "REJECTED",
        "SUPERSEDED",
        "WITHDRAWN",
    )


def assert_component_supply(data: dict):
    assert_versioned_row(data)
    assert data["component_type"] in ("COMPRESSOR", "CONTROL_BOARD")
    assert isinstance(data["part_number"], str)
    assert isinstance(data["supplier_lot_code"], str)
    assert isinstance(data["supply_month"], str) and len(data["supply_month"]) == 7
    assert isinstance(data["total_allocatable_units"], int)
    assert data["total_allocatable_units"] >= 1
    assert data["allocation_policy"] in ("PRIORITY_WATERFALL", "DEMAND_PRORATA")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "DERATED", "CLOSED")
    assert data["derate_pct"] in (0, 25, 50, 100), (
        f"only four cut values are ever stored, got {data['derate_pct']}"
    )
    assert_supply_conservation(data)


def assert_allocation_line(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["distributor_order_id"])
    assert is_valid_uuid(data["component_supply_id"])
    assert data["component_type"] in ("COMPRESSOR", "CONTROL_BOARD")
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["status"] in ("RESERVED", "COMMITTED", "REVOKED", "RELEASED")


def assert_distributor_order(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["distributor_code"], str)
    assert is_valid_uuid(data["platform_id"])
    assert isinstance(data["region_code"], str)
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert 1 <= data["priority_score"] <= 100
    assert isinstance(data["requested_delivery_month"], str)
    assert data["allocation_status"] in (
        "UNALLOCATED",
        "PARTIALLY_ALLOCATED",
        "FULLY_ALLOCATED",
    )
    assert data["fulfillment_status"] in ("PENDING", "STAGED", "SHIPPED", "CANCELLED")
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert isinstance(data["shipped_units"], int) and data["shipped_units"] >= 0
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_warehouse(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["pallet_capacity"], int) and data["pallet_capacity"] >= 1
    assert isinstance(data["pallets_reserved_current"], int)
    assert data["pallets_reserved_current"] >= 0


def assert_warehouse_reservation(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["warehouse_id"])
    assert is_valid_uuid(data["build_order_id"])
    assert isinstance(data["start_date"], str) and len(data["start_date"]) == 10
    assert isinstance(data["end_date"], str) and len(data["end_date"]) == 10
    assert data["end_date"] > data["start_date"], (
        "end_date must fall strictly after start_date"
    )
    assert isinstance(data["pallet_units"], int) and data["pallet_units"] >= 1
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_test_cell(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["cell_code"], str) and 1 <= len(data["cell_code"]) <= 32
    assert isinstance(data["cooldown_minutes"], int)
    assert 0 <= data["cooldown_minutes"] <= 240
    assert data["status"] == "ACTIVE", "cells are never retired in this scope"


def assert_build_order(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["platform_id"])
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert isinstance(data["is_preseason"], bool)
    assert data["status"] in (
        "DRAFT",
        "COIL_FAB",
        "BRAZED",
        "REWORK",
        "LEAK_PASSED",
        "CHARGED",
        "RUN_PASSED",
        "RELEASED_TO_STOCK",
        "SCRAPPED",
        "CANCELLED",
        "HOLD_REGULATORY",
    )
    assert isinstance(data["rework_count"], int) and 0 <= data["rework_count"] <= 3
    assert isinstance(data["charge_grams"], int) and data["charge_grams"] >= 0
    assert data["latest_leak_verdict"] in (None, "PASS", "FAIL")
    assert data["latest_run_verdict"] in (None, "PASS", "FAIL")


def assert_leak_test(data: dict):
    assert_append_only_row(data)
    assert is_valid_uuid(data["build_order_id"])
    assert data["method"] in ("HELIUM_MASS_SPEC", "PRESSURE_DECAY")
    assert data["verdict"] in ("PASS", "FAIL")
    assert data["applied_limit"] is not None
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    assert is_iso8601_timestamp(data["performed_at"])
    if data["method"] == "HELIUM_MASS_SPEC":
        assert data["measured_leak_rate_g_per_year"] is not None
    else:
        assert data["decay_kpa"] is not None
        assert data["hold_minutes"] is not None


def assert_run_test(data: dict):
    assert_append_only_row(data)
    assert is_valid_uuid(data["build_order_id"])
    assert is_valid_uuid(data["test_cell_id"])
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["window_end_utc"] > data["window_start_utc"]
    assert isinstance(data["measured_capacity_btuh"], int)
    assert isinstance(data["measured_power_w"], int) and data["measured_power_w"] >= 1
    assert isinstance(data["corrected_capacity_btuh"], int), (
        "corrected_capacity_btuh is a whole number of BTU per hour"
    )
    assert_four_decimals(data["capacity_ratio"], "capacity_ratio")
    assert_four_decimals(data["efficiency_ratio"], "efficiency_ratio")
    assert data["verdict"] in ("PASS", "FAIL")
    assert float(data["applied_efficiency_tolerance"]) >= 0.90, (
        "applied_efficiency_tolerance is never permitted below 0.90"
    )
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    assert is_iso8601_timestamp(data["performed_at"])


def assert_warranty_claim(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["platform_id"])
    assert data["failure_code"] in (
        "COMPRESSOR_FAILURE",
        "CONTROL_BOARD_FAULT",
        "COIL_LEAK",
        "CHARGE_LOSS",
        "FAN_MOTOR",
    )
    assert isinstance(data["claim_cost_cents"], int) and data["claim_cost_cents"] >= 0
    assert data["component_type"] in (None, "COMPRESSOR", "CONTROL_BOARD")
    assert data["status"] in ("OPEN", "LINKED_TO_CAPA", "CLOSED")
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert is_iso8601_timestamp(data["filed_at"])
    # The two component fields move together.
    has_type = data["component_type"] is not None
    has_lot = data.get("supplier_lot_code") is not None
    assert has_type == has_lot, (
        "component_type and supplier_lot_code move together"
    )


def assert_supplier_corrective_action(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["component_supply_id"])
    assert is_valid_uuid(data["warranty_claim_id"])
    assert data["component_type"] in ("COMPRESSOR", "CONTROL_BOARD")
    assert_two_decimals(data["trigger_claim_rate_pct"], "trigger_claim_rate_pct")
    assert data["derate_pct"] in (25, 50, 100), (
        f"a corrective action's cut is only ever 25, 50, or 100, got {data['derate_pct']}"
    )
    assert isinstance(data["cited_claim_count"], int) and data["cited_claim_count"] >= 1
    assert data["status"] in ("OPEN", "CLOSED_EFFECTIVE", "CLOSED_INEFFECTIVE")
    assert data["resolution"] in (None, "EFFECTIVE", "INEFFECTIVE")


# ---------------------------------------------------------------------------
# Conserved identities (PRD §2.9)
# ---------------------------------------------------------------------------


def assert_supply_conservation(supply: dict):
    """effective_allocatable_units equals available + reserved + committed."""
    effective = supply["effective_allocatable_units"]
    available = supply["available_units"]
    reserved = supply["reserved_units"]
    committed = supply["committed_units"]
    assert available >= 0, (
        f"available_units is never stored as a negative balance, got {available}"
    )
    assert effective == available + reserved + committed, (
        f"conservation broken: effective_allocatable_units {effective} != "
        f"available {available} + reserved {reserved} + committed {committed}"
    )


def assert_effective_units_truncated(supply: dict):
    """effective_allocatable_units truncates the surviving percentage down."""
    total = supply["total_allocatable_units"]
    derate = supply["derate_pct"]
    expected = (total * (100 - derate)) // 100
    assert supply["effective_allocatable_units"] == expected, (
        f"effective_allocatable_units should truncate to {expected} for "
        f"{total} units at a {derate} percent cut, got "
        f"{supply['effective_allocatable_units']}"
    )


def assert_warehouse_pallet_identity(warehouse: dict, active_reservations_on_clock_date):
    """pallets_reserved_current equals the summed pallet_units of the active
    reservations covering the logical clock's date."""
    expected = sum(r["pallet_units"] for r in active_reservations_on_clock_date)
    assert warehouse["pallets_reserved_current"] == expected, (
        f"pallets_reserved_current should be {expected}, got "
        f"{warehouse['pallets_reserved_current']}"
    )


def assert_order_dimensions(order: dict, allocation_status: str, fulfillment_status: str):
    """The two order status fields are independent dimensions."""
    assert order["allocation_status"] == allocation_status, (
        f"allocation_status should be {allocation_status}, got {order['allocation_status']}"
    )
    assert order["fulfillment_status"] == fulfillment_status, (
        f"fulfillment_status should be {fulfillment_status}, "
        f"got {order['fulfillment_status']}"
    )


def assert_list_count(items: list, meta: dict, expected: int, label="rows"):
    assert len(items) == expected, f"expected {expected} {label}, got {len(items)}"
    assert meta["total_count"] == expected, (
        f"total_count should be {expected}, got {meta['total_count']}"
    )
