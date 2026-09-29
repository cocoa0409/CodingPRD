"""Round trips that must leave a conserved total exactly where it started.

A van part row is walked through dispatch, escalation, re-dispatch and resolution
at three different reservation sizes; a supply item's national pool is walked
through an allocation and a route cancellation. Neither conserved total moves.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    activate_agreement,
    add_stop,
    add_telemetry,
    allocate,
    arrive_call,
    cancel_route_payload,
    create_agreement,
    create_call,
    create_outlet,
    create_position,
    create_route,
    create_supply_item,
    create_unit,
    create_van_stock,
    dispatch_call,
    escalate_call,
    pin_clock,
    read_call,
    read_position,
    read_route,
    read_stop,
    read_supply_item,
    read_van_stock,
    resolve_call,
    restock_van,
    route_version,
    run_forecast,
    TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
TECH = TEST_USERS["technician_headers"]


def _restocked_van_and_an_open_call():
    """Van V-12 loaded with 5 pump assemblies and restocked by 3, plus one NO_POUR call."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Truck Stop Diner 6",
        account_code="ACCT-CI-A",
        region_code="R17",
        throughput_tier="LARGE",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=9000,
        equipment_value_cents=520000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=45,
    )
    unit = create_unit(
        outlet["id"], agreement["id"], serial_number="SN-CI-A-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    stock = create_van_stock("V-12", "PUMP_ASSY_12", 5)
    stock = restock_van(stock["id"], 3)
    call = create_call(unit["id"], "NO_POUR", "2026-08-01T00:00:00Z")
    return stock, call


def _allocated_stop_on_a_planned_route():
    """A PLANNED route holding a 32-unit allocation drawn from a 1000-unit pool."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Ballpark Bleacher Bar",
        account_code="ACCT-CI-B",
        region_code="R18",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"], agreement["id"], serial_number="SN-CI-B-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code="COKE_CART_CI",
        brand_name="Coca-Cola",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=1000,
    )
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-31T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], 6)
    forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    route = create_route(
        route_code="RT-CI-1",
        depot_region_code="R18",
        service_date="2026-08-02T00:00:00Z",
        van_code="V-21",
        capacity_units=500,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1, "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z"
    )
    allocation = allocate(stop["id"], [position["id"]])
    return {
        "item": item,
        "position": position,
        "forecast": forecast,
        "route": route,
        "stop": stop,
        "allocation": allocation,
    }


def _van_total(row):
    return row["on_van_units"] + row["reserved_units"] + row["consumed_units"]


class TestVanPartsConservation:
    def test_every_bucket_move_preserves_the_loaded_total(self, api):
        """PRD §2.11: "Units move between the three live buckets and are never minted
        or destroyed: a dispatch reservation moves units from `on_van_units` into
        `reserved_units`; an escalation or a cancellation moves the whole held
        reservation back from `reserved_units` into `on_van_units`; a resolution
        clears the reservation, credits the fitted quantity to `consumed_units` and
        returns the unfitted remainder to `on_van_units`; and a restock raises
        `on_van_units` and `restocked_units` together, which is the only operation
        that raises the conserved total."

        Design: Difficulty/compensating_invariant/van_parts_conserved_across_dispatch_escalate_redispatch_resolve
        """
        stock, call = _restocked_van_and_an_open_call()
        loaded = read_van_stock(stock["id"])
        assert loaded["on_van_units"] == 8
        assert _van_total(loaded) == 8

        dispatch_call(
            call["id"], "V-12", "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        after_dispatch = read_van_stock(stock["id"])
        assert (after_dispatch["on_van_units"], after_dispatch["reserved_units"],
                after_dispatch["consumed_units"]) == (6, 2, 0)

        arrive_call(call["id"], TECH)
        escalate_call(call["id"], "WRONG_PART", TECH)
        after_escalation = read_van_stock(stock["id"])
        assert (after_escalation["on_van_units"], after_escalation["reserved_units"],
                after_escalation["consumed_units"]) == (8, 0, 0)
        assert read_call(call["id"])["reserved_part_stock_id"] is None

        dispatch_call(
            call["id"], "V-12", "2026-08-01T13:00:00Z", "2026-08-01T15:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=3,
        )
        after_redispatch = read_van_stock(stock["id"])
        assert (after_redispatch["on_van_units"], after_redispatch["reserved_units"],
                after_redispatch["consumed_units"]) == (5, 3, 0)

        arrive_call(call["id"], TECH)
        resolve_call(call["id"], "PART_REPLACED", TECH, consumed_part_units=1)
        settled = read_van_stock(stock["id"])
        assert (settled["on_van_units"], settled["reserved_units"],
                settled["consumed_units"]) == (7, 0, 1)
        assert _van_total(settled) == 8

    def test_the_loading_history_is_never_rewritten_by_the_round_trip(self, api):
        """PRD §2.11: "`initial_units` is fixed at creation from the units first
        loaded onto the van and never changes thereafter."

        Design: Difficulty/compensating_invariant/van_parts_conserved_across_dispatch_escalate_redispatch_resolve
        """
        stock, call = _restocked_van_and_an_open_call()

        dispatch_call(
            call["id"], "V-12", "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        arrive_call(call["id"], TECH)
        escalate_call(call["id"], "WRONG_PART", TECH)
        dispatch_call(
            call["id"], "V-12", "2026-08-01T13:00:00Z", "2026-08-01T15:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=3,
        )
        arrive_call(call["id"], TECH)
        resolved = resolve_call(call["id"], "PART_REPLACED", TECH, consumed_part_units=1)

        final = read_van_stock(stock["id"])
        assert final["initial_units"] == 5
        assert final["restocked_units"] == 3
        assert _van_total(final) == final["initial_units"] + final["restocked_units"]

        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_code"] == "PART_REPLACED"
        assert resolved["consumed_part_units"] == 1
        assert resolved["reserved_part_units"] == 0
        assert resolved["reserved_part_stock_id"] is None
        assert resolved["escalation_count"] == 1
        assert resolved["version"] == 7


class TestNationalPoolConservation:
    def test_cancelling_the_route_skips_the_stop_and_returns_the_commitment(self, api):
        """PRD §3.7: "Cancellation moves it to `CANCELLED` from either `PLANNED` or
        `DISPATCHED`, requires `expected_route_version` and accepts an optional
        `reason_code`; it drives every stop of the route in `PENDING` or `ARRIVED` to
        `SKIPPED` with `skip_reason_code` `ACCESS_DENIED`, releases each of those
        stops' positions restoring both the SKUs' `reserved_pool_units` and the
        route's `committed_units`, and advances the route's `version` by one."

        Design: Difficulty/compensating_invariant/national_pool_conserved_across_allocation_and_route_cancel
        """
        scenario = _allocated_stop_on_a_planned_route()
        assert scenario["forecast"]["requested_units"] == 34
        assert scenario["forecast"]["alert_level"] == "CRITICAL"
        assert scenario["allocation"]["total_allocated_units"] == 32
        assert read_route(scenario["route"]["id"])["committed_units"] == 32

        cancelled = validate_success(
            api.cancel_route(
                scenario["route"]["id"],
                cancel_route_payload(
                    route_version(scenario["route"]["id"]), reason_code="DEPOT_OUTAGE"
                ),
                PLANNER,
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["committed_units"] == 0
        assert cancelled["delivered_units"] == 0

        stop = read_stop(scenario["stop"]["id"])
        assert stop["status"] == "SKIPPED"
        assert stop["skip_reason_code"] == "ACCESS_DENIED"
        assert stop["delivered_units"] == 0

    def test_the_pool_returns_to_its_pre_allocation_value(self, api):
        """PRD §2.11: "A supply item's `national_allocation_units` is never changed by
        allocation or release; across a full allocate-then-release cycle its
        `reserved_pool_units` returns to exactly its pre-allocation value, which holds
        precisely because grants are always whole multiples of `case_pack_units`."

        Design: Difficulty/compensating_invariant/national_pool_conserved_across_allocation_and_route_cancel
        """
        scenario = _allocated_stop_on_a_planned_route()
        assert read_supply_item(scenario["item"]["id"])["reserved_pool_units"] == 32

        validate_success(
            api.cancel_route(
                scenario["route"]["id"],
                cancel_route_payload(
                    route_version(scenario["route"]["id"]), reason_code="DEPOT_OUTAGE"
                ),
                PLANNER,
            )
        )

        item = read_supply_item(scenario["item"]["id"])
        assert item["reserved_pool_units"] == 0
        assert item["national_allocation_units"] == 1000

        position = read_position(scenario["position"]["id"])
        assert position["allocated_units"] == 0
        assert position["planned_route_stop_id"] is None
        assert position["on_hand_units"] == 6
        assert position["requested_units"] == 34
