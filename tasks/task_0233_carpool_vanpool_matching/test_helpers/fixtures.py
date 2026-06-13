"""Composite setup helpers for the Carpool & Vanpool Matching API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database starts empty before every test. Fixtures
use get_success_data() (lenient) so setup failures surface as clear "Setup failed"
errors rather than confusing assertion mismatches.

Identity threading: Driver and Rider are entity_backed:Member (PRD §2.1). Every
ownership-gated call uses make_driver_headers(driver_id) / make_rider_headers(rider_id)
with the actual Member id, never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_platform_ops_headers,
    make_program_admin_headers,
    make_driver_headers,
    make_rider_headers,
)
from . import factories as f

PA = make_program_admin_headers()
OPS = make_platform_ops_headers()


# ---------------------------------------------------------------------------
# Tier 1/2: base primitives
# ---------------------------------------------------------------------------
def create_program(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_employer_program(
        f.create_employer_program_payload(**overrides), PA))


def create_member(program_id, full_name="Rae", api=api_client, **overrides) -> dict:
    return get_success_data(api.create_member(
        f.create_member_payload(program_id, full_name=full_name, **overrides), PA))


def create_driver_member(program_id, full_name="Dee", api=api_client, **overrides) -> dict:
    overrides.setdefault("can_drive", True)
    return create_member(program_id, full_name=full_name, api=api, **overrides)


def create_rider_member(program_id, full_name="Rae", wallet_balance_cents=50000,
                        api=api_client, **overrides) -> dict:
    overrides.setdefault("wallet_balance_cents", wallet_balance_cents)
    return create_member(program_id, full_name=full_name, api=api, **overrides)


def create_vehicle(driver_id, plate="VAN-1", seat_capacity=6, api=api_client, **overrides) -> dict:
    payload = f.create_vehicle_payload(driver_id, plate=plate, seat_capacity=seat_capacity, **overrides)
    return get_success_data(api.create_vehicle(payload, make_driver_headers(driver_id)))


def create_pool(program_id, driver_id, vehicle_id, api=api_client, **overrides) -> dict:
    payload = f.create_pool_payload(program_id, driver_id, vehicle_id, **overrides)
    return get_success_data(api.create_pool(payload, make_driver_headers(driver_id)))


def add_membership(pool_id, rider_id, expected_pool_version, api=api_client, **overrides) -> dict:
    payload = f.create_membership_payload(pool_id, rider_id, expected_pool_version, **overrides)
    return get_success_data(api.create_membership(payload, make_rider_headers(rider_id)))


def activate_pool(pool_id, driver_id, api=api_client) -> dict:
    return get_success_data(api.activate_pool(pool_id, make_driver_headers(driver_id)))


def create_trip(pool_id, driver_id, api=api_client, **overrides) -> dict:
    payload = f.create_trip_payload(pool_id, **overrides)
    return get_success_data(api.create_trip(payload, make_driver_headers(driver_id)))


def create_reservation(trip_id, rider_id, expected_trip_version, api=api_client, **overrides) -> dict:
    payload = f.create_reservation_payload(trip_id, rider_id, expected_trip_version, **overrides)
    return get_success_data(api.create_reservation(payload, make_rider_headers(rider_id)))


# ---------------------------------------------------------------------------
# Tier 2: an ACTIVE pool with a driver, vehicle, and one seed membership.
# Returns a context dict with every id and the live pool version.
# ---------------------------------------------------------------------------
def setup_active_pool(api=api_client, seat_capacity=6, pool_kind="VANPOOL",
                      base_cost_cents=2000, per_mile_cents=120, hov_eligible=True,
                      seed_rider_name="Seed", seed_rider_wallet=50000,
                      program_overrides=None, origin_zone="Z-N", dest_zone="Z-DT",
                      departure_days=None) -> dict:
    """Program ACTIVE + driver + vehicle + pool with one ACTIVE seed membership,
    then activated. Returns a context dict.
    """
    program_overrides = program_overrides or {}
    departure_days = departure_days or ["MON", "TUE", "WED", "THU", "FRI"]
    prog = create_program(api=api, **program_overrides)
    drv = create_driver_member(prog["id"], full_name="Dee", api=api)
    seed = create_rider_member(prog["id"], full_name=seed_rider_name,
                               wallet_balance_cents=seed_rider_wallet, api=api)
    veh = create_vehicle(drv["id"], seat_capacity=seat_capacity, hov_eligible=hov_eligible, api=api)
    pool = create_pool(prog["id"], drv["id"], veh["id"], api=api,
                       kind=pool_kind, base_cost_cents=base_cost_cents,
                       per_mile_cents=per_mile_cents, origin_zone=origin_zone,
                       dest_zone=dest_zone, departure_days=list(departure_days))
    add_membership(pool["id"], seed["id"], pool["version"], api=api)
    activated = activate_pool(pool["id"], drv["id"], api=api)
    return {
        "program": prog, "program_id": prog["id"],
        "driver": drv, "driver_id": drv["id"],
        "seed": seed, "seed_id": seed["id"],
        "vehicle": veh, "vehicle_id": veh["id"],
        "pool": activated, "pool_id": pool["id"],
        "pool_version": activated["version"],
    }


def current_trip_version(trip_id, driver_id, api=api_client) -> int:
    return get_success_data(api.get_trip(trip_id, make_driver_headers(driver_id)))["version"]


# ---------------------------------------------------------------------------
# Tier 3: walk a reservation through to a completed (settled) trip.
# ---------------------------------------------------------------------------
def setup_completed_single_rider_trip(api=api_client, base_cost_cents=2000,
                                      per_mile_cents=120, distance_miles=10.0,
                                      hov_lane_used_create=True, hov_lane_used_complete=True,
                                      pay_now=True, program_overrides=None,
                                      rider_wallet=50000) -> dict:
    """Build a program/pool, reserve one rider seat, board, check-in, depart,
    and complete the trip. Returns a context dict including the completed
    reservation and trip.
    """
    ctx = setup_active_pool(api=api, base_cost_cents=base_cost_cents,
                            per_mile_cents=per_mile_cents,
                            seed_rider_name="Rae", seed_rider_wallet=rider_wallet,
                            program_overrides=program_overrides)
    drv_id = ctx["driver_id"]
    rider = ctx["seed"]
    trip = create_trip(ctx["pool_id"], drv_id, api=api,
                       distance_miles=distance_miles, hov_lane_used=hov_lane_used_create)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api,
                             seat_count=1, pay_now=pay_now)
    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))
    get_success_data(api.check_in_reservation(res["id"], make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip["id"], make_driver_headers(drv_id)))
    completed = get_success_data(api.complete_trip(
        trip["id"], {"hov_lane_used": hov_lane_used_complete}, make_driver_headers(drv_id)))
    ctx.update({"rider": rider, "rider_id": rider["id"], "trip": completed,
                "trip_id": trip["id"], "reservation_id": res["id"]})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: accumulate realized NO_SHOW events to drive a rider's reliability
# score down to an exact target. Each NO_SHOW subtracts 15.0 (PRD §3.8).
# A fresh member starts at 100.0; n no-shows -> 100.0 - 15.0*n.
# ---------------------------------------------------------------------------
def lower_reliability_via_no_shows(program_id, driver_id, rider_id, n_no_shows,
                                   api=api_client, start_date_day=9) -> None:
    """Drive `n_no_shows` realized NO_SHOW reliability events for `rider_id` by
    creating a dedicated pool of n single-seat trips that the rider reserves but
    never checks into; each depart cascades the RESERVED reservation to NO_SHOW.

    The rider must already hold an ACTIVE membership pathway; here we build an
    independent pool owned by `driver_id` for these strike trips.
    """
    veh = create_vehicle(driver_id, plate=f"STK-{rider_id[:4]}", seat_capacity=6, api=api)
    pool = create_pool(program_id, driver_id, veh["id"], api=api)
    add_membership(pool["id"], rider_id, pool["version"], api=api)
    activate_pool(pool["id"], driver_id, api=api)
    for i in range(n_no_shows):
        dep = f"2026-07-{start_date_day + i:02d}T15:00:00Z"
        trip = create_trip(pool["id"], driver_id, api=api, departure_at=dep, distance_miles=10.0)
        create_reservation(trip["id"], rider_id, trip["version"], api=api, seat_count=1)
        get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(driver_id)))
        get_success_data(api.depart_trip(trip["id"], make_driver_headers(driver_id)))


def setup_rider_with_reliability(target_no_shows, api=api_client, rider_wallet=50000,
                                 program_overrides=None) -> dict:
    """Create a program + driver + rider; drive `target_no_shows` realized NO_SHOWs
    so the rider's confirmed reliability_score is 100.0 - 15.0*target_no_shows.
    Returns a context dict with program/driver/rider ids.
    """
    prog = create_program(api=api, **(program_overrides or {}))
    drv = create_driver_member(prog["id"], full_name="Dee", api=api)
    rider = create_rider_member(prog["id"], full_name="Rae", wallet_balance_cents=rider_wallet, api=api)
    if target_no_shows > 0:
        lower_reliability_via_no_shows(prog["id"], drv["id"], rider["id"], target_no_shows, api=api)
    return {"program": prog, "program_id": prog["id"],
            "driver": drv, "driver_id": drv["id"],
            "rider": rider, "rider_id": rider["id"]}


# ---------------------------------------------------------------------------
# GRH claim chains
# ---------------------------------------------------------------------------
def create_grh_claim(rider_id, program_id, api=api_client, claimed_fare_cents=4000,
                     reason_code="ILLNESS", **overrides) -> dict:
    payload = f.create_grh_claim_payload(rider_id, program_id,
                                         claimed_fare_cents=claimed_fare_cents,
                                         reason_code=reason_code, **overrides)
    return get_success_data(api.create_grh_claim(payload, make_rider_headers(rider_id)))


def approve_and_reimburse_grh(grh_id, api=api_client) -> dict:
    get_success_data(api.approve_grh_claim(grh_id, PA))
    return get_success_data(api.reimburse_grh_claim(grh_id, PA))


def reimburse_grh_event(rider_id, program_id, claimed_fare_cents, api=api_client) -> dict:
    """Create -> approve -> reimburse a GRH claim of `claimed_fare_cents`."""
    grh = create_grh_claim(rider_id, program_id, api=api,
                           claimed_fare_cents=claimed_fare_cents)
    return approve_and_reimburse_grh(grh["id"], api=api)
