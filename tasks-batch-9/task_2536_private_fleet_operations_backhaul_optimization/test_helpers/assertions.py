"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    MAX_DAILY_DRIVE_MINUTES,
    MAX_DAILY_DUTY_MINUTES,
    MAX_WEEKLY_ON_DUTY_MINUTES,
    SAFETY_SCORE_CEILING,
    SAFETY_SCORE_FLOOR,
)


def assert_common_fields(data: dict) -> None:
    """id / created_at / updated_at / version, present on every versioned entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict) -> None:
    """id and created_at only: the shape of an append-only record."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_store(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["dock_count"] >= 1
    assert data["cases_per_hour_unload_rate"] >= 1
    assert 0 <= data["dock_open_minute"] <= 1439
    assert 0 <= data["dock_close_minute"] <= 1439
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["open_scheduled_cases"] >= 0
    assert data["delivered_cases_total"] >= 0


def assert_domicile(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["domicile_code"], str) and data["domicile_code"]
    assert data["tractor_capacity"] >= 1
    assert data["driver_headcount_target"] >= 1
    assert data["fixed_ownership_cents_per_day"] >= 0
    assert data["overhead_cents_per_day"] >= 0
    assert data["dedicated_rate_cents_per_mile"] >= 0
    assert data["dedicated_rate_cents_per_case"] >= 0
    assert data["assigned_driver_count"] >= 0
    assert float(data["balance_index"]) >= 0
    assert data["accrued_pay_cents"] >= 0


def assert_pay_plan(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    for field in (
        "mileage_cents_per_mile",
        "stop_cents_per_stop",
        "drop_hook_cents",
        "hourly_cents_per_minute",
        "minimum_daily_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"
    assert 0.0 <= float(data["backhaul_bonus_pct"]) <= 1.0


def assert_driver(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["driver_code"], str) and 1 <= len(data["driver_code"]) <= 16
    assert is_valid_uuid(data["domicile_id"])
    assert is_valid_uuid(data["pay_plan_id"])
    assert isinstance(data["seniority_date"], str) and len(data["seniority_date"]) == 10
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert data["hos_status"] in ("AVAILABLE", "ON_DUTY")
    assert 0 <= data["drive_minutes_used_today"]
    assert 0 <= data["duty_minutes_used_today"]
    assert 0 <= data["weekly_on_duty_minutes"]
    assert data["open_penalty_points"] >= 0
    assert SAFETY_SCORE_FLOOR <= data["safety_score"] <= SAFETY_SCORE_CEILING
    assert isinstance(data["coaching_hold"], bool)
    assert data["ytd_gross_cents"] >= 0


def assert_driver_safety_identity(data: dict) -> None:
    """safety_score is 100 less the open penalty points, floored at zero."""
    expected = max(SAFETY_SCORE_FLOOR, SAFETY_SCORE_CEILING - data["open_penalty_points"])
    assert data["safety_score"] == expected, (
        f"safety_score {data['safety_score']} does not match "
        f"100 - {data['open_penalty_points']} floored at 0"
    )


def assert_tractor(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert is_valid_uuid(data["domicile_id"])
    assert data["odometer_miles"] >= 0
    assert data["pm_interval_miles"] >= 1
    assert data["pm_last_service_odometer"] >= 0
    assert data["miles_since_pm"] >= 0
    assert isinstance(data["pm_hold"], bool)
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "IN_SHOP")


def assert_tractor_pm_counter(data: dict) -> None:
    """miles_since_pm is re-derived from the odometer and the last service reading."""
    expected = data["odometer_miles"] - data["pm_last_service_odometer"]
    assert data["miles_since_pm"] == expected, (
        f"miles_since_pm {data['miles_since_pm']} is not "
        f"{data['odometer_miles']} - {data['pm_last_service_odometer']}"
    )


def assert_trailer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["trailer_code"], str) and data["trailer_code"]
    assert is_valid_uuid(data["domicile_id"])
    assert data["trailer_type"] in ("DRY_VAN", "REEFER")
    assert data["capacity_cases"] >= 1
    assert is_iso8601_timestamp(data["inspection_due_at"])
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "IN_SHOP")


def assert_order(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["cases"] >= 1
    assert data["weight_lbs"] >= 0
    assert is_iso8601_timestamp(data["requested_window_start"])
    assert is_iso8601_timestamp(data["requested_window_end"])
    assert data["temperature_mode"] in ("DRY", "REFRIGERATED")
    assert data["priority"] >= 1
    assert data["status"] in ("UNSCHEDULED", "SCHEDULED", "DELIVERED", "CANCELLED")


def assert_trip(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["trip_code"], str) and data["trip_code"]
    assert is_valid_uuid(data["domicile_id"])
    assert is_iso8601_timestamp(data["planned_start_at"])
    assert data["plan_status"] in (
        "DRAFT", "PLANNED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert data["settlement_status"] in (
        "PENDING", "ACCRUED", "DISPUTED", "ADJUSTED", "SETTLED",
    )
    assert data["stop_count"] >= 0
    for field in (
        "total_miles", "loaded_miles", "empty_miles", "planned_drive_minutes",
        "planned_service_minutes", "planned_break_minutes", "planned_duty_minutes",
        "planned_delivery_cases", "peak_case_load", "delivered_cases",
        "planned_pay_cents", "driver_pay_cents", "backhaul_credit_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"


def assert_trip_mileage_split(data: dict) -> None:
    """Loaded and empty miles partition the trip's total miles."""
    assert data["loaded_miles"] + data["empty_miles"] == data["total_miles"], (
        f"loaded {data['loaded_miles']} + empty {data['empty_miles']} "
        f"!= total {data['total_miles']}"
    )


def assert_trip_duty_identity(data: dict) -> None:
    """Planned duty is drive plus service plus break minutes."""
    expected = (
        data["planned_drive_minutes"]
        + data["planned_service_minutes"]
        + data["planned_break_minutes"]
    )
    assert data["planned_duty_minutes"] == expected, (
        f"planned_duty_minutes {data['planned_duty_minutes']} != "
        f"{data['planned_drive_minutes']} + {data['planned_service_minutes']} "
        f"+ {data['planned_break_minutes']}"
    )


def assert_trip_stop(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["trip_id"])
    assert data["sequence"] >= 1
    assert data["stop_type"] in ("DELIVERY", "VENDOR_PICKUP", "DROP_OFF", "FUEL")
    assert is_iso8601_timestamp(data["scheduled_arrival_at"])
    assert is_iso8601_timestamp(data["scheduled_departure_at"])
    assert data["drive_minutes_from_prev"] >= 0
    assert data["miles_from_prev"] >= 0
    assert isinstance(data["segment_loaded"], bool)
    assert data["service_minutes"] >= 0
    assert data["status"] in ("PLANNED", "ARRIVED", "COMPLETED", "SKIPPED")


def assert_backhaul_offer(data: dict) -> None:
    assert_common_fields(data)
    assert data["origin_kind"] in ("VENDOR_PICKUP", "THIRD_PARTY")
    assert isinstance(data["shipper_name"], str) and data["shipper_name"]
    assert is_valid_uuid(data["dest_store_id"])
    assert data["revenue_cents"] >= 1
    assert data["cases"] >= 1
    assert data["weight_lbs"] >= 0
    assert data["deadhead_miles"] >= 0
    assert data["loaded_miles"] >= 0
    assert data["temperature_mode"] in ("DRY", "REFRIGERATED")
    assert data["status"] in (
        "PROPOSED", "UNDER_REVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED",
    )
    assert 0 <= data["review_round"] <= 3
    assert isinstance(data["margin_exception_approved"], bool)


def assert_offer_margin_identity(data: dict) -> None:
    """Contribution margin is gross margin less commission."""
    assert data["contribution_margin_cents"] == (
        data["gross_margin_cents"] - data["commission_cents"]
    ), (
        f"contribution_margin {data['contribution_margin_cents']} != "
        f"gross {data['gross_margin_cents']} - commission {data['commission_cents']}"
    )


def assert_work_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["asset_kind"] in ("TRACTOR", "TRAILER")
    if data["asset_kind"] == "TRACTOR":
        assert is_valid_uuid(data["tractor_id"])
        assert data["trailer_id"] is None
    else:
        assert is_valid_uuid(data["trailer_id"])
        assert data["tractor_id"] is None
    assert data["service_type"] in ("PM_A", "PM_B", "INSPECTION", "REPAIR")
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert data["status"] in ("SCHEDULED", "DEFERRED", "IN_SHOP", "COMPLETED", "CANCELLED")
    assert 0 <= data["deferral_count"] <= 2
    assert isinstance(data["auto_generated"], bool)


def assert_pay_statement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["driver_id"])
    assert is_valid_uuid(data["trip_id"])
    assert is_valid_uuid(data["pay_plan_id"])
    assert isinstance(data["pay_plan_version"], int) and data["pay_plan_version"] >= 1
    assert data["variant"] in ("PLANNED_ACCRUAL", "FINAL_SETTLEMENT")
    for field in (
        "mileage_cents", "activity_cents", "hourly_cents", "bonus_cents",
        "guarantee_makeup_cents", "gross_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"
    assert data["status"] in ("ACCRUED", "SETTLED", "REVERSED")


def assert_statement_gross_identity(data: dict) -> None:
    """Gross is the four components plus any guarantee make-up."""
    subtotal = (
        data["mileage_cents"] + data["activity_cents"]
        + data["hourly_cents"] + data["bonus_cents"]
    )
    assert data["gross_cents"] == subtotal + data["guarantee_makeup_cents"], (
        f"gross {data['gross_cents']} != subtotal {subtotal} + "
        f"makeup {data['guarantee_makeup_cents']}"
    )


def assert_route_posting(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert is_valid_uuid(data["domicile_id"])
    assert data["weekly_miles"] >= 0
    assert data["weekly_stops"] >= 0
    assert data["status"] in ("OPEN", "AWARDED", "VACANT", "CANCELLED")
    assert data["bid_count"] >= 0


def assert_route_bid(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["route_posting_id"])
    assert is_valid_uuid(data["driver_id"])
    assert isinstance(data["seniority_date_snapshot"], str)
    assert 0 <= data["safety_score_snapshot"] <= 100
    assert data["status"] in ("SUBMITTED", "AWARDED", "PASSED_OVER", "WITHDRAWN")


def assert_telematics_event(data: dict) -> None:
    assert_append_only_fields(data)
    assert "updated_at" not in data, "an append-only record must not report updated_at"
    assert "version" not in data, "an append-only record must not report version"
    assert is_valid_uuid(data["driver_id"])
    assert data["event_type"] in ("HARD_BRAKE", "SPEEDING", "FOLLOWING_DISTANCE", "SEATBELT")
    assert 1 <= data["severity"] <= 3
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["penalty_points"] >= 0
    assert isinstance(data["coached"], bool)


def assert_hos_within_ceilings(driver: dict) -> None:
    """No accepted operation may leave a driver above any of the three ceilings."""
    assert driver["drive_minutes_used_today"] <= MAX_DAILY_DRIVE_MINUTES
    assert driver["duty_minutes_used_today"] <= MAX_DAILY_DUTY_MINUTES
    assert driver["weekly_on_duty_minutes"] <= MAX_WEEKLY_ON_DUTY_MINUTES


def assert_envelope_meta(body: dict, expected_response_type: str) -> None:
    """Every response carries the request id, its timestamp and the response type."""
    meta = body.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "api_request_timestamp must be ISO 8601"
    )
    assert body.get("response_type") == expected_response_type, (
        f"expected response_type {expected_response_type!r}, got {body.get('response_type')!r}"
    )
