"""Entity assertions and domain invariant checkers.

All comparisons of ISO timestamps go through assert_ts_eq, which compares the
instants (parsing ISO 8601 and accepting optional fractional seconds) rather
than raw strings, so serializer formatting differences never break a test.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_ts(value: str) -> datetime:
    assert isinstance(value, str), f"Expected ISO timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_ts_eq(actual, expected: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant."""
    assert actual is not None, f"{label} must be non-null, got None"
    a = _parse_ts(actual)
    e = _parse_ts(expected)
    assert a == e, f"{label}: expected instant {expected}, got {actual}"


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def _assert_append_only(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"


def assert_shipper(data: dict):
    _assert_common(data, "Shipper")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert isinstance(data["default_shrink_allowance_pct"], (int, float))


def assert_driver(data: dict):
    _assert_common(data, "Driver")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["license_no"], str) and len(data["license_no"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["session_driving_minutes"], int)
    assert isinstance(data["calendar_day_driving_minutes"], int)
    assert isinstance(data["cycle_on_duty_minutes_8d"], int)
    assert isinstance(data["driving_since_break_minutes"], int)
    assert data["duty_window_expires_at"] is None or \
        is_iso8601_timestamp(data["duty_window_expires_at"])
    assert data["hos_status"] in [
        "ELIGIBLE", "BREAK_REQUIRED", "SESSION_EXHAUSTED", "WINDOW_CLOSED",
        "CYCLE_EXHAUSTED",
    ]
    assert isinstance(data["critical_incident_count_90d"], int)


def assert_duty_event(data: dict):
    _assert_append_only(data, "DriverDutyEvent")
    assert data["event_type"] in [
        "DUTY_ON", "DUTY_OFF", "DRIVING_ON", "DRIVING_OFF",
        "BREAK_START", "BREAK_END",
    ]
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["source"] in ["MANUAL", "SYSTEM"]
    assert "load_id" in data


def assert_trailer(data: dict):
    _assert_common(data, "Trailer")
    assert isinstance(data["trailer_no"], str) and len(data["trailer_no"]) > 0
    assert isinstance(data["max_gross_weight_lb"], int)
    assert data["washout_status"] in ["CLEAN", "DIRTY", "STALE"]
    assert data["last_washed_at"] is None or \
        is_iso8601_timestamp(data["last_washed_at"])
    assert data["washout_valid_until"] is None or \
        is_iso8601_timestamp(data["washout_valid_until"])
    assert data["dirtied_at"] is None or is_iso8601_timestamp(data["dirtied_at"])
    assert data["reserved_until"] is None or \
        is_iso8601_timestamp(data["reserved_until"])


def assert_compartment(data: dict):
    _assert_common(data, "TrailerCompartment")
    assert isinstance(data["trailer_id"], str)
    assert isinstance(data["compartment_index"], int)
    assert isinstance(data["max_head_count"], int)
    assert isinstance(data["max_weight_lb"], int)
    assert isinstance(data["occupied_head_count"], int)
    assert isinstance(data["occupied_weight_lb"], int)


def assert_load(data: dict):
    _assert_common(data, "Load")
    assert data["species"] in ["CATTLE", "SWINE", "SHEEP", "HORSES"]
    assert isinstance(data["declared_head_count"], int)
    assert isinstance(data["declared_weight_lb"], int)
    assert isinstance(data["origin"], str)
    assert isinstance(data["destination"], str)
    assert is_iso8601_timestamp(data["planned_departure_at"])
    assert isinstance(data["planned_duration_hours"], int)
    assert isinstance(data["rate_per_loaded_mile_cents"], int)
    assert isinstance(data["loaded_miles"], int)
    assert isinstance(data["effective_shrink_pct"], (int, float))
    assert isinstance(data["is_backhaul"], bool)
    assert data["status"] in [
        "DRAFT", "PLANNED", "PAPERWORK_VERIFIED", "ASSIGNED", "IN_TRANSIT",
        "WEATHER_HOLD", "REST_UNLOAD", "ARRIVED", "DELIVERED", "CANCELLED",
    ]
    assert isinstance(data["allocated_head_count"], int)
    assert isinstance(data["allocated_weight_lb"], int)


def assert_allocation(data: dict):
    _assert_common(data, "CompartmentAllocation")
    assert isinstance(data["load_id"], str)
    assert isinstance(data["trailer_compartment_id"], str)
    assert isinstance(data["head_count"], int)
    assert isinstance(data["avg_weight_lb"], (int, float))
    assert isinstance(data["weight_lb"], int)
    assert data["status"] in ["ACTIVE", "RELEASED"]
    assert data["release_reason"] is None or data["release_reason"] in [
        "REPLANNED", "CANCELLED", "DELIVERED",
    ]


def assert_health_paper(data: dict):
    _assert_common(data, "HealthPaper")
    assert isinstance(data["load_id"], str)
    assert isinstance(data["cert_number"], str)
    assert data["species"] in ["CATTLE", "SWINE", "SHEEP", "HORSES"]
    assert isinstance(data["head_count_listed"], int)
    assert data["status"] in ["PENDING", "VERIFIED", "REJECTED"]
    assert isinstance(data["created_by_user_id"], str)


def assert_brand_inspection(data: dict):
    _assert_common(data, "BrandInspection")
    assert isinstance(data["load_id"], str)
    assert isinstance(data["inspection_no"], str)
    assert is_iso8601_timestamp(data["inspected_at"])
    assert isinstance(data["head_count_inspected"], int)
    assert data["status"] in ["PENDING", "VERIFIED", "REJECTED"]
    assert isinstance(data["created_by_user_id"], str)


def assert_washout_event(data: dict):
    _assert_append_only(data, "WashoutEvent")
    assert isinstance(data["trailer_id"], str)
    assert is_iso8601_timestamp(data["washed_at"])
    assert data["method"] in ["HIGH_PRESSURE", "STEAM", "CHEMICAL"]


def assert_weight_ticket(data: dict):
    _assert_append_only(data, "WeightTicket")
    assert isinstance(data["load_id"], str)
    assert data["ticket_type"] in ["ORIGIN", "DELIVERY"]
    assert isinstance(data["gross_lb"], int)
    assert isinstance(data["tare_lb"], int)
    assert isinstance(data["net_weight_lb"], int)
    assert is_iso8601_timestamp(data["weighed_at"])
    assert data["net_weight_lb"] == data["gross_lb"] - data["tare_lb"], \
        "net_weight_lb must equal gross_lb - tare_lb"


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert isinstance(data["load_id"], str)
    assert data["status"] in [
        "PRELIMINARY", "PENDING", "DISPUTED", "COUNTERED", "RESOLVED", "PAID",
    ]
    for field in ("base_amount_cents", "provisional_amount_cents",
                  "shrink_allowance_lb", "shrink_lb", "excess_shrink_lb",
                  "shrink_penalty_cents", "welfare_deduction_cents",
                  "dispute_adjustment_cents", "final_amount_cents"):
        assert isinstance(data[field], int), \
            f"Settlement.{field} must be an integer, got {data.get(field)!r}"


def assert_incident(data: dict):
    _assert_common(data, "WelfareIncident")
    assert isinstance(data["load_id"], str)
    assert isinstance(data["driver_id"], str)
    assert data["incident_type"] in ["INJURY", "DOWNER", "DEAD_ON_ARRIVAL",
                                     "ESCAPE"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["head_count_affected"], int)
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["status"] in ["REPORTED", "UNDER_REVIEW", "CLOSED"]


def assert_weather_hold(data: dict):
    _assert_common(data, "WeatherHold")
    assert isinstance(data["load_id"], str)
    assert data["hold_type"] in ["HEAT", "COLD"]
    assert isinstance(data["temperature_f"], int)
    assert data["status"] in ["ACTIVE", "RELEASED"]
    assert data["released_at"] is None or is_iso8601_timestamp(data["released_at"])


def assert_settlement_money_identity(data: dict):
    """Money identity (PRD §3.6): final always equals provisional less the
    shrink penalty less the welfare deduction, floored at zero."""
    expected = max(
        0,
        data["provisional_amount_cents"]
        - data["shrink_penalty_cents"]
        - data["welfare_deduction_cents"],
    )
    assert data["final_amount_cents"] == expected, (
        f"final_amount_cents {data['final_amount_cents']} != "
        f"max(0, {data['provisional_amount_cents']} - "
        f"{data['shrink_penalty_cents']} - {data['welfare_deduction_cents']})"
    )
