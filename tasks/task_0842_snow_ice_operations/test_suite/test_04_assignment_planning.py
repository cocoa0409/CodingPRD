"""Assignment-planning guards: window validity, vehicle safety, operator on-call,
vehicle double-booking, operator rest buffer, validation priority conflicts, and
optimistic concurrency on the owning storm.

Corner queue: validations section + cross_cutting_complexity_layers (OCC / replan).
Difficulty queue: resource_temporal_overlap, priority_pair_validation_conflict.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    new_depot, new_vehicle, new_operator, new_route, new_storm, new_callout,
    activate_storm, get_storm_version, new_assignment, start_assignment,
    setup_started_assignment, setup_storm_scene, make_operator_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]


def _assignment_body(route_id, vehicle_id, operator_id, version, **overrides):
    body = {
        "route_id": route_id, "vehicle_id": vehicle_id, "operator_id": operator_id,
        "assignment_type": "PLOWING",
        "window_start_at": "2026-02-10T01:00:00Z", "window_end_at": "2026-02-10T05:00:00Z",
        "planned_material_tons": 2.0, "expected_storm_event_version": version,
    }
    body.update(overrides)
    return body


# --- Corner: validations --------------------------------------------------

def test_callout_zero_length_window_rejected(api):
    """PRD §3.3: "First, the window must be well-formed: `window_end_at` must be strictly
    later than `window_start_at`, or the create is rejected with `ERR_INVALID_WINDOW`
    (HTTP 422)."

    Design: Corner/validations/callout_invalid_window_returns_422
    """
    op = new_operator()
    storm = new_storm(severity="LIGHT")
    resp = api.create_callout(storm["id"], {"operator_id": op["id"],
                              "window_start_at": "2026-02-10T08:00:00Z",
                              "window_end_at": "2026-02-10T08:00:00Z"}, DISPATCH)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value, 422)


def test_plow_only_vehicle_on_plowing_run_rejected(api):
    """PRD §3.4: "when the `assignment_type` is `PLOWING`, the vehicle's `has_spreader`
    must be true, or the create is rejected with `ERR_VEHICLE_MISSING_SPREADER` (HTTP
    422)."

    Design: Corner/validations/assign_plow_vehicle_to_plowing_rejected
    """
    depot = new_depot()
    veh = new_vehicle(depot["id"], vehicle_type="PLOW", unit_number="P1")
    op = new_operator()
    route = new_route()
    storm = new_storm(severity="SEVERE")
    new_callout(storm["id"], op["id"])
    v = get_storm_version(storm["id"])
    resp = api.create_assignment(storm["id"],
                                 _assignment_body(route["id"], veh["id"], op["id"], v), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_MISSING_SPREADER.value, 422)


def test_assign_route_already_in_progress_rejected(api):
    """PRD §3.4: "If, however, an existing assignment for that storm-and-route pairing is
    `IN_PROGRESS` rather than merely `PLANNED`, the route is already being actively
    serviced and the create is rejected with `ERR_ROUTE_ALREADY_ACTIVE` rather than
    superseding live work."

    Design: Corner/validations/assign_route_with_in_progress_rejected
    """
    scene = setup_started_assignment(planned_material_tons=2.0)  # veh1 IN_PROGRESS on route
    veh2 = new_vehicle(scene["depot"]["id"], unit_number="T2")
    v2 = get_storm_version(scene["storm"]["id"])
    resp = api.create_assignment(scene["storm"]["id"],
                                 _assignment_body(scene["route"]["id"], veh2["id"],
                                                  scene["operator"]["id"], v2,
                                                  window_start_at="2026-02-10T06:00:00Z",
                                                  window_end_at="2026-02-10T09:00:00Z"), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_ROUTE_ALREADY_ACTIVE.value, 409)


def test_adjacent_vehicle_windows_allowed(api):
    """PRD §3.4: "no other assignment for the same vehicle in `PLANNED` or `IN_PROGRESS`
    status may have a half-open occupation window `[window_start_at, window_end_at)` that
    overlaps this one — abutting windows where one ends exactly as the other starts are
    allowed".

    Design: Corner/validations/adjacent_vehicle_windows_allowed
    """
    depot = new_depot()
    veh = new_vehicle(depot["id"])
    op = new_operator()
    route1 = new_route(name="Main St")
    route2 = new_route(name="Second St")
    storm = new_storm(severity="SEVERE")
    new_callout(storm["id"], op["id"])
    activate_storm(storm["id"])
    v1 = get_storm_version(storm["id"])
    new_assignment(storm["id"], route1["id"], veh["id"], op["id"], v1)  # 01:00-05:00
    v2 = get_storm_version(storm["id"])
    resp = api.create_assignment(storm["id"],
                                 _assignment_body(route2["id"], veh["id"], op["id"], v2,
                                                  window_start_at="2026-02-10T05:00:00Z",
                                                  window_end_at="2026-02-10T09:00:00Z"), DISPATCH)
    data = validate_success(resp, 201)
    assert data["status"] == "PLANNED", data


# --- Difficulty: resource_temporal_overlap / vehicle_window_overlap -------

def _double_book_scene():
    depot = new_depot()
    veh = new_vehicle(depot["id"])
    op = new_operator()
    route1 = new_route(name="Main St")
    route2 = new_route(name="Second St")
    storm = new_storm(severity="SEVERE")
    new_callout(storm["id"], op["id"])
    v1 = get_storm_version(storm["id"])
    new_assignment(storm["id"], route1["id"], veh["id"], op["id"], v1)  # 01:00-05:00 PLANNED
    v2 = get_storm_version(storm["id"])
    return {"storm": storm, "veh": veh, "op": op, "route2": route2, "v2": v2}


def test_vehicle_partial_window_overlap_rejected(api):
    """PRD §3.4: "The vehicle must not be double-booked: no other assignment for the same
    vehicle in `PLANNED` or `IN_PROGRESS` status may have a half-open occupation window
    `[window_start_at, window_end_at)` that overlaps this one — abutting windows where one
    ends exactly as the other starts are allowed — otherwise the create is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/vehicle_window_overlap
    """
    s = _double_book_scene()
    resp = api.create_assignment(s["storm"]["id"],
                                 _assignment_body(s["route2"]["id"], s["veh"]["id"], s["op"]["id"],
                                                  s["v2"], window_start_at="2026-02-10T03:00:00Z",
                                                  window_end_at="2026-02-10T07:00:00Z"), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value, 409)


def test_vehicle_contained_window_overlap_rejected(api):
    """PRD §3.4: "The vehicle must not be double-booked: no other assignment for the same
    vehicle in `PLANNED` or `IN_PROGRESS` status may have a half-open occupation window
    `[window_start_at, window_end_at)` that overlaps this one — abutting windows where one
    ends exactly as the other starts are allowed — otherwise the create is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/vehicle_window_overlap
    """
    s = _double_book_scene()
    # 02:00-04:00 sits fully inside the existing 01:00-05:00 window.
    resp = api.create_assignment(s["storm"]["id"],
                                 _assignment_body(s["route2"]["id"], s["veh"]["id"], s["op"]["id"],
                                                  s["v2"], window_start_at="2026-02-10T02:00:00Z",
                                                  window_end_at="2026-02-10T04:00:00Z"), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value, 409)


# --- Difficulty: resource_temporal_overlap / operator_rest_buffer ---------

def test_operator_rest_buffer_violation_rejected(api):
    """PRD §3.3: "No other callout for the same operator that is in `ISSUED` or
    `COMPLETED` status may fall within eight hours of this window; concretely, this
    window's `window_start_at` must be at least eight hours after the other callout's
    `window_end_at`, or the other callout's `window_start_at` must be at least eight hours
    after this window's `window_end_at`. If neither holds, the create is rejected with
    `ERR_OPERATOR_REST_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/operator_rest_buffer
    """
    op = new_operator()
    storm = new_storm(severity="SEVERE")
    new_callout(storm["id"], op["id"],
                window_start_at="2026-02-10T00:00:00Z", window_end_at="2026-02-10T08:00:00Z")
    resp = api.create_callout(storm["id"], {"operator_id": op["id"],
                              "window_start_at": "2026-02-10T10:00:00Z",  # 2h gap < 8h
                              "window_end_at": "2026-02-10T18:00:00Z"}, DISPATCH)
    validate_error(resp, ApiErrorId.ERR_OPERATOR_REST_VIOLATION.value, 409)


def test_operator_rest_buffer_exactly_eight_hours_allowed(api):
    """PRD §3.3: "this window's `window_start_at` must be at least eight hours after the
    other callout's `window_end_at`, or the other callout's `window_start_at` must be at
    least eight hours after this window's `window_end_at`. If neither holds, the create is
    rejected with `ERR_OPERATOR_REST_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/operator_rest_buffer
    """
    op = new_operator()
    storm = new_storm(severity="SEVERE")
    new_callout(storm["id"], op["id"],
                window_start_at="2026-02-10T00:00:00Z", window_end_at="2026-02-10T08:00:00Z")
    # start 16:00 == 08:00 + 8h -> "at least eight hours after" is satisfied.
    resp = api.create_callout(storm["id"], {"operator_id": op["id"],
                              "window_start_at": "2026-02-10T16:00:00Z",
                              "window_end_at": "2026-02-10T20:00:00Z"}, DISPATCH)
    data = validate_success(resp, 201)
    assert data["status"] == "ISSUED", data


# --- Difficulty: priority_pair_validation_conflict / state_over_fiscal ----

def test_state_check_precedes_material_check_salt(api):
    """PRD §2.10: "Sixth, the target must be in the state the requested transition
    requires, yielding the state error described with each workflow below. The remaining
    domain checks — vehicle safety, operator on-call status, vehicle double-booking, the
    optimistic-concurrency version match, window validity, and depot material sufficiency
    — follow". PRD §3.6: "The assignment must be `IN_PROGRESS`, or the request is rejected
    with `ERR_ASSIGNMENT_NOT_IN_PROGRESS`."

    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_application
    """
    # PLANNED (never started) assignment; depot holds only 1.0 salt ton; request 999.
    scene = setup_storm_scene(activate=True, salt_tons_on_hand=1.0)
    v = get_storm_version(scene["storm"]["id"])
    asg = new_assignment(scene["storm"]["id"], scene["route"]["id"], scene["vehicle"]["id"],
                         scene["operator"]["id"], v)
    resp = api.create_application(asg["id"],
                                  {"depot_id": scene["depot"]["id"], "material_type": "SALT",
                                   "salt_tons": 999, "lane_miles_treated": 2.0, "pavement_temp_f": 15},
                                  make_operator_headers(scene["operator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_IN_PROGRESS.value, 409)
    depot = validate_success(api.get_depot(scene["depot"]["id"], TEST_USERS["yard_headers"]), 200)
    assert depot["salt_tons_on_hand"] == 1.00, depot


def test_state_check_precedes_material_check_brine(api):
    """PRD §2.10: "Sixth, the target must be in the state the requested transition
    requires, yielding the state error described with each workflow below. The remaining
    domain checks — vehicle safety, operator on-call status, vehicle double-booking, the
    optimistic-concurrency version match, window validity, and depot material sufficiency
    — follow". PRD §3.6: "The assignment must be `IN_PROGRESS`, or the request is rejected
    with `ERR_ASSIGNMENT_NOT_IN_PROGRESS`."

    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_application
    """
    scene = setup_storm_scene(activate=True, brine_gallons_on_hand=1.0)
    v = get_storm_version(scene["storm"]["id"])
    asg = new_assignment(scene["storm"]["id"], scene["route"]["id"], scene["vehicle"]["id"],
                         scene["operator"]["id"], v)
    resp = api.create_application(asg["id"],
                                  {"depot_id": scene["depot"]["id"], "material_type": "BRINE",
                                   "brine_gallons": 999, "lane_miles_treated": 2.0, "pavement_temp_f": 15},
                                  make_operator_headers(scene["operator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_IN_PROGRESS.value, 409)


# --- Difficulty: priority_pair_validation_conflict / safety_over_referential

def _safety_scene(vehicle_type="COMBO", vehicle_status=None):
    depot = new_depot()
    kwargs = {"vehicle_type": vehicle_type}
    if vehicle_status:
        kwargs["status"] = vehicle_status
    veh = new_vehicle(depot["id"], **kwargs)
    op = new_operator()  # NO callout for the storm -> not on call
    route = new_route()
    storm = new_storm(severity="SEVERE")
    v = get_storm_version(storm["id"])
    return {"storm": storm, "veh": veh, "op": op, "route": route, "v": v}


def test_vehicle_safety_precedes_operator_on_call_out_of_service(api):
    """PRD §2.10: "The remaining domain checks — vehicle safety, operator on-call status,
    vehicle double-booking, the optimistic-concurrency version match, window validity, and
    depot material sufficiency — follow, each described in its workflow section." PRD §3.4:
    "The chosen vehicle must not be `OUT_OF_SERVICE`, or the create is rejected with
    `ERR_VEHICLE_OUT_OF_SERVICE` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_assignment
    """
    s = _safety_scene(vehicle_status="OUT_OF_SERVICE")
    resp = api.create_assignment(s["storm"]["id"],
                                 _assignment_body(s["route"]["id"], s["veh"]["id"], s["op"]["id"],
                                                  s["v"]), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_OUT_OF_SERVICE.value, 422)


def test_vehicle_safety_precedes_operator_on_call_missing_spreader(api):
    """PRD §2.10: "The remaining domain checks — vehicle safety, operator on-call status,
    vehicle double-booking, the optimistic-concurrency version match, window validity, and
    depot material sufficiency — follow, each described in its workflow section." PRD §3.4:
    "when the `assignment_type` is `PLOWING`, the vehicle's `has_spreader` must be true, or
    the create is rejected with `ERR_VEHICLE_MISSING_SPREADER` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_assignment
    """
    s = _safety_scene(vehicle_type="PLOW")  # has_spreader false; operator still not on-call
    resp = api.create_assignment(s["storm"]["id"],
                                 _assignment_body(s["route"]["id"], s["veh"]["id"], s["op"]["id"],
                                                  s["v"]), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_MISSING_SPREADER.value, 422)


# --- Corner: cross_cutting_complexity_layers (OCC / replan) ---------------

def test_assignment_create_correct_version_succeeds_and_bumps(api):
    """PRD §2.6: "A request to create an assignment under a storm must carry
    `expected_storm_event_version`, and this field is mandatory on that request. Its value
    must equal the target storm event's current `version`." PRD §3.4: "The successful
    create also increments the storm's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    scene = setup_storm_scene(activate=True)
    v = get_storm_version(scene["storm"]["id"])
    resp = api.create_assignment(scene["storm"]["id"],
                                 _assignment_body(scene["route"]["id"], scene["vehicle"]["id"],
                                                  scene["operator"]["id"], v), DISPATCH)
    validate_success(resp, 201)
    after = validate_success(api.get_storm_event(scene["storm"]["id"], DISPATCH), 200)
    assert after["version"] == v + 1, f"expected version {v + 1}, got {after['version']}"


def test_assignment_create_stale_version_rejected(api):
    """PRD §2.6: "If another writer has advanced the storm's `version` since the client
    last read it — for instance, by creating an assignment that bumped the storm and
    possibly superseded the route's prior plan — the create is rejected with
    `ERR_STALE_STORM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_storm_version_conflict
    """
    depot = new_depot()
    veh1 = new_vehicle(depot["id"], unit_number="T1")
    veh2 = new_vehicle(depot["id"], unit_number="T2")
    op = new_operator()
    route1 = new_route(name="Main St")
    route2 = new_route(name="Second St")
    storm = new_storm(severity="SEVERE")
    new_callout(storm["id"], op["id"])
    activate_storm(storm["id"])
    v0 = get_storm_version(storm["id"])
    new_assignment(storm["id"], route1["id"], veh1["id"], op["id"], v0)  # bumps to v0+1
    resp = api.create_assignment(storm["id"],
                                 _assignment_body(route2["id"], veh2["id"], op["id"], v0,
                                                  window_start_at="2026-02-10T05:00:00Z",
                                                  window_end_at="2026-02-10T09:00:00Z"), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_STALE_STORM_VERSION.value, 412)


def test_replan_supersedes_prior_planned_assignment(api):
    """PRD §3.4: "When the create succeeds, any existing assignment for the very same
    storm-and-route pairing that is currently in `PLANNED` status is superseded — it
    transitions `PLANNED → SUPERSEDED` — so that the newest plan for a street wins."

    Design: Corner/cross_cutting_complexity_layers/replan_supersedes_prior_planned_assignment
    """
    depot = new_depot()
    veh1 = new_vehicle(depot["id"], unit_number="T1")
    veh2 = new_vehicle(depot["id"], unit_number="T2")
    op = new_operator()
    route = new_route(name="Main St")
    storm = new_storm(severity="SEVERE")
    new_callout(storm["id"], op["id"])
    activate_storm(storm["id"])
    v1 = get_storm_version(storm["id"])
    asg_a = new_assignment(storm["id"], route["id"], veh1["id"], op["id"], v1)  # PLANNED
    v2 = get_storm_version(storm["id"])
    resp = api.create_assignment(storm["id"],
                                 _assignment_body(route["id"], veh2["id"], op["id"], v2), DISPATCH)
    asg_b = validate_success(resp, 201)
    after_a = validate_success(api.get_assignment(asg_a["id"], DISPATCH), 200)
    assert after_a["status"] == "SUPERSEDED", after_a
    assert asg_b["status"] == "PLANNED", asg_b
