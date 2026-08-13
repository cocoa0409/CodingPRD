"""Unit registration, hour-meter telemetry, PM threshold, and the energy program."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_unit,
    get_unit,
    make_checked_out_contract,
    make_unit,
    validate_error,
    validate_success,
)


class TestUnitRegistration:
    def test_unit_create_computed_fields_initialized(self, api,
                                                     fleet_manager_headers):
        """PRD §3.1: "From these inputs the system derives the rest:
        `fuel_program` mirrors `power_type` (battery units take charge and swap
        events, LP units take refills); `hour_meter` and `last_pm_hours` start
        at 0, so `next_pm_due_hours` initially equals `pm_interval_hours`;
        `maintenance_posture` starts `PM_OK`; `availability_status` starts
        `AVAILABLE`;" and "`utilization_pct_90d` starts at 0.0 pending any
        rental history." PRD §2.4: "`version` (integer): starts at 1 when the
        resource is created".

        Design: Corner/entities/unit_create_computed_fields_initialized
        """
        resp = api.create_unit(
            {"serial_number": "SN-ENT1", "model": "8FBCU25",
             "power_type": "BATTERY", "disposition": "RENTAL_FLEET",
             "daily_rate_cents": 16000, "weekly_rate_cents": 75000,
             "monthly_rate_cents": 220000, "pm_interval_hours": 300},
            fleet_manager_headers)
        created = validate_success(resp, 201)
        data = validate_success(api.get_unit(created["id"], fleet_manager_headers))
        assert_unit(data)
        assert data["hour_meter"] == 0
        assert data["last_pm_hours"] == 0
        assert data["next_pm_due_hours"] == 300
        assert data["maintenance_posture"] == "PM_OK"
        assert data["availability_status"] == "AVAILABLE"
        assert data["fuel_program"] == "BATTERY"
        assert data["utilization_pct_90d"] == pytest.approx(0.0)
        assert data["version"] == 1

    def test_get_nonexistent_unit_returns_not_found(self, api,
                                                    fleet_manager_headers):
        """PRD §2.5: resources referenced by path identifiers yield
        "`ERR_NOT_FOUND` when it does not resolve to an existing resource";
        PRD §5 maps `ERR_NOT_FOUND` to HTTP 404.

        Design: Corner/entities/get_nonexistent_unit_returns_not_found
        """
        resp = api.get_unit("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                            fleet_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_create_unit_invalid_enum_returns_invalid_request(
            self, api, fleet_manager_headers):
        """PRD §3.1: "`power_type` of either `BATTERY` or `LP`"; PRD §2.6 lists
        "enum values valid" under request-body shape, rejected with
        `ERR_INVALID_REQUEST` (PRD §5: HTTP 400).

        Design: Corner/entities/create_unit_invalid_enum_returns_invalid_request
        """
        resp = api.create_unit(
            {"serial_number": "SN-ENT2", "model": "X", "power_type": "DIESEL",
             "disposition": "RENTAL_FLEET", "daily_rate_cents": 15000,
             "weekly_rate_cents": 70000, "monthly_rate_cents": 210000,
             "pm_interval_hours": 500},
            fleet_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_registrar_cannot_create_units(self, api, training_registrar_headers):
        """PRD §4: POST /fleet/units is authorized for FleetManager only;
        PRD §2.1: "A request whose role is not permitted for the target endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/registrar_cannot_create_units
        """
        resp = api.create_unit(
            {"serial_number": "SN-RB3", "model": "8FGCU25", "power_type": "LP",
             "disposition": "RENTAL_FLEET", "daily_rate_cents": 15000,
             "weekly_rate_cents": 70000, "monthly_rate_cents": 210000,
             "pm_interval_hours": 500},
            training_registrar_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestMeterReadings:
    def test_meter_reading_is_append_only_subresource(self, api,
                                                      fleet_manager_headers):
        """PRD §2.4: "Sub-resources that exist only as children of a parent —
        quote lines, meter readings, fuel events, and lease inspections — carry
        only `id` and `created_at`. Both `updated_at` and `version` are absent
        on those four resource types."

        Design: Corner/entities/immutable_event_entities_have_no_update
        """
        unit = make_unit(serial_number="SN-ENT3")
        resp = api.create_meter_reading(unit["id"], {"reading_hours": 10},
                                        fleet_manager_headers)
        data = validate_success(resp, 201)
        assert isinstance(data["id"], str) and data["id"]
        assert isinstance(data["created_at"], str) and data["created_at"]
        assert "version" not in data, "meter readings must not carry version"
        assert "updated_at" not in data, "meter readings must not carry updated_at"

    def test_hour_meter_regression_rejected(self, api, fleet_manager_headers):
        """PRD §3.4: "the value must be strictly greater than the unit's current
        `hour_meter`, else the reading is rejected with
        `ERR_HOUR_METER_REGRESSION`."

        Design: Corner/validations/hour_meter_regression_rejected
        """
        unit = make_unit(serial_number="SN-V1")
        validate_success(api.create_meter_reading(unit["id"], {"reading_hours": 500},
                                                  fleet_manager_headers), 201)
        resp = api.create_meter_reading(unit["id"], {"reading_hours": 400},
                                        fleet_manager_headers)
        validate_error(resp, ApiErrorId.ERR_HOUR_METER_REGRESSION, 422)
        assert get_unit(unit["id"])["hour_meter"] == 500, \
            "rejected reading must not move the hour meter"


class TestPmDueBoundary:
    def test_pm_ok_strictly_below_threshold(self, api, fleet_manager_headers):
        """PRD §2.11: "the unit is `PM_DUE` if and only if its current
        `hour_meter` reading is greater than or equal to `next_pm_due_hours`" —
        at 499 with `next_pm_due_hours` 500 the unit stays `PM_OK`.

        Design: Difficulty/boundary_precision_check/pm_due_at_exact_interval
        """
        unit = make_unit(serial_number="SN-BP1", pm_interval_hours=500)
        validate_success(api.create_meter_reading(unit["id"], {"reading_hours": 499},
                                                  fleet_manager_headers), 201)
        data = get_unit(unit["id"])
        assert data["maintenance_posture"] == "PM_OK", \
            "499 < 500 must leave the posture PM_OK"
        assert data["next_pm_due_hours"] == 500
        assert data["hour_meter"] == 499

    def test_pm_due_at_exact_threshold(self, api, fleet_manager_headers):
        """PRD §2.11: "The boundary is inclusive: a reading of exactly
        `next_pm_due_hours` means the unit is due." `next_pm_due_hours` stays
        500 until a PM service completes (PRD §3.5).

        Design: Difficulty/boundary_precision_check/pm_due_at_exact_interval
        """
        unit = make_unit(serial_number="SN-BP1B", pm_interval_hours=500)
        validate_success(api.create_meter_reading(unit["id"], {"reading_hours": 499},
                                                  fleet_manager_headers), 201)
        validate_success(api.create_meter_reading(unit["id"], {"reading_hours": 500},
                                                  fleet_manager_headers), 201)
        data = get_unit(unit["id"])
        assert data["maintenance_posture"] == "PM_DUE", \
            "500 >= 500 must flip the posture to PM_DUE"
        assert data["next_pm_due_hours"] == 500, \
            "next_pm_due_hours is unchanged until a PM service completes"
        assert data["hour_meter"] == 500


class TestParallelPostureDimensions:
    def test_meter_reading_on_rent_flips_posture_only(self, api,
                                                      fleet_manager_headers):
        """PRD §2.11: "Because the dimensions are parallel, a rule that gates on
        one dimension (say, checkout requiring `PM_OK`) says nothing about the
        other, and transitions on one never implicitly move the other except
        where §3 states so explicitly." PRD §3.4: a reading that reaches
        `next_pm_due_hours` flips posture "from `PM_OK` to `PM_DUE`".

        Design: Difficulty/non_linear_state_machine/unit_parallel_availability_posture
        """
        _customer, unit, contract = make_checked_out_contract(
            start_date="2026-08-01", end_date="2026-08-20",
            unit_overrides={"serial_number": "SN-PL1"})
        assert unit["availability_status"] == "ON_RENT"
        validate_success(api.create_meter_reading(
            unit["id"], {"reading_hours": 500,
                         "note": "telematics push while on rent"},
            fleet_manager_headers), 201)
        data = get_unit(unit["id"])
        assert data["availability_status"] == "ON_RENT", \
            "availability dimension must be untouched by a meter reading"
        assert data["maintenance_posture"] == "PM_DUE"
        assert data["hour_meter"] == 500

    def test_hour_meter_advances_independently_of_availability(self, api,
                                                               fleet_manager_headers):
        """PRD §3.4: "Every recorded reading echoes its parent `unit_id`,
        advances the unit's `hour_meter` to the new value, and re-evaluates the
        planned-maintenance threshold of §2.11". The unit stays ON_RENT (§2.11
        parallel dimensions) while the meter advance drives 0 -> 500.

        Design: Difficulty/non_linear_state_machine/unit_parallel_availability_posture
        """
        _customer, unit, _contract = make_checked_out_contract(
            start_date="2026-08-01", end_date="2026-08-20",
            unit_overrides={"serial_number": "SN-PL2"})
        validate_success(api.create_meter_reading(unit["id"],
                                                  {"reading_hours": 500},
                                                  fleet_manager_headers), 201)
        data = get_unit(unit["id"])
        assert data["hour_meter"] == 500
        assert data["availability_status"] == "ON_RENT"
        assert data["maintenance_posture"] == "PM_DUE"


class TestFuelProgram:
    def test_battery_charge_event_cost(self, api, fleet_manager_headers):
        """PRD §3.4: "On a `BATTERY` unit, a `CHARGE` event costs the metered
        `kwh` times 12 cents per kilowatt-hour, rounded half up to whole cents";
        "A 100-kWh charge therefore costs 1200 cents".

        Design: Difficulty/dual_variant_calc/fuel_cost_battery_vs_lp
        """
        unit = make_unit(serial_number="SN-BAT1", model="8FBCU25",
                         power_type="BATTERY", disposition="NEW_SALE",
                         daily_rate_cents=16000, weekly_rate_cents=75000,
                         monthly_rate_cents=220000)
        resp = api.create_fuel_event(unit["id"], {"event_type": "CHARGE",
                                                  "kwh": 100},
                                     fleet_manager_headers)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 1200, "100 kWh * 12 cents must cost 1200"
        assert data["event_type"] == "CHARGE"

    def test_lp_refill_event_cost(self, api, fleet_manager_headers):
        """PRD §3.4: "On an `LP` unit, an `LP_REFILL` costs 4500 cents per
        cylinder exchanged times `cylinders`, plus a flat 1500-cent delivery
        fee" — "a two-cylinder LP refill costs 10500 cents — the same
        replenishment intent priced by two different algorithms."

        Design: Difficulty/dual_variant_calc/fuel_cost_battery_vs_lp
        """
        unit = make_unit(serial_number="SN-LP1", disposition="NEW_SALE")
        resp = api.create_fuel_event(unit["id"], {"event_type": "LP_REFILL",
                                                  "cylinders": 2},
                                     fleet_manager_headers)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 10500, "2 * 4500 + 1500 must cost 10500"
        assert data["event_type"] == "LP_REFILL"

    def test_swap_fee_math(self, api, fleet_manager_headers):
        """PRD §3.4: "a `SWAP` event adds a flat 2500-cent exchange fee on top
        of the same metered energy charge" — 50 kWh costs 2500 + 50*12 = 3100
        cents; 0 kWh costs exactly the 2500-cent fee.

        Design: Corner/calculations/fuel_swap_fee_math
        """
        unit = make_unit(serial_number="SN-CAL1", model="8FBCU25",
                         power_type="BATTERY", daily_rate_cents=16000,
                         weekly_rate_cents=75000, monthly_rate_cents=220000)
        resp = api.create_fuel_event(unit["id"], {"event_type": "SWAP",
                                                  "kwh": 50},
                                     fleet_manager_headers)
        assert validate_success(resp, 201)["cost_cents"] == 3100
        resp = api.create_fuel_event(unit["id"], {"event_type": "SWAP",
                                                  "kwh": 0},
                                     fleet_manager_headers)
        assert validate_success(resp, 201)["cost_cents"] == 2500

    def test_fuel_program_mismatch_rejected(self, api, fleet_manager_headers):
        """PRD §3.4: "the two programs are not interchangeable: an event type
        that does not match the unit's program is rejected with
        `ERR_FUEL_PROGRAM_MISMATCH`."

        Design: Corner/validations/fuel_program_mismatch_rejected
        """
        unit = make_unit(serial_number="SN-V3")  # LP unit
        resp = api.create_fuel_event(unit["id"], {"event_type": "CHARGE",
                                                  "kwh": 50},
                                     fleet_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FUEL_PROGRAM_MISMATCH, 422)
        listed = validate_success(api.list_fuel_events(unit["id"],
                                                       fleet_manager_headers))
        assert listed == [], "rejected fuel event must not be persisted"
