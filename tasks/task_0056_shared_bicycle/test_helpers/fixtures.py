"""Composite setup helpers for the Shared Bicycle test suite.

Most interesting test claims require the system to be in a specific
state reached through 5–15 API calls (region → bike → on-shelf → rider
→ wallet top-up → ride → end → etc.). These helpers encapsulate those
preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):
- Rider is ENTITY-BACKED: 'When X-User-Role is Rider, X-User-ID is the
  id of the acting Rider entity; ownership checks on any resource that
  references a Rider compare the resource's foreign-key field to
  X-User-ID.' Every ownership-gated call by a Rider principal MUST use
  make_rider_headers(rider['id']), never a shared fallback string.
- Admin / Operator / FieldStaff are OPAQUE.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    adjust_payload,
    assign_workorder_payload,
    bike_fault_report_payload,
    clock_advance_payload,
    create_bike_payload,
    create_geofence_payload,
    create_loss_record_payload,
    create_region_payload,
    create_rider_payload,
    create_ride_payload,
    create_transfer_payload,
    create_workorder_payload,
    dispute_payload,
    emit_event_payload,
    end_ride_payload,
    grant_free_minutes_payload,
    make_square_polygon,
    patch_bike_payload,
    patch_geofence_payload,
    patch_region_payload,
    resolve_workorder_payload,
    ride_fault_report_payload,
    shelf_payload,
    wallet_credit_payload,
)
from .test_users import (
    TEST_USERS,
    make_rider_headers,
)


# ===========================================================================
# Shared role-header constants (all opaque roles)
# ===========================================================================
ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_headers_alt"]
OPERATOR = TEST_USERS["operator_headers"]
OPERATOR_ALT = TEST_USERS["operator_headers_alt"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]


# ===========================================================================
# Clock helper (PRD §2.6, §3.9)
# ===========================================================================
def advance_clock(minutes: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.6: 'The clock-advance capability accepts a single
    non-negative integer minutes parameter.'"""
    return get_success_data(api_client.advance_clock(
        clock_advance_payload(minutes=minutes), headers or ADMIN,
    ))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.9: 'The platform exposes an admin-only test-driving sweep
    capability that walks every bike with status AVAILABLE and opens
    work orders.'"""
    return get_success_data(api_client.run_sweep(headers or ADMIN))


# ===========================================================================
# Region
# ===========================================================================
def create_region(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'An admin sets it up.'"""
    return get_success_data(api_client.create_region(
        create_region_payload(**overrides), ADMIN,
    ))


def get_region(region_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_region(
        region_id, headers or ADMIN,
    ))


def patch_region(region_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.patch_region(
        region_id, patch_region_payload(**overrides), ADMIN,
    ))


# ===========================================================================
# Geofence
# ===========================================================================
def create_geofence(region_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'An admin defines a fence inside a specific region.'"""
    return get_success_data(api_client.create_geofence(
        region_id, create_geofence_payload(**overrides), ADMIN,
    ))


# ===========================================================================
# Bike
# ===========================================================================
def create_bike(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'A bike is registered to the platform.'"""
    return get_success_data(api_client.create_bike(
        create_bike_payload(**overrides), ADMIN,
    ))


def get_bike(bike_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_bike(
        bike_id, headers or ADMIN,
    ))


def shelf_bike_on(region_id: str, bike_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.2: 'Bringing a bike on-shelf into a specific region.'"""
    return get_success_data(api_client.shelf_bike(
        region_id, bike_id, shelf_payload(action="ON"),
        headers or OPERATOR,
    ))


def shelf_bike_off(region_id: str, bike_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.2: 'Taking a bike off-shelf — the same shelf endpoint with
    the opposite action.'"""
    return get_success_data(api_client.shelf_bike(
        region_id, bike_id, shelf_payload(action="OFF"),
        headers or OPERATOR,
    ))


def patch_bike(bike_id: str,
               headers: Optional[Dict[str, str]] = None,
               **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.patch_bike(
        bike_id, patch_bike_payload(**overrides),
        headers or FIELD_STAFF,
    ))


def recall_bike(bike_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.recall_bike(
        bike_id, headers or OPERATOR,
    ))


def release_recall_bike(
    bike_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(api_client.release_recall_bike(
        bike_id, headers or OPERATOR,
    ))


def scrap_bike(bike_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.scrap_bike(
        bike_id, headers or ADMIN,
    ))


# ===========================================================================
# Rider
# ===========================================================================
def create_rider(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'Riders are registered with a display name.'"""
    return get_success_data(api_client.create_rider(
        create_rider_payload(**overrides), ADMIN,
    ))


def get_rider(rider_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.1: 'A rider may read and act only on their own ... Rider
    record.' Pass make_rider_headers(rider_id) when the assertion
    requires ownership; the default uses Admin which can read any rider."""
    return get_success_data(api_client.get_rider(
        rider_id, headers or ADMIN,
    ))


def credit_wallet(rider_id: str, amount_cents: int) -> Dict[str, Any]:
    """PRD §3.3: 'Admin top-up credits an amount_cents directly into
    wallet_balance_cents.'"""
    return get_success_data(api_client.credit_wallet(
        rider_id, wallet_credit_payload(amount_cents=amount_cents), ADMIN,
    ))


def grant_free_minutes(rider_id: str, minutes: int) -> Dict[str, Any]:
    """PRD §3.3: 'Free-minute grant adds minutes to free_minutes_remaining.'"""
    return get_success_data(api_client.grant_free_minutes(
        rider_id, grant_free_minutes_payload(minutes=minutes), ADMIN,
    ))


def buy_monthly_pass(rider_id: str) -> Dict[str, Any]:
    """PRD §3.3: 'Monthly-pass purchase debits the rider's wallet by
    MONTHLY_PASS_PRICE_CENTS and sets monthly_pass_expires_minute to the
    current clock_minutes plus 43200 minutes.' The Rider role is
    entity-backed so identity must be threaded."""
    return get_success_data(api_client.buy_monthly_pass(
        rider_id, make_rider_headers(rider_id),
    ))


def create_funded_rider(
    *,
    wallet_balance_cents: int = 10000,
    free_minutes: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a rider, credit their wallet to `wallet_balance_cents`,
    and optionally grant free minutes. Returns the refreshed rider."""
    rider = create_rider(**overrides)
    if wallet_balance_cents > 0:
        credit_wallet(rider["id"], wallet_balance_cents)
    if free_minutes > 0:
        grant_free_minutes(rider["id"], free_minutes)
    return get_rider(rider["id"])


# ===========================================================================
# Ride
# ===========================================================================
def start_ride(rider: Dict[str, Any], bike: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.4: 'A rider initiates a ride by submitting a rider_id and
    a bike_id.' Uses make_rider_headers because POST /rides is an
    ownership-gated Rider-role action."""
    return get_success_data(api_client.create_ride(
        create_ride_payload(rider_id=rider["id"], bike_id=bike["id"]),
        make_rider_headers(rider["id"]),
    ))


def end_ride(ride: Dict[str, Any],
             end_lat: float = 30.5,
             end_lng: float = 120.5,
             rider_id: Optional[str] = None) -> Dict[str, Any]:
    """PRD §3.4: 'Locking up and ending the ride is the rider supplying
    an end_lat and end_lng.'"""
    rid = rider_id or ride["rider_id"]
    return get_success_data(api_client.end_ride(
        ride["id"],
        end_ride_payload(end_lat=end_lat, end_lng=end_lng),
        make_rider_headers(rid),
    ))


def report_fault_during_ride(
    ride: Dict[str, Any],
    *,
    end_lat: float = 30.5,
    end_lng: float = 120.5,
    category: str = "FLAT_TIRE",
    rider_id: Optional[str] = None,
) -> Dict[str, Any]:
    rid = rider_id or ride["rider_id"]
    return get_success_data(api_client.fault_report_ride(
        ride["id"],
        ride_fault_report_payload(
            end_lat=end_lat, end_lng=end_lng, category=category,
        ),
        make_rider_headers(rid),
    ))


def dispute_ride(ride: Dict[str, Any],
                 reason: str = "Fare looks wrong",
                 rider_id: Optional[str] = None) -> Dict[str, Any]:
    rid = rider_id or ride["rider_id"]
    return get_success_data(api_client.dispute_ride(
        ride["id"], dispute_payload(reason=reason),
        make_rider_headers(rid),
    ))


def adjust_ride(ride_id: str, new_final_fare_cents: int) -> Dict[str, Any]:
    return get_success_data(api_client.adjust_ride(
        ride_id,
        adjust_payload(new_final_fare_cents=new_final_fare_cents),
        ADMIN,
    ))


def void_ride(ride_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.void_ride(ride_id, ADMIN))


def get_ride(ride_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Default to ADMIN to dodge ownership gating during inspection."""
    return get_success_data(api_client.get_ride(
        ride_id, headers or ADMIN,
    ))


# ===========================================================================
# WorkOrder
# ===========================================================================
def create_workorder(
    *,
    bike_id: str,
    cause: str = "USER_REPORT",
    category: str = "FLAT_TIRE",
    sla_minutes: int = 240,
) -> Dict[str, Any]:
    return get_success_data(api_client.create_workorder(
        create_workorder_payload(
            bike_id=bike_id, cause=cause, category=category,
            sla_minutes=sla_minutes,
        ),
        OPERATOR,
    ))


def assign_workorder(workorder_id: str,
                     assigned_operator_id: str = "operator-assigned-001",
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.assign_workorder(
        workorder_id,
        assign_workorder_payload(assigned_operator_id=assigned_operator_id),
        headers or OPERATOR,
    ))


def resolve_workorder(workorder_id: str,
                      resolution_note: str = "Repaired") -> Dict[str, Any]:
    return get_success_data(api_client.resolve_workorder(
        workorder_id,
        resolve_workorder_payload(resolution_note=resolution_note),
        OPERATOR,
    ))


def cancel_workorder(workorder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_workorder(
        workorder_id, OPERATOR,
    ))


def list_workorders(**params: Any) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api_client.list_workorders(
        ADMIN, params=params or None,
    ))
    return rows


def find_workorder_for_bike(bike_id: str,
                            status: Optional[str] = None) -> Dict[str, Any]:
    """Find the most recently-opened WorkOrder for a given bike.

    Paginates server-side because tests share a single long-running
    process; accumulated state across earlier tests can easily exceed
    the default pagination window. PRD §2.3 supports limit up to 100.
    """
    matching: List[Dict[str, Any]] = []
    offset = 0
    page_size = 100
    while True:
        params: Dict[str, Any] = {"limit": page_size, "offset": offset}
        if status is not None:
            params["status"] = status
        rows = list_workorders(**params)
        matching.extend(w for w in rows if w.get("bike_id") == bike_id)
        if len(rows) < page_size:
            break
        offset += page_size
    assert matching, (
        f"No WorkOrder found for bike {bike_id} (status filter={status!r})"
    )
    return matching[-1]


# ===========================================================================
# TransferOrder
# ===========================================================================
def create_transfer(
    *,
    from_region_id: str,
    to_region_id: str,
    bike_ids: List[str],
) -> Dict[str, Any]:
    return get_success_data(api_client.create_transfer(
        create_transfer_payload(
            from_region_id=from_region_id,
            to_region_id=to_region_id,
            bike_ids=bike_ids,
        ),
        OPERATOR,
    ))


def dispatch_transfer(transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.dispatch_transfer(
        transfer_id, OPERATOR,
    ))


def complete_transfer(transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.complete_transfer(
        transfer_id, OPERATOR,
    ))


def cancel_transfer(transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_transfer(
        transfer_id, OPERATOR,
    ))


# ===========================================================================
# LossRecord
# ===========================================================================
def create_loss_record(
    *,
    bike_id: str,
    cause: str = "DAMAGE",
    responsibility: str = "UNKNOWN",
    responsible_party_id: Optional[str] = None,
    financial_impact_cents: int = 5000,
) -> Dict[str, Any]:
    return get_success_data(api_client.create_loss_record(
        create_loss_record_payload(
            bike_id=bike_id,
            cause=cause,
            responsibility=responsibility,
            responsible_party_id=responsible_party_id,
            financial_impact_cents=financial_impact_cents,
        ),
        ADMIN,
    ))


def list_loss_records(**params: Any) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api_client.list_loss_records(
        ADMIN, params=params or None,
    ))
    return rows


def get_region_loss_rate(region_id: str) -> Dict[str, Any]:
    """PRD §3.11: 'The region-level loss-rate read is admin-only.'"""
    return get_success_data(api_client.get_region_loss_rate(
        region_id, ADMIN,
    ))


# ===========================================================================
# Audit logs
# ===========================================================================
def list_audit_logs(**params: Any) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api_client.list_audit_logs(
        ADMIN, params=params or None,
    ))
    return rows


# ===========================================================================
# COMPOSITE / TIERED HELPERS
# ===========================================================================

# ---------------------------------------------------------------------------
# Tier 2 — Region + bike(s) ready for unlock
# ---------------------------------------------------------------------------
def setup_region_with_bikes(
    *,
    deployment_quota: int = 10,
    low_density_threshold: int = 0,
    high_density_threshold: int = 999,
    in_zone_return_reward_cents: int = 0,
    out_of_zone_penalty_cents: int = 0,
    num_bikes: int = 1,
    model: str = "STANDARD",
    battery_pct: Optional[int] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Region with `num_bikes` ON_SHELF / AVAILABLE bikes ready for unlock.

    All bikes share the same model. For E_BIKE, battery_pct defaults to
    100 (so on-shelf is unblocked).
    """
    # Auto-bump deployment_quota so the requested num_bikes can all be
    # ON_SHELF (PRD §3.2: 'deployed_count plus one must not exceed
    # deployment_quota'). The caller passed a default quota but expects
    # num_bikes to land on-shelf — honour their stated num_bikes intent.
    if num_bikes > deployment_quota:
        deployment_quota = num_bikes
    region = create_region(
        deployment_quota=deployment_quota,
        low_density_threshold=low_density_threshold,
        high_density_threshold=high_density_threshold,
        in_zone_return_reward_cents=in_zone_return_reward_cents,
        out_of_zone_penalty_cents=out_of_zone_penalty_cents,
    )
    bikes: List[Dict[str, Any]] = []
    for _ in range(num_bikes):
        kwargs: Dict[str, Any] = {"model": model}
        if model == "E_BIKE":
            kwargs["battery_pct"] = battery_pct if battery_pct is not None else 100
        elif battery_pct is not None:
            kwargs["battery_pct"] = battery_pct
        bike = create_bike(**kwargs)
        shelf_bike_on(region["id"], bike["id"])
        bikes.append(get_bike(bike["id"]))
    return get_region(region["id"]), bikes


def setup_basic_ride_scenario(
    *,
    wallet_balance_cents: int = 10000,
    free_minutes: int = 0,
    model: str = "STANDARD",
    **region_overrides: Any,
) -> Dict[str, Any]:
    """Single region + single ON_SHELF AVAILABLE bike + single funded
    Rider. Returns dict {region, bike, rider}."""
    region, bikes = setup_region_with_bikes(num_bikes=1, model=model,
                                            **region_overrides)
    rider = create_funded_rider(
        wallet_balance_cents=wallet_balance_cents,
        free_minutes=free_minutes,
    )
    return {"region": region, "bike": bikes[0], "rider": rider}


# ---------------------------------------------------------------------------
# Tier 3 — Full ride lifecycle helpers
# ---------------------------------------------------------------------------
def run_full_ride(
    *,
    duration_minutes: int = 20,
    end_lat: float = 30.5,
    end_lng: float = 120.5,
    wallet_balance_cents: int = 10000,
    free_minutes: int = 0,
    model: str = "STANDARD",
    in_zone_return_reward_cents: int = 0,
    out_of_zone_penalty_cents: int = 0,
    **region_overrides: Any,
) -> Dict[str, Any]:
    """End-to-end: region → bike → rider → unlock → advance clock →
    end-ride at given (end_lat, end_lng). Returns dict {region, bike,
    rider, ride (settled)}."""
    ctx = setup_basic_ride_scenario(
        wallet_balance_cents=wallet_balance_cents,
        free_minutes=free_minutes,
        model=model,
        in_zone_return_reward_cents=in_zone_return_reward_cents,
        out_of_zone_penalty_cents=out_of_zone_penalty_cents,
        **region_overrides,
    )
    ride = start_ride(ctx["rider"], ctx["bike"])
    if duration_minutes > 0:
        advance_clock(duration_minutes)
    settled = end_ride(ride, end_lat=end_lat, end_lng=end_lng,
                       rider_id=ctx["rider"]["id"])
    ctx["ride"] = settled
    return ctx


def settle_ride_and_dispute(
    *,
    duration_minutes: int = 20,
    **kwargs: Any,
) -> Dict[str, Any]:
    """End-to-end: settle a ride, then open a dispute. Returns dict
    with 'ride' carrying status DISPUTED."""
    ctx = run_full_ride(duration_minutes=duration_minutes, **kwargs)
    disputed = dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
    ctx["ride"] = disputed
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — Density/posture targeting
# ---------------------------------------------------------------------------
def setup_region_at_posture(
    target_posture: str,
    *,
    deployment_quota: int = 20,
    low_density_threshold: int = 4,
    high_density_threshold: int = 10,
    available_count_override: Optional[int] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a region and deploy enough AVAILABLE bikes so that
    density_posture matches target_posture (LOW | NORMAL | HIGH).

    PRD §2.7: LOW when available_count <= low_density_threshold,
    HIGH when available_count >= high_density_threshold.
    """
    if available_count_override is not None:
        num = available_count_override
    elif target_posture == "LOW":
        num = low_density_threshold     # boundary <= threshold
    elif target_posture == "HIGH":
        num = high_density_threshold    # boundary >= threshold
    elif target_posture == "NORMAL":
        num = low_density_threshold + 1
        if num >= high_density_threshold:
            raise ValueError(
                "Thresholds too tight for NORMAL posture; widen them"
            )
    else:
        raise ValueError(f"Unknown posture {target_posture}")
    region, bikes = setup_region_with_bikes(
        deployment_quota=deployment_quota,
        low_density_threshold=low_density_threshold,
        high_density_threshold=high_density_threshold,
        num_bikes=num,
    )
    region = get_region(region["id"])
    if region["density_posture"] != target_posture:
        raise AssertionError(
            f"Setup failed: expected posture {target_posture}, got "
            f"{region['density_posture']} "
            f"(available_count={region['available_count']}, "
            f"low={low_density_threshold}, high={high_density_threshold})"
        )
    return region, bikes


# ---------------------------------------------------------------------------
# Tier 4 — Transfer cascade targeting
# ---------------------------------------------------------------------------
def setup_transfer_cascade_three_hop() -> Dict[str, Any]:
    """Build the depth-3 cascade scenario:
      - R_LOW: posture=LOW (deploy 2 bikes; low=4 high=10)
      - R_SRC: posture=HIGH (deploy 6 bikes; low=0 high=5)
      - T1: REPLENISH plan from R_SRC -> R_LOW with 5 bikes (will flip
        R_LOW from LOW to NORMAL on completion).
      - T2: REPLENISH plan from R_SRC -> R_LOW with 1 bike (will be
        auto-cancelled by the hop-3 cascade after T1 completes).
    Dispatches T1, returns {r_low, r_src, t1, t2, t1_bikes, t2_bike,
    r_low_initial, r_src_initial}.
    """
    r_low, _ = setup_region_at_posture(
        "LOW", deployment_quota=20,
        low_density_threshold=4, high_density_threshold=10,
        available_count_override=2,
    )
    r_src, r_src_bikes = setup_region_at_posture(
        "HIGH", deployment_quota=20,
        low_density_threshold=0, high_density_threshold=5,
        available_count_override=6,
    )
    # snapshot pre-state
    r_low_initial = dict(r_low)
    r_src_initial = dict(r_src)

    # Pick 5 bikes for T1, 1 bike for T2 (disjoint sets)
    t1_bike_ids = [b["id"] for b in r_src_bikes[:5]]
    t2_bike_ids = [r_src_bikes[5]["id"]]

    t1 = create_transfer(
        from_region_id=r_src["id"], to_region_id=r_low["id"],
        bike_ids=t1_bike_ids,
    )
    t2 = create_transfer(
        from_region_id=r_src["id"], to_region_id=r_low["id"],
        bike_ids=t2_bike_ids,
    )
    # Dispatch T1 only (T2 stays PLANNED so hop-3 can cancel it)
    t1 = dispatch_transfer(t1["id"])
    return {
        "r_low": r_low, "r_src": r_src,
        "r_low_initial": r_low_initial, "r_src_initial": r_src_initial,
        "t1": t1, "t2": t2,
        "t1_bike_ids": t1_bike_ids, "t2_bike_ids": t2_bike_ids,
    }


# ---------------------------------------------------------------------------
# Tier 4 — Fault cascade (depth-2)
# ---------------------------------------------------------------------------
def setup_region_with_exact_available(
    *,
    available: int,
    low: int,
    high: int,
    deployment_quota: int = 20,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Same as setup_region_at_posture but specifying available_count
    directly. Returns (region, bikes)."""
    region, bikes = setup_region_with_bikes(
        deployment_quota=deployment_quota,
        low_density_threshold=low,
        high_density_threshold=high,
        num_bikes=available,
    )
    return get_region(region["id"]), bikes


# ---------------------------------------------------------------------------
# Tier 4 — Fare boundary targeting
# ---------------------------------------------------------------------------
def setup_minimal_fare_scenario(
    *,
    model: str = "STANDARD",
    in_zone_return_reward_cents: int = 0,
    out_of_zone_penalty_cents: int = 0,
    wallet_balance_cents: int = 10000,
    free_minutes: int = 0,
) -> Dict[str, Any]:
    """Region with reward=0 penalty=0 (so fare math is pure base_fare)
    and one funded rider on one ON_SHELF AVAILABLE bike."""
    return setup_basic_ride_scenario(
        deployment_quota=10,
        low_density_threshold=0,
        high_density_threshold=999,
        in_zone_return_reward_cents=in_zone_return_reward_cents,
        out_of_zone_penalty_cents=out_of_zone_penalty_cents,
        wallet_balance_cents=wallet_balance_cents,
        free_minutes=free_minutes,
        model=model,
    )


# ---------------------------------------------------------------------------
# Tier 4 — Restricted/Forbidden geofence layouts
# ---------------------------------------------------------------------------
def setup_region_with_restricted_zone(
    *,
    center_lat: float = 30.5,
    center_lng: float = 120.5,
    side: float = 0.001,
    out_of_zone_penalty_cents: int = 200,
    in_zone_return_reward_cents: int = 0,
    deployment_quota: int = 10,
    num_bikes: int = 1,
    model: str = "STANDARD",
) -> Dict[str, Any]:
    """Region with an active RESTRICTED Geofence centred at
    (center_lat, center_lng). End-of-ride coords inside the polygon
    will trigger penalty per PRD §3.4."""
    region, bikes = setup_region_with_bikes(
        deployment_quota=deployment_quota,
        low_density_threshold=0,
        high_density_threshold=999,
        in_zone_return_reward_cents=in_zone_return_reward_cents,
        out_of_zone_penalty_cents=out_of_zone_penalty_cents,
        num_bikes=num_bikes,
        model=model,
    )
    fence = create_geofence(
        region["id"],
        kind="RESTRICTED",
        polygon=make_square_polygon(
            center_lat=center_lat, center_lng=center_lng, side=side,
        ),
        active=True,
    )
    return {"region": region, "bikes": bikes, "fence": fence,
            "restricted_lat": center_lat, "restricted_lng": center_lng,
            "outside_lat": center_lat + 1.0, "outside_lng": center_lng + 1.0}


def setup_region_with_allowed_parking(
    *,
    center_lat: float = 30.5,
    center_lng: float = 120.5,
    side: float = 0.001,
    in_zone_return_reward_cents: int = 200,
    out_of_zone_penalty_cents: int = 0,
    deployment_quota: int = 10,
    num_bikes: int = 1,
    model: str = "STANDARD",
) -> Dict[str, Any]:
    """Region with an active ALLOWED_PARKING Geofence. End-of-ride
    coords inside the polygon trigger reward per PRD §3.4."""
    region, bikes = setup_region_with_bikes(
        deployment_quota=deployment_quota,
        low_density_threshold=0,
        high_density_threshold=999,
        in_zone_return_reward_cents=in_zone_return_reward_cents,
        out_of_zone_penalty_cents=out_of_zone_penalty_cents,
        num_bikes=num_bikes,
        model=model,
    )
    fence = create_geofence(
        region["id"],
        kind="ALLOWED_PARKING",
        polygon=make_square_polygon(
            center_lat=center_lat, center_lng=center_lng, side=side,
        ),
        active=True,
    )
    return {"region": region, "bikes": bikes, "fence": fence,
            "allowed_lat": center_lat, "allowed_lng": center_lng,
            "outside_lat": center_lat + 1.0, "outside_lng": center_lng + 1.0}


def setup_region_with_forbidden_zone(
    *,
    center_lat: float = 30.5,
    center_lng: float = 120.5,
    side: float = 0.001,
    deployment_quota: int = 10,
    num_bikes: int = 1,
) -> Dict[str, Any]:
    """Region with an active FORBIDDEN Geofence. Unlocks of bikes
    located in the polygon are blocked per PRD §3.4; end-of-ride coords
    in the polygon are also blocked."""
    region, bikes = setup_region_with_bikes(
        deployment_quota=deployment_quota,
        low_density_threshold=0,
        high_density_threshold=999,
        in_zone_return_reward_cents=0,
        out_of_zone_penalty_cents=0,
        num_bikes=num_bikes,
    )
    fence = create_geofence(
        region["id"],
        kind="FORBIDDEN",
        polygon=make_square_polygon(
            center_lat=center_lat, center_lng=center_lng, side=side,
        ),
        active=True,
    )
    return {"region": region, "bikes": bikes, "fence": fence,
            "forbidden_lat": center_lat, "forbidden_lng": center_lng,
            "outside_lat": center_lat + 1.0, "outside_lng": center_lng + 1.0}


# ---------------------------------------------------------------------------
# Pass-purchase / pre-funded rider helpers (PRD §3.3)
# ---------------------------------------------------------------------------
def setup_rider_with_monthly_pass(
    *,
    wallet_balance_cents: int = 10000,
    free_minutes: int = 0,
    pre_pass_topup_cents: int = 50_000,
) -> Dict[str, Any]:
    """Create a rider whose wallet is large enough to cover the
    monthly-pass purchase. PRD §3.3 does not pin MONTHLY_PASS_PRICE_CENTS
    publicly, so we top up generously, buy the pass, then leave the
    rider at the resulting (post-debit) balance."""
    rider = create_rider()
    credit_wallet(rider["id"], pre_pass_topup_cents)
    if free_minutes > 0:
        grant_free_minutes(rider["id"], free_minutes)
    rider = buy_monthly_pass(rider["id"])
    # Adjust wallet up to the caller-requested floor if needed.
    current_wallet = rider.get("wallet_balance_cents", 0)
    if wallet_balance_cents > current_wallet:
        credit_wallet(rider["id"], wallet_balance_cents - current_wallet)
    return get_rider(rider["id"])


# ---------------------------------------------------------------------------
# Convenience: settle a known-fare ride for use in dispute/adjust tests
# ---------------------------------------------------------------------------
def settle_simple_standard_ride(
    *,
    duration_minutes: int = 20,
    wallet_balance_cents: int = 10000,
) -> Dict[str, Any]:
    """Settle a STANDARD-bike ride at NONE-fence end coords with no
    free minutes / no pass. Fare math is deterministic:
      chargeable = duration, base = first_seg * 30 + over * 50.
    Returns {region, bike, rider, ride}."""
    return run_full_ride(
        duration_minutes=duration_minutes,
        end_lat=10.0, end_lng=10.0,        # far from any geofence
        wallet_balance_cents=wallet_balance_cents,
        free_minutes=0,
        model="STANDARD",
        in_zone_return_reward_cents=0,
        out_of_zone_penalty_cents=0,
    )


__all__ = [
    "ADMIN", "ADMIN_ALT", "OPERATOR", "OPERATOR_ALT", "FIELD_STAFF",
    "advance_clock", "run_sweep",
    "create_region", "get_region", "patch_region",
    "create_geofence",
    "create_bike", "get_bike",
    "shelf_bike_on", "shelf_bike_off",
    "patch_bike",
    "recall_bike", "release_recall_bike", "scrap_bike",
    "create_rider", "get_rider", "credit_wallet",
    "grant_free_minutes", "buy_monthly_pass",
    "create_funded_rider",
    "start_ride", "end_ride", "report_fault_during_ride",
    "dispute_ride", "adjust_ride", "void_ride", "get_ride",
    "create_workorder", "assign_workorder", "resolve_workorder",
    "cancel_workorder", "list_workorders", "find_workorder_for_bike",
    "create_transfer", "dispatch_transfer", "complete_transfer",
    "cancel_transfer",
    "create_loss_record", "list_loss_records", "get_region_loss_rate",
    "list_audit_logs",
    "setup_region_with_bikes",
    "setup_basic_ride_scenario",
    "run_full_ride",
    "settle_ride_and_dispute",
    "setup_region_at_posture",
    "setup_transfer_cascade_three_hop",
    "setup_region_with_exact_available",
    "setup_minimal_fare_scenario",
    "setup_region_with_restricted_zone",
    "setup_region_with_allowed_parking",
    "setup_region_with_forbidden_zone",
    "setup_rider_with_monthly_pass",
    "settle_simple_standard_ride",
]
