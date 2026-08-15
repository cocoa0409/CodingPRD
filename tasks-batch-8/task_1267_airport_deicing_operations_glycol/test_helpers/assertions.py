"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, *, has_version: bool = True):
    assert isinstance(data, dict), "entity payload must be a dict"
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    if has_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601"
        )
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        assert "updated_at" not in data, "immutable event must not expose updated_at"
        assert "version" not in data, "immutable event must not expose version"


def assert_deice_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("min_collection_pct"), (int, float))
    assert isinstance(data.get("fluid_ops_minimum_liters"), int)
    assert isinstance(data.get("storm_surcharge_pct"), (int, float))
    assert data.get("posture") in ("NORMAL", "FLUID_CONSTRAINED", "PERMIT_SUSPENDED")
    assert isinstance(data.get("active_supply_alert"), bool)
    assert isinstance(data.get("collected_pool_liters"), (int, float))
    assert isinstance(data.get("ops_epoch_index"), int)


def assert_deice_pad(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("max_size_class") in ("SMALL", "MEDIUM", "LARGE")
    assert isinstance(data.get("rated_collection_pct"), (int, float))
    assert data.get("status") in ("AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE")


def assert_weather_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert data.get("precip_type") in ("SNOW", "FREEZING_FOG", "FREEZING_RAIN", "MIXED")
    assert data.get("precip_rate") in ("LIGHT", "MODERATE", "HEAVY")
    assert data.get("severity") in ("LEVEL_1", "LEVEL_2", "LEVEL_3")
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert data.get("ended_at") is None or is_iso8601_timestamp(data["ended_at"])
    assert isinstance(data.get("required_crew_count"), int)
    assert isinstance(data.get("assigned_crew_count"), int)
    assert data.get("staffing_status") in ("ADEQUATE", "SHORT")
    assert isinstance(data.get("escalation_level"), int)
    assert data.get("status") in ("FORECASTED", "ACTIVE", "ENDED", "CANCELLED")


def assert_fluid_tank(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert data.get("fluid_type") in ("TYPE_I", "TYPE_IV")
    assert data.get("concentration_pct") in (100, 75, 50)
    assert isinstance(data.get("capacity_liters"), int)
    assert isinstance(data.get("on_hand_liters"), (int, float))
    assert isinstance(data.get("reserved_liters"), (int, float))
    assert isinstance(data.get("available_liters"), (int, float))
    assert isinstance(data.get("reorder_threshold_liters"), int)
    assert data.get("status") in ("EMPTY", "REORDER_PENDING", "OK")


def assert_airline(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("credit_limit_cents"), int)
    assert isinstance(data.get("outstanding_balance_cents"), int)
    assert isinstance(data.get("monthly_billed_liters"), int)
    assert isinstance(data.get("month_key"), str)


def assert_deice_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("airline_id"), str) and is_valid_uuid(data["airline_id"])
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert isinstance(data.get("flight_number"), str)
    assert isinstance(data.get("aircraft_type"), str)
    assert data.get("size_class") in ("SMALL", "MEDIUM", "LARGE")
    assert is_iso8601_timestamp(data.get("scheduled_departure", ""))
    assert data.get("fluid_type") in ("TYPE_I", "TYPE_IV")
    assert data.get("priority") in ("EMERGENCY", "SCHEDULED", "FLEXIBLE")
    assert isinstance(data.get("estimated_liters"), int)
    assert data.get("assigned_tank_id") is None or is_valid_uuid(
        data["assigned_tank_id"]
    )
    assert data.get("fluid_reservation_status") in ("RESERVED", "UNRESERVED")
    assert data.get("assigned_pad_id") is None or is_valid_uuid(data["assigned_pad_id"])
    assert isinstance(data.get("epochs_in_queue"), int)
    assert isinstance(data.get("defer_count"), int)
    assert data.get("status") in (
        "QUEUED",
        "ASSIGNED",
        "IN_PROGRESS",
        "DEFERRED",
        "COMPLETED",
        "ABORTED",
        "EXPIRED",
    )


def assert_deice_operation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("request_id"), str) and is_valid_uuid(data["request_id"])
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert isinstance(data.get("pad_id"), str) and is_valid_uuid(data["pad_id"])
    assert isinstance(data.get("tank_id"), str) and is_valid_uuid(data["tank_id"])
    assert data.get("parent_operation_id") is None or is_valid_uuid(
        data["parent_operation_id"]
    )
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data.get("status") in (
        "PLANNED",
        "SPRAYING",
        "AWAITING_INSPECTION",
        "CLEARED",
        "REWORK_REQUIRED",
        "CANCELLED",
        "VOIDED",
    )


def assert_inspection(data: dict):
    _assert_common_fields(data, has_version=False)
    assert isinstance(data.get("operation_id"), str) and is_valid_uuid(
        data["operation_id"]
    )
    assert data.get("kind") in ("ACCEPTANCE", "POST_TREATMENT")
    assert data.get("result") in ("PASS", "FAIL")
    assert isinstance(data.get("findings"), str)
    assert isinstance(data.get("inspector_id"), str) and data["inspector_id"]


def assert_discharge_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert isinstance(data.get("permit_number"), str) and data["permit_number"]
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert isinstance(data.get("max_single_reading_mg_l"), (int, float))
    assert isinstance(data.get("rolling_window_days"), int)
    assert isinstance(data.get("rolling_window_max_liters"), int)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "SUPERSEDED", "EXPIRED")


def assert_effluent_reading(data: dict):
    _assert_common_fields(data, has_version=False)
    assert isinstance(data.get("permit_id"), str) and is_valid_uuid(data["permit_id"])
    assert is_iso8601_timestamp(data.get("measured_at", ""))
    assert isinstance(data.get("concentration_mg_l"), (int, float))
    assert isinstance(data.get("volume_liters"), int)
    assert isinstance(data.get("violation"), bool)


def assert_spill_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert isinstance(data.get("tank_id"), str) and is_valid_uuid(data["tank_id"])
    assert isinstance(data.get("quantity_liters"), (int, float))
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert data.get("classification") in ("REPORTABLE", "MINOR")
    assert isinstance(data.get("reporter_id"), str) and data["reporter_id"]
    assert data.get("confirmed_by") is None or isinstance(data["confirmed_by"], str)
    assert data.get("closed_by") is None or isinstance(data["closed_by"], str)
    assert data.get("status") in ("REPORTED", "CONFIRMED", "CLOSED")


def assert_recycling_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert isinstance(data.get("vendor_name"), str) and data["vendor_name"]
    assert isinstance(data.get("min_concentration_pct"), (int, float))
    assert isinstance(data.get("price_per_liter_cents"), int)
    assert isinstance(data.get("contracted_min_liters"), int)
    assert isinstance(data.get("delivered_liters"), (int, float))
    assert isinstance(data.get("total_revenue_cents"), int)
    assert data.get("last_shipment_revenue_cents") is None or isinstance(
        data["last_shipment_revenue_cents"], int
    )
    assert data.get("status") in ("ACTIVE", "FULFILLED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("airline_id"), str) and is_valid_uuid(data["airline_id"])
    assert isinstance(data.get("station_id"), str) and is_valid_uuid(data["station_id"])
    assert isinstance(data.get("operation_id"), str) and is_valid_uuid(
        data["operation_id"]
    )
    assert data.get("supersedes_invoice_id") is None or is_valid_uuid(
        data["supersedes_invoice_id"]
    )
    assert isinstance(data.get("pad_fee_cents"), int)
    assert isinstance(data.get("fluid_charge_cents"), int)
    assert isinstance(data.get("storm_surcharge_cents"), int)
    assert isinstance(data.get("total_cents"), int)
    assert data.get("pricing_variant") in ("MARGINAL_TIER", "FLAT_TIER")
    assert data.get("status") in ("DRAFT", "ISSUED", "VOID", "SUPERSEDED")
