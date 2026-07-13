"""The sortie: arrival, the drop, recovery, the two energy variants and the four-hop
retirement cascade."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    approve_authorization,
    assert_delivery_drop,
    assert_hours,
    assert_instant,
    assert_km,
    assert_money,
    assert_pct,
    charge_battery,
    create_order,
    dispatch_order,
    drop_flight,
    file_authorization,
    launch_flight,
    arrive_flight,
    list_maintenance_logs,
    read_battery,
    read_customer,
    read_drone,
    read_flight,
    read_nest,
    read_order,
    recover_flight,
    release_flight,
    setup_dropping_flight,
    setup_planned_flight,
    setup_recovered_flight,
    setup_returning_flight,
    setup_world,
)
from test_helpers.test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["dispatch_operator_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


def _fly_one_lap(w, order, actual_route_km=11.100):
    """Take one order from QUOTED all the way to a RECOVERED sortie on the world's airframe."""
    flight = dispatch_order(order["id"], w["nest"]["id"], order["version"])
    auth = file_authorization(flight["id"])
    approve_authorization(auth["id"])
    release_flight(flight["id"])
    launch_flight(flight["id"])
    arrive_flight(flight["id"])
    drop_flight(flight["id"])
    return recover_flight(flight["id"], actual_route_km)


# =================================================================== arrival and drop
def test_arrival_on_a_planned_flight_is_rejected(api):
    """PRD §3.7: "**Arrival over the dropoff point** moves the flight `LAUNCHED → DROPPING` and
    advances its `version`. It carries no body. Reporting arrival on a flight that is not
    `LAUNCHED` is rejected with `ERR_FLIGHT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/arrive_on_planned_flight_rejected
    """
    w = setup_planned_flight()

    resp = api.arrive_flight(w["flight"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_FLIGHT_INVALID_STATE.value)

    assert read_flight(w["flight"]["id"])["ops_state"] == "PLANNED"


def test_drop_creates_a_delivery_drop_copied_from_the_order(api):
    """PRD §3.7: "A **delivery drop** record is created for the flight: its `flight_id` names
    the sortie, its `drop_lat` and `drop_lon` are copied from the order's frozen dropoff
    coordinates (not from any coordinate the operator supplies), and `confirmed_by_user_id`
    records the operator's `X-User-ID`."
    PRD §3.7: "The flight moves `DROPPING → RETURNING` and its `version` advances. The order
    bubbles up `IN_TRANSIT → DELIVERED` and its `version` advances. And the customer's ledgers
    settle: the order's `order_total` is subtracted from `held_total` and added to
    `billed_total`, so the money leaves the authorization bucket and lands in the captured
    bucket in one step."
    PRD §3.10: "The drop confirmations of a flight are listable too — there will be either zero
    or one."

    Design: Corner/endpoints/drop_creates_delivery_drop_reachable_via_subresource
    """
    w = setup_dropping_flight()

    drop = validate_success(
        api.drop_flight(
            w["flight"]["id"], {"hover_alt_ft": 15, "photo_ref": "photo-1"}, OPERATOR
        ),
        201,
    )

    assert_delivery_drop(drop)
    assert drop["flight_id"] == w["flight"]["id"]
    assert drop["drop_lat"] == 37.05
    assert drop["drop_lon"] == -122.0
    assert drop["hover_alt_ft"] == 15
    assert drop["confirmed_by_user_id"] == "op-1"

    listed, meta = validate_paginated(
        api.list_flight_delivery_drops(
            w["flight"]["id"], make_customer_headers(w["customer"]["id"])
        )
    )
    assert meta["total_count"] == 1
    assert len(listed) == 1
    assert listed[0]["id"] == drop["id"]

    assert read_order(w["order"]["id"])["status"] == "DELIVERED"
    customer = read_customer(w["customer"]["id"])
    assert_money(customer["billed_total"], 8.96, "billed_total")
    assert_money(customer["held_total"], 0.00, "held_total")
    assert read_flight(w["flight"]["id"])["ops_state"] == "RETURNING"


def test_the_drop_cascade_is_visible_immediately_with_no_settling_delay(api):
    """PRD §2.10: "The three events that move money are dispatch (which adds the order's
    `order_total` to `held_total`), abort of a sortie whose order is `ASSIGNED` or `IN_TRANSIT`
    (which subtracts the same amount from `held_total`), and payload drop (which subtracts the
    amount from `held_total` and adds it to `billed_total`)."
    PRD §3.7: "The flight moves `DROPPING → RETURNING` and its `version` advances. The order
    bubbles up `IN_TRANSIT → DELIVERED` and its `version` advances. And the customer's ledgers
    settle: the order's `order_total` is subtracted from `held_total` and added to
    `billed_total`, so the money leaves the authorization bucket and lands in the captured
    bucket in one step."
    PRD §2.10: "Dispatch increments it by one; recovery decrements it by one; an abort from any
    non-terminal `ops_state` decrements it by one."

    Design: Corner/consistency_model/cascade_visible_in_the_same_response_immediately
    """
    w = setup_dropping_flight()

    validate_success(
        api.drop_flight(
            w["flight"]["id"], {"hover_alt_ft": 20, "photo_ref": "photo-1"}, OPERATOR
        ),
        201,
    )

    # A read issued straight afterwards already reflects the whole chain.
    assert read_order(w["order"]["id"])["status"] == "DELIVERED"
    customer = read_customer(w["customer"]["id"])
    assert_money(customer["held_total"], 0.00, "held_total")
    assert_money(customer["billed_total"], 8.96, "billed_total")

    flight = read_flight(w["flight"]["id"])
    assert flight["ops_state"] == "RETURNING"
    assert flight["clearance_state"] == "CLEARED"

    assert read_nest(w["nest"]["id"])["reserved_pads"] == 1, (
        "the pad is only freed at recovery, not at the drop"
    )


# ================================================== the two energy variants on one row
def test_dispatch_writes_the_provisional_energy_including_the_planning_reserve(api):
    """PRD §3.4: "The `planned_route_km` is twice the planar distance from the nest's
    coordinates to the order's frozen dropoff point — out and back — at three decimal places."
    PRD §3.4: "The provisional figure written to the flight as `required_energy_pct` at
    dispatch is the core consumption of the `planned_route_km`, plus 3.0 percent of hover
    allowance, plus a 15.0 percent planning reserve — the whole sum rounded half up to one
    decimal place, with no intermediate rounding."

    Design: Difficulty/dual_variant_calc/energy_provisional_vs_actual_on_flight
    """
    w = setup_planned_flight()

    flight = read_flight(w["flight"]["id"])
    assert_km(flight["planned_route_km"], 11.100, "planned_route_km")
    # 11.100 * 1.6 * 1.16 = 20.6016; + 3.0 hover + 15.0 reserve = 38.6016 -> 38.6.
    assert_pct(flight["required_energy_pct"], 38.6, "required_energy_pct")
    assert flight["actual_energy_pct"] is None, "the actual variant is null until recovery"


def test_recovery_writes_the_actual_energy_without_the_reserve_and_debits_the_pack(api):
    """PRD §3.7: "The reported route is stored and the flight's `actual_energy_pct` is computed
    with the **actual** variant of the energy formula — deliberately different from the
    provisional one. The payload factor and the wind factor are exactly as at dispatch (the
    actual variant reuses the frozen `wind_kph_at_dispatch` and the order's `payload_weight_g`;
    it never re-reads the weather feed), and the core consumption is computed on the reported
    `actual_route_km` rather than the planned one. To that core, 3.0 percent of hover allowance
    is added — and nothing else. The 15.0 percent planning reserve is a margin that is never
    consumed, and it is absent from the actual variant entirely. The sum is rounded half up to
    one decimal place. A consequence worth internalizing: feeding an `actual_route_km` exactly
    equal to the `planned_route_km` still yields two different numbers, because the reserve is
    present in one variant and not the other."
    PRD §3.7: "The installed pack moves `IN_USE → COOLDOWN`, its `cycle_count` increases by
    one, and its `charge_pct` is debited by the flight's `actual_energy_pct` — the new charge is
    the old charge minus the actual energy, rounded half up to one decimal place, and floored at
    zero so it never goes negative."

    Design: Difficulty/dual_variant_calc/energy_provisional_vs_actual_on_flight
    """
    w = setup_returning_flight()

    flight = validate_success(
        api.recover_flight(w["flight"]["id"], 11.100, OPERATOR)
    )

    assert_pct(flight["required_energy_pct"], 38.6, "required_energy_pct")
    assert_pct(flight["actual_energy_pct"], 23.6, "actual_energy_pct")
    assert_pct(
        flight["required_energy_pct"] - flight["actual_energy_pct"],
        15.0,
        "the 15.0 planning reserve is the whole difference",
    )
    assert_pct(read_battery(w["battery"]["id"])["charge_pct"], 76.4, "charge_pct")


# ==================================================== the airframe's cyclic lifecycle
def test_the_airframe_returns_to_idle_after_each_sortie(api):
    """PRD §3.7: "If the pack did not retire, the drone simply moves `IN_FLIGHT → IDLE` and is
    ready for its next sortie."
    PRD §3.4: "The winning drone moves `IDLE → RESERVED` and its `version` advances by one."
    PRD §3.6: "The drone goes `RESERVED → IN_FLIGHT` and its `version` advances."

    Design: Difficulty/non_linear_state_machine/drone_cyclic_idle_reserved_inflight_idle_twice
    """
    w = setup_recovered_flight()
    assert read_drone(w["drone"]["id"])["status"] == "IDLE", "lap 1 closes the cycle"

    charge_battery(w["battery"]["id"], 100)  # COOLDOWN -> READY closes the pack's loop
    order_2 = create_order(w["customer"]["id"], w["sa"]["id"])

    flight_2 = dispatch_order(order_2["id"], w["nest"]["id"], order_2["version"])
    assert read_drone(w["drone"]["id"])["status"] == "RESERVED"

    auth = file_authorization(flight_2["id"])
    approve_authorization(auth["id"])
    release_flight(flight_2["id"])
    launch_flight(flight_2["id"])
    assert read_drone(w["drone"]["id"])["status"] == "IN_FLIGHT"

    arrive_flight(flight_2["id"])
    drop_flight(flight_2["id"], photo_ref="photo-2")
    recover_flight(flight_2["id"], 11.100)
    assert read_drone(w["drone"]["id"])["status"] == "IDLE", "lap 2 closes the same cycle again"


def test_airframe_hours_and_pack_cycles_accumulate_across_two_laps(api):
    """PRD §3.7: "Either way, the drone's `flight_hours` and its `hours_since_service` both
    increase by the same amount — the reported `actual_route_km` divided by the airframe's
    `cruise_speed_kmh`, rounded half up to two decimal places — and the drone's `version`
    advances."
    PRD §3.2: "Charging a `COOLDOWN` pack back up to `READY` is the edge that closes the pack's
    operating cycle `READY → IN_USE → COOLDOWN → READY`, and a healthy pack goes around that
    loop until its cycles run out."

    Design: Difficulty/non_linear_state_machine/drone_cyclic_idle_reserved_inflight_idle_twice
    """
    w = setup_recovered_flight()
    drone = read_drone(w["drone"]["id"])
    assert_hours(drone["flight_hours"], 0.19, "flight_hours")
    assert_hours(drone["hours_since_service"], 0.19, "hours_since_service")

    charge_battery(w["battery"]["id"], 100)
    order_2 = create_order(w["customer"]["id"], w["sa"]["id"])
    _fly_one_lap(w, order_2)

    drone = read_drone(w["drone"]["id"])
    # 11.100 km / 60 km/h = 0.185 h -> 0.19 per lap, twice.
    assert_hours(drone["flight_hours"], 0.38, "flight_hours")
    assert_hours(drone["hours_since_service"], 0.38, "hours_since_service")

    battery = read_battery(w["battery"]["id"])
    assert battery["cycle_count"] == 2, "each recovery consumes exactly one cycle"
    assert_pct(battery["charge_pct"], 76.4, "charge_pct")


# ======================================================== the four-hop retirement cascade
def test_recovery_retires_the_pack_at_three_hundred_cycles_and_grounds_the_airframe(api):
    """PRD §3.7: "Because hop 1 incremented the cycle count, the pack is re-checked against its
    retirement life: if `cycle_count` has now reached 300 or more, the pack moves
    `COOLDOWN → RETIRED`."
    PRD §3.7: "Because hop 2 may have retired the pack, the drone's fate depends on it. If the
    pack retired, the drone's `installed_battery_id` is cleared to null and the drone moves
    `IN_FLIGHT → GROUNDED`."
    PRD §3.2: "Every pack publishes a computed `health_pct`: one hundred, minus the pack's
    `cycle_count` divided by 300 and expressed as a percentage — that is, one hundred minus one
    hundred times the ratio of `cycle_count` to 300 — rounded half up to one decimal place, and
    floored at zero so that it never goes negative."

    Design: Difficulty/transitive_cascade/retirement_cascade_recover_to_battery_to_drone_to_maintenance_log
    """
    w = setup_returning_flight(battery_serial="B-9", battery_cycle_count=299)

    flight = validate_success(api.recover_flight(w["flight"]["id"], 11.100, OPERATOR))
    assert flight["ops_state"] == "RECOVERED"
    assert_pct(flight["actual_energy_pct"], 23.6, "actual_energy_pct")

    battery = read_battery(w["battery"]["id"])
    assert battery["cycle_count"] == 300
    assert_pct(battery["charge_pct"], 76.4, "charge_pct")
    assert battery["state"] == "RETIRED"
    assert_pct(battery["health_pct"], 0.0, "health_pct")

    drone = read_drone(w["drone"]["id"])
    assert drone["installed_battery_id"] is None
    assert drone["status"] == "GROUNDED"
    assert_hours(drone["flight_hours"], 0.19, "flight_hours")
    assert_hours(drone["hours_since_service"], 0.19, "hours_since_service")


def test_retirement_schedules_a_battery_swap_order_and_still_frees_the_pad(api):
    """PRD §3.7: "Because hop 3 may have grounded the drone, a maintenance work order follows
    it: when and only when the drone was grounded by a pack retirement, a maintenance log is
    created with `work_type` `BATTERY_SWAP`, `status` `SCHEDULED`, `incident_id` null,
    `scheduled_start` at the current logical clock, and `scheduled_end` 60 minutes later."
    PRD §3.7: "Independently of all four hops, the recovery nest's `reserved_pads` decreases by
    one."

    Design: Difficulty/transitive_cascade/retirement_cascade_recover_to_battery_to_drone_to_maintenance_log
    """
    w = setup_recovered_flight(battery_serial="B-9", battery_cycle_count=299)

    logs, meta = validate_paginated(
        api.list_maintenance_logs(TECH, params={"drone_id": w["drone"]["id"]})
    )
    assert meta["total_count"] == 1, "exactly one work order follows the retirement"
    log = logs[0]
    assert log["work_type"] == "BATTERY_SWAP"
    assert log["status"] == "SCHEDULED"
    assert log["incident_id"] is None
    assert_instant(log["scheduled_start"], "2026-06-01T09:00:00Z", "scheduled_start")
    assert_instant(log["scheduled_end"], "2026-06-01T10:00:00Z", "scheduled_end")

    assert read_nest(w["nest"]["id"])["reserved_pads"] == 0, (
        "recovery gives the pad slot back even when the pack retires"
    )
