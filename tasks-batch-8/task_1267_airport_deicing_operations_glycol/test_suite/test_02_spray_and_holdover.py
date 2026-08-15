"""Tests for spray execution, holdover computation, and collection percentage."""
import pytest

from test_helpers import (

    ApiErrorId,
    TEST_USERS,
    complete_operation,
    create_airline,
    create_and_activate_weather_event,
    create_deice_request_payload,
    create_fluid_tank,
    create_reserved_request,
    create_station,
    get_operation_for_request,
    make_airline_rep_headers,
    record_acceptance_inspection,
    setup_operation_awaiting_inspection,
    setup_operation_cleared,
    setup_operation_spraying,
    setup_operational_base,
    setup_request_assigned,
    start_operation,
    validate_error,
    validate_success,
)


class TestHoldoverTableVariant:
    def test_holdover_type_i_snow_light_uses_table_constant(self, api):
        """PRD §3.5: "For `TYPE_I` fluid at any concentration: 45 minutes with no
        active precipitation, 25 in `SNOW`, 15 in `FREEZING_FOG`, 9 in
        `FREEZING_RAIN`, and 12 in `MIXED` conditions." And: "When no event is
        active, or the active event's rate is `LIGHT` (whose factor is 1.0), the
        `TABLE` variant applies and the temperature-adjusted base stands as-is."

        Design: Corner/calculations/holdover_type_i_snow_light_uses_table_constant
        """
        station, permit, tank, pad, airline = setup_operational_base()
        create_and_activate_weather_event(
            station["id"],
            precip_type="SNOW",
            precip_rate="LIGHT",
            severity="LEVEL_1",
        )
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")
        from test_helpers import assign_request_payload
        payload = assign_request_payload(pad["id"])
        api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        operation = get_operation_for_request(request["id"])
        record_acceptance_inspection(operation["id"], inspector_id="insp-1")

        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": -5},
            TEST_USERS["pad_operator_headers"],
        )
        data = validate_success(resp)
        assert data["holdover_variant"] == "TABLE"
        assert data["holdover_minutes"] == 25

    def test_holdover_table_vs_rate_adjusted(self, api):
        """PRD §3.5: "a `TYPE_IV` operation at 100 percent concentration spraying
        in `SNOW` with the thermometer at minus five degrees records 60 minutes
        under `TABLE`, but only 30 minutes when a `HEAVY` event is active and
        `RATE_ADJUSTED` applies."

        Design: Difficulty/dual_variant_calc/holdover_table_vs_rate_adjusted
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "fluid_type": "TYPE_IV",
                "concentration_pct": 100,
                "capacity_liters": 50000,
                "on_hand_liters": 20000,
                "reorder_threshold_liters": 300,
            },
            pad_overrides={"max_size_class": "LARGE"},
        )
        create_and_activate_weather_event(
            station["id"],
            precip_type="SNOW",
            precip_rate="HEAVY",
            severity="LEVEL_1",
        )
        request = create_reserved_request(
            airline, station, tank, size_class="LARGE", fluid_type="TYPE_IV"
        )
        from test_helpers import assign_request_payload
        payload = assign_request_payload(pad["id"])
        api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        operation = get_operation_for_request(request["id"])
        record_acceptance_inspection(operation["id"], inspector_id="insp-1")

        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": -5},
            TEST_USERS["pad_operator_headers"],
        )
        data = validate_success(resp)
        assert data["holdover_variant"] == "RATE_ADJUSTED"
        assert data["holdover_minutes"] == 30
        assert data["holdover_minutes"] != 60

    def test_holdover_multi_input_conditional_lookup(self, api):
        """PRD §3.5: "For `TYPE_IV` at 75 percent: 80, 35, 25, 15, and 18."
        "when the outside air temperature is at or below minus ten degrees
        Celsius, the base is multiplied by 0.8." "0.5 for `HEAVY`."

        Design: Difficulty/combinatorial_formula/holdover_multi_input_conditional_lookup
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "fluid_type": "TYPE_IV",
                "concentration_pct": 75,
                "capacity_liters": 50000,
                "on_hand_liters": 20000,
                "reorder_threshold_liters": 300,
            },
            pad_overrides={"max_size_class": "LARGE"},
        )
        create_and_activate_weather_event(
            station["id"],
            precip_type="SNOW",
            precip_rate="HEAVY",
            severity="LEVEL_1",
        )
        request = create_reserved_request(
            airline, station, tank, size_class="LARGE", fluid_type="TYPE_IV"
        )
        from test_helpers import assign_request_payload
        payload = assign_request_payload(pad["id"])
        api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        operation = get_operation_for_request(request["id"])
        record_acceptance_inspection(operation["id"], inspector_id="insp-1")

        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": -12},
            TEST_USERS["pad_operator_headers"],
        )
        data = validate_success(resp)
        # 35 * 0.8 * 0.5 = 14.0, floor 5 not binding.
        assert data["holdover_minutes"] == 14
        assert data["holdover_variant"] == "RATE_ADJUSTED"


class TestHoldoverVariantSelection:
    def test_holdover_table_variant_without_active_event(self, api):
        """PRD §3.5: "When no event is active, or the active event's rate is
        `LIGHT` (whose factor is 1.0), the `TABLE` variant applies and the
        temperature-adjusted base stands as-is."

        Design: Difficulty/dual_variant_calc/holdover_table_vs_rate_adjusted
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "fluid_type": "TYPE_IV",
                "concentration_pct": 100,
                "capacity_liters": 50000,
                "on_hand_liters": 20000,
                "reorder_threshold_liters": 300,
            },
            pad_overrides={"max_size_class": "LARGE"},
        )
        # No weather event created — TABLE variant applies.
        request = create_reserved_request(
            airline, station, tank, size_class="LARGE", fluid_type="TYPE_IV"
        )
        from test_helpers import assign_request_payload
        payload = assign_request_payload(pad["id"])
        api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        operation = get_operation_for_request(request["id"])
        record_acceptance_inspection(operation["id"], inspector_id="insp-1")

        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": -5},
            TEST_USERS["pad_operator_headers"],
        )
        data = validate_success(resp)
        assert data["holdover_variant"] == "TABLE"
        # TYPE_IV at 100% with no active precipitation reads 120 from the
        # table; at -5 C (warmer than -10) the temperature factor is 1.0.
        assert data["holdover_minutes"] == 120

    def test_holdover_multi_input_floor_applies(self, api):
        """PRD §3.5: "Either way, the result is rounded half-up to whole minutes
        after all multipliers, and a floor of five minutes is applied so that
        `holdover_minutes` never lands below 5."

        Design: Difficulty/combinatorial_formula/holdover_multi_input_conditional_lookup
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "fluid_type": "TYPE_IV",
                "concentration_pct": 50,
                "capacity_liters": 50000,
                "on_hand_liters": 20000,
                "reorder_threshold_liters": 300,
            },
            pad_overrides={"max_size_class": "LARGE"},
        )
        # FREEZING_RAIN base is 7; cold factor 0.8 and HEAVY 0.5 would give 2.8,
        # but the floor of 5 applies.
        create_and_activate_weather_event(
            station["id"],
            precip_type="FREEZING_RAIN",
            precip_rate="HEAVY",
            severity="LEVEL_1",
        )
        request = create_reserved_request(
            airline, station, tank, size_class="LARGE", fluid_type="TYPE_IV"
        )
        from test_helpers import assign_request_payload
        payload = assign_request_payload(pad["id"])
        api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        operation = get_operation_for_request(request["id"])
        record_acceptance_inspection(operation["id"], inspector_id="insp-1")

        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": -12},
            TEST_USERS["pad_operator_headers"],
        )
        data = validate_success(resp)
        # 7 * 0.8 * 0.5 = 2.8 → floor 5.
        assert data["holdover_minutes"] == 5
        assert data["holdover_variant"] == "RATE_ADJUSTED"


class TestAcceptanceGate:
    def test_acceptance_fail_does_not_enable_start(self, api):
        """PRD §3.5: "An acceptance inspection with result `PASS` must already
        exist for the operation; starting without one is rejected with
        `ERR_ACCEPTANCE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/operation_start_requires_acceptance_pass
        """
        station, permit, tank, pad, airline, request, operation = setup_request_assigned()

        # An ACCEPTANCE FAIL does not satisfy the gate.
        from test_helpers import create_inspection_payload, make_inspector_headers
        resp = api.create_inspection(
            create_inspection_payload(operation["id"], kind="ACCEPTANCE", result="FAIL"),
            make_inspector_headers("insp-1"),
        )
        validate_success(resp, expected_status=201)

        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": 0},
            TEST_USERS["pad_operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_REQUIRED)

    def test_operation_start_requires_acceptance_pass(self, api):
        """PRD §3.5: "An acceptance inspection with result `PASS` must already
        exist for the operation; starting without one is rejected with
        `ERR_ACCEPTANCE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/operation_start_requires_acceptance_pass
        """
        station, permit, tank, pad, airline, request, operation = setup_request_assigned()

        # Start without acceptance inspection.
        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": 0},
            TEST_USERS["pad_operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_REQUIRED)

        resp = api.get_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "PLANNED"

        # After ACCEPTANCE PASS, start succeeds.
        record_acceptance_inspection(operation["id"], inspector_id="insp-1")
        resp = api.start_deice_operation(
            operation["id"],
            {"oat_celsius": 0},
            TEST_USERS["pad_operator_headers"],
        )
        assert validate_success(resp)["status"] == "SPRAYING"

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "IN_PROGRESS"


class TestCollectionPercentage:
    def test_collection_pct_below_minimum_flagged(self, api):
        """PRD §3.5: "`collection_flag`, which is `OK` when the percentage meets
        or exceeds the station's `min_collection_pct` — a reading exactly equal
        to the minimum passes — and `BELOW_MINIMUM` otherwise."

        Design: Difficulty/boundary_precision_check/collection_pct_at_exactly_minimum_passes
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_spraying()
        )
        data = complete_operation(operation["id"], actual_liters=200, collected_liters=99)
        assert data["collection_pct"] == 49.5
        assert data["collection_flag"] == "BELOW_MINIMUM"

    def test_collection_pct_at_exactly_minimum_passes(self, api):
        """PRD §3.5: "`collection_flag`, which is `OK` when the percentage meets
        or exceeds the station's `min_collection_pct` — a reading exactly equal
        to the minimum passes — and `BELOW_MINIMUM` otherwise."

        Design: Difficulty/boundary_precision_check/collection_pct_at_exactly_minimum_passes
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "capacity_liters": 50000,
                "on_hand_liters": 20000,
                "reorder_threshold_liters": 300,
            }
        )
        # Op1: exactly at minimum (50.0).
        r1 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA1", scheduled_departure="2026-05-01T12:00:00Z"
        )
        from test_helpers import assign_request_payload
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:00:00Z",
            window_end="2026-05-01T10:30:00Z",
        )
        api.assign_deice_request(
            r1["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op1 = get_operation_for_request(r1["id"])
        record_acceptance_inspection(op1["id"], inspector_id="insp-1")
        start_operation(op1["id"], oat_celsius=0)
        data1 = complete_operation(op1["id"], actual_liters=200, collected_liters=100)
        assert data1["collection_pct"] == 50.0
        assert data1["collection_flag"] == "OK"

        from test_helpers import record_post_treatment_inspection
        record_post_treatment_inspection(op1["id"], result="PASS", inspector_id="insp-2")

        # Op2: just below minimum (49.5).
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op2 = get_operation_for_request(r2["id"])
        record_acceptance_inspection(op2["id"], inspector_id="insp-1")
        start_operation(op2["id"], oat_celsius=0)
        data2 = complete_operation(op2["id"], actual_liters=200, collected_liters=99)
        assert data2["collection_pct"] == 49.5
        assert data2["collection_flag"] == "BELOW_MINIMUM"

    def test_collection_pct_precision_two_thirds(self, api):
        """PRD §2.5: "Percentages derived at runtime, such as an operation's
        collection percentage, are rounded half-up to exactly two decimal
        places."

        Design: Corner/calculations/collection_pct_precision_two_thirds
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_spraying()
        )
        data = complete_operation(operation["id"], actual_liters=3, collected_liters=2)
        assert data["collection_pct"] == 66.67
        assert data["collection_flag"] == "OK"


class TestCompleteValidation:
    def test_complete_from_planned_returns_invalid_state(self, api):
        """PRD §3.5: "Completion is recorded by the `PadOperator` with the
        `actual_liters` sprayed and the `collected_liters` recovered by the
        pad's collection system, moving the operation from `SPRAYING` to
        `AWAITING_INSPECTION`." A PLANNED operation is not SPRAYING.

        Design: Corner/state_machines/complete_from_planned_returns_invalid_state
        """
        station, permit, tank, pad, airline, request, operation = setup_request_assigned(
            tank_overrides={
                "capacity_liters": 10000,
                "on_hand_liters": 5000,
                "reorder_threshold_liters": 300,
            }
        )
        assert operation["status"] == "PLANNED"

        resp = api.complete_deice_operation(
            operation["id"],
            {"actual_liters": 100, "collected_liters": 60},
            TEST_USERS["pad_operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # No side effects fired.
        resp = api.get_fluid_tank(tank["id"], TEST_USERS["pad_operator_headers"])
        assert validate_success(resp)["on_hand_liters"] == 5000


class TestCreditLimitGate:
    def test_credit_limit_exceeded_on_request_create(self, api):
        """PRD §3.3: "The airline's outstanding exposure — its
        `outstanding_balance_cents` — plus the new request's estimated charge
        must not exceed the airline's `credit_limit_cents`. The estimated charge
        is deliberately simple: the `estimated_liters` multiplied by the base
        per-liter rate for the requested fluid type — 90 cents per liter for
        `TYPE_I` and 140 cents per liter for `TYPE_IV` — with no tier multiplier
        and no storm surcharge. If the sum exceeds the credit limit, creation is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Corner/errors/credit_limit_exceeded_on_request_create
        """
        station = create_station()
        create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=5000,
            reorder_threshold_liters=300,
        )
        airline = create_airline(credit_limit_cents=1000)

        payload = create_deice_request_payload(
            airline["id"], station["id"], size_class="MEDIUM"
        )
        resp = api.create_deice_request(
            payload, make_airline_rep_headers(airline["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
