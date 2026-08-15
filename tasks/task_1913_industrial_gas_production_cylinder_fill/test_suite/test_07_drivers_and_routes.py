"""Driver certification and hazmat routing: window overlap, cert cascades,
dispatch revalidation, and the Driver role's scoped permissions (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_test_driver,
    create_test_route,
    get_driver,
    get_route,
    make_driver_headers,
    set_logical_clock,
    setup_assigned_route,
    setup_dispatched_route,
    validate_error,
    validate_success,
)

LC = TEST_USERS["logistics_coordinator_headers"]
PM = TEST_USERS["plant_manager_headers"]

NONFLAMMABLE = {"endorsement_class": "NONFLAMMABLE_GAS", "expiry_date": "2027-01-01"}


def _route(date="2026-08-05", start=8, end=12, classes=("NONFLAMMABLE_GAS",), name="S1"):
    return create_test_route(
        route_date=date, window_start_hour=start, window_end_hour=end,
        stops=[{"stop_name": name, "hazmat_classes": list(classes)}],
    )


# --- Difficulty: resource_temporal_overlap / driver_route_half_open_overlap ---

def test_same_date_interior_window_overlap_rejected(api):
    """PRD §3.7: "the driver must hold no other route in `DRIVER_ASSIGNED` or
    `DISPATCHED` on the same `route_date` whose half-open window overlaps this
    one, where windows that merely touch — one ending exactly when the other
    begins — do not overlap; a genuine overlap is rejected with
    `ERR_DRIVER_ROUTE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/driver_route_half_open_overlap
    """
    driver = create_test_driver(driver_name="D-TO1")
    route_a = _route(start=8, end=12, name="A1")
    validate_success(api.assign_driver(route_a["id"], {"driver_id": driver["id"]}, LC), 200)

    route_b = _route(start=10, end=14, name="B1")
    res = api.assign_driver(route_b["id"], {"driver_id": driver["id"]}, LC)
    validate_error(res, ApiErrorId.ERR_DRIVER_ROUTE_OVERLAP.value)
    assert get_route(route_b["id"])["status"] == "PLANNED"


def test_different_date_same_window_allowed(api):
    """PRD §3.7: "the driver must hold no other route in `DRIVER_ASSIGNED` or
    `DISPATCHED` on the same `route_date` whose half-open window overlaps this
    one" — routes on a different `route_date` never collide.

    Design: Difficulty/resource_temporal_overlap/driver_route_half_open_overlap
    """
    driver = create_test_driver(driver_name="D-TO1B")
    route_a = _route(date="2026-08-05", start=8, end=12, name="A1")
    validate_success(api.assign_driver(route_a["id"], {"driver_id": driver["id"]}, LC), 200)

    route_c = _route(date="2026-08-06", start=8, end=12, name="C1")
    assigned = validate_success(
        api.assign_driver(route_c["id"], {"driver_id": driver["id"]}, LC), 200
    )
    assert assigned["status"] == "DRIVER_ASSIGNED"


# --- Difficulty: boundary_precision_check / route_window_adjacency_half_open ---

def test_touching_windows_allowed(api):
    """PRD §3.7: "windows that merely touch — one ending exactly when the other
    begins — do not overlap"
    PRD §3.7: "a `window_start_hour` between 0 and 23 inclusive, a
    `window_end_hour` between 1 and 24 inclusive and strictly greater than the
    start — together defining a half-open window that includes the start hour and
    excludes the end hour"

    Design: Difficulty/boundary_precision_check/route_window_adjacency_half_open
    """
    driver = create_test_driver(driver_name="D-BP4")
    route_a = _route(start=8, end=12, name="A1")
    validate_success(api.assign_driver(route_a["id"], {"driver_id": driver["id"]}, LC), 200)

    route_b = _route(start=12, end=16, name="B1")
    assigned = validate_success(
        api.assign_driver(route_b["id"], {"driver_id": driver["id"]}, LC), 200
    )
    assert assigned["status"] == "DRIVER_ASSIGNED", "12-16 after 08-12: touching is allowed"


def test_one_hour_interior_overlap_rejected(api):
    """PRD §3.7: "the driver must hold no other route in `DRIVER_ASSIGNED` or
    `DISPATCHED` on the same `route_date` whose half-open window overlaps this
    one, where windows that merely touch — one ending exactly when the other
    begins — do not overlap; a genuine overlap is rejected with
    `ERR_DRIVER_ROUTE_OVERLAP`."

    Design: Difficulty/boundary_precision_check/route_window_adjacency_half_open
    """
    driver = create_test_driver(driver_name="D-BP4B")
    route_a = _route(start=8, end=12, name="A1")
    validate_success(api.assign_driver(route_a["id"], {"driver_id": driver["id"]}, LC), 200)

    route_c = _route(start=11, end=13, name="C1")
    res = api.assign_driver(route_c["id"], {"driver_id": driver["id"]}, LC)
    validate_error(res, ApiErrorId.ERR_DRIVER_ROUTE_OVERLAP.value)
    assert get_route(route_c["id"])["status"] == "PLANNED"


# --- Difficulty: priority_pair_validation_conflict / dispatch_assign_conflict_safety_beats_temporal ---

def _setup_safety_vs_temporal():
    """Driver holds only NONFLAMMABLE_GAS and already owns route X (08-12); route
    Y (10-14) demands POISON_GAS — missing class AND overlapping window."""
    driver = create_test_driver(driver_name="D-PP2")
    route_x = _route(start=8, end=12, name="X1")
    validate_success(api_client.assign_driver(route_x["id"], {"driver_id": driver["id"]}, LC), 200)
    route_y = _route(start=10, end=14, classes=("POISON_GAS",), name="Y1")
    return driver, route_x, route_y


def test_missing_endorsement_reported_over_window_overlap(api):
    """PRD §2.8: "When several checks could reject the same request, the
    rejection reported is the earliest applicable check in the order below"
    (hazmat coverage is check 8; route window overlap is check 10).
    PRD §3.7: "a required class for which the driver holds no endorsement at all
    is rejected with `ERR_HAZMAT_ENDORSEMENT_MISSING`; a class whose only
    covering endorsement expires before the `route_date` is rejected with
    `ERR_DRIVER_CERT_EXPIRED`, as is a medical card expiring before the
    `route_date`."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_assign_conflict_safety_beats_temporal
    """
    driver, route_x, route_y = _setup_safety_vs_temporal()
    res = api.assign_driver(route_y["id"], {"driver_id": driver["id"]}, LC)
    validate_error(res, ApiErrorId.ERR_HAZMAT_ENDORSEMENT_MISSING.value)


def test_rejected_assignment_leaves_route_unassigned(api):
    """PRD §3.7: "A successful assignment sets `driver_id`, moves the route to
    `DRIVER_ASSIGNED`, and increments its `version`." — a rejected assignment
    does none of these.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_assign_conflict_safety_beats_temporal
    """
    driver, route_x, route_y = _setup_safety_vs_temporal()
    res = api.assign_driver(route_y["id"], {"driver_id": driver["id"]}, LC)
    validate_error(res, ApiErrorId.ERR_HAZMAT_ENDORSEMENT_MISSING.value)
    after = get_route(route_y["id"])
    assert after["status"] == "PLANNED"
    assert after["driver_id"] is None


# --- Difficulty: cross_entity_state_dependency / dispatch_requires_driver_qualified_at_current_clock ---

def _setup_stale_cert_dispatch():
    """Driver medical expires 2026-08-10; route assigned while the clock is
    2026-08-01; clock then advanced past the medical expiry."""
    driver = create_test_driver(
        driver_name="D-CE4", medical_card_expiry="2026-08-10",
        hazmat_endorsements=[NONFLAMMABLE],
    )
    route = _route(date="2026-08-05", start=8, end=12, name="S1")
    validate_success(api_client.assign_driver(route["id"], {"driver_id": driver["id"]}, LC), 200)
    set_logical_clock("2026-08-15T00:00:00Z")
    return driver, route


def test_dispatch_rejected_when_medical_expired_at_current_clock(api):
    """PRD §3.7: "Dispatch re-validates against the current moment: the route
    must be `DRIVER_ASSIGNED` (else `ERR_ROUTE_INVALID_STATE`), and the driver
    must still be `QUALIFIED` with a medical card unexpired at the current clock
    date, otherwise the dispatch is rejected with `ERR_DRIVER_CERT_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_driver_qualified_at_current_clock
    """
    driver, route = _setup_stale_cert_dispatch()
    res = api.dispatch_route(route["id"], LC)
    validate_error(res, ApiErrorId.ERR_DRIVER_CERT_EXPIRED.value)


def test_failed_dispatch_is_not_a_cascade(api):
    """PRD §3.7: "otherwise the dispatch is rejected with
    `ERR_DRIVER_CERT_EXPIRED`. Success moves the route to `DISPATCHED` with a
    `version` increment." — a rejected dispatch performs no transition, and the
    cert-expiry cascade is defined only for driver record updates ("Updating a
    driver's `medical_card_expiry` or `hazmat_endorsements` such that any expiry
    falls earlier than the logical clock date flips the driver from `QUALIFIED`
    to `CERT_EXPIRED` and cascades"), not for dispatch failures.

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_driver_qualified_at_current_clock
    """
    driver, route = _setup_stale_cert_dispatch()
    res = api.dispatch_route(route["id"], LC)
    validate_error(res, ApiErrorId.ERR_DRIVER_CERT_EXPIRED.value)
    route_after = get_route(route["id"])
    assert route_after["status"] == "DRIVER_ASSIGNED"
    assert route_after["driver_id"] == driver["id"]
    assert get_driver(driver["id"])["status"] == "QUALIFIED"


# --- Difficulty: transitive_cascade / driver_cert_cascade_depth2 ---

def _setup_two_route_driver():
    """One driver holding a DRIVER_ASSIGNED route (08-12) and a DISPATCHED route
    (13-17) on the same date — non-overlapping half-open windows."""
    driver = create_test_driver(driver_name="D-TC2", medical_card_expiry="2026-08-20")
    route_a = _route(start=8, end=12, name="A1")
    validate_success(api_client.assign_driver(route_a["id"], {"driver_id": driver["id"]}, LC), 200)
    route_b = _route(start=13, end=17, name="B1")
    validate_success(api_client.assign_driver(route_b["id"], {"driver_id": driver["id"]}, LC), 200)
    validate_success(api_client.dispatch_route(route_b["id"], LC), 200)
    return driver, route_a, route_b


def test_cert_expiry_unassigns_assigned_route(api):
    """PRD §3.7: "Updating a driver's `medical_card_expiry` or
    `hazmat_endorsements` such that any expiry falls earlier than the logical
    clock date flips the driver from `QUALIFIED` to `CERT_EXPIRED` and cascades:
    every route of that driver in `DRIVER_ASSIGNED` or `DISPATCHED` returns to
    `PLANNED` with its `driver_id` cleared to null, and the driver's and each
    touched route's `version` increment."

    Design: Difficulty/transitive_cascade/driver_cert_cascade_depth2
    """
    driver, route_a, route_b = _setup_two_route_driver()
    patched = validate_success(
        api.patch_driver(driver["id"], {"medical_card_expiry": "2026-07-01"}, LC), 200
    )
    assert patched["status"] == "CERT_EXPIRED"
    after = get_route(route_a["id"])
    assert after["status"] == "PLANNED"
    assert after["driver_id"] is None


def test_cert_expiry_unassigns_dispatched_route(api):
    """PRD §3.7: "every route of that driver in `DRIVER_ASSIGNED` or
    `DISPATCHED` returns to `PLANNED` with its `driver_id` cleared to null, and
    the driver's and each touched route's `version` increment."

    Design: Difficulty/transitive_cascade/driver_cert_cascade_depth2
    """
    driver, route_a, route_b = _setup_two_route_driver()
    validate_success(
        api.patch_driver(driver["id"], {"medical_card_expiry": "2026-07-01"}, LC), 200
    )
    after = get_route(route_b["id"])
    assert after["status"] == "PLANNED", "DISPATCHED routes revert too"
    assert after["driver_id"] is None


# --- Difficulty: non_linear_state_machine / route_driver_unassign_reassign_cycle ---

def test_expired_driver_route_reverts_to_planned(api):
    """PRD §3.7: "Updating a driver's `medical_card_expiry` or
    `hazmat_endorsements` such that any expiry falls earlier than the logical
    clock date flips the driver from `QUALIFIED` to `CERT_EXPIRED` and cascades:
    every route of that driver in `DRIVER_ASSIGNED` or `DISPATCHED` returns to
    `PLANNED` with its `driver_id` cleared to null"

    Design: Difficulty/non_linear_state_machine/route_driver_unassign_reassign_cycle
    """
    driver, route = setup_assigned_route(
        driver_overrides={"driver_name": "D-NL3",
                          "medical_card_expiry": "2026-08-20"}
    )
    patched = validate_success(
        api.patch_driver(driver["id"], {"medical_card_expiry": "2026-07-01"}, LC), 200
    )
    assert patched["status"] == "CERT_EXPIRED"
    after = get_route(route["id"])
    assert after["status"] == "PLANNED"
    assert after["driver_id"] is None


def test_reinstated_driver_can_be_reassigned(api):
    """PRD §3.7: "Reinstatement — from `SUSPENDED` or from `CERT_EXPIRED` back to
    `QUALIFIED` — requires the medical card and every endorsement to expire on or
    after the clock date, and is rejected with `ERR_DRIVER_CERT_EXPIRED` when any
    credential is still expired."
    PRD §3.7: "A successful assignment sets `driver_id`, moves the route to
    `DRIVER_ASSIGNED`, and increments its `version`."

    Design: Difficulty/non_linear_state_machine/route_driver_unassign_reassign_cycle
    """
    driver, route = setup_assigned_route(
        driver_overrides={"driver_name": "D-NL3B",
                          "medical_card_expiry": "2026-08-20"}
    )
    validate_success(
        api.patch_driver(driver["id"], {"medical_card_expiry": "2026-07-01"}, LC), 200
    )
    validate_success(
        api.patch_driver(driver["id"], {"medical_card_expiry": "2027-06-01"}, LC), 200
    )
    reinstated = validate_success(
        api.set_driver_status(driver["id"], {"target_status": "QUALIFIED"}, LC), 200
    )
    assert reinstated["status"] == "QUALIFIED"

    reassigned = validate_success(
        api.assign_driver(route["id"], {"driver_id": driver["id"]}, LC), 200
    )
    assert reassigned["status"] == "DRIVER_ASSIGNED"
    assert reassigned["driver_id"] == driver["id"]


# --- Corner: endpoints / driver_completes_own_assigned_route ---

def test_driver_completes_own_assigned_route(api):
    """PRD §3.7: "Completion is permitted only from `DISPATCHED` (else
    `ERR_ROUTE_INVALID_STATE`) and may be performed by a `LogisticsCoordinator`
    or by the `Driver` whose identity equals the route's `driver_id` — a
    different driver is rejected with `ERR_UNAUTHORIZED_ROLE`; the route lands in
    `COMPLETED`, terminal."
    PRD §2.1: "Ownership checks on resources that reference a driver compare the
    resource's `driver_id` field to `X-User-ID`: a `Driver` may complete only a
    route assigned to them personally, and a `Driver` may never cancel a route."

    Design: Corner/endpoints/driver_completes_own_assigned_route
    """
    driver1 = create_test_driver(driver_name="D-EP1-A")
    driver2 = create_test_driver(driver_name="D-EP1-B")
    route = _route(name="S1")
    validate_success(api.assign_driver(route["id"], {"driver_id": driver1["id"]}, LC), 200)
    validate_success(api.dispatch_route(route["id"], LC), 200)

    res = api.set_route_status(
        route["id"], {"target_status": "COMPLETED"}, make_driver_headers(driver2["id"])
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    completed = validate_success(
        api.set_route_status(
            route["id"], {"target_status": "COMPLETED"},
            make_driver_headers(driver1["id"]),
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"


# --- Corner: rbac / driver_cannot_cancel_route ---

def test_driver_cannot_cancel_route(api):
    """PRD §3.7: "Cancellation is a coordinator-only action permitted from
    `PLANNED`, `DRIVER_ASSIGNED`, or `DISPATCHED` — from a terminal state it is
    rejected with `ERR_ROUTE_INVALID_STATE`, and a `Driver` attempting any
    cancellation is rejected with `ERR_UNAUTHORIZED_ROLE`; the route lands in
    `CANCELLED`, terminal."

    Design: Corner/rbac/driver_cannot_cancel_route
    """
    driver, route = setup_dispatched_route(driver_overrides={"driver_name": "D-RB2"})
    res = api.set_route_status(
        route["id"], {"target_status": "CANCELLED"}, make_driver_headers(driver["id"])
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    assert get_route(route["id"])["status"] == "DISPATCHED"
