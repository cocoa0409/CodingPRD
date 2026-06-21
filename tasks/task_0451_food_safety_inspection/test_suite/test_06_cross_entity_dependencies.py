"""Cross-entity state dependencies (inspection-start gated on establishment status,
complaint-close gated on linked-inspection status) and inspector / route resource
contention (exact-day double-booking, route-day capacity at and over the boundary).

Queue A (Difficulty): cross_entity_state_dependency, resource_temporal_overlap,
                      boundary_precision_check (route capacity boundary).
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_inspector, create_permitted_establishment,
    setup_suspended_via_closed_grade, setup_dispatched_complaint,
    setup_route_with_stops, schedule_inspection, start_inspection,
    set_clock,
    TEST_USERS, make_inspector_headers,
)

CLERK = TEST_USERS["permit_clerk_headers"]
DIRECTOR = TEST_USERS["health_director_headers"]


# ─── cross_entity_state_dependency / cesd_inspection_start_blocked_by_revoked ─
def test_start_inspection_blocked_by_revoked_establishment(api):
    """PRD §3.4: "starting requires the inspection to be `SCHEDULED` (otherwise
    `ERR_INSPECTION_NOT_SCHEDULED`), requires the acting inspector's `X-User-ID` to equal
    the inspection's `inspector_id` (otherwise `ERR_NOT_ASSIGNED_INSPECTOR`), and requires
    the establishment not to be revoked (otherwise `ERR_ESTABLISHMENT_REVOKED`)."

    A SCHEDULED reinspection on an establishment that is then REVOKED cannot be started.

    Design: Difficulty/cross_entity_state_dependency/cesd_inspection_start_blocked_by_revoked_establishment
    """
    set_clock(70)
    est, inspector, routine = setup_suspended_via_closed_grade(scheduled_index=70)[:3]
    # A still-SCHEDULED reinspection exists when the establishment is revoked.
    sched = schedule_inspection(est["id"], inspector["id"], 72, "REINSPECTION",
                                reinspection_of_id=routine["id"])
    validate_success(api.revoke_establishment(est["id"], DIRECTOR), 200)
    refetched = validate_success(api.get_establishment(est["id"], DIRECTOR), 200)
    assert refetched["status"] == "REVOKED", f"establishment revoked, got {refetched['status']}"

    res = api.start_inspection(sched["id"], make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_ESTABLISHMENT_REVOKED", expected_status=409)
    after = validate_success(api.get_inspection(sched["id"], CLERK), 200)
    assert after["status"] == "SCHEDULED", f"rejected start leaves SCHEDULED, got {after['status']}"


def test_finalize_blocked_by_revoked_establishment(api):
    """PRD §3.7: "it requires that the establishment not be revoked, since an inspection
    cannot be finalized — nor started — on a revoked establishment, which is rejected with
    `ERR_ESTABLISHMENT_REVOKED`."

    A COMPLETED inspection cannot be finalized once its establishment is REVOKED.

    Design: Difficulty/cross_entity_state_dependency/cesd_inspection_start_blocked_by_revoked_establishment
    """
    from test_helpers import setup_completed_inspection
    set_clock(70)
    est, inspector, completed = setup_completed_inspection(scheduled_index=70, violations=[])
    validate_success(api.revoke_establishment(est["id"], DIRECTOR), 200)
    res = api.finalize_inspection(
        completed["id"], {"expected_inspection_version": completed["version"]},
        make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_ESTABLISHMENT_REVOKED", expected_status=409)


# ─── cross_entity_state_dependency / cesd_complaint_close_blocked_by_open ────
def test_close_complaint_blocked_by_open_linked_inspection(api):
    """PRD §3.9: "closing requires the complaint to be `DISPATCHED` (otherwise
    `ERR_COMPLAINT_NOT_DISPATCHED`) and requires that the linked inspection have reached
    `FINALIZED` (otherwise `ERR_COMPLAINT_INSPECTION_OPEN`)."

    A DISPATCHED complaint whose spawned COMPLAINT inspection is still SCHEDULED cannot be
    closed.

    Design: Difficulty/cross_entity_state_dependency/cesd_complaint_close_blocked_by_open_linked_inspection
    """
    est, inspector, complaint = setup_dispatched_complaint(
        complaint_type="FOODBORNE_ILLNESS", reported_ill_count=3, scheduled_index=80)
    assert complaint["status"] == "DISPATCHED", f"complaint dispatched, got {complaint['status']}"
    assert complaint["linked_inspection_id"] is not None, "linked_inspection_id must be set"
    res = api.close_complaint(complaint["id"], CLERK)
    validate_error(res, "ERR_COMPLAINT_INSPECTION_OPEN", expected_status=409)
    after = validate_success(api.get_complaint(complaint["id"], CLERK), 200)
    assert after["status"] == "DISPATCHED", f"rejected close leaves DISPATCHED, got {after['status']}"


def test_dispatch_spawns_scheduled_complaint_inspection(api):
    """PRD §3.9: "Dispatch spawns a new `COMPLAINT`-type inspection in the `SCHEDULED`
    status, scheduled at the current clock index and assigned to the dispatching inspector,
    records that inspection's id on the complaint's `linked_inspection_id`, and moves the
    complaint to `DISPATCHED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_complaint_close_blocked_by_open_linked_inspection
    """
    est, inspector, complaint = setup_dispatched_complaint(
        complaint_type="FOODBORNE_ILLNESS", reported_ill_count=3, scheduled_index=80)
    linked = validate_success(api.get_inspection(complaint["linked_inspection_id"], CLERK), 200)
    assert linked["inspection_type"] == "COMPLAINT", f"spawned inspection is COMPLAINT, got {linked['inspection_type']}"
    assert linked["status"] == "SCHEDULED", f"spawned inspection is SCHEDULED, got {linked['status']}"


# ─── resource_temporal_overlap / rto_inspector_exact_day_collision ───────────
def test_inspector_double_booked_on_same_scheduled_index(api):
    """PRD §3.4: "The same inspector cannot be booked twice on the same day: if scheduling
    would place this inspection's `inspector_id` on a `scheduled_index` already occupied by
    another non-terminal inspection for that inspector, the request is rejected with
    `ERR_INSPECTOR_DOUBLE_BOOKED`."

    One SCHEDULED inspection for i1 at scheduled_index 90; a second for the same inspector
    at the same index collides.

    Design: Difficulty/resource_temporal_overlap/rto_inspector_exact_day_collision
    """
    set_clock(85)
    inspector = create_inspector()
    est1, _, _ = create_permitted_establishment(name="Diner E1", address="1 Main St")
    est2, _, _ = create_permitted_establishment(name="Diner E2", address="2 Main St")
    schedule_inspection(est1["id"], inspector["id"], 90, "ROUTINE")
    res = api.create_inspection(
        {"establishment_id": est2["id"], "inspector_id": inspector["id"],
         "inspection_type": "ROUTINE", "scheduled_index": 90}, CLERK)
    validate_error(res, "ERR_INSPECTOR_DOUBLE_BOOKED", expected_status=409)


def test_inspector_distinct_indices_do_not_collide(api):
    """PRD §3.4: "The same inspector cannot be booked twice on the same day: if scheduling
    would place this inspection's `inspector_id` on a `scheduled_index` already occupied by
    another non-terminal inspection for that inspector, the request is rejected with
    `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Two inspections for the same inspector on different scheduled_index values do not
    collide (the exclusion is a same-day point collision).

    Design: Difficulty/resource_temporal_overlap/rto_inspector_exact_day_collision
    """
    set_clock(85)
    inspector = create_inspector()
    est1, _, _ = create_permitted_establishment(name="Diner E1", address="1 Main St")
    est2, _, _ = create_permitted_establishment(name="Diner E2", address="2 Main St")
    schedule_inspection(est1["id"], inspector["id"], 90, "ROUTINE")
    res = api.create_inspection(
        {"establishment_id": est2["id"], "inspector_id": inspector["id"],
         "inspection_type": "ROUTINE", "scheduled_index": 91}, CLERK)
    second = validate_success(res, 201)
    assert second["scheduled_index"] == 91, f"distinct day schedules cleanly, got {second['scheduled_index']}"


# ─── resource_temporal_overlap / rto_route_day_aggregate_capacity_overflow ───
def test_route_capacity_exceeded_at_dispatch(api):
    """PRD §3.4: "Dispatch requires the route to be `PLANNED` (otherwise
    `ERR_ROUTE_NOT_PLANNED`); it also requires that the route's `route_date_index` be no
    earlier than the current clock index (otherwise `ERR_ROUTE_DATE_IN_PAST`) and that the
    route's `planned_stop_count` not exceed the assigned inspector's `max_daily_route_stops`
    (otherwise `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    An inspector with max_daily_route_stops 1 on a route holding 2 SCHEDULED inspections:
    dispatching trips ERR_ROUTE_CAPACITY_EXCEEDED (2 > 1).

    Design: Difficulty/resource_temporal_overlap/rto_route_day_aggregate_capacity_overflow
    """
    set_clock(95)
    inspector, route, inspections = setup_route_with_stops(
        num_stops=2, route_date_index=95, max_daily_route_stops=1, scheduled_base=95)
    assert route["planned_stop_count"] == 2, f"route holds 2 stops, got {route['planned_stop_count']}"
    res = api.dispatch_inspection_route(route["id"], make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=409)


def test_route_capacity_within_limit_dispatches(api):
    """PRD §3.4: "that the route's `planned_stop_count` not exceed the assigned inspector's
    `max_daily_route_stops` (otherwise `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    An inspector with max_daily_route_stops 3 on a route holding 2 SCHEDULED inspections
    dispatches successfully (2 does not exceed 3).

    Design: Difficulty/resource_temporal_overlap/rto_route_day_aggregate_capacity_overflow
    """
    set_clock(95)
    inspector, route, inspections = setup_route_with_stops(
        num_stops=2, route_date_index=95, max_daily_route_stops=3, scheduled_base=95)
    res = api.dispatch_inspection_route(route["id"], make_inspector_headers(inspector["id"]))
    dispatched = validate_success(res, 200)
    assert dispatched["status"] == "DISPATCHED", f"2 <= 3 dispatches, got {dispatched['status']}"


# ─── boundary_precision_check / bpc_route_capacity_at_exactly_max_stops ──────
def test_route_capacity_at_exactly_max_stops_dispatches(api):
    """PRD §3.4: "that the route's `planned_stop_count` not exceed the assigned inspector's
    `max_daily_route_stops` (otherwise `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    planned_stop_count 2 == max_daily_route_stops 2: dispatch succeeds (inclusive boundary —
    2 does not exceed 2).

    Design: Difficulty/boundary_precision_check/bpc_route_capacity_at_exactly_max_stops
    """
    set_clock(60)
    inspector, route, inspections = setup_route_with_stops(
        num_stops=2, route_date_index=60, max_daily_route_stops=2, scheduled_base=60)
    assert route["planned_stop_count"] == 2, f"route holds 2 stops, got {route['planned_stop_count']}"
    res = api.dispatch_inspection_route(route["id"], make_inspector_headers(inspector["id"]))
    dispatched = validate_success(res, 200)
    assert dispatched["status"] == "DISPATCHED", (
        f"2 <= 2 passes the inclusive capacity boundary, got {dispatched['status']}")


def test_route_capacity_one_over_max_stops_rejected(api):
    """PRD §3.4: "that the route's `planned_stop_count` not exceed the assigned inspector's
    `max_daily_route_stops` (otherwise `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    planned_stop_count 3 with max_daily_route_stops 2: one over the boundary trips
    ERR_ROUTE_CAPACITY_EXCEEDED.

    Design: Difficulty/boundary_precision_check/bpc_route_capacity_at_exactly_max_stops
    """
    set_clock(60)
    inspector, route, inspections = setup_route_with_stops(
        num_stops=3, route_date_index=60, max_daily_route_stops=2, scheduled_base=60)
    assert route["planned_stop_count"] == 3, f"route holds 3 stops, got {route['planned_stop_count']}"
    res = api.dispatch_inspection_route(route["id"], make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=409)
