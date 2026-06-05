"""Optimistic concurrency on vehicle holds, tier-threshold promotion, and the
immediate-consistency guarantee at pickup.
"""
from test_helpers import (
    validate_success, validate_error,
    make_fleet_manager_headers, make_rental_agent_headers,
    create_member, set_member_loyalty,
    create_reservation, confirm_reservation, hold_vehicle,
    setup_fleet, setup_confirmed_reservation,
    get_vehicle, get_ledger_entries,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import find_ledger_entries

FM = make_fleet_manager_headers()
RA = make_rental_agent_headers()


# ===========================================================================
# Queue B — cross_cutting_complexity_layers: optimistic concurrency
# ===========================================================================
def test_hold_with_stale_vehicle_version_rejected(api):
    """PRD §2.9: "If another writer has advanced the vehicle's `version` since
    the client last read it — for instance, another agent has already held that
    same `AVAILABLE` vehicle and taken it out of the available pool — the values
    no longer match and the request is rejected with `ERR_STALE_VERSION` (HTTP
    412), leaving the single existing hold intact."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_vehicle_version_on_hold_returns_412
    """
    fleet = setup_fleet(api=api, num_vehicles=2)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    veh1 = fleet["vehicles"][0]
    veh1_ver_pre = veh1["version"]
    member = create_member(api=api)

    res1 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    confirm_reservation(res1["id"], api=api)
    res2 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-08-01T10:00:00Z", "2026-08-04T10:00:00Z", api=api)
    confirm_reservation(res2["id"], api=api)

    # First hold succeeds and advances the version.
    hold_vehicle(veh1["id"], res1["id"], veh1_ver_pre, api=api)
    # Second hold carries the now-stale pre-hold version.
    resp = api.hold_vehicle(veh1["id"], {"reservation_id": res2["id"],
                                         "expected_vehicle_version": veh1_ver_pre}, RA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    veh1_after = get_vehicle(veh1["id"], api=api)
    assert veh1_after["held_by_reservation_id"] == res1["id"], "the original hold stands"


def test_hold_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.4: "A successful hold sets `held_by_reservation_id` to the
    reservation, decrements the class `available_count` through reconciliation,
    and increments the vehicle's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_vehicle_version_on_hold_succeeds
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh = ctx["reservation"], ctx["vehicles"][0]
    held = validate_success(api.hold_vehicle(veh["id"], {
        "reservation_id": res["id"], "expected_vehicle_version": veh["version"],
    }, RA))
    assert held["status"] == "RESERVED"
    assert held["held_by_reservation_id"] == res["id"]
    assert held["version"] == veh["version"] + 1


def test_tier_promotion_at_silver_threshold_inclusive(api):
    """PRD §3.2: "A member with at least 2000 lifetime points is `GOLD`;
    otherwise a member with at least 500 lifetime points is `SILVER`; otherwise
    the member is `STANDARD`."

    Design: Corner/cross_cutting_complexity_layers/tier_promotion_at_silver_threshold_inclusive_boundary
    """
    member = create_member(api=api)
    set_member_loyalty(member["id"], api=api, lifetime_points=500, points_balance=500)
    fetched = validate_success(api.get_member(member["id"], RA))
    assert fetched["tier"] == "SILVER", "lifetime_points == 500 is the inclusive SILVER edge"


# ===========================================================================
# Queue B — consistency_model: immediate consistency at pickup
# ===========================================================================
def test_pickup_immediately_reflects_on_rent_and_ledger(api):
    """PRD §3.5: "On success, the reservation advances `CONFIRMED → PICKED_UP`, a
    new `RentalAgreement` is created in `OPEN` status referencing the reservation
    and the assigned vehicle, and the vehicle moves to `ON_RENT`"
    PRD §3.5: "ledger lines are written for the date-driven charges only — a
    `BASE_RENTAL` line ... whose amounts equal the corresponding components of
    the quoted estimate."

    Design: Corner/consistency_model/pickup_immediately_reflects_on_rent_and_ledger
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    res, veh = ctx["reservation"], ctx["vehicles"][0]
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)

    agreement = validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res["id"], veh["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)
    assert agreement["status"] == "OPEN"

    veh_after = get_vehicle(veh["id"], api=api)
    assert veh_after["status"] == "ON_RENT"

    entries = get_ledger_entries(agreement["id"], api=api)
    base = find_ledger_entries(entries, "BASE_RENTAL")
    assert len(base) == 1
    assert base[0]["amount_cents"] == 15000, "3-day ECON daily 5000 base"
