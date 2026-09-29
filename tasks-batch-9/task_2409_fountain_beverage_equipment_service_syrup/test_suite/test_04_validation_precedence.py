"""Two requests that break two rules at once, checking which rule answers.

The validation ladder of §2.6 fixes the answer in both cases: the frozen-posture
rung outranks the pool-sufficiency rung on an allocation, and the van-window rung
outranks the part-availability rung on a dispatch.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    activate_agreement,
    add_stop,
    add_telemetry,
    allocation_payload,
    ApiErrorId,
    create_agreement,
    create_call,
    create_outlet,
    create_position,
    create_route,
    create_supply_item,
    create_unit,
    create_van_stock,
    dispatch_call,
    dispatch_call_payload,
    place_compliance_hold,
    pin_clock,
    read_call,
    read_outlet,
    read_position,
    read_route,
    read_stop,
    read_supply_item,
    read_van_stock,
    run_forecast,
    TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
OFFICER = TEST_USERS["officer_headers"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_alt_headers"]


def _frozen_outlet_with_an_exhausted_pool():
    """A CRITICAL position on a FROZEN outlet whose SKU pool holds only 2 units."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Zoo Pavilion Cafe",
        account_code="ACCT-PP-A",
        region_code="R9",
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
        outlet["id"], agreement["id"], serial_number="SN-PP-A-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code="SCARCE_CART",
        brand_name="Fanta",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=2,
    )
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-31T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], 6)
    forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    held = place_compliance_hold(outlet["id"], OFFICER, "SANITATION_AUDIT_FAIL")
    route = create_route(
        route_code="RT-PP-1",
        depot_region_code="R9",
        service_date="2026-08-02T00:00:00Z",
        van_code="V-51",
        capacity_units=500,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1, "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z"
    )
    return {
        "outlet": outlet,
        "item": item,
        "position": position,
        "forecast": forecast,
        "held": held,
        "route": route,
        "stop": stop,
    }


def _van_with_one_part_already_reserved():
    """Van V-88 holds a single VALVE_KIT_7 unit, already reserved by a 09:00-11:00 call."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Bowling Center Grill",
        account_code="ACCT-PP-B",
        region_code="R10",
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
        outlet["id"], agreement["id"], serial_number="SN-PP-B-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    stock = create_van_stock("V-88", "VALVE_KIT_7", 1)
    first = create_call(unit["id"], "LEAK", "2026-08-01T00:00:00Z")
    second = create_call(unit["id"], "OFF_RATIO", "2026-08-01T00:00:00Z")
    first = dispatch_call(
        first["id"], "V-88", "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z", TECH,
        part_sku="VALVE_KIT_7", part_units=1,
    )
    return stock, first, second


class TestFrozenPostureOutranksPoolExhaustion:
    def test_frozen_posture_answers_before_the_pool_is_ever_measured(self, api):
        """PRD §3.7: "Allocation is refused outright with
        `ERR_OUTLET_POSTURE_FROZEN` when the stop's outlet is `FROZEN`, checked
        before the waterfall is ever entered."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_allocation_pool_exhausted
        """
        scenario = _frozen_outlet_with_an_exhausted_pool()
        assert scenario["forecast"]["requested_units"] == 34
        assert scenario["forecast"]["alert_level"] == "CRITICAL"
        assert scenario["held"]["service_posture"] == "FROZEN"

        response = api.allocate_stop(
            scenario["stop"]["id"],
            allocation_payload([scenario["position"]["id"]]),
            PLANNER,
        )
        body = validate_error(response, ApiErrorId.ERR_OUTLET_POSTURE_FROZEN.value, 409)
        assert body["error_id"] != ApiErrorId.ERR_ALLOCATION_POOL_EXHAUSTED.value

    def test_the_refused_allocation_persists_nothing(self, api):
        """PRD §2.6: "Checks are evaluated in the following priority order, and the
        first failure terminates the request. Nothing is persisted when a request
        fails at any rung of this ladder."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_allocation_pool_exhausted
        """
        scenario = _frozen_outlet_with_an_exhausted_pool()

        api.allocate_stop(
            scenario["stop"]["id"],
            allocation_payload([scenario["position"]["id"]]),
            PLANNER,
        )

        position = read_position(scenario["position"]["id"])
        assert position["allocated_units"] == 0
        assert position["planned_route_stop_id"] is None

        item = read_supply_item(scenario["item"]["id"])
        assert item["reserved_pool_units"] == 0
        assert item["national_allocation_units"] == 2

        assert read_route(scenario["route"]["id"])["committed_units"] == 0

        stop = read_stop(scenario["stop"]["id"])
        assert stop["status"] == "PENDING"
        assert stop["version"] == 1

        outlet = read_outlet(scenario["outlet"]["id"])
        assert outlet["open_compliance_hold_count"] == 1
        assert outlet["service_posture"] == "FROZEN"


class TestVanWindowConflictOutranksPartShortage:
    def test_the_travel_buffer_conflict_answers_before_the_part_count(self, api):
        """PRD §2.6: "**Van window clash.** The requested van window must not
        collide with another `DISPATCHED` or `ON_SITE` call on the same van under
        the closed-interval, 30-minute-buffer rule of §2.9, otherwise
        `ERR_VAN_WINDOW_CONFLICT` (409) on
        `POST /fountain-network/service-calls/{id}/dispatch`."

        Design: Difficulty/priority_pair_validation_conflict/van_window_conflict_outranks_insufficient_van_parts
        """
        stock, _first, second = _van_with_one_part_already_reserved()
        assert read_van_stock(stock["id"])["on_van_units"] == 0

        response = api.dispatch_service_call(
            second["id"],
            dispatch_call_payload(
                "V-88", "2026-08-01T11:20:00Z", "2026-08-01T12:20:00Z",
                part_sku="VALVE_KIT_7", part_units=1,
            ),
            TECH_ALT,
        )
        body = validate_error(response, ApiErrorId.ERR_VAN_WINDOW_CONFLICT.value, 409)
        assert body["error_id"] != ApiErrorId.ERR_INSUFFICIENT_VAN_PARTS.value

    def test_the_refused_dispatch_leaves_call_and_van_ledger_untouched(self, api):
        """PRD §2.11: "For every van part stock row, the sum of `on_van_units`,
        `reserved_units` and `consumed_units` equals the sum of `initial_units` and
        `restocked_units`."

        Design: Difficulty/priority_pair_validation_conflict/van_window_conflict_outranks_insufficient_van_parts
        """
        stock, first, second = _van_with_one_part_already_reserved()

        api.dispatch_service_call(
            second["id"],
            dispatch_call_payload(
                "V-88", "2026-08-01T11:20:00Z", "2026-08-01T12:20:00Z",
                part_sku="VALVE_KIT_7", part_units=1,
            ),
            TECH_ALT,
        )

        refused = read_call(second["id"])
        assert refused["status"] == "OPEN"
        assert refused["van_code"] is None
        assert refused["reserved_part_units"] == 0
        assert refused["version"] == 1

        holder = read_call(first["id"])
        assert holder["status"] == "DISPATCHED"
        assert holder["assigned_tech_user_id"] == TECH["X-User-ID"]

        ledger = read_van_stock(stock["id"])
        assert ledger["on_van_units"] == 0
        assert ledger["reserved_units"] == 1
        assert ledger["consumed_units"] == 0
        assert ledger["initial_units"] == 1
        assert (
            ledger["on_van_units"] + ledger["reserved_units"] + ledger["consumed_units"]
            == ledger["initial_units"] + ledger["restocked_units"] == 1
        )
