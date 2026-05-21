"""Composite setup helpers — multi-step state builders.

These helpers encapsulate the 5–15 API-call sequences required to reach
the system states tests need to assert on. They use get_success_data
(the lenient validator) so setup failures surface as clear "Setup
failed" errors rather than confusing assertion failures.

PRD §2.1 identity threading: ANY call performed as Rider uses headers
minted via make_rider_headers(rider["id"]); ANY call performed as
Driver uses make_driver_headers(driver["id"]). The shared
TEST_USERS["rider_fallback_headers"] / TEST_USERS["driver_fallback_headers"]
are reserved for tests that do not exercise ownership.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_hours_iso,
    add_seconds_iso,
    airport_queue_join_payload,
    clock_advance_payload,
    create_dispute_payload,
    create_driver_payload,
    create_grid_payload,
    create_quest_bonus_payload,
    create_ride_payload,
    create_rider_payload,
    create_rush_hour_window_payload,
    go_online_payload,
    grid_code_with_numeric,
    iso_from_dt,
    iso_now_utc,
    patch_driver_quest_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_rider_headers,
)


# ---------------------------------------------------------------------------
# Convenience header accessors.
# ---------------------------------------------------------------------------
def admin_headers() -> Dict[str, str]:
    return TEST_USERS["platform_admin_headers"]


def dispute_ops_headers() -> Dict[str, str]:
    return TEST_USERS["dispute_ops_headers"]


# ===========================================================================
# Tier 1: Single-entity factories (always-fresh primary entities).
# ===========================================================================
def create_grid(*, is_airport: bool = False,
                rush_hour_eligible: bool = True,
                code: Optional[str] = None,
                **payload_overrides) -> Dict[str, Any]:
    """POST /grids as PlatformAdmin. Returns the created GeoGrid dict."""
    overrides: Dict[str, Any] = {
        "is_airport": is_airport,
        "rush_hour_eligible": rush_hour_eligible,
    }
    if code is not None:
        overrides["code"] = code
    overrides.update(payload_overrides)
    payload = create_grid_payload(**overrides)
    resp = api_client.create_grid(payload, admin_headers())
    return get_success_data(resp)


def create_driver(**payload_overrides) -> Dict[str, Any]:
    """POST /drivers as PlatformAdmin. Returns the created Driver dict."""
    payload = create_driver_payload(**payload_overrides)
    resp = api_client.create_driver(payload, admin_headers())
    return get_success_data(resp)


def create_rider(**payload_overrides) -> Dict[str, Any]:
    """POST /riders as PlatformAdmin. Returns the created Rider dict."""
    payload = create_rider_payload(**payload_overrides)
    resp = api_client.create_rider(payload, admin_headers())
    return get_success_data(resp)


def get_grid(grid_id: str) -> Dict[str, Any]:
    resp = api_client.get_grid(grid_id, admin_headers())
    return get_success_data(resp)


def get_driver(driver_id: str, *, as_admin: bool = True) -> Dict[str, Any]:
    headers = admin_headers() if as_admin else make_driver_headers(driver_id)
    resp = api_client.get_driver(driver_id, headers)
    return get_success_data(resp)


def get_rider(rider_id: str, *, as_admin: bool = True) -> Dict[str, Any]:
    headers = admin_headers() if as_admin else make_rider_headers(rider_id)
    resp = api_client.get_rider(rider_id, headers)
    return get_success_data(resp)


def get_ride(ride_id: str, *, as_admin: bool = True,
             rider_id: Optional[str] = None,
             driver_id: Optional[str] = None) -> Dict[str, Any]:
    """Read a Ride; default actor is PlatformAdmin (per PRD §4 roles
    list, both PlatformAdmin and DisputeOps may read any ride). If
    rider_id / driver_id is supplied, the call is made as that entity
    with proper ownership headers."""
    if rider_id is not None:
        headers = make_rider_headers(rider_id)
    elif driver_id is not None:
        headers = make_driver_headers(driver_id)
    elif as_admin:
        headers = admin_headers()
    else:
        headers = admin_headers()
    resp = api_client.get_ride(ride_id, headers)
    return get_success_data(resp)


def get_dispute(dispute_id: str, *, as_admin: bool = True,
                rider_id: Optional[str] = None) -> Dict[str, Any]:
    if rider_id is not None:
        headers = make_rider_headers(rider_id)
    elif as_admin:
        headers = dispute_ops_headers()
    else:
        headers = dispute_ops_headers()
    resp = api_client.get_dispute(dispute_id, headers)
    return get_success_data(resp)


def get_quest_bonus(quest_id: str) -> Dict[str, Any]:
    resp = api_client.get_quest_bonus(quest_id, admin_headers())
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Driver / Rider lifecycle building blocks.
# ===========================================================================
def driver_go_online(driver_id: str, grid_code: str) -> Dict[str, Any]:
    """POST /drivers/{id}/go-online with the driver's own identity."""
    resp = api_client.go_online(
        driver_id, go_online_payload(grid_code),
        make_driver_headers(driver_id),
    )
    return get_success_data(resp)


def driver_go_offline(driver_id: str) -> Dict[str, Any]:
    resp = api_client.go_offline(
        driver_id, make_driver_headers(driver_id),
    )
    return get_success_data(resp)


def create_and_online_driver(grid_code: str,
                             **overrides) -> Dict[str, Any]:
    """Combined: create a Driver (admin) + go online at grid_code
    (driver). Returns the post-online Driver dict.
    """
    driver = create_driver(**overrides)
    return driver_go_online(driver["id"], grid_code)


def create_rider_entity(**overrides) -> Dict[str, Any]:
    """Alias to keep the Rider counterpart obvious."""
    return create_rider(**overrides)


# ===========================================================================
# Tier 3: Ride lifecycle shortcuts.
# ===========================================================================
def create_requested_ride(rider_id: str, pickup_grid_code: str,
                          dropoff_grid_code: Optional[str] = None,
                          distance_km: float = 5.0,
                          **payload_overrides) -> Dict[str, Any]:
    """POST /rides as the owning Rider. Returns the REQUESTED Ride."""
    payload = create_ride_payload(
        pickup_grid_code=pickup_grid_code,
        dropoff_grid_code=dropoff_grid_code,
        distance_km=distance_km,
        **payload_overrides,
    )
    resp = api_client.create_ride(payload, make_rider_headers(rider_id))
    return get_success_data(resp)


def assign_ride(ride_id: str,
                allow_neighbor_grid: bool = False) -> Dict[str, Any]:
    """POST /rides/{id}/assign as PlatformAdmin. Optional
    allow_neighbor_grid per PRD §3.3."""
    payload: Dict[str, Any] = {}
    if allow_neighbor_grid:
        payload["allow_neighbor_grid"] = True
    resp = api_client.assign_ride(ride_id, admin_headers(),
                                  payload if payload else None)
    return get_success_data(resp)


def start_ride(ride_id: str, driver_id: str) -> Dict[str, Any]:
    resp = api_client.start_ride(ride_id, make_driver_headers(driver_id))
    return get_success_data(resp)


def complete_ride(ride_id: str, driver_id: str) -> Dict[str, Any]:
    resp = api_client.complete_ride(
        ride_id, make_driver_headers(driver_id),
    )
    return get_success_data(resp)


def cancel_ride(ride_id: str, rider_id: str) -> Dict[str, Any]:
    resp = api_client.cancel_ride(
        ride_id, make_rider_headers(rider_id),
    )
    return get_success_data(resp)


def create_assigned_ride(rider_id: str, pickup_grid_code: str,
                         dropoff_grid_code: Optional[str] = None,
                         distance_km: float = 5.0,
                         allow_neighbor_grid: bool = False,
                         ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create + assign a Ride. Returns (ride, post_assign_driver)."""
    ride = create_requested_ride(
        rider_id, pickup_grid_code, dropoff_grid_code, distance_km,
    )
    assigned = assign_ride(ride["id"],
                           allow_neighbor_grid=allow_neighbor_grid)
    driver = get_driver(assigned["driver_id"])
    return assigned, driver


def create_on_trip_ride(rider_id: str, pickup_grid_code: str,
                        dropoff_grid_code: Optional[str] = None,
                        distance_km: float = 5.0,
                        ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a Ride to ON_TRIP. Returns (ride, driver)."""
    assigned, driver = create_assigned_ride(
        rider_id, pickup_grid_code, dropoff_grid_code, distance_km,
    )
    on_trip = start_ride(assigned["id"], driver["id"])
    return on_trip, driver


def create_completed_ride(rider_id: str, pickup_grid_code: str,
                          dropoff_grid_code: Optional[str] = None,
                          distance_km: float = 5.0,
                          ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a Ride to COMPLETED. Returns (ride, driver)."""
    on_trip, driver = create_on_trip_ride(
        rider_id, pickup_grid_code, dropoff_grid_code, distance_km,
    )
    completed = complete_ride(on_trip["id"], driver["id"])
    return completed, driver


# ===========================================================================
# Tier 4: Surge / multiplier targeting.
#
# These helpers stage the supply/demand counts needed to land a grid on a
# specific surge tier under PRD §2.5.
# ===========================================================================
def setup_grid_with_supply(*, num_drivers: int = 1,
                           is_airport: bool = False,
                           rush_hour_eligible: bool = False,
                           code: Optional[str] = None,
                           ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a grid + num_drivers drivers all AVAILABLE in it.

    Returns (grid, drivers_list_after_going_online). The grid dict is
    refreshed after all drivers are online.
    """
    grid = create_grid(
        is_airport=is_airport, rush_hour_eligible=rush_hour_eligible,
        code=code,
    )
    drivers: List[Dict[str, Any]] = []
    for _ in range(num_drivers):
        drivers.append(create_and_online_driver(grid["code"]))
    refreshed = get_grid(grid["id"])
    return refreshed, drivers


def setup_grid_with_demand_ratio(*, num_drivers: int,
                                 num_open_demand: int,
                                 is_airport: bool = False,
                                 rush_hour_eligible: bool = False,
                                 code: Optional[str] = None,
                                 ) -> Dict[str, Any]:
    """Create a grid with exactly num_drivers AVAILABLE and
    num_open_demand REQUESTED rides pinned to it. Used to put the grid
    on a specific surge tier per PRD §2.5.

    Returns dict with keys: grid (refreshed), drivers (list), rides
    (list of REQUESTED rides), rider (the Rider who issued the demand).
    """
    grid, drivers = setup_grid_with_supply(
        num_drivers=num_drivers, is_airport=is_airport,
        rush_hour_eligible=rush_hour_eligible, code=code,
    )
    rider = create_rider()
    rides: List[Dict[str, Any]] = []
    for _ in range(num_open_demand):
        rides.append(create_requested_ride(rider["id"], grid["code"]))
    refreshed = get_grid(grid["id"])
    return {
        "grid": refreshed,
        "drivers": drivers,
        "rides": rides,
        "rider": rider,
    }


# ===========================================================================
# Tier 5: Rush-Hour / Quest / Dispute setup helpers.
# ===========================================================================
def create_rush_hour_window(*, day_of_week: str = "MON",
                            start_minute: int = 480,
                            end_minute: int = 540,
                            additive_bonus: float = 0.50,
                            label: Optional[str] = None,
                            ) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {
        "day_of_week": day_of_week,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "additive_bonus": additive_bonus,
    }
    if label is not None:
        overrides["label"] = label
    payload = create_rush_hour_window_payload(**overrides)
    resp = api_client.create_rush_hour_window(payload, admin_headers())
    return get_success_data(resp)


def create_quest_bonus(*, target_ride_count: int = 2,
                       bonus_amount_cents: int = 5_000,
                       window_start: Optional[str] = None,
                       window_end: Optional[str] = None,
                       name: Optional[str] = None,
                       ) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {
        "target_ride_count": target_ride_count,
        "bonus_amount_cents": bonus_amount_cents,
    }
    if name is not None:
        overrides["name"] = name
    payload = create_quest_bonus_payload(
        window_start=window_start,
        window_end=window_end,
        **overrides,
    )
    resp = api_client.create_quest_bonus(payload, admin_headers())
    return get_success_data(resp)


def enroll_driver_in_quest(driver_id: str, quest_id: Optional[str],
                           *, current_version: int) -> Dict[str, Any]:
    """PATCH /drivers/{id}/quest with the driver's own identity. PRD §3.6
    allows the Driver or PlatformAdmin actor; we use the driver
    identity to exercise the ownership pathway too."""
    payload = patch_driver_quest_payload(quest_id, version=current_version)
    resp = api_client.patch_driver_quest(
        driver_id, payload, make_driver_headers(driver_id),
    )
    return get_success_data(resp)


def advance_clock_to(target_iso: str) -> None:
    """POST /_clock/advance as PlatformAdmin."""
    payload = clock_advance_payload(target_iso)
    resp = api_client.clock_advance(payload, admin_headers())
    get_success_data(resp)


def join_airport_queue(driver_id: str, grid_code: str) -> Dict[str, Any]:
    payload = airport_queue_join_payload(grid_code)
    resp = api_client.airport_queue_join(
        payload, make_driver_headers(driver_id),
    )
    return get_success_data(resp)


def leave_airport_queue(driver_id: str) -> Dict[str, Any]:
    resp = api_client.airport_queue_leave(make_driver_headers(driver_id))
    return get_success_data(resp)


def list_airport_queue(grid_code: str) -> List[Dict[str, Any]]:
    resp = api_client.list_airport_queue(
        admin_headers(), params={"grid_code": grid_code, "limit": 100},
    )
    data = get_success_data(resp)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data  # type: ignore[return-value]


def create_open_dispute(ride_id: str, rider_id: str,
                        requested_refund_cents: int,
                        reason_code: str = "OVERCHARGE",
                        ) -> Dict[str, Any]:
    """POST /disputes as the owning Rider. Returns the OPEN Dispute."""
    payload = create_dispute_payload(
        ride_id=ride_id,
        requested_refund_cents=requested_refund_cents,
        reason_code=reason_code,
    )
    resp = api_client.create_dispute(payload, make_rider_headers(rider_id))
    return get_success_data(resp)


def approve_dispute(dispute_id: str,
                    approved_refund_cents: Optional[int] = None,
                    ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if approved_refund_cents is not None:
        payload["approved_refund_cents"] = approved_refund_cents
    resp = api_client.approve_dispute(
        dispute_id, dispute_ops_headers(),
        payload if payload else None,
    )
    return get_success_data(resp)


def reject_dispute(dispute_id: str) -> Dict[str, Any]:
    resp = api_client.reject_dispute(dispute_id, dispute_ops_headers())
    return get_success_data(resp)


def sweep_recompute_surge() -> List[Dict[str, Any]]:
    """POST /_sweep/recompute_surge. Returns the HeatMapSnapshot batch."""
    resp = api_client.sweep_recompute_surge(admin_headers())
    data = get_success_data(resp)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data  # type: ignore[return-value]


def list_heatmap() -> List[Dict[str, Any]]:
    resp = api_client.get_heatmap(admin_headers())
    data = get_success_data(resp)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data  # type: ignore[return-value]


# ===========================================================================
# Tier 6: Composite scenarios driven by SCAFFOLD_DIFFICULTY_DESIGN recipes.
# ===========================================================================
def setup_disputed_ride(distance_km: float = 5.0,
                        requested_refund_cents: int = 300,
                        ) -> Dict[str, Any]:
    """Full path from grid through COMPLETED ride to DISPUTED with an
    OPEN dispute. Returns {grid, rider, driver, ride, dispute}.

    The grid is non-airport, rush_hour_eligible=False, supply=1
    (one available driver), demand=0 — so surge multiplier is 1.00 and
    fares are predictable.
    """
    grid, drivers = setup_grid_with_supply(
        num_drivers=1, is_airport=False, rush_hour_eligible=False,
    )
    rider = create_rider()
    ride, driver = create_completed_ride(
        rider["id"], grid["code"], distance_km=distance_km,
    )
    dispute = create_open_dispute(
        ride["id"], rider["id"], requested_refund_cents,
    )
    return {
        "grid": grid,
        "rider": rider,
        "driver": driver,
        "ride": ride,
        "dispute": dispute,
    }


def setup_ride_quoted_vs_final_divergence() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN dual_variant_calc /
    ride_quoted_vs_final_fare_divergence.

    Stages a ride whose quoted_fare (computed at REQUESTED with
    multiplier=1.00) diverges from final_fare (computed at COMPLETED
    with multiplier=3.00 because supply collapsed and 5 new requests
    push the ratio above 4.0).

    Returns {grid, rider, driver, ride_under_test, extra_requested_rides}.
    """
    # Grid: non-airport, rush_hour_eligible=False so rush bonus
    # contributes 0.00 at both REQUESTED and COMPLETED instants.
    grid, drivers = setup_grid_with_supply(
        num_drivers=2, is_airport=False, rush_hour_eligible=False,
    )
    rider = create_rider()
    # 1 demand vs 2 supply at request time → ratio 0.5 → multiplier 1.00.
    ride = create_requested_ride(
        rider["id"], grid["code"], distance_km=5.0,
    )
    # Take one driver offline so post-assignment we'll have 0 supply
    # available for the new requests; both drivers were available
    # before the ride was assigned.
    driver_d2 = drivers[1]
    driver_go_offline(driver_d2["id"])
    # Assign the ride; ride.driver_id is now D1. After assignment grid
    # has active=0 demand=0 → surge 1.00.
    assigned = assign_ride(ride["id"])
    d1_id = assigned["driver_id"]
    # Bring a fresh driver online in the same grid (active=1) and have
    # 5 other riders request rides (demand=5). Ratio=5.0 > 4.0 →
    # multiplier saturates at MULTIPLIER_CAP=3.00.
    fresh_driver = create_and_online_driver(grid["code"])
    extra_rides: List[Dict[str, Any]] = []
    extra_rider = create_rider()
    for _ in range(5):
        extra_rides.append(create_requested_ride(
            extra_rider["id"], grid["code"], distance_km=2.0,
        ))
    # Start + complete the ride under test.
    start_ride(assigned["id"], d1_id)
    completed = complete_ride(assigned["id"], d1_id)
    return {
        "grid": get_grid(grid["id"]),
        "rider": rider,
        "driver_id": d1_id,
        "ride": completed,
        "extra_rides": extra_rides,
        "fresh_driver": fresh_driver,
    }


def setup_three_hop_assign_cascade(grid_code: Optional[str] = None,
                                   ) -> Dict[str, Any]:
    """transitive_cascade / assign_cascade_three_hops:
    Grid + 1 AVAILABLE driver + 1 REQUESTED Ride → trigger assign.
    Returns {grid, rider, driver, ride} BEFORE assignment is triggered.
    """
    grid = create_grid(is_airport=False, rush_hour_eligible=False,
                       code=grid_code)
    driver = create_and_online_driver(grid["code"])
    rider = create_rider()
    ride = create_requested_ride(
        rider["id"], grid["code"], distance_km=2.0,
    )
    return {
        "grid": get_grid(grid["id"]),
        "rider": rider,
        "driver": driver,
        "ride": ride,
    }


def setup_two_hop_refund_cascade() -> Dict[str, Any]:
    """transitive_cascade / refund_cascade_two_hops:
    Reach an OPEN Dispute on a COMPLETED Ride with known fare/earnings,
    ready to be approved.

    Caller advances by calling approve_dispute(dispute["id"], ...).
    Returns {grid, rider, driver, ride, dispute}.
    """
    return setup_disputed_ride(distance_km=5.0,
                               requested_refund_cents=300)


def setup_airport_grid_with_queued_driver() -> Dict[str, Any]:
    """non_linear_state_machine / driver_branching_airport_queue_dimension:
    Build an AIRPORT grid + non-airport G-002, drivers D1 (at airport,
    queued) and D2 (at G-002, AVAILABLE).
    """
    airport = create_grid(is_airport=True, rush_hour_eligible=False)
    g002 = create_grid(is_airport=False, rush_hour_eligible=False)
    d1 = create_and_online_driver(airport["code"])
    d2 = create_and_online_driver(g002["code"])
    # D1 joins the queue.
    join_airport_queue(d1["id"], airport["code"])
    return {
        "airport": get_grid(airport["id"]),
        "g002": get_grid(g002["id"]),
        "d1": get_driver(d1["id"]),
        "d2": get_driver(d2["id"]),
    }


def setup_quest_payout_scenario(target_ride_count: int = 2,
                                bonus_amount_cents: int = 5_000,
                                ) -> Dict[str, Any]:
    """dual_variant_calc / driver_total_earnings_vs_quest_bonus_aggregation.

    Creates Q1 (window_start=T0, window_end=T0+3600s), driver D1
    enrolled, advances clock to T0 (Q1 → ACTIVE), then completes
    target_ride_count rides for D1 in-window.

    Returns {grid, rider, driver, quest, t0, t_end, completed_rides}.
    """
    # Anchor everything to a future T0 so window_start hasn't passed.
    t0 = add_hours_iso(iso_now_utc(), 1)
    t_end = add_seconds_iso(t0, 3600)
    quest = create_quest_bonus(
        target_ride_count=target_ride_count,
        bonus_amount_cents=bonus_amount_cents,
        window_start=t0,
        window_end=t_end,
    )
    grid, drivers = setup_grid_with_supply(
        num_drivers=1, is_airport=False, rush_hour_eligible=False,
    )
    driver = drivers[0]
    # Enroll the driver. Read its current version to satisfy OCC.
    driver_full = get_driver(driver["id"])
    enroll_driver_in_quest(driver["id"], quest["id"],
                           current_version=driver_full["version"])
    rider = create_rider()
    # Advance clock to T0 → Q1 ACTIVE.
    advance_clock_to(t0)
    # Now drive target_ride_count rides to COMPLETED for D1.
    completed: List[Dict[str, Any]] = []
    for _ in range(target_ride_count):
        ride = create_requested_ride(
            rider["id"], grid["code"], distance_km=2.0,
        )
        # Sole driver in grid; assignment will select D1.
        assign_ride(ride["id"])
        start_ride(ride["id"], driver["id"])
        completed.append(complete_ride(ride["id"], driver["id"]))
    return {
        "grid": get_grid(grid["id"]),
        "rider": rider,
        "driver": get_driver(driver["id"]),
        "quest": get_quest_bonus(quest["id"]),
        "t0": t0,
        "t_end": t_end,
        "completed_rides": completed,
    }


def setup_two_adjacent_grids() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return two grids whose numeric codes differ by exactly 1 — used
    for the allow_neighbor_grid pathway per PRD §3.3.

    Returns (grid_a, grid_b) where grid_a.code = G-NNN and grid_b.code
    = G-(NNN+1).
    """
    # Pick an unused base in the upper half of the namespace to avoid
    # collision with other auto-allocated grids in the same test.
    import random
    base = random.randint(100, 800)
    grid_a = create_grid(is_airport=False, rush_hour_eligible=False,
                         code=grid_code_with_numeric(base))
    grid_b = create_grid(is_airport=False, rush_hour_eligible=False,
                         code=grid_code_with_numeric(base + 1))
    return grid_a, grid_b


def setup_completed_ride_with_known_fare(
    distance_km: float = 5.0,
) -> Dict[str, Any]:
    """Reach a COMPLETED Ride with multiplier=1.00 throughout (no surge,
    no rush bonus). The fare arithmetic is then exactly predictable.

    Returns {grid, rider, driver, ride}.
    """
    grid, drivers = setup_grid_with_supply(
        num_drivers=1, is_airport=False, rush_hour_eligible=False,
    )
    rider = create_rider()
    ride, driver = create_completed_ride(
        rider["id"], grid["code"], distance_km=distance_km,
    )
    return {
        "grid": get_grid(grid["id"]),
        "rider": rider,
        "driver": get_driver(driver["id"]),
        "ride": ride,
    }


__all__ = [
    "admin_headers",
    "advance_clock_to",
    "approve_dispute",
    "assign_ride",
    "cancel_ride",
    "complete_ride",
    "create_and_online_driver",
    "create_assigned_ride",
    "create_completed_ride",
    "create_driver",
    "create_grid",
    "create_on_trip_ride",
    "create_open_dispute",
    "create_quest_bonus",
    "create_requested_ride",
    "create_rider",
    "create_rider_entity",
    "create_rush_hour_window",
    "dispute_ops_headers",
    "driver_go_offline",
    "driver_go_online",
    "enroll_driver_in_quest",
    "get_dispute",
    "get_driver",
    "get_grid",
    "get_quest_bonus",
    "get_ride",
    "get_rider",
    "join_airport_queue",
    "leave_airport_queue",
    "list_airport_queue",
    "list_heatmap",
    "reject_dispute",
    "setup_airport_grid_with_queued_driver",
    "setup_completed_ride_with_known_fare",
    "setup_disputed_ride",
    "setup_grid_with_demand_ratio",
    "setup_grid_with_supply",
    "setup_quest_payout_scenario",
    "setup_ride_quoted_vs_final_divergence",
    "setup_three_hop_assign_cascade",
    "setup_two_adjacent_grids",
    "setup_two_hop_refund_cascade",
    "start_ride",
    "sweep_recompute_surge",
]
