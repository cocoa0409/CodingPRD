"""Transitive cascades and compensating (conservation) invariants.

Queue A: transitive_cascade (deliver -> vehicle suspend -> fleet suspend; membership cancel
-> order cancel -> reservation release), compensating_invariant (fuel reservation and fleet
budget conserved across a commit/reserve-then-release round trip).
"""
from test_helpers import (
    validate_success,
    make_member_headers, make_fleet_manager_headers, make_driver_headers,
    setup_fleet_single_vehicle_order_arrived, setup_member_order_routed,
    setup_perfill_order_routed, setup_fleet_order_scheduled,
    get_order, get_vehicle, get_fleet_account, get_compartment,
    assert_compartment_conservation, assert_fleet_budget_conservation,
    assert_vehicle_budget_conservation,
)


# ─── Queue A: transitive_cascade / deliver -> vehicle suspend -> fleet suspend ─

def test_deliver_settles_and_suspends_vehicle_at_cap(api):
    """PRD §3.6: "If the vehicle has a cap above 0 and its `settled_spend_cents` reaches or
    exceeds its `monthly_spend_cap_cents`, the vehicle is automatically suspended
    (`ACTIVE → SUSPENDED`);"
    PRD §3.6: "the vehicle's `committed_spend_cents` is reduced by the order's original
    estimated total and its `settled_spend_cents` is increased by the final
    `total_cost_cents`;"

    Design: Difficulty/transitive_cascade/deliver_settles_suspends_vehicle_then_suspends_fleet
    """
    ctx = setup_fleet_single_vehicle_order_arrived()
    res = api.deliver_order(ctx["order_id"], {"dispensed_gallons": 10},
                            make_driver_headers(ctx["driver_id"]))
    order = validate_success(res, 200)
    assert order["total_cost_cents"] == 5790, "fuel 4590 + service 1200 = 5790"
    veh = get_vehicle(ctx["vehicle_id"])
    assert veh["settled_spend_cents"] == 5790
    assert veh["status"] == "SUSPENDED", "settled 5790 >= cap 5790 auto-suspends the vehicle"


def test_deliver_cascade_suspends_fleet_account(api):
    """PRD §3.6: "that auto-suspension of a fleet-linked vehicle increments the fleet
    account's `suspended_vehicle_count` and decrements its `active_vehicle_count`, and if
    that decrement brings the account's `active_vehicle_count` to 0 the fleet account is
    itself suspended."

    Design: Difficulty/transitive_cascade/deliver_settles_suspends_vehicle_then_suspends_fleet
    """
    ctx = setup_fleet_single_vehicle_order_arrived()
    api.deliver_order(ctx["order_id"], {"dispensed_gallons": 10},
                      make_driver_headers(ctx["driver_id"]))
    fa = get_fleet_account(ctx["fleet_account_id"])
    assert fa["suspended_vehicle_count"] == 1
    assert fa["active_vehicle_count"] == 0
    assert fa["status"] == "SUSPENDED", "the last active vehicle suspending suspends the account"


# ─── Queue A: transitive_cascade / membership cancel -> order cancel -> release ─

def test_membership_cancel_cascades_to_routed_order(api):
    """PRD §3.8: "Cancellation then cascades to the member's live orders: every
    `DeliveryOrder` carrying this `membership_id` that is still `SCHEDULED` or `ROUTED`
    transitions to `CANCELLED`, and each such cascaded cancellation itself releases that
    order's fuel reservation (if it was `ROUTED`)"

    Design: Difficulty/transitive_cascade/membership_cancel_cascades_order_cancel_releases_reservation
    """
    ctx = setup_member_order_routed()
    res = api.cancel_membership(ctx["membership_id"], make_member_headers(ctx["customer_id"]))
    mem = validate_success(res, 200)
    assert mem["status"] == "CANCELLED"
    assert get_order(ctx["order_id"])["status"] == "CANCELLED"


def test_membership_cancel_releases_compartment_reservation(api):
    """PRD §3.8: "each such cascaded cancellation itself releases that order's fuel
    reservation (if it was `ROUTED`) and releases the vehicle's committed spend"
    PRD §2.7: "cancelling the order, reporting inaccessibility, or tearing down the route
    releases exactly those same gallons, so a reserve-then-release round trip leaves
    available gallons unchanged."

    Design: Difficulty/transitive_cascade/membership_cancel_cascades_order_cancel_releases_reservation
    """
    ctx = setup_member_order_routed()
    api.cancel_membership(ctx["membership_id"], make_member_headers(ctx["customer_id"]))
    comp = get_compartment(ctx["truck_id"], ctx["compartment_id"])
    assert comp["gallons_reserved"] == 0
    assert comp["gallons_available"] == 100
    assert_compartment_conservation(comp)


# ─── Queue A: compensating_invariant / fuel reservation conserved ───────────

def test_fuel_reservation_released_on_order_cancel(api):
    """PRD §2.7: "Reserving and releasing gallons form a compensating pair: assigning an
    order to a route reserves the order's requested gallons, and cancelling the order,
    reporting inaccessibility, or tearing down the route releases exactly those same
    gallons, so a reserve-then-release round trip leaves available gallons unchanged."

    Design: Difficulty/compensating_invariant/fuel_reservation_conserved_across_reserve_then_release
    """
    ctx = setup_perfill_order_routed()
    res = api.cancel_order(ctx["order_id"], make_member_headers(ctx["customer_id"]))
    order = validate_success(res, 200)
    assert order["status"] == "CANCELLED"
    comp = get_compartment(ctx["truck_id"], ctx["compartment_id"])
    assert comp["gallons_reserved"] == 0
    assert comp["gallons_available"] == 100, "reserve 8 then release 8 leaves available at 100"


def test_fuel_reservation_round_trip_conserves_onboard(api):
    """PRD §2.7: "For every `TruckCompartment`, the sum of `gallons_reserved` and
    `gallons_available` always equals `gallons_onboard`, with both `gallons_reserved` and
    `gallons_available` never negative."

    Design: Difficulty/compensating_invariant/fuel_reservation_conserved_across_reserve_then_release
    """
    ctx = setup_perfill_order_routed()
    before = get_compartment(ctx["truck_id"], ctx["compartment_id"])
    assert before["gallons_reserved"] == 8, "assign-route reserved the 8 requested gallons"
    assert_compartment_conservation(before)
    api.cancel_order(ctx["order_id"], make_member_headers(ctx["customer_id"]))
    after = get_compartment(ctx["truck_id"], ctx["compartment_id"])
    assert after["gallons_onboard"] == before["gallons_onboard"], "onboard unchanged by reserve/release"
    assert_compartment_conservation(after)


# ─── Queue A: compensating_invariant / fleet budget conserved ───────────────

def test_fleet_order_cancel_releases_committed_budget(api):
    """PRD §2.7: "Committing and releasing form a compensating pair: creating an order
    reserves its estimated total into the committed bucket, and cancelling that order
    releases exactly the same amount, so a create-then-cancel round trip leaves the
    remaining budget unchanged."

    Design: Difficulty/compensating_invariant/fleet_budget_conserved_across_commit_then_release
    """
    ctx = setup_fleet_order_scheduled()
    res = api.cancel_order(ctx["order_id"], make_fleet_manager_headers(ctx["customer_id"]))
    order = validate_success(res, 200)
    assert order["status"] == "CANCELLED"
    veh = get_vehicle(ctx["vehicle_id"])
    assert veh["committed_spend_cents"] == 0
    assert veh["remaining_budget_cents"] == 100000, "full cap restored after cancel"


def test_fleet_account_budget_conserved_after_cancel(api):
    """PRD §2.7: "The parallel account-level law holds on every `FleetAccount`: the sum of
    `committed_budget_cents`, `settled_budget_cents`, and `remaining_budget_cents` always
    equals `monthly_budget_cap_cents`."

    Design: Difficulty/compensating_invariant/fleet_budget_conserved_across_commit_then_release
    """
    ctx = setup_fleet_order_scheduled()
    api.cancel_order(ctx["order_id"], make_fleet_manager_headers(ctx["customer_id"]))
    fa = get_fleet_account(ctx["fleet_account_id"])
    assert fa["committed_budget_cents"] == 0, "cancel releases the committed estimate"
    assert_fleet_budget_conservation(fa)
    veh = get_vehicle(ctx["vehicle_id"])
    assert_vehicle_budget_conservation(veh)
