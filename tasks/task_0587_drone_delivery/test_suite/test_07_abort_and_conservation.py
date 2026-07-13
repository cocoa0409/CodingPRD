"""The abort: the unwind path, and the two conserved quantities it must not leak."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_hours,
    assert_km,
    assert_money,
    assert_pct,
    charge_battery,
    dispatch_order_payload,
    read_battery,
    read_customer,
    read_drone,
    read_flight,
    read_nest,
    read_order,
    setup_launched_flight,
    setup_planned_flight,
    setup_recovered_flight,
)
from test_helpers.test_users import TEST_USERS

OPERATOR = TEST_USERS["dispatch_operator_headers"]
DIRECTOR = TEST_USERS["flight_director_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


# ============================================================ conserved quantity: money
def test_dispatch_holds_the_fare_and_the_compensating_abort_returns_it_to_zero(api):
    """PRD §2.10: "A customer's `held_total` is money authorized but not yet captured, and
    after every request it must equal — rounded half up to 2 decimal places — the sum of
    `order_total` across that customer's orders whose `status` is `ASSIGNED` or `IN_TRANSIT`."
    PRD §2.10: "A dispatch followed by its compensating abort therefore returns `held_total` to
    exactly its pre-dispatch value with zero drift, and leaves `billed_total` untouched."

    Design: Difficulty/compensating_invariant/dispatch_then_abort_conserves_customer_funds
    """
    w = setup_planned_flight()
    assert_money(w["order"]["order_total"], 8.96, "order_total")

    before = read_customer(w["customer"]["id"])
    assert_money(before["held_total"], 8.96, "held_total after dispatch")
    assert_money(before["billed_total"], 0.00, "billed_total after dispatch")

    validate_success(api.abort_flight(w["flight"]["id"], DIRECTOR))

    after = read_customer(w["customer"]["id"])
    assert_money(after["held_total"], 0.00, "held_total after the compensating abort")
    assert_money(after["billed_total"], 0.00, "billed_total is untouched by an abort")


def test_abort_from_planned_reverts_the_order_and_leaves_the_pack_untouched(api):
    """PRD §3.7: "**From `PLANNED`.** The airframe never left the pad. The drone moves
    `RESERVED → IDLE` and its `version` advances — unless the same cascade is grounding that
    drone, in which case the drone ends up `GROUNDED` instead. The pack is untouched: it never
    left `READY`, so no cycle is consumed and no charge is debited. The order moves
    `ASSIGNED → QUOTED` and its `version` advances, and the customer's `held_total` is reduced
    by the order's `order_total`, compensating the dispatch hold exactly. The order is now
    re-dispatchable — an order may be dispatched, aborted, and dispatched again any number of
    times."
    PRD §3.7: "Regardless of the `ops_state` it starts from, abort sets the flight's
    `abort_reason` — `OPERATOR` when a human initiated it, `DRONE_GROUNDED` when the grounding
    cascade of §3.8 forced it, `WEATHER` when a weather stand-down forced it — moves `ops_state`
    to `ABORTED`, advances the flight's `version`, and releases the pad: the recovery nest's
    `reserved_pads` decreases by one, exactly as recovery would have done."

    Design: Difficulty/compensating_invariant/dispatch_then_abort_conserves_customer_funds
    """
    w = setup_planned_flight()

    flight = validate_success(api.abort_flight(w["flight"]["id"], DIRECTOR))
    assert flight["ops_state"] == "ABORTED"
    assert flight["abort_reason"] == "OPERATOR"

    assert read_order(w["order"]["id"])["status"] == "QUOTED"
    assert read_drone(w["drone"]["id"])["status"] == "IDLE"

    battery = read_battery(w["battery"]["id"])
    assert battery["state"] == "READY", "the pack never left READY on a PLANNED abort"
    assert battery["cycle_count"] == 0, "no cycle is consumed"
    assert_pct(battery["charge_pct"], 100, "charge_pct")

    assert_money(read_customer(w["customer"]["id"])["billed_total"], 0.00, "billed_total")


# ============================================================= conserved quantity: pads
def test_abort_of_a_launched_sortie_gives_the_pad_slot_back(api):
    """PRD §2.10: "A nest's `reserved_pads` is the count of physical pad slots currently held,
    and after every request it must equal the number of flights whose `recovery_nest_id` is that
    nest and whose `ops_state` is one of `PLANNED`, `LAUNCHED`, `DROPPING` or `RETURNING`."
    PRD §3.7: "**From `LAUNCHED`.** The airframe was airborne, so the pack must be debited. The
    flight's `actual_route_km` is set to the reported value, and to 0.0 when the abort was
    triggered by the system rather than by a human report. The flight's `actual_energy_pct` is
    computed with the actual variant exactly as on recovery. The pack moves `IN_USE → COOLDOWN`,
    its `cycle_count` increases by one, and its `charge_pct` is debited by `actual_energy_pct`,
    floored at zero — and the retirement rule applies here exactly as it does on recovery: a
    `cycle_count` that reaches 300 retires the pack, which in turn un-links it from the drone,
    grounds the drone and schedules a `BATTERY_SWAP` maintenance log. Otherwise the drone moves
    `IN_FLIGHT → IDLE` (or straight to `GROUNDED` when the cascade is grounding it). Either way
    the drone's `flight_hours` and `hours_since_service` both increase by the reported route
    divided by `cruise_speed_kmh`, rounded half up to two decimal places, and its `version`
    advances. The order moves `IN_TRANSIT → QUOTED` and its `version` advances, and the
    customer's `held_total` is reduced by the order's `order_total`."

    Design: Difficulty/compensating_invariant/dispatch_then_abort_conserves_nest_pad_slots
    """
    w = setup_launched_flight(pad_count=1)
    assert read_nest(w["nest"]["id"])["reserved_pads"] == 1, "the sortie saturates the 1-pad nest"

    flight = validate_success(
        api.abort_flight(w["flight"]["id"], OPERATOR, {"actual_route_km": 5.550})
    )

    assert flight["ops_state"] == "ABORTED"
    assert_km(flight["actual_route_km"], 5.550, "actual_route_km")
    # 5.550 * 1.6 * 1.16 = 10.3008; + 3.0 hover (no reserve) = 13.3008 -> 13.3.
    assert_pct(flight["actual_energy_pct"], 13.3, "actual_energy_pct")

    battery = read_battery(w["battery"]["id"])
    assert battery["cycle_count"] == 1
    assert_pct(battery["charge_pct"], 86.7, "charge_pct")

    assert_hours(read_drone(w["drone"]["id"])["flight_hours"], 0.09, "flight_hours")
    assert read_nest(w["nest"]["id"])["reserved_pads"] == 0, "the abort must release the pad slot"


def test_the_freed_pad_slot_lets_the_same_order_be_redispatched(api):
    """PRD §2.10: "Dispatch increments it by one; recovery decrements it by one; an abort from
    any non-terminal `ops_state` decrements it by one. Flights in `RECOVERED` or `ABORTED` never
    count."
    PRD §3.7: "The order moves `ASSIGNED → QUOTED` and its `version` advances, and the
    customer's `held_total` is reduced by the order's `order_total`, compensating the dispatch
    hold exactly. The order is now re-dispatchable — an order may be dispatched, aborted, and
    dispatched again any number of times."

    Design: Difficulty/compensating_invariant/dispatch_then_abort_conserves_nest_pad_slots
    """
    w = setup_launched_flight(pad_count=1)
    validate_success(api.abort_flight(w["flight"]["id"], OPERATOR, {"actual_route_km": 5.550}))

    assert read_order(w["order"]["id"])["status"] == "QUOTED"
    assert_money(read_customer(w["customer"]["id"])["held_total"], 0.00, "held_total")
    assert read_nest(w["nest"]["id"])["reserved_pads"] == 0

    charge_battery(w["battery"]["id"], 100)  # COOLDOWN -> READY so the airframe is eligible again
    order = read_order(w["order"]["id"])

    flight_2 = validate_success(
        api.dispatch_order(
            order["id"], dispatch_order_payload(w["nest"]["id"], order["version"]), OPERATOR
        ),
        201,
    )
    assert flight_2["ops_state"] == "PLANNED"
    assert read_nest(w["nest"]["id"])["reserved_pads"] == 1, (
        "the freed slot is genuinely reusable"
    )


# ================================================================= terminal lockdown
def test_aborting_a_recovered_flight_is_rejected(api):
    """PRD §3.7: "**The abort** is the unwind, and it is available to a `DispatchOperator` or a
    `FlightDirector` on any non-terminal sortie. It optionally carries an `actual_route_km`
    reporting how far the airframe got. Aborting a flight already in `RECOVERED` or `ABORTED` is
    rejected with `ERR_FLIGHT_TERMINAL` (HTTP 409)."
    PRD §2.10: "Flights in `RECOVERED` or `ABORTED` never count."

    Design: Corner/state_machines/abort_on_recovered_flight_rejected
    """
    w = setup_recovered_flight()

    resp = api.abort_flight(w["flight"]["id"], OPERATOR, {"actual_route_km": 11.100})
    validate_error(resp, ApiErrorId.ERR_FLIGHT_TERMINAL.value)

    assert read_flight(w["flight"]["id"])["ops_state"] == "RECOVERED"
    assert read_nest(w["nest"]["id"])["reserved_pads"] == 0, (
        "the rejected abort must not decrement the ledger a second time"
    )
    assert read_battery(w["battery"]["id"])["cycle_count"] == 1, "no second debit"
