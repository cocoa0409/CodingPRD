"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Status value sets, mirroring the lifecycle enumerations in PRD §3.
_PLANT_STATES = {"OPERATING", "MAINTENANCE_SHUTDOWN"}
_TANK_STATES = {"IN_SERVICE", "MAINTENANCE", "QUARANTINED"}
_CYLINDER_STATES = {
    "IN_STOCK", "RESERVED", "FILLED", "ON_RENT", "QUARANTINED", "LOST", "RETIRED",
}
_HYDRO_STATES = {"COMPLIANT", "DUE_SOON", "OVERDUE"}
_LOT_STATES = {
    "PLANNED", "FILLING", "AWAITING_ANALYSIS", "RELEASED", "ANALYSIS_FAILED",
    "RECALLED", "VENTED",
}
_ANALYSIS_RESULTS = {"PASS", "MARGINAL", "FAIL", "PASS_OVERRIDE"}
_ANALYSIS_STATES = {"RECORDED", "OVERRIDDEN"}
_CUSTOMER_STATES = {"ACTIVE", "CREDIT_HOLD"}
_RENTAL_STATES = {"ACTIVE", "OVERDUE", "RECALL_HOLD", "RETURNED", "LOST_SETTLED"}
_DRIVER_STATES = {"QUALIFIED", "SUSPENDED", "CERT_EXPIRED"}
_ROUTE_STATES = {"PLANNED", "DRIVER_ASSIGNED", "DISPATCHED", "COMPLETED", "CANCELLED"}
_INSTALLATION_STATES = {"PROPOSED", "INSTALLED", "ACTIVE", "PAUSED", "DECOMMISSIONED"}
_REPLENISHMENT_STATES = {"PENDING", "DELIVERED", "CANCELLED", "SUPERSEDED"}
_BLEND_STATES = {
    "DRAFT", "APPROVED", "BLENDING", "AWAITING_ANALYSIS", "RELEASED", "REWORK",
}
_BILLING_RUN_STATES = {"DRAFT", "FINALIZED", "POSTED"}
_PRODUCT_CODES = {"O2", "N2", "AR", "CO2", "H2", "HE"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_plant(data: dict):
    _assert_common(data)
    assert isinstance(data["plant_name"], str) and data["plant_name"]
    assert data["status"] in _PLANT_STATES


def assert_tank(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert data["product_code"] in _PRODUCT_CODES
    assert isinstance(data["capacity_liters"], int) and data["capacity_liters"] > 0
    assert isinstance(data["reorder_point_liters"], int)
    assert 0 <= data["reorder_point_liters"] <= data["capacity_liters"]
    assert isinstance(data["current_level_liters"], (int, float))
    assert isinstance(data["reserved_liters"], (int, float))
    assert isinstance(data["drawn_liters"], (int, float))
    assert isinstance(data["low_level_flag"], bool)
    assert data["status"] in _TANK_STATES


def assert_tank_volume_invariants(data: dict):
    """Volume-ledger sanity that must hold after any tank operation (PRD §2.10)."""
    assert data["reserved_liters"] >= 0, "reserved_liters must never go negative"
    assert data["drawn_liters"] >= 0, "drawn_liters must never go negative"
    assert 0 <= data["current_level_liters"] <= data["capacity_liters"]
    assert data["low_level_flag"] == (
        data["current_level_liters"] <= data["reorder_point_liters"]
    ), "low_level_flag must equal current_level_liters <= reorder_point_liters"


def assert_telemetry_reading(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # Append-only record: updated_at and version are absent (PRD §2.5).
    assert "updated_at" not in data, "telemetry readings must not carry updated_at"
    assert "version" not in data, "telemetry readings must not carry version"
    assert isinstance(data["measured_level_liters"], (int, float))
    assert data["source"] in {
        "IOT_SENSOR", "MANUAL_DIP", "INITIAL_LOAD", "SYSTEM_REPLENISHMENT",
    }
    assert (data.get("tank_id") is None) != (data.get("installation_id") is None), (
        "exactly one of tank_id / installation_id must be set"
    )


def assert_cylinder(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["size_code"] in {"SMALL", "STANDARD", "LARGE"}
    assert data["service_gas"] in _PRODUCT_CODES
    assert data["water_capacity_liters"] == {"SMALL": 10, "STANDARD": 50, "LARGE": 100}[
        data["size_code"]
    ]
    assert isinstance(data["last_hydro_date"], str)
    assert isinstance(data["hydro_due_date"], str)
    assert data["hydro_status"] in _HYDRO_STATES
    assert data["status"] in _CYLINDER_STATES
    assert "current_fill_lot_id" in data
    assert "last_fill_lot_id" in data


def assert_fill_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tank_id", ""))
    assert data["product_code"] in _PRODUCT_CODES
    assert isinstance(data["target_fill_pressure_bar"], int)
    assert data["target_fill_pressure_bar"] > 0
    assert isinstance(data["draw_estimate_liters"], (int, float))
    assert "draw_actual_liters" in data
    assert data["status"] in _LOT_STATES


def assert_purity_analysis(data: dict):
    _assert_common(data)
    assert data["subject_type"] in {"FILL_LOT", "BLEND_ORDER"}
    assert data["result"] in _ANALYSIS_RESULTS
    assert data["status"] in _ANALYSIS_STATES
    assert isinstance(data["recorded_by_user_id"], str)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert data["billing_variant"] in {"CALENDAR_DAY", "GRACE_PERIOD"}
    assert isinstance(data["free_days"], int) and data["free_days"] >= 0
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert isinstance(data["recall_flag"], bool)
    assert data["status"] in _CUSTOMER_STATES


def assert_rental(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("cylinder_id", ""))
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert isinstance(data["planned_days"], int) and data["planned_days"] > 0
    assert isinstance(data["out_date"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["billed_through_date"], str)
    assert isinstance(data["demurrage_billed_cents"], int)
    assert data["status"] in _RENTAL_STATES


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["driver_name"], str) and data["driver_name"]
    assert data["cdl_class"] in {"A", "B"}
    assert isinstance(data["hazmat_endorsements"], list)
    assert isinstance(data["medical_card_expiry"], str)
    assert data["status"] in _DRIVER_STATES


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["route_date"], str)
    assert isinstance(data["window_start_hour"], int)
    assert 0 <= data["window_start_hour"] <= 23
    assert isinstance(data["window_end_hour"], int)
    assert 1 <= data["window_end_hour"] <= 24
    assert data["window_end_hour"] > data["window_start_hour"]
    assert isinstance(data["stops"], list) and len(data["stops"]) >= 1
    assert "driver_id" in data
    assert data["status"] in _ROUTE_STATES


def assert_installation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["product_code"] in _PRODUCT_CODES
    assert isinstance(data["capacity_liters"], int) and data["capacity_liters"] > 0
    assert isinstance(data["current_level_liters"], (int, float))
    assert isinstance(data["max_order_qty_liters"], int)
    assert data["max_order_qty_liters"] > 0
    assert data["status"] in _INSTALLATION_STATES


def assert_replenishment_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("installation_id", ""))
    assert isinstance(data["scheduled_delivery_at"], str)
    assert isinstance(data["requested_qty_liters"], (int, float))
    assert data["requested_qty_liters"] > 0
    assert data["status"] in _REPLENISHMENT_STATES


def assert_blend_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["batch_qty_liters"], int) and data["batch_qty_liters"] > 0
    assert isinstance(data["components"], list) and len(data["components"]) >= 2
    assert isinstance(data["component_cost_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert data["total_price_cents"] == (
        data["component_cost_cents"] + data["service_fee_cents"]
    ), "total_price_cents must equal component_cost_cents + service_fee_cents"
    assert data["status"] in _BLEND_STATES


def assert_billing_run(data: dict):
    _assert_common(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data.get("charge_lines", []), list)
    assert isinstance(data.get("total_charges_cents", 0), int)
    assert data["status"] in _BILLING_RUN_STATES
