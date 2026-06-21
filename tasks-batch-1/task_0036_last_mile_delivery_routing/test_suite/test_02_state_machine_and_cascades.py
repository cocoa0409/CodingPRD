"""Stop redelivery loop, parcel branch, multi-hop cascades, conserved quantities.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade,
compensating_invariant.
"""
import pytest
from test_helpers import validate_success, get_success_data, TEST_USERS
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]


# ===========================================================================
# non_linear_state_machine / stop_redelivery_loop_cycle
# ===========================================================================

def test_stop_cycles_attempted_redelivery_attempted(api):
    """PRD §3.5: "A stop that has gone to `REDELIVERY_SCHEDULED` is eligible for
    a fresh attempt and can again be driven to `DELIVERED` or back to
    `ATTEMPTED` per §3.4."

    Design: Difficulty/non_linear_state_machine/stop_redelivery_loop_cycle
    """
    s = fx.setup_redelivery_scheduled_stop(name_suffix="cyc", service_date="2026-06-14")
    attempt = fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "NO_ONE_HOME")

    stop = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop["status"] == "ATTEMPTED", (
        f"second failed attempt out of REDELIVERY_SCHEDULED returns to ATTEMPTED, got {stop['status']}")
    assert stop["attempt_count"] == 2
    assert attempt["attempt_index"] == 2


def test_attempt_index_increments_across_cycle(api):
    """PRD §3.4: "Each attempt also carries a computed `attempt_index`, the
    1-based chronological ordinal of that attempt on its stop (ordered by
    `created_at`), equal to the stop's `attempt_count` immediately after the append."

    Design: Difficulty/non_linear_state_machine/stop_redelivery_loop_cycle
    """
    s = fx.setup_redelivery_scheduled_stop(name_suffix="cyc2", service_date="2026-06-14")
    attempt = fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "REFUSED")
    assert attempt["attempt_index"] == 2, (
        f"attempt_index equals attempt_count after append, got {attempt['attempt_index']}")


# ===========================================================================
# non_linear_state_machine / parcel_branch_delivered_vs_returned
# ===========================================================================

def test_max_attempts_reschedule_drives_failed_and_returns_parcel(api):
    """PRD §3.5: "Once `attempt_count` has reached 3, redelivery is exhausted:
    rescheduling instead drives the stop to `FAILED`, cascades the parcel from
    `ROUTED` to `RETURNED`, and adds the return penalty to the driver's
    `failure_points`."

    Design: Difficulty/non_linear_state_machine/parcel_branch_delivered_vs_returned
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="br", service_date="2026-06-15")
    stop_id, driver_id, parcel_id = s["stop"]["id"], s["driver"]["id"], s["parcel"]["id"]
    # Three failed attempts, with a reschedule between the first two pairs.
    fx.log_attempt(stop_id, driver_id, "NO_ONE_HOME")
    fx.reschedule(stop_id)
    fx.log_attempt(stop_id, driver_id, "NO_ONE_HOME")
    fx.reschedule(stop_id)
    fx.log_attempt(stop_id, driver_id, "NO_ONE_HOME")
    data = validate_success(api.reschedule_stop(stop_id, DM))

    assert data["status"] == "FAILED", f"expected FAILED, got {data['status']}"
    assert data["attempt_count"] == 3
    parcel = validate_success(api.get_parcel(parcel_id, DM))
    assert parcel["status"] == "RETURNED", f"parcel should be RETURNED, got {parcel['status']}"


def test_parcel_branches_to_delivered_on_successful_attempt(api):
    """PRD §3.4: "A successful attempt — `outcome` of `DELIVERED` — drives the
    stop to `DELIVERED` from either `OUT_FOR_DELIVERY` or `REDELIVERY_SCHEDULED`,
    and cascades the parcel from `ROUTED` to `DELIVERED`."

    Design: Difficulty/non_linear_state_machine/parcel_branch_delivered_vs_returned
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="br2", service_date="2026-06-15")
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED")
    parcel = validate_success(api.get_parcel(s["parcel"]["id"], DM))
    assert parcel["status"] == "DELIVERED", (
        f"parcel forks ROUTED->DELIVERED on a successful attempt, got {parcel['status']}")


# ===========================================================================
# transitive_cascade / route_cancel_cascade_depth3_to_center_count
# ===========================================================================

def test_route_cancel_cascades_to_stop_parcel_and_center_count(api):
    """PRD §3.3: "Cancellation moves the route to `CANCELLED` and cascades down:
    every non-`CANCELLED` stop on the route is moved to `CANCELLED`, and for each
    such cascaded stop its parcel reverts from `ROUTED` back to `SORTED`, the
    parcel's `sorted_at_center_id` is restored to the route's `origin_center_id`,
    and that origin center's `sorted_count` is recomputed upward."

    Design: Difficulty/transitive_cascade/route_cancel_cascade_depth3_to_center_count
    """
    center = fx.create_center(name="Hub7", sort_capacity=10)
    driver = fx.create_driver(name="Dc", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=4.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-16")
    stop = fx.add_stop(route["id"], parcel["id"])

    rdata = validate_success(api.cancel_route(route["id"], DM))
    assert rdata["status"] == "CANCELLED"

    stop_d = validate_success(api.get_stop(stop["id"], DM))
    assert stop_d["status"] == "CANCELLED"
    parcel_d = validate_success(api.get_parcel(parcel["id"], DM))
    assert parcel_d["status"] == "SORTED"
    assert parcel_d["sorted_at_center_id"] == center["id"]
    center_d = validate_success(api.get_transit_center(center["id"], DM))
    assert center_d["sorted_count"] == 1, (
        f"origin center sorted_count restored to 1, got {center_d['sorted_count']}")


def test_route_cancel_restores_parcel_sorted_at_center_id(api):
    """PRD §3.3: "for each such cascaded stop its parcel reverts from `ROUTED`
    back to `SORTED`, the parcel's `sorted_at_center_id` is restored to the
    route's `origin_center_id`, and that origin center's `sorted_count` is
    recomputed upward."

    Design: Difficulty/transitive_cascade/route_cancel_cascade_depth3_to_center_count
    """
    center = fx.create_center(name="Hub7b", sort_capacity=10)
    driver = fx.create_driver(name="Dc2", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=4.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-16")
    fx.add_stop(route["id"], parcel["id"])
    fx.cancel_route(route["id"])

    parcel_d = validate_success(api.get_parcel(parcel["id"], DM))
    assert parcel_d["status"] == "SORTED"
    assert parcel_d["sorted_at_center_id"] == center["id"], (
        "parcel.sorted_at_center_id must be restored to the route's origin center")


# ===========================================================================
# transitive_cascade / attempt_delivered_cascade_depth2_to_parcel
# ===========================================================================

def test_delivered_attempt_cascades_stop_and_parcel(api):
    """PRD §3.4: "A successful attempt — `outcome` of `DELIVERED` — drives the
    stop to `DELIVERED` from either `OUT_FOR_DELIVERY` or `REDELIVERY_SCHEDULED`,
    and cascades the parcel from `ROUTED` to `DELIVERED`."

    Design: Difficulty/transitive_cascade/attempt_delivered_cascade_depth2_to_parcel
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="dl", service_date="2026-06-17")
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED")

    stop = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop["status"] == "DELIVERED"
    parcel = validate_success(api.get_parcel(s["parcel"]["id"], DM))
    assert parcel["status"] == "DELIVERED"


def test_delivered_attempt_stop_hop_is_delivered(api):
    """PRD §3.4: "A successful attempt — `outcome` of `DELIVERED` — drives the
    stop to `DELIVERED` from either `OUT_FOR_DELIVERY` or `REDELIVERY_SCHEDULED`,
    and cascades the parcel from `ROUTED` to `DELIVERED`."

    Design: Difficulty/transitive_cascade/attempt_delivered_cascade_depth2_to_parcel
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="dl2", service_date="2026-06-17")
    data = validate_success(api.create_attempt(
        s["stop"]["id"], {"outcome": "DELIVERED"},
        fx.make_driver_headers(s["driver"]["id"]),
    ), expected_status=201)
    assert data["outcome"] == "DELIVERED"
    stop = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop["status"] == "DELIVERED", (
        f"stop hop OUT_FOR_DELIVERY->DELIVERED, got {stop['status']}")


# ===========================================================================
# compensating_invariant / center_sorted_count_conserved_across_route_and_cancel
# ===========================================================================

def test_center_sorted_count_conserved_across_route_and_cancel(api):
    """PRD §3.1: "A center's `sorted_count` is always the count of parcels whose
    `status` is exactly `SORTED` and whose `sorted_at_center_id` equals that
    center's `id`; this recomputation runs on every sort, on stop creation (when
    a parcel leaves `SORTED` for `ROUTED`), and on stop or route cancellation
    (when a parcel reverts to `SORTED`)."

    Design: Difficulty/compensating_invariant/center_sorted_count_conserved_across_route_and_cancel
    """
    center = fx.create_center(name="Hub17", sort_capacity=10)
    driver = fx.create_driver(name="Dci", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=2.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-23")
    fx.add_stop(route["id"], parcel["id"])
    # at this point count is 0 (parcel ROUTED)
    fx.cancel_route(route["id"])

    center_d = validate_success(api.get_transit_center(center["id"], DM))
    assert center_d["sorted_count"] == 1, (
        f"sorted_count returns to its pre-route value 1, got {center_d['sorted_count']}")
    parcel_d = validate_success(api.get_parcel(parcel["id"], DM))
    assert parcel_d["status"] == "SORTED"


def test_center_sorted_count_drops_to_zero_after_stop_add(api):
    """PRD §3.1: "A center's `sorted_count` is always the count of parcels whose
    `status` is exactly `SORTED` and whose `sorted_at_center_id` equals that
    center's `id`; this recomputation runs on every sort, on stop creation (when
    a parcel leaves `SORTED` for `ROUTED`)".

    Design: Difficulty/compensating_invariant/center_sorted_count_conserved_across_route_and_cancel
    """
    center = fx.create_center(name="Hub17b", sort_capacity=10)
    driver = fx.create_driver(name="Dci2", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=2.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-23")
    fx.add_stop(route["id"], parcel["id"])
    # forward leg only: parcel ROUTED, count 1 -> 0
    center_d = validate_success(api.get_transit_center(center["id"], DM))
    assert center_d["sorted_count"] == 0, (
        f"forward leg drops sorted_count to 0, got {center_d['sorted_count']}")


# ===========================================================================
# compensating_invariant / committed_weight_conserved_across_stop_add_and_cancel
# ===========================================================================

def test_committed_weight_conserved_across_stop_add_and_cancel(api):
    """PRD §3.3: "Cancelling a `PENDING` stop moves it from `PENDING` to
    `CANCELLED`, reverts its parcel from `ROUTED` back to `SORTED` with the
    parcel's `sorted_at_center_id` restored to the route's `origin_center_id`,
    recomputes that origin center's `sorted_count` upward, and recomputes the
    route's load metrics."

    Design: Difficulty/compensating_invariant/committed_weight_conserved_across_stop_add_and_cancel
    """
    center = fx.create_center(name="Hub18", sort_capacity=10)
    driver = fx.create_driver(name="Dcw", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=2.5)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-24")
    stop = fx.add_stop(route["id"], parcel["id"])
    sdata = validate_success(api.cancel_stop(stop["id"], DM))
    assert sdata["status"] == "CANCELLED"

    route_d = validate_success(api.get_route(route["id"], DM))
    assert route_d["committed_weight_kg"] == 0.0, (
        f"committed_weight_kg returns to 0.0 after stop cancel, got {route_d['committed_weight_kg']}")
    parcel_d = validate_success(api.get_parcel(parcel["id"], DM))
    assert parcel_d["status"] == "SORTED"


def test_committed_weight_reflects_stop_add_before_cancel(api):
    """PRD §3.3: "On success, the new stop starts in `PENDING`, the parcel moves
    from `SORTED` to `ROUTED`, the origin center's `sorted_count` is recomputed
    downward, the route's `stop_count`, `planned_weight_kg`, and
    `committed_weight_kg` are recomputed".

    Design: Difficulty/compensating_invariant/committed_weight_conserved_across_stop_add_and_cancel
    """
    center = fx.create_center(name="Hub18b", sort_capacity=10)
    driver = fx.create_driver(name="Dcw2", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=2.5)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-24")
    fx.add_stop(route["id"], parcel["id"])
    # forward leg only: committed_weight_kg 0.0 -> 2.5
    route_d = validate_success(api.get_route(route["id"], DM))
    assert route_d["committed_weight_kg"] == 2.5, (
        f"stop add raises committed_weight_kg to 2.5, got {route_d['committed_weight_kg']}")
