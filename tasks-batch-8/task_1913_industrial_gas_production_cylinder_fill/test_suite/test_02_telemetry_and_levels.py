"""Telemetry projection, low-level flag reconciliation, and reading validation
(PRD §3.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_tank_volume_invariants,
    create_test_customer,
    create_test_installation,
    create_test_plant,
    create_test_tank,
    get_tank,
    set_logical_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


def test_late_reading_does_not_move_current_level(api):
    """PRD §3.1: "the governing reading is the one with the greatest
    `measured_at`, with ties broken in favor of the later `created_at` — a
    later-recorded reading wins an equal `measured_at`. A late-arriving reading
    whose `measured_at` is earlier than the current governing reading's changes
    nothing."

    Design: Corner/calculations/telemetry_late_reading_does_not_reorder
    """
    plant = create_test_plant(plant_name="P-CA1")
    tank = create_test_tank(plant["id"])
    assert tank["current_level_liters"] == pytest.approx(5000.0, abs=0.01)

    set_logical_clock("2026-08-01T06:00:00Z")
    validate_success(
        api.create_telemetry_reading(
            {"tank_id": tank["id"], "measured_level_liters": 4000,
             "measured_at": "2026-08-01T02:00:00Z", "source": "IOT_SENSOR"}, OP),
        201,
    )
    after_first = get_tank(tank["id"])
    assert after_first["current_level_liters"] == pytest.approx(4000.0, abs=0.01)

    # Late arrival: measured at 01:00, earlier than the governing 02:00 reading.
    validate_success(
        api.create_telemetry_reading(
            {"tank_id": tank["id"], "measured_level_liters": 4500,
             "measured_at": "2026-08-01T01:00:00Z", "source": "MANUAL_DIP"}, OP),
        201,
    )
    after_late = get_tank(tank["id"])
    assert after_late["current_level_liters"] == pytest.approx(4000.0, abs=0.01), (
        "a backdated reading must not reorder the projection"
    )


def test_newer_reading_becomes_governing(api):
    """PRD §3.1: "the governing reading is the one with the greatest
    `measured_at`, with ties broken in favor of the later `created_at` — a
    later-recorded reading wins an equal `measured_at`. A late-arriving reading
    whose `measured_at` is earlier than the current governing reading's changes
    nothing."

    Design: Corner/calculations/telemetry_late_reading_does_not_reorder
    """
    plant = create_test_plant(plant_name="P-CA1B")
    tank = create_test_tank(plant["id"])
    set_logical_clock("2026-08-01T06:00:00Z")
    validate_success(
        api.create_telemetry_reading(
            {"tank_id": tank["id"], "measured_level_liters": 4000,
             "measured_at": "2026-08-01T02:00:00Z", "source": "IOT_SENSOR"}, OP),
        201,
    )
    validate_success(
        api.create_telemetry_reading(
            {"tank_id": tank["id"], "measured_level_liters": 4200,
             "measured_at": "2026-08-01T03:00:00Z", "source": "IOT_SENSOR"}, OP),
        201,
    )
    after_newer = get_tank(tank["id"])
    assert after_newer["current_level_liters"] == pytest.approx(4200.0, abs=0.01), (
        "a reading with a later measured_at becomes governing"
    )


def test_low_level_flag_reconciles_on_readings(api):
    """PRD §3.1: "A tank's `low_level_flag` is true exactly when
    `current_level_liters` is less than or equal to `reorder_point_liters`, and
    is recomputed whenever the current level changes."

    Design: Corner/complexity_layers/low_level_flag_reconciles_on_readings
    """
    plant = create_test_plant(plant_name="P-CL4")
    tank = create_test_tank(plant["id"], initial_level_liters=5000,
                            reorder_point_liters=500)
    assert tank["low_level_flag"] is False

    set_logical_clock("2026-08-01T06:00:00Z")
    validate_success(
        api.create_telemetry_reading(
            {"tank_id": tank["id"], "measured_level_liters": 500,
             "measured_at": "2026-08-01T01:00:00Z", "source": "IOT_SENSOR"}, OP),
        201,
    )
    at_point = get_tank(tank["id"])
    assert at_point["current_level_liters"] == pytest.approx(500.0, abs=0.01)
    assert at_point["low_level_flag"] is True, "equality at the reorder point flags"
    assert_tank_volume_invariants(at_point)

    validate_success(
        api.create_telemetry_reading(
            {"tank_id": tank["id"], "measured_level_liters": 501,
             "measured_at": "2026-08-01T02:00:00Z", "source": "IOT_SENSOR"}, OP),
        201,
    )
    above_point = get_tank(tank["id"])
    assert above_point["current_level_liters"] == pytest.approx(501.0, abs=0.01)
    assert above_point["low_level_flag"] is False


def test_telemetry_future_dated_rejected(api):
    """PRD §3.1: "a `measured_at` instant that must not be later than the logical
    clock (future-dated readings are rejected with `ERR_TELEMETRY_FUTURE_DATED`)"
    — part of: "Each reading carries exactly one of `tank_id` or
    `installation_id` (see §2.9), a `measured_level_liters` between zero and the
    owner's capacity inclusive, a `measured_at` instant that must not be later
    than the logical clock (future-dated readings are rejected with
    `ERR_TELEMETRY_FUTURE_DATED`), and a `source` of `IOT_SENSOR`, `MANUAL_DIP`,
    `INITIAL_LOAD`, or `SYSTEM_REPLENISHMENT`; the server stamps
    `recorded_by_user_id` from the caller's header."

    Design: Corner/validations/telemetry_future_dated_rejected
    """
    plant = create_test_plant(plant_name="P-VA2")
    tank = create_test_tank(plant["id"])
    # Startup default clock is exactly 2026-08-01T00:00:00Z (PRD §2.4).
    res = api.create_telemetry_reading(
        {"tank_id": tank["id"], "measured_level_liters": 4900,
         "measured_at": "2026-08-01T00:00:01Z", "source": "IOT_SENSOR"}, OP)
    validate_error(res, ApiErrorId.ERR_TELEMETRY_FUTURE_DATED.value)


def test_telemetry_measured_exactly_at_clock_accepted(api):
    """PRD §3.1: "a `measured_at` instant that must not be later than the logical
    clock (future-dated readings are rejected with `ERR_TELEMETRY_FUTURE_DATED`)"
    — "not later than" admits equality, so a reading stamped exactly at the
    startup clock (2026-08-01T00:00:00Z, PRD §2.4) is accepted.

    Design: Corner/validations/telemetry_future_dated_rejected
    """
    plant = create_test_plant(plant_name="P-VA2B")
    tank = create_test_tank(plant["id"])
    res = api.create_telemetry_reading(
        {"tank_id": tank["id"], "measured_level_liters": 4900,
         "measured_at": "2026-08-01T00:00:00Z", "source": "IOT_SENSOR"}, OP)
    reading = validate_success(res, 201)
    assert reading["measured_level_liters"] == 4900


def test_telemetry_xor_violation_rejected(api):
    """PRD §2.9: "Two resource families carry polymorphic references governed by
    an exactly-one rule: a telemetry reading targets exactly one of `tank_id` or
    `installation_id`, and a purity analysis targets exactly one of `fill_lot_id`
    or `blend_order_id` as selected by its `subject_type`; supplying both sides
    or neither side is a well-formedness violation rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/telemetry_xor_violation_rejected
    """
    plant = create_test_plant(plant_name="P-VA3")
    tank = create_test_tank(plant["id"])
    customer = create_test_customer(account_name="C-VA3")
    installation = create_test_installation(customer["id"])
    res = api.create_telemetry_reading(
        {
            "tank_id": tank["id"],
            "installation_id": installation["id"],
            "measured_level_liters": 100,
            "measured_at": "2026-08-01T00:00:00Z",
            "source": "MANUAL_DIP",
        },
        OP,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
