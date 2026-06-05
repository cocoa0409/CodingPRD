"""Validation priority conflicts, numeric boundaries, cross-entity state guards,
and temporal overlap checks at sort and dispatch.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]
SA = TEST_USERS["sort_associate_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ===========================================================================
# priority_pair_validation_conflict / hazmat_safety_beats_sort_capacity_constraint
# ===========================================================================

def test_hazmat_hub_error_beats_sort_capacity_error(api):
    """PRD §3.1: "If the parcel's `hazmat_class` is anything other than `NONE`,
    the target center's `hazmat_certified` must be true, or the request is
    rejected with `ERR_HAZMAT_HUB_NOT_CERTIFIED`. The hub must also have room:
    its `sorted_count` must be strictly less than its `sort_capacity`, otherwise
    the sort is rejected with `ERR_SORT_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/hazmat_safety_beats_sort_capacity_constraint
    """
    center = fx.create_center(name="Hub9", hazmat_certified=False, sort_capacity=1)
    pf = fx.create_parcel(weight_kg=1.0)
    fx.sort_parcel(pf["id"], center["id"])  # fills capacity
    ph = fx.create_parcel(weight_kg=1.0, hazmat_class="CLASS_3")

    resp = api.sort_parcel(ph["id"], {"center_id": center["id"]}, SA)
    validate_error(resp, ApiErrorId.ERR_HAZMAT_HUB_NOT_CERTIFIED)
    # hazmat parcel itself never sorted (state unchanged)
    parcel_d = validate_success(api.get_parcel(ph["id"], DM))
    assert parcel_d["status"] == "RECEIVED"


def test_hazmat_error_returned_even_when_center_full(api):
    """PRD §3.1: "If the parcel's `hazmat_class` is anything other than `NONE`,
    the target center's `hazmat_certified` must be true, or the request is
    rejected with `ERR_HAZMAT_HUB_NOT_CERTIFIED`. The hub must also have room:
    its `sorted_count` must be strictly less than its `sort_capacity`, otherwise
    the sort is rejected with `ERR_SORT_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/hazmat_safety_beats_sort_capacity_constraint
    """
    center = fx.create_center(name="Hub9b", hazmat_certified=False, sort_capacity=1)
    pf = fx.create_parcel(weight_kg=1.0)
    fx.sort_parcel(pf["id"], center["id"])  # at capacity
    ph = fx.create_parcel(weight_kg=1.0, hazmat_class="CLASS_8")
    resp = api.sort_parcel(ph["id"], {"center_id": center["id"]}, SA)
    # both hazmat-uncertified and full; safety check must win
    validate_error(resp, ApiErrorId.ERR_HAZMAT_HUB_NOT_CERTIFIED)


# ===========================================================================
# priority_pair_validation_conflict / capacity_fiscal_beats_occ_constraint
# ===========================================================================

def test_vehicle_capacity_error_beats_stale_version_error(api):
    """PRD §3.3: "The route's `committed_weight_kg` must not exceed the driver's
    `vehicle_capacity_kg`; if it does, the dispatch is rejected with
    `ERR_VEHICLE_CAPACITY_EXCEEDED`."
    PRD §3.3: "Finally, the request's `expected_route_version` must equal the
    route's current `version`, or it is rejected with `ERR_STALE_ROUTE_VERSION`
    (HTTP 412) per §2.8."

    Design: Difficulty/priority_pair_validation_conflict/capacity_fiscal_beats_occ_constraint
    """
    center = fx.create_center(name="Hub10", sort_capacity=10)
    driver = fx.create_driver(name="Dlow", vehicle_capacity_kg=5)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=9.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-18")
    fx.add_stop(route["id"], parcel["id"])
    rv = fx.current_route_version(route["id"])

    resp = api.dispatch_route(route["id"], {"expected_route_version": rv - 1}, DM)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_CAPACITY_EXCEEDED)
    route_d = validate_success(api.get_route(route["id"], DM))
    assert route_d["status"] == "PLANNING"


def test_capacity_error_with_stale_version_leaves_route_planning(api):
    """PRD §3.3: "The route's `committed_weight_kg` must not exceed the driver's
    `vehicle_capacity_kg`; if it does, the dispatch is rejected with
    `ERR_VEHICLE_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/capacity_fiscal_beats_occ_constraint
    """
    center = fx.create_center(name="Hub10b", sort_capacity=10)
    driver = fx.create_driver(name="Dlow2", vehicle_capacity_kg=5)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=9.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-18")
    fx.add_stop(route["id"], parcel["id"])
    rv = fx.current_route_version(route["id"])
    # carry stale version AND over capacity; capacity (fiscal) must surface
    resp = api.dispatch_route(route["id"], {"expected_route_version": rv - 1}, DM)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_CAPACITY_EXCEEDED)
    route_d = validate_success(api.get_route(route["id"], DM))
    assert route_d["status"] == "PLANNING"


# ===========================================================================
# boundary_precision_check / sort_capacity_boundary_at_capacity_rejected
# ===========================================================================

def test_sort_at_capacity_boundary_rejected(api):
    """PRD §3.1: "The hub must also have room: its `sorted_count` must be
    strictly less than its `sort_capacity`, otherwise the sort is rejected with
    `ERR_SORT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/sort_capacity_boundary_at_capacity_rejected
    """
    center = fx.create_center(name="Hub11", sort_capacity=1)
    pa = fx.create_parcel(weight_kg=1.0)
    fx.sort_parcel(pa["id"], center["id"])  # sorted_count == 1 == capacity
    pb = fx.create_parcel(weight_kg=1.0)

    resp = api.sort_parcel(pb["id"], {"center_id": center["id"]}, SA)
    validate_error(resp, ApiErrorId.ERR_SORT_CAPACITY_EXCEEDED)
    center_d = validate_success(api.get_transit_center(center["id"], DM))
    assert center_d["sorted_count"] == 1


def test_sort_below_capacity_boundary_allowed(api):
    """PRD §3.1: "The hub must also have room: its `sorted_count` must be
    strictly less than its `sort_capacity`, otherwise the sort is rejected with
    `ERR_SORT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/sort_capacity_boundary_at_capacity_rejected
    """
    center = fx.create_center(name="Hub11b", sort_capacity=2)
    pa = fx.create_parcel(weight_kg=1.0)
    fx.sort_parcel(pa["id"], center["id"])  # sorted_count 1 < capacity 2
    pb = fx.create_parcel(weight_kg=1.0)
    data = validate_success(api.sort_parcel(pb["id"], {"center_id": center["id"]}, SA))
    assert data["status"] == "SORTED"
    center_d = validate_success(api.get_transit_center(center["id"], DM))
    assert center_d["sorted_count"] == 2


# ===========================================================================
# boundary_precision_check / vehicle_capacity_boundary_equal_allowed
# ===========================================================================

def test_dispatch_at_capacity_boundary_equal_allowed(api):
    """PRD §3.3: "The route's `committed_weight_kg` must not exceed the driver's
    `vehicle_capacity_kg`; if it does, the dispatch is rejected with
    `ERR_VEHICLE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/vehicle_capacity_boundary_equal_allowed
    """
    center = fx.create_center(name="Hub12", sort_capacity=10)
    driver = fx.create_driver(name="Deq", vehicle_capacity_kg=10)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=10.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-19")
    stop = fx.add_stop(route["id"], parcel["id"])
    rv = fx.current_route_version(route["id"])

    data = validate_success(api.dispatch_route(route["id"], {"expected_route_version": rv}, DM))
    assert data["status"] == "DISPATCHED", (
        f"committed == capacity (10 == 10) must be allowed, got {data['status']}")
    stop_d = validate_success(api.get_stop(stop["id"], DM))
    assert stop_d["status"] == "OUT_FOR_DELIVERY"


def test_dispatch_over_capacity_boundary_rejected(api):
    """PRD §3.3: "The route's `committed_weight_kg` must not exceed the driver's
    `vehicle_capacity_kg`; if it does, the dispatch is rejected with
    `ERR_VEHICLE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/vehicle_capacity_boundary_equal_allowed
    """
    center = fx.create_center(name="Hub12b", sort_capacity=10)
    driver = fx.create_driver(name="Deq2", vehicle_capacity_kg=10)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=10.5)  # just over 10
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-19")
    fx.add_stop(route["id"], parcel["id"])
    rv = fx.current_route_version(route["id"])
    resp = api.dispatch_route(route["id"], {"expected_route_version": rv}, DM)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_CAPACITY_EXCEEDED)


# ===========================================================================
# cross_entity_state_dependency / dispatch_blocked_by_suspended_driver
# ===========================================================================

def test_dispatch_blocked_by_suspended_driver(api):
    """PRD §3.3: "The assigned driver's `status` must be `ACTIVE`, or the
    dispatch is rejected with `ERR_DRIVER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_driver
    """
    center = fx.create_center(name="Hub13", sort_capacity=10)
    driver = fx.create_driver(name="Dsus", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-20")
    fx.add_stop(route["id"], parcel["id"])
    get_success_data(api.suspend_driver(driver["id"], DM))
    rv = fx.current_route_version(route["id"])

    resp = api.dispatch_route(route["id"], {"expected_route_version": rv}, DM)
    validate_error(resp, ApiErrorId.ERR_DRIVER_SUSPENDED)
    route_d = validate_success(api.get_route(route["id"], DM))
    assert route_d["status"] == "PLANNING"


def test_dispatch_succeeds_with_active_driver(api):
    """PRD §3.3: "The assigned driver's `status` must be `ACTIVE`, or the
    dispatch is rejected with `ERR_DRIVER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_driver
    """
    center = fx.create_center(name="Hub13b", sort_capacity=10)
    driver = fx.create_driver(name="Dact", vehicle_capacity_kg=50)  # stays ACTIVE
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-20")
    fx.add_stop(route["id"], parcel["id"])
    rv = fx.current_route_version(route["id"])
    data = validate_success(api.dispatch_route(route["id"], {"expected_route_version": rv}, DM))
    assert data["status"] == "DISPATCHED", (
        f"an ACTIVE driver permits dispatch, got {data['status']}")


# ===========================================================================
# cross_entity_state_dependency / sort_blocked_by_closed_center
# ===========================================================================

def test_sort_blocked_by_closed_center(api):
    """PRD §3.1: "Sorting is a `SortAssociate` action that moves a parcel from
    `RECEIVED` to `SORTED` at a chosen hub, supplied as `center_id` in the
    request. The parcel must currently be in `RECEIVED` (otherwise
    `ERR_PARCEL_NOT_RECEIVED`), and the target center must be `OPEN` (otherwise
    `ERR_CENTER_CLOSED`)."

    Design: Difficulty/cross_entity_state_dependency/sort_blocked_by_closed_center
    """
    center = fx.create_center(name="Hub14", sort_capacity=10)
    get_success_data(api.close_transit_center(center["id"], DM))
    parcel = fx.create_parcel(weight_kg=1.0)

    resp = api.sort_parcel(parcel["id"], {"center_id": center["id"]}, SA)
    validate_error(resp, ApiErrorId.ERR_CENTER_CLOSED)
    parcel_d = validate_success(api.get_parcel(parcel["id"], DM))
    assert parcel_d["status"] == "RECEIVED"


def test_sort_succeeds_into_open_center(api):
    """PRD §3.1: "The parcel must currently be in `RECEIVED` (otherwise
    `ERR_PARCEL_NOT_RECEIVED`), and the target center must be `OPEN` (otherwise
    `ERR_CENTER_CLOSED`)."

    Design: Difficulty/cross_entity_state_dependency/sort_blocked_by_closed_center
    """
    center = fx.create_center(name="Hub14b", sort_capacity=10)  # stays OPEN
    parcel = fx.create_parcel(weight_kg=1.0)
    data = validate_success(api.sort_parcel(parcel["id"], {"center_id": center["id"]}, SA))
    assert data["status"] == "SORTED", (
        f"sorting into an OPEN center succeeds, got {data['status']}")


# ===========================================================================
# resource_temporal_overlap / appointment_buffered_window_conflict_on_route
# ===========================================================================

def test_appointment_buffered_window_conflict(api):
    """PRD §3.7: "The requested window must not collide with another
    non-`CANCELLED` stop on the same route once a 30-minute buffer is taken into
    account: a conflict exists when the requested start is earlier than another
    stop's window end plus 30 minutes and, simultaneously, the requested end plus
    30 minutes is later than that other stop's window start."

    Design: Difficulty/resource_temporal_overlap/appointment_buffered_window_conflict_on_route
    """
    center = fx.create_center(name="Hub15", sort_capacity=10)
    driver = fx.create_driver(name="Dt", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-21")
    fx.add_stop(route["id"], pa["id"], sequence=1, window_start_min=540, window_end_min=600)
    sb = fx.add_stop(route["id"], pb["id"], sequence=2, window_start_min=800, window_end_min=860)
    appt = fx.create_appointment(sb["id"], requested_start_min=610, requested_end_min=670)

    resp = api.apply_appointment(appt["id"], CSA)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_WINDOW_CONFLICT)
    appt_d = validate_success(api.get_appointment(appt["id"], CSA))
    assert appt_d["status"] == "REQUESTED"
    stop_d = validate_success(api.get_stop(sb["id"], DM))
    assert stop_d["window_start_min"] == 800


def test_appointment_outside_buffer_applies(api):
    """PRD §3.7: "a conflict exists when the requested start is earlier than
    another stop's window end plus 30 minutes and, simultaneously, the requested
    end plus 30 minutes is later than that other stop's window start."

    Design: Difficulty/resource_temporal_overlap/appointment_buffered_window_conflict_on_route
    """
    center = fx.create_center(name="Hub15b", sort_capacity=10)
    driver = fx.create_driver(name="Dt2", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-21")
    fx.add_stop(route["id"], pa["id"], sequence=1, window_start_min=540, window_end_min=600)
    sb = fx.add_stop(route["id"], pb["id"], sequence=2, window_start_min=900, window_end_min=960)
    # request [700,760]: 700 >= 600+30, gap to A is well over 30 -> no conflict
    appt = fx.create_appointment(sb["id"], requested_start_min=700, requested_end_min=760)
    data = validate_success(api.apply_appointment(appt["id"], CSA))
    assert data["status"] == "APPLIED", (
        f"a window outside the 30-min buffer applies cleanly, got {data['status']}")


# ===========================================================================
# resource_temporal_overlap / driver_double_booked_same_service_date
# ===========================================================================

def test_driver_double_booked_same_service_date(api):
    """PRD §3.3: "The driver must not already hold another `DISPATCHED` route
    whose `service_date` is identical to this route's `service_date`: dispatch
    claims the whole day exclusively, keyed on exact `service_date` string
    equality, and a collision is rejected with `ERR_DRIVER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/driver_double_booked_same_service_date
    """
    center = fx.create_center(name="Hub16", sort_capacity=10)
    driver = fx.create_driver(name="Ddb", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    r1 = fx.create_route(driver["id"], center["id"], service_date="2026-06-22")
    fx.add_stop(r1["id"], pa["id"])
    fx.dispatch_route(r1["id"])
    r2 = fx.create_route(driver["id"], center["id"], service_date="2026-06-22")
    fx.add_stop(r2["id"], pb["id"])
    rv2 = fx.current_route_version(r2["id"])

    resp = api.dispatch_route(r2["id"], {"expected_route_version": rv2}, DM)
    validate_error(resp, ApiErrorId.ERR_DRIVER_DOUBLE_BOOKED)
    r2_d = validate_success(api.get_route(r2["id"], DM))
    assert r2_d["status"] == "PLANNING"


def test_driver_dispatched_on_distinct_dates_allowed(api):
    """PRD §3.3: "The driver must not already hold another `DISPATCHED` route
    whose `service_date` is identical to this route's `service_date`: dispatch
    claims the whole day exclusively, keyed on exact `service_date` string
    equality, and a collision is rejected with `ERR_DRIVER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/driver_double_booked_same_service_date
    """
    center = fx.create_center(name="Hub16b", sort_capacity=10)
    driver = fx.create_driver(name="Ddb2", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    r1 = fx.create_route(driver["id"], center["id"], service_date="2026-06-22")
    fx.add_stop(r1["id"], pa["id"])
    fx.dispatch_route(r1["id"])
    r2 = fx.create_route(driver["id"], center["id"], service_date="2026-06-23")  # different date
    fx.add_stop(r2["id"], pb["id"])
    rv2 = fx.current_route_version(r2["id"])
    data = validate_success(api.dispatch_route(r2["id"], {"expected_route_version": rv2}, DM))
    assert data["status"] == "DISPATCHED", (
        f"a distinct service_date is not double-booked, got {data['status']}")
