"""Route planning, dispatch, pickup execution, and theft-cascade tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_container,
    create_customer,
    create_manifest,
    create_theft_incident_payload,
    create_truck,
    dispatch_manifest,
    get_success_data,
    make_driver_headers,
    manifest_visits,
    container_visits,
    set_clock,
    setup_completed_visit,
    setup_dispatched_single_stop,
    start_visit,
    complete_visit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    BILL,
    DISP,
    FOPS,
    PLANT,
    create_active_customer,
    create_contract,
)


# ---------------------------------------------------------------------------
# Corner: dispatch side effect flips PLACED -> ACTIVE
# ---------------------------------------------------------------------------

def test_dispatch_activates_placed_container(api, field_ops_headers):
    """PRD §3.3: "A new container starts in `PLACED` status and remains `PLACED`
    until a route covering it is dispatched, at which point it flips `PLACED` →
    `ACTIVE` automatically."
    PRD §3.4: "On dispatch, every `PLACED` stop container transitions to
    `ACTIVE` and the manifest's `version` increments."

    Design: Corner/endpoints/c_dispatch_activates_placed_container
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Place House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKPL")
    assert container["status"] == "PLACED"
    truck = create_truck(plate="T-C15", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    after = get_success_data(api.get_container(container["id"], field_ops_headers))
    assert after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: truck service-date point uniqueness (difficulty instance)
# ---------------------------------------------------------------------------

def _point_setup(api):
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Point House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKPT")
    truck = create_truck(plate="T-13", tank_capacity=500)
    manifest1 = create_manifest(truck["id"], [container["id"]],
                                service_date="2026-08-10")
    return customer, container, truck, manifest1


def test_second_manifest_same_truck_same_date_rejected(api):
    """PRD §3.4: "Only one manifest may exist per truck per service date — a
    date-point uniqueness rule, not an interval rule — and a second manifest
    for the same truck and date is rejected with `ERR_MANIFEST_DATE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/truck_service_date_point_uniqueness
    """
    _, container, truck, _ = _point_setup(api)
    resp = api.create_manifest(
        {
            "truck_id": truck["id"],
            "driver_ref": "drv-2",
            "service_date": "2026-08-10",
            "container_ids": [container["id"]],
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_MANIFEST_DATE_CONFLICT, expected_status=409)


def test_manifest_same_truck_next_date_allowed(api):
    """PRD §3.4: "Only one manifest may exist per truck per service date — a
    date-point uniqueness rule, not an interval rule"

    Design: Difficulty/resource_temporal_overlap/truck_service_date_point_uniqueness
    """
    _, container, truck, _ = _point_setup(api)
    resp = api.create_manifest(
        {
            "truck_id": truck["id"],
            "driver_ref": "drv-1",
            "service_date": "2026-08-11",
            "container_ids": [container["id"]],
        },
        DISP,
    )
    data = validate_success(resp, expected_status=201)
    assert data["service_date"] == "2026-08-11"
    assert data["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty: dispatch fill equals tank capacity (boundary)
# ---------------------------------------------------------------------------

def _tank_boundary_setup(api):
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Tank House")
    c1 = create_container(customer["id"], capacity=400, fill_rate=250, lock_code="LKT1")
    c2 = create_container(customer["id"], capacity=400, fill_rate=250, lock_code="LKT2")
    c3 = create_container(customer["id"], capacity=400, fill_rate=250, lock_code="LKT3")
    c4 = create_container(customer["id"], capacity=400, fill_rate=251, lock_code="LKT4")
    truck = create_truck(plate="T-10", tank_capacity=500)
    man_ok = create_manifest(truck["id"], [c1["id"], c2["id"]],
                             service_date="2026-08-05")
    man_bad = create_manifest(truck["id"], [c3["id"], c4["id"]],
                              service_date="2026-08-06")
    return man_ok, man_bad


def test_dispatch_projected_fill_equal_to_capacity_allowed(api):
    """PRD §3.4: "the projected fill fits the tank, where a projection strictly
    greater than `tank_capacity_gallons` is rejected with
    `ERR_TANK_CAPACITY_EXCEEDED` while a projection exactly equal to capacity
    dispatches"
    PRD §3.4: "for each stop, the system takes the smaller of the container's
    `capacity_gallons` and its `est_fill_rate_gal_per_week`, then sums across
    all stops, expressed at two decimal places."

    Design: Difficulty/boundary_precision_check/dispatch_fill_equals_tank_capacity_allowed
    """
    man_ok, _ = _tank_boundary_setup(api)
    assert man_ok["projected_fill_gallons"] == pytest.approx(500, abs=0.001), (
        "min(400,250) + min(400,250) == 500, exactly truck capacity"
    )
    resp = api.dispatch_manifest(man_ok["id"], {"start_level_gallons": 0}, DISP)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "DISPATCHED"


def test_dispatch_projected_fill_above_capacity_rejected(api):
    """PRD §2.9: "a projection strictly greater than tank capacity rejects the
    dispatch, while a projection exactly equal to capacity is permitted."

    Design: Difficulty/boundary_precision_check/dispatch_fill_equals_tank_capacity_allowed
    """
    _, man_bad = _tank_boundary_setup(api)
    assert man_bad["projected_fill_gallons"] == pytest.approx(501, abs=0.001)
    resp = api.dispatch_manifest(man_bad["id"], {"start_level_gallons": 0}, DISP)
    validate_error(resp, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED, expected_status=422)


# ---------------------------------------------------------------------------
# Corner: dispatch with out-of-service truck / suspended customer
# ---------------------------------------------------------------------------

def test_dispatch_out_of_service_truck_rejected(api):
    """PRD §3.4: "Dispatch refuses a truck that is `OUT_OF_SERVICE` with
    `ERR_TRUCK_UNAVAILABLE`."

    Design: Corner/errors/c_dispatch_out_of_service_truck_rejected
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Fleet House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKFL")
    truck = create_truck(plate="T-C22", tank_capacity=500)
    get_success_data(
        api.set_truck_service_status(truck["id"], {"status": "OUT_OF_SERVICE"}, DISP)
    )
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-08-05")
    resp = api.dispatch_manifest(manifest["id"], {"start_level_gallons": 0}, DISP)
    validate_error(resp, ApiErrorId.ERR_TRUCK_UNAVAILABLE, expected_status=409)
    after = get_success_data(api.get_manifest(manifest["id"], DISP))
    assert after["status"] == "DRAFT"


def test_dispatch_suspended_customer_rejected(api, field_ops_headers):
    """PRD §3.4: "every stop container's customer is `ACTIVE` — a suspended
    customer anywhere on the route yields `ERR_CUSTOMER_SUSPENDED`."

    Design: Corner/validations/c_dispatch_suspended_customer_rejected
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Susp House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKSU")
    get_success_data(
        api.suspend_customer(
            customer["id"], {"reason": "chronic inaccessibility"}, field_ops_headers
        )
    )
    truck = create_truck(plate="T-C14", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-08-05")
    resp = api.dispatch_manifest(manifest["id"], {"start_level_gallons": 0}, DISP)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED, expected_status=409)
    after = get_success_data(api.get_manifest(manifest["id"], DISP))
    assert after["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: pickup complete from SCHEDULED rejected (invalid transition)
# ---------------------------------------------------------------------------

def test_pickup_complete_from_scheduled_rejected(api):
    """PRD §3.5: "At the tank, the driver completes the visit (`EN_ROUTE` →
    `COMPLETED`) by recording `pump_gallons`"
    PRD §2.8: "fifth, state-machine legality — the requested transition must be
    defined from the entity's current state, including terminal-state lockdown
    (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/c_pickup_complete_from_scheduled_rejected
    """
    ctx = setup_dispatched_single_stop(name="SM House", truck_plate="T-C1")
    set_clock("2026-08-05T08:00:00Z")
    # Visit is still SCHEDULED (never started).
    resp = api.complete_pickup_visit(
        ctx["visit"]["id"],
        {"pump_gallons": 100.00, "field_moisture_pct": 5.0},
        make_driver_headers("drv-1"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_pickup_visit(ctx["visit"]["id"], DISP))
    assert after["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: completing before the scheduled date (default clock, no clock-set)
# ---------------------------------------------------------------------------

def test_complete_before_service_date_rejected(api):
    """PRD §3.5: "the logical clock date must be on or after the visit's
    `scheduled_date`, otherwise `ERR_PICKUP_WINDOW_FUTURE`"
    PRD §2.4: "Before any such call, the clock's startup default is exactly
    2026-08-01T00:00:00Z; the server must not fall back to wall-clock time at
    any point."

    Design: Corner/validations/c_complete_before_service_date_rejected
    """
    # No clock-set: default clock is 2026-08-01T00:00:00Z.
    customer = create_customer(name="Early House", address="33 Fry Way")
    contract = create_contract(customer["id"], activate=True)
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKE")
    truck = create_truck(plate="T-C11", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    visit = manifest_visits(manifest["id"])[0]
    start_visit(visit["id"])
    resp = api.complete_pickup_visit(
        visit["id"],
        {"pump_gallons": 100.00, "field_moisture_pct": 5.0},
        make_driver_headers("drv-1"),
    )
    validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_FUTURE, expected_status=422)


# ---------------------------------------------------------------------------
# Corner: pump over container capacity
# ---------------------------------------------------------------------------

def test_pump_over_container_capacity_rejected(api):
    """PRD §3.5: "it must not exceed the container's `capacity_gallons`,
    otherwise `ERR_CONTAINER_CAPACITY_EXCEEDED`."

    Design: Corner/errors/c_pump_over_container_capacity_rejected
    """
    ctx = setup_dispatched_single_stop(name="Over House", truck_plate="T-C23")
    set_clock("2026-08-05T08:00:00Z")
    start_visit(ctx["visit"]["id"])
    resp = api.complete_pickup_visit(
        ctx["visit"]["id"],
        {"pump_gallons": 400.00, "field_moisture_pct": 5.0},
        make_driver_headers("drv-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CONTAINER_CAPACITY_EXCEEDED,
                   expected_status=422)
    after = get_success_data(api.get_pickup_visit(ctx["visit"]["id"], DISP))
    assert after["status"] == "EN_ROUTE"


# ---------------------------------------------------------------------------
# Corner / Difficulty: theft cascade
# ---------------------------------------------------------------------------

def _theft_cascade_setup(api):
    """Customer ACTIVE, one ACTIVE container, three dispatched manifests each
    with the container as sole stop; theft incident REPORTED."""
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Cascade House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKC")
    truck = create_truck(plate="T-5", tank_capacity=500)
    visits = []
    for date in ("2026-08-03", "2026-08-04", "2026-08-05"):
        manifest = create_manifest(truck["id"], [container["id"]], service_date=date)
        dispatch_manifest(manifest["id"], start_level=0)
        visits.append(manifest_visits(manifest["id"])[0])
    incident = get_success_data(
        api.create_theft_incident(
            create_theft_incident_payload(
                container_id=container["id"], evidence_note="lock cut, oil drained"
            ),
            FOPS,
        )
    )
    set_clock("2026-08-06T00:00:00Z")
    return customer, container, incident, visits


def test_theft_confirm_locks_container_and_skips_scheduled_visits(api, field_ops_headers):
    """PRD §3.3: "The incident moves `REPORTED` → `CONFIRMED`. The container
    moves `ACTIVE` → `LOCKED`. Every `SCHEDULED` pickup visit of that container
    moves to `SKIPPED`, with `skipped_at` stamped from the logical clock"

    Design: Difficulty/transitive_cascade/theft_confirm_lock_skip_suspend_cascade
    """
    _, container, incident, visits = _theft_cascade_setup(api)
    get_success_data(api.confirm_theft_incident(incident["id"], FOPS))
    container_after = get_success_data(api.get_container(container["id"], field_ops_headers))
    assert container_after["status"] == "LOCKED"
    for v in visits:
        v_after = get_success_data(api.get_pickup_visit(v["id"], DISP))
        assert v_after["status"] == "SKIPPED"
        assert v_after["skipped_at"], "skipped_at must be stamped on each skip"


def test_theft_confirm_suspends_customer_at_threshold(api, field_ops_headers):
    """PRD §3.3: "For each skipped visit, the owning customer's
    `missed_pickup_count` is recomputed, and when the count reaches the
    suspension threshold of 3 the customer transitions `ACTIVE` → `SUSPENDED`."

    Design: Difficulty/transitive_cascade/theft_confirm_lock_skip_suspend_cascade
    """
    customer, _, incident, _ = _theft_cascade_setup(api)
    get_success_data(api.confirm_theft_incident(incident["id"], FOPS))
    customer_after = get_success_data(api.get_customer(customer["id"], field_ops_headers))
    assert customer_after["missed_pickup_count"] == 3
    assert customer_after["status"] == "SUSPENDED"


def test_theft_confirm_skips_only_scheduled_visits(api, field_ops_headers):
    """PRD §3.3: "visits already `EN_ROUTE` are deliberately not auto-skipped,
    because the driver is already on site and decides between completing and
    failing."
    PRD §3.1: "Whenever a skip lands and the recomputed count is at least 3
    while the customer is `ACTIVE`, the customer transitions `ACTIVE` →
    `SUSPENDED` automatically."

    Design: Corner/state_machines/c_theft_confirm_skips_only_scheduled_visits
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Cond House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKCD")
    truck = create_truck(plate="T-C3", tank_capacity=500)
    man1 = create_manifest(truck["id"], [container["id"]], service_date="2026-08-03")
    dispatch_manifest(man1["id"], start_level=0)
    man2 = create_manifest(truck["id"], [container["id"]], service_date="2026-08-04")
    dispatch_manifest(man2["id"], start_level=0)
    v1 = manifest_visits(man1["id"])[0]
    v2 = manifest_visits(man2["id"])[0]
    start_visit(v1["id"])  # v1 -> EN_ROUTE
    incident = get_success_data(
        api.create_theft_incident(
            create_theft_incident_payload(
                container_id=container["id"], evidence_note="fresh tool marks"
            ),
            FOPS,
        )
    )
    get_success_data(api.confirm_theft_incident(incident["id"], FOPS))
    v1_after = get_success_data(api.get_pickup_visit(v1["id"], DISP))
    v2_after = get_success_data(api.get_pickup_visit(v2["id"], DISP))
    assert v1_after["status"] == "EN_ROUTE", "in-progress visit must not be skipped"
    assert v2_after["status"] == "SKIPPED"
    customer_after = get_success_data(api.get_customer(customer["id"], field_ops_headers))
    assert customer_after["missed_pickup_count"] == 1
    assert customer_after["status"] == "ACTIVE", "count 1 is below the threshold of 3"


# ---------------------------------------------------------------------------
# Corner: container unlock blocked by confirmed theft; reopens after resolve
# ---------------------------------------------------------------------------

def test_container_unlock_blocked_by_confirmed_theft_rejected(api, field_ops_headers):
    """PRD §3.3: "Removal or unlocking while a confirmed incident exists is
    rejected with `ERR_THEFT_UNRESOLVED`; otherwise unlocking returns the
    container `LOCKED` → `ACTIVE`."

    Design: Corner/state_machines/c_container_unlock_blocked_by_confirmed_theft_rejected
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Lock House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKU")
    truck = create_truck(plate="T-C2", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    incident = get_success_data(
        api.create_theft_incident(
            create_theft_incident_payload(
                container_id=container["id"], evidence_note="hinge cut"
            ),
            FOPS,
        )
    )
    get_success_data(api.confirm_theft_incident(incident["id"], FOPS))
    resp = api.unlock_container(container["id"], field_ops_headers)
    validate_error(resp, ApiErrorId.ERR_THEFT_UNRESOLVED, expected_status=409)
    get_success_data(
        api.resolve_theft_incident(
            incident["id"], {"resolution_note": "lock replaced"}, FOPS
        )
    )
    unlocked = get_success_data(api.unlock_container(container["id"], field_ops_headers))
    assert unlocked["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: pickup complete requires container ACTIVE (cross-entity guard)
# ---------------------------------------------------------------------------

def _locked_en_route_setup(api):
    """Visit EN_ROUTE; theft CONFIRMED locks the container (EN_ROUTE not skipped)."""
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Guard House")
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKG")
    truck = create_truck(plate="T-11", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    visit = manifest_visits(manifest["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(visit["id"])
    incident = get_success_data(
        api.create_theft_incident(
            create_theft_incident_payload(
                container_id=container["id"], evidence_note="lock missing"
            ),
            FOPS,
        )
    )
    get_success_data(api.confirm_theft_incident(incident["id"], FOPS))
    return customer, container, manifest, visit


def test_complete_on_locked_container_rejected(api):
    """PRD §3.5: "the container must be `ACTIVE`, and completing against a
    `LOCKED` container is rejected with `ERR_CONTAINER_LOCKED`"

    Design: Difficulty/cross_entity_state_dependency/pickup_complete_requires_container_active
    """
    _, _, _, visit = _locked_en_route_setup(api)
    resp = api.complete_pickup_visit(
        visit["id"],
        {"pump_gallons": 100.00, "field_moisture_pct": 5.0},
        make_driver_headers("drv-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CONTAINER_LOCKED, expected_status=409)


def test_complete_on_locked_container_leaves_visit_untouched(api):
    """PRD §3.5: "Completion is guarded by four checks: the container must be
    `ACTIVE`, and completing against a `LOCKED` container is rejected with
    `ERR_CONTAINER_LOCKED`; the logical clock date must be on or after the
    visit's `scheduled_date`, otherwise `ERR_PICKUP_WINDOW_FUTURE`; the pump
    reading must be greater than zero, otherwise `ERR_VALIDATION`; and it must
    not exceed the container's `capacity_gallons`, otherwise
    `ERR_CONTAINER_CAPACITY_EXCEEDED`."

    Design: Difficulty/cross_entity_state_dependency/pickup_complete_requires_container_active
    """
    _, _, _, visit = _locked_en_route_setup(api)
    api.complete_pickup_visit(
        visit["id"],
        {"pump_gallons": 100.00, "field_moisture_pct": 5.0},
        make_driver_headers("drv-1"),
    )
    after = get_success_data(api.get_pickup_visit(visit["id"], DISP))
    assert after["status"] == "EN_ROUTE"
    assert after.get("net_gallons_provisional") in (None, 0), (
        "net_gallons_provisional must not be computed on a rejected completion"
    )


# ---------------------------------------------------------------------------
# Difficulty: priority pair — LOCKED beats capacity (both violated)
# ---------------------------------------------------------------------------

def test_locked_container_error_wins_over_capacity_error(api):
    """PRD §2.8: "sixth, domain state guards — container not locked, contract
    engagement, sample re-grade discipline, customer not suspended
    (`ERR_CONTAINER_LOCKED`, `ERR_CONTRACT_NOT_ACTIVE`,
    `ERR_SAMPLE_ALREADY_GRADED`, `ERR_CUSTOMER_SUSPENDED`); seventh, optimistic
    concurrency (`ERR_STALE_VERSION`); eighth, safety gates — truck
    availability and open spill complaints (`ERR_TRUCK_UNAVAILABLE`,
    `ERR_SPILL_COMPLAINT_OPEN`); ninth, business constraints — contract term
    overlap, manifest date uniqueness, tank capacity, container capacity, tank
    balance, and duplicate billing periods (`ERR_CONTRACT_TERM_OVERLAP`,
    `ERR_MANIFEST_DATE_CONFLICT`, `ERR_TANK_CAPACITY_EXCEEDED`,
    `ERR_CONTAINER_CAPACITY_EXCEEDED`, `ERR_TANK_IMBALANCE`,
    `ERR_DUPLICATE_PERIOD`)"
    PRD §2.8: "Every request is validated against a fixed sequence of check
    categories, and a failure in an earlier category surfaces its error without
    evaluating later categories."

    Design: Difficulty/priority_pair_validation_conflict/locked_container_vs_capacity_priority
    """
    _, _, _, visit = _locked_en_route_setup(api)
    resp = api.complete_pickup_visit(
        visit["id"],
        {"pump_gallons": 999, "field_moisture_pct": 5.0},
        make_driver_headers("drv-1"),
    )
    # Container capacity is 300; pump 999 violates capacity too, but the
    # state-guard category precedes business constraints in PRD §2.8's order.
    validate_error(resp, ApiErrorId.ERR_CONTAINER_LOCKED, expected_status=409)


def test_locked_container_priority_leaves_visit_en_route(api):
    """PRD §2.8: "Every request is validated against a fixed sequence of check
    categories, and a failure in an earlier category surfaces its error without
    evaluating later categories."

    Design: Difficulty/priority_pair_validation_conflict/locked_container_vs_capacity_priority
    """
    _, _, _, visit = _locked_en_route_setup(api)
    api.complete_pickup_visit(
        visit["id"],
        {"pump_gallons": 999, "field_moisture_pct": 5.0},
        make_driver_headers("drv-1"),
    )
    after = get_success_data(api.get_pickup_visit(visit["id"], DISP))
    assert after["status"] == "EN_ROUTE", "no partial mutation may occur"


# ---------------------------------------------------------------------------
# Corner: driver identity / ownership on visit start
# ---------------------------------------------------------------------------

def test_driver_mismatch_forbidden(api):
    """PRD §3.5: "The acting `X-User-ID` must equal the manifest's
    `driver_ref` — a driver working another driver's route is rejected with
    `ERR_FORBIDDEN_ROLE`"

    Design: Corner/rbac/c_driver_mismatch_forbidden
    """
    ctx = setup_dispatched_single_stop(name="Route House", truck_plate="T-C19")
    resp = api.start_pickup_visit(ctx["visit"]["id"], make_driver_headers("drv-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    started = get_success_data(
        api.start_pickup_visit(ctx["visit"]["id"], make_driver_headers("drv-1"))
    )
    assert started["status"] == "EN_ROUTE"


# ---------------------------------------------------------------------------
# Corner: OCC on manifest patch
# ---------------------------------------------------------------------------

def _occ_manifest_setup(api):
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Plan House")
    c1 = create_container(customer["id"], capacity=300, fill_rate=100, lock_code="LKM1")
    c2 = create_container(customer["id"], capacity=300, fill_rate=100, lock_code="LKM2")
    truck = create_truck(plate="T-C20", tank_capacity=500)
    manifest = create_manifest(truck["id"], [c1["id"]], service_date="2026-08-05")
    return customer, c1, c2, truck, manifest, manifest["version"]


def test_manifest_patch_with_current_version_succeeds(api):
    """PRD §3.4: "The replacement request must carry
    `expected_manifest_version` matching the manifest's current `version`
    (§2.7); a mismatch is rejected with `ERR_STALE_VERSION`, since a newer stop
    plan legitimately supersedes the one the dispatcher last observed."
    PRD §3.4: "A successful re-plan deletes the existing `SCHEDULED` visits,
    recreates them from the new stop list, recomputes `projected_fill_gallons`,
    and increments the manifest's `version`."

    Design: Corner/cross_cutting_layers/c_occ_stale_manifest_patch_412
    """
    _, c1, c2, _, manifest, man_v = _occ_manifest_setup(api)
    resp = api.patch_manifest(
        manifest["id"],
        {"expected_manifest_version": man_v, "container_ids": [c2["id"]]},
        DISP,
    )
    data = validate_success(resp, expected_status=200)
    assert data["version"] == man_v + 1
    visits = manifest_visits(manifest["id"])
    assert len(visits) == 1
    assert visits[0]["container_id"] == c2["id"]


def test_manifest_patch_with_stale_version_rejected(api):
    """PRD §2.7: "If another dispatcher has advanced the manifest's version
    since the client last read it — the newer stop plan legitimately supersedes
    the prior one — the patch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/c_occ_stale_manifest_patch_412
    """
    _, c1, c2, _, manifest, man_v = _occ_manifest_setup(api)
    get_success_data(
        api.patch_manifest(
            manifest["id"],
            {"expected_manifest_version": man_v, "container_ids": [c2["id"]]},
            DISP,
        )
    )
    resp = api.patch_manifest(
        manifest["id"],
        {"expected_manifest_version": man_v,
         "container_ids": [c1["id"], c2["id"]]},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
