"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LOAD_STATUSES = [
    "TENDERED", "SCREENED", "ACCEPTED", "ASSIGNED", "DISPATCHED", "IN_TRANSIT",
    "DELIVERED", "INVOICED", "CLOSED", "REJECTED", "CANCELLED",
]
TRIP_STATUSES = [
    "PLANNED", "DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_DELIVERY",
    "COMPLETED", "CANCELLED",
]
ACCESSORIAL_STATUSES = [
    "PENDING", "SUBMITTED", "APPROVED", "DISPUTED", "BILLED", "REJECTED",
]


def _assert_common_fields(data: dict):
    """PRD §2.5: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def _assert_append_only_fields(data: dict):
    """PRD §2.5: append-only telemetry carries id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_driver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cdl_number"], str) and data["cdl_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["pay_model"] in ("MILEAGE", "PERCENTAGE")
    assert data["employment_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["duty_status"] in ("OFF_DUTY", "SLEEPER", "DRIVING", "ON_DUTY")
    assert isinstance(data["safety_score"], int) and 0 <= data["safety_score"] <= 100


def assert_tractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE")
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["current_fuel_gallons"], int)
    assert 0 <= data["current_fuel_gallons"] <= data["tank_capacity_gallons"]


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")


def assert_lane(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loaded_miles"], int) and data["loaded_miles"] >= 1
    assert isinstance(data["rpm_floor_cents"], int) and data["rpm_floor_cents"] >= 0


def assert_state_fuel_rate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["tax_cents_per_gallon"], int)
    assert data["tax_cents_per_gallon"] >= 0
    assert isinstance(data["avg_pump_price_cents"], int)
    assert data["avg_pump_price_cents"] >= 1
    assert is_iso8601_timestamp(data["effective_from"])


def assert_load(data: dict):
    _assert_common_fields(data)
    assert data["status"] in LOAD_STATUSES
    assert isinstance(data["rate_cents"], int) and data["rate_cents"] >= 1
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] >= 1
    assert isinstance(data["total_accessorial_cents"], int)
    assert data["total_accessorial_cents"] >= 0
    assert isinstance(data["reassignment_count"], int)
    assert data["reassignment_count"] >= 0


def assert_trip(data: dict):
    _assert_common_fields(data)
    assert data["status"] in TRIP_STATUSES
    assert isinstance(data["planned_deadhead_miles"], int)
    assert data["planned_deadhead_miles"] >= 0
    assert isinstance(data["route_states"], list)


def assert_duty_event(data: dict):
    _assert_append_only_fields(data)
    assert data["event_type"] in ("OFF_DUTY", "SLEEPER", "DRIVING", "ON_DUTY")
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_check_call(data: dict):
    _assert_append_only_fields(data)
    assert data["kind"] in (
        "ARRIVED_PICKUP", "DEPARTED_PICKUP", "EN_ROUTE",
        "ARRIVED_DELIVERY", "DELIVERED",
    )
    assert is_iso8601_timestamp(data["occurred_at"])
    assert isinstance(data["odometer_miles"], int)


def assert_accessorial(data: dict):
    _assert_common_fields(data)
    assert data["type"] in (
        "DETENTION_PICKUP", "DETENTION_DELIVERY", "LAYOVER", "LUMPER", "STOP_OFF",
    )
    assert data["status"] in ACCESSORIAL_STATUSES
    assert data["source"] in ("AUTO_DETENTION", "MANUAL")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_fuel_purchase(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["gallons"], int) and data["gallons"] >= 1
    assert isinstance(data["pump_price_cents"], int) and data["pump_price_cents"] >= 1
    assert data["total_cost_cents"] == data["gallons"] * data["pump_price_cents"]
    assert data["net_effective_price_cents"] == (
        data["pump_price_cents"] - data["tax_paid_cents"] // data["gallons"]
    )


def assert_safety_event(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ("INSPECTION_VIOLATION", "CRASH_AT_FAULT", "HOS_VIOLATION")
    assert data["source"] in ("MANUAL", "AUTO_HOS")
    assert isinstance(data["voided"], bool)


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "PAID")
    for field in ("trip_pay_cents", "accessorial_share_cents",
                  "manual_adjustment_cents", "guarantee_top_up_cents",
                  "gross_pay_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["gross_pay_cents"] == (
        data["trip_pay_cents"] + data["accessorial_share_cents"]
        + data["manual_adjustment_cents"] + data["guarantee_top_up_cents"]
    ), "gross must equal the sum of its components"


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    for field in ("linehaul_cents", "fuel_surcharge_cents",
                  "accessorial_total_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["total_cents"] == (
        data["linehaul_cents"] + data["fuel_surcharge_cents"]
        + data["accessorial_total_cents"]
    ), "invoice total must equal linehaul + fuel surcharge + accessorial total"
