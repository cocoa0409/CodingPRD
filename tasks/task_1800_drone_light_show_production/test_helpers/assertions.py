"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. The three immutable telemetry record types
(SimulationRun, WeatherReading, FlightLog) are asserted to carry only
id + created_at among the system-managed fields — no updated_at, no
version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Shared field-shape helpers
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict):
    """Standard system-managed properties on every primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """Immutable telemetry rows carry id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable telemetry must not carry updated_at"
    assert "version" not in data, "immutable telemetry must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert -90 <= data["latitude"] <= 90
    assert -180 <= data["longitude"] <= 180
    assert data["ground_length_m"] > 0
    assert data["ground_width_m"] > 0
    assert data["site_max_wind_kt"] > 0
    assert data["site_max_gust_kt"] > 0
    assert data["site_max_altitude_ft"] > 0


def assert_show_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["lifecycle_status"] in [
        "PLANNING", "DESIGN_LOCKED", "AUTHORIZED", "READY", "GO_CERTIFIED",
        "EXECUTED", "POSTPONED", "CANCELLED",
    ]
    assert data["payment_status"] in [
        "DEPOSIT_DUE", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED",
    ]
    assert data["readiness_posture"] in ["NOT_READY", "CLEARED", "GO"]
    assert data["cancellation_status"] in ["NONE", "FILED", "SETTLED", "VOIDED"]
    for field in ("contract_value_cents", "deposit_cents", "balance_cents",
                  "paid_total_cents", "refunded_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["deposit_cents"] + data["balance_cents"] == data["contract_value_cents"], \
        "deposit + balance must equal the contract value"
    assert isinstance(data["drone_count_planned"], int) and data["drone_count_planned"] >= 1
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0
    assert isinstance(data["backup_consumed"], bool)


def assert_airspace_authorization(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("show_event_id", "")), "show_event_id must be a UUID"
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED",
        "DENIED", "REVOKED", "EXPIRED", "WITHDRAWN",
    ]
    assert data["altitude_ceiling_ft"] > 0
    assert isinstance(data["waiver_types"], list)


def assert_show_design(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("show_event_id", "")), "show_event_id must be a UUID"
    assert data["status"] in ["DRAFT", "SIMULATED", "LOCKED", "SUPERSEDED"]
    assert isinstance(data["design_version_no"], int) and data["design_version_no"] >= 1
    assert isinstance(data["drone_count"], int) and data["drone_count"] >= 1
    assert data["max_altitude_ft"] > 0
    assert isinstance(data["duration_sec"], int) and data["duration_sec"] >= 60
    assert data["min_separation_m"] > 0


def assert_simulation_run(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("show_design_id", "")), "show_design_id must be a UUID"
    assert data["verdict"] in ["PASS", "FAIL"]
    assert data["min_separation_observed_m"] >= 0
    assert 0 <= data["battery_draw_pct"] <= 100
    assert data["max_speed_mps"] >= 0


def assert_safety_configuration(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("show_event_id", "")), "show_event_id must be a UUID"
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED"]
    assert data["geofence_radius_m"] > 0
    assert data["altitude_hard_ceiling_ft"] > 0
    assert data["lost_link_action"] in [
        "HOVER_THEN_LAND", "RETURN_TO_HOME", "IMMEDIATE_LAND",
    ]
    assert data["geofence_breach_action"] in ["RETURN_TO_HOME", "IMMEDIATE_LAND"]
    assert 10 <= data["battery_rtl_threshold_pct"] <= 80
    assert isinstance(data.get("created_by_user_id"), str)


def assert_drone(data: dict):
    assert_common_fields(data)
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert isinstance(data["model"], str) and len(data["model"]) > 0
    assert data["status"] in [
        "AVAILABLE", "CHARGING", "RESERVED", "IN_MAINTENANCE",
        "GROUNDED", "RETIRED",
    ]
    assert isinstance(data["charge_pct"], int) and 0 <= data["charge_pct"] <= 100
    assert isinstance(data["battery_cycle_count"], int) and data["battery_cycle_count"] >= 0


def assert_charge_bay(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["bay_code"], str) and len(data["bay_code"]) > 0
    assert isinstance(data["port_count"], int) and data["port_count"] >= 1


def assert_charge_session(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("drone_id", "")), "drone_id must be a UUID"
    assert is_valid_uuid(data.get("charge_bay_id", "")), "charge_bay_id must be a UUID"
    assert data["status"] in ["ACTIVE", "COMPLETED", "INTERRUPTED"]
    assert isinstance(data["charge_from_pct"], int)
    assert is_iso8601_timestamp(data.get("started_at", "")), \
        "started_at must be ISO 8601"


def assert_launch_grid_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("show_event_id", "")), "show_event_id must be a UUID"
    assert is_valid_uuid(data.get("drone_id", "")), "drone_id must be a UUID"
    assert data["status"] in ["ASSIGNED", "VOIDED", "FLOWN", "RECONCILED"]
    assert isinstance(data["grid_row"], int) and data["grid_row"] >= 0
    assert isinstance(data["grid_col"], int) and data["grid_col"] >= 0


def assert_weather_reading(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert data["wind_speed_kt"] >= 0
    assert data["gust_kt"] >= data["wind_speed_kt"], "gust must be >= sustained wind"
    assert data["precip_mm_hr"] >= 0


def assert_go_no_go_evaluation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("show_event_id", "")), "show_event_id must be a UUID"
    assert data["verdict"] in ["GO", "NO_GO"]
    assert data["status"] in ["PROVISIONAL", "CERTIFIED"]
    assert isinstance(data["reason_codes"], list)
    assert isinstance(data["effective_wind_limit_kt"], (int, float))
    assert isinstance(data["effective_gust_limit_kt"], (int, float))
    if data["verdict"] == "GO":
        assert data["reason_codes"] == [], "a GO verdict carries no reason codes"


def assert_incident_report(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("show_event_id", "")), "show_event_id must be a UUID"
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["source"] in ["MANUAL", "AUTO_DEVIATION"]
    assert data["status"] in [
        "FILED", "UNDER_INVESTIGATION", "CLOSED_CONFIRMED", "CLOSED_REJECTED",
    ]
    assert isinstance(data.get("filed_by_user_id"), str)
    if data["severity"] == "MAJOR":
        assert data.get("drone_id"), "MAJOR reports must name a drone"


def assert_flight_log(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("show_event_id", "")), "show_event_id must be a UUID"
    assert is_valid_uuid(data.get("drone_id", "")), "drone_id must be a UUID"
    assert data["flag_status"] in ["RECEIVED", "FLAGGED"]
    assert isinstance(data["battery_consumed_pct"], int)
    assert 0 <= data["battery_consumed_pct"] <= 100
    assert data["max_altitude_reached_ft"] >= 0
    assert data["max_deviation_m"] >= 0
