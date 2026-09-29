"""Wet weather, frost law and the suspension loop."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_shutdown_order,
    build_network,
    declare_shutdown,
    dispatch_load,
    lift_shutdown,
    list_shutdown_orders,
    read_crew,
    read_crew_assignment,
    read_load,
    read_mill_contract,
    read_shutdown_order,
    read_tract,
    validate_error,
    validate_success,
)


class TestShutdownCascade:
    def test_declaring_a_shutdown_suspends_the_tract_and_stands_the_crew_down(
        self, api, ops_headers
    ):
        """PRD §3.5: "Hop one creates the order and moves the tract
        `ACTIVE → SUSPENDED`, incrementing the tract's `suspension_count` by 1."
        PRD §3.5: "Hop two-a: because the tract became `SUSPENDED`, every crew
        assignment on it in `WORKING` moves to `STOOD_DOWN`, and hop three-a follows —
        because an assignment stood down, its crew moves `ON_TRACT → STOOD_DOWN`."

        Design: Difficulty/transitive_cascade/shutdown_cascade_tract_then_load_then_contract_reopens
        """
        scn = build_network(contract={"quota_tons": 26.5})
        dispatch_load(scn)

        order = declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=85)

        assert_shutdown_order(order)
        assert order["status"] == "ACTIVE"
        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "SUSPENDED"
        assert tract["suspension_count"] == 1
        assert read_crew_assignment(scn["ca_id"])["status"] == "STOOD_DOWN"
        assert read_crew(scn["crew_id"])["status"] == "STOOD_DOWN"

    def test_the_shutdown_cancels_the_in_flight_load_and_reopens_the_filled_contract(
        self, api, ops_headers
    ):
        """PRD §3.5: "Hop two-b runs in parallel over the wood: because the tract
        became `SUSPENDED`, every load off that tract whose `dispatch_status` is
        `DISPATCHED` or `IN_TRANSIT` moves to `CANCELLED`."
        PRD §3.5: "Hop three-b: because those loads were cancelled, each mill contract
        they drew against loses the cancelled load's `estimated_net_tons` from
        `reserved_tons` and recomputes `available_tons`. Hop four-b: because that
        recomputed `available_tons` rose above zero, a contract that had gone `FILLED`
        returns to `OPEN`."
        PRD §3.7: "A cancelled load's `settlement_status` stays `UNSETTLED` forever —
        cancelled wood never enters a settlement statement."

        Design: Difficulty/transitive_cascade/shutdown_cascade_tract_then_load_then_contract_reopens
        """
        scn = build_network(contract={"quota_tons": 26.5})
        load = dispatch_load(scn)
        assert read_mill_contract(scn["mc_a_id"])["status"] == "FILLED"

        declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=85)

        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "CANCELLED"
        assert load_row["settlement_status"] == "UNSETTLED"

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["delivered_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(26.50, abs=0.005)
        assert contract["status"] == "OPEN"


class TestSuspensionLoop:
    def test_one_lap_of_the_loop_returns_the_tract_and_its_crew_to_work(
        self, api, ops_headers
    ):
        """PRD §3.5: "On success the order's `status` becomes `LIFTED`, `lifted_at` is
        stamped from the logical clock, and `lift_soil_moisture_index` stores the
        supplied reading."
        PRD §3.5: "Because the order was lifted and no other `ACTIVE` order remains on
        the tract, the tract returns `SUSPENDED → ACTIVE`; because the tract returned
        to `ACTIVE`, every crew assignment on it in `STOOD_DOWN` returns to `WORKING`;
        and because those assignments returned to `WORKING`, their crews return
        `STOOD_DOWN → ON_TRACT`."

        Design: Difficulty/non_linear_state_machine/tract_active_suspended_active_loop_twice_with_suspension_counter
        """
        scn = build_network()

        order = declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=80)
        lift_shutdown(scn, order["id"], soil_moisture_index=60)

        lifted = read_shutdown_order(scn["tract_id"], order["id"])
        assert lifted["status"] == "LIFTED"
        assert lifted["lift_soil_moisture_index"] == 60

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "ACTIVE"
        assert tract["suspension_count"] == 1
        assert read_crew_assignment(scn["ca_id"])["status"] == "WORKING"
        assert read_crew(scn["crew_id"])["status"] == "ON_TRACT"

    def test_two_laps_leave_the_tract_active_with_a_suspension_count_of_two(
        self, api, ops_headers
    ):
        """PRD §3.5: "This is a genuine loop. A tract may run
        `ACTIVE → SUSPENDED → ACTIVE` as many times as the weather demands, and
        `suspension_count` records how many laps were run."
        PRD §3.5: "Orders declared for the other three reasons carry no moisture
        threshold."

        Design: Difficulty/non_linear_state_machine/tract_active_suspended_active_loop_twice_with_suspension_counter
        """
        scn = build_network()

        first = declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=80)
        lift_shutdown(scn, first["id"], soil_moisture_index=60)
        second = declare_shutdown(scn, reason="FIRE_DANGER", soil_moisture_index=90)
        lift_shutdown(scn, second["id"], soil_moisture_index=90)

        assert read_shutdown_order(scn["tract_id"], first["id"])["status"] == "LIFTED"
        second_row = read_shutdown_order(scn["tract_id"], second["id"])
        assert second_row["status"] == "LIFTED"
        assert second_row["lift_soil_moisture_index"] == 90

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "ACTIVE"
        assert tract["suspension_count"] == 2
        assert read_crew_assignment(scn["ca_id"])["status"] == "WORKING"
        assert read_crew(scn["crew_id"])["status"] == "ON_TRACT"


class TestMoistureThresholds:
    def test_wet_weather_declaration_below_the_threshold_is_refused(
        self, api, ops_headers
    ):
        """PRD §3.5: "A `WET_WEATHER` order carries one further precondition: the
        supplied `soil_moisture_index` must be **at least 72**, since below that
        reading the ground is not wet enough to justify a shutdown, and a declaration
        below the threshold is refused with `ERR_WET_THRESHOLD_NOT_MET`."
        PRD §3.5: "Orders declared for the other three reasons carry no moisture
        threshold."

        Design: Corner/validations/declaring_a_wet_weather_shutdown_below_the_moisture_threshold_is_rejected
        """
        scn = build_network()

        refused = api.create_shutdown_order(
            scn["tract_id"],
            {"reason": "WET_WEATHER", "soil_moisture_index": 71},
            ops_headers,
        )
        validate_error(refused, ApiErrorId.ERR_WET_THRESHOLD_NOT_MET.value, 422)

        admitted = validate_success(
            api.create_shutdown_order(
                scn["tract_id"],
                {"reason": "FIRE_DANGER", "soil_moisture_index": 71},
                ops_headers,
            ),
            201,
        )
        assert admitted["status"] == "ACTIVE"
        assert admitted["reason"] == "FIRE_DANGER"

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "SUSPENDED"
        assert tract["suspension_count"] == 1
        assert read_crew_assignment(scn["ca_id"])["status"] == "STOOD_DOWN"

    def test_lifting_a_wet_weather_order_at_exactly_seventy_two_is_refused(
        self, api, ops_headers
    ):
        """PRD §3.5: "For a `WET_WEATHER` order, the supplied reading must be
        **strictly below 72**; a lift attempted while the reading is still 72 or above
        is refused with `ERR_WET_THRESHOLD_STILL_MET`."

        Design: Corner/state_machines/lifting_a_wet_weather_order_at_moisture_seventy_two_is_refused
        """
        scn = build_network()
        order = declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=90)

        response = api.lift_shutdown_order(
            order["id"], {"soil_moisture_index": 72}, ops_headers
        )
        validate_error(response, ApiErrorId.ERR_WET_THRESHOLD_STILL_MET.value, 422)

        still_active = read_shutdown_order(scn["tract_id"], order["id"])
        assert still_active["status"] == "ACTIVE"
        assert still_active.get("lift_soil_moisture_index") is None

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "SUSPENDED"
        assert tract["suspension_count"] == 1

    def test_lifting_an_already_lifted_order_is_refused(self, api, ops_headers):
        """PRD §3.5: "The order must still be `ACTIVE`, or the call is refused with
        `ERR_INVALID_SHUTDOWN_ORDER_STATE`, and its tract must be `SUSPENDED`."

        Design: Corner/state_machines/lifting_an_already_lifted_shutdown_order_returns_invalid_state
        """
        scn = build_network()
        order = declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=88)
        lift_shutdown(scn, order["id"], soil_moisture_index=40)

        response = api.lift_shutdown_order(
            order["id"], {"soil_moisture_index": 30}, ops_headers
        )
        validate_error(response, ApiErrorId.ERR_INVALID_SHUTDOWN_ORDER_STATE.value, 409)

        lifted = read_shutdown_order(scn["tract_id"], order["id"])
        assert lifted["status"] == "LIFTED"
        assert lifted["lift_soil_moisture_index"] == 40

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "ACTIVE"
        assert tract["suspension_count"] == 1

    def test_second_shutdown_on_a_suspended_tract_reports_the_existing_order(
        self, api, ops_headers
    ):
        """PRD §2.7: "This rung sits deliberately **above** the tract-state rung that
        follows it, so a second shutdown declared on an already-suspended tract reports
        the existing order rather than the tract's `SUSPENDED` status."
        PRD §3.5: "Declaring an order requires the tract to be `ACTIVE` and requires
        that the tract carry no other order still `ACTIVE` — and as §2.7 sets out, the
        duplicate-order check runs *first*, so a second declaration against an
        already-suspended tract reports `ERR_ACTIVE_SHUTDOWN_ORDER` rather than
        `ERR_INVALID_TRACT_STATE`."

        Design: Corner/state_machines/declaring_a_second_shutdown_while_one_is_active_returns_active_shutdown_order
        """
        scn = build_network()
        first = declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=85)

        response = api.create_shutdown_order(
            scn["tract_id"],
            {"reason": "FIRE_DANGER", "soil_moisture_index": 10},
            ops_headers,
        )
        error = validate_error(response, ApiErrorId.ERR_ACTIVE_SHUTDOWN_ORDER.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_TRACT_STATE.value

        assert read_shutdown_order(scn["tract_id"], first["id"])["status"] == "ACTIVE"
        assert len(list_shutdown_orders(scn["tract_id"])) == 1

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "SUSPENDED"
        assert tract["suspension_count"] == 1
        assert read_crew_assignment(scn["ca_id"])["status"] == "STOOD_DOWN"
        assert read_crew(scn["crew_id"])["status"] == "STOOD_DOWN"
