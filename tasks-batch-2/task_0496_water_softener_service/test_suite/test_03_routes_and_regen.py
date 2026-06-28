"""Routes, route stops, meter readings / regeneration boundaries, warranty coverage
boundaries, and temporal-overlap / service-gap conflicts.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_active_system,
    setup_dispatched_route_with_stop,
    setup_planned_route_with_active_system,
    setup_account_with_accepted_test,
    setup_triaged_claim,
    create_system_payload,
    create_route_payload,
    create_route_stop_payload,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Transitive cascade depth-2: route complete force-skips SCHEDULED stops
# ===========================================================================
def test_route_complete_skips_scheduled_stops(api):
    """PRD §3.4: "Completing a route advances it from `DISPATCHED` to `COMPLETED`
    and force-skips any straggler stops: every `RouteStop` still in `SCHEDULED`
    transitions to `SKIPPED` as a cascade, and a skipped stop fires no service side
    effects."

    Design: Difficulty/transitive_cascade/route_complete_skips_scheduled_stops_depth2
    """
    ctx = setup_dispatched_route_with_stop(stop_type="INSPECTION")  # one SCHEDULED stop, never serviced
    completed = validate_success(api.complete_route(ctx["route"]["id"], ctx["tech_headers"]), 200)
    assert completed["status"] == "COMPLETED"
    stop = validate_success(api.get_route_stop(ctx["stop"]["id"], SM), 200)
    assert stop["status"] == "SKIPPED"


# ===========================================================================
# Boundary: regen_health flips to DUE at exactly capacity_gallons
# ===========================================================================
def test_regen_due_at_exactly_capacity_gallons(api):
    """PRD §3.3: "if `gallons_since_regen` is at least the cycle capacity multiplied
    by the grace factor of 1.25, the health becomes `OVERDUE`; otherwise if
    `gallons_since_regen` is at least the cycle capacity, the health becomes `DUE`;
    otherwise it stays `NOMINAL`. Each boundary is inclusive — reaching the
    threshold exactly counts as having crossed it."

    Design: Difficulty/boundary_precision_check/regen_due_exactly_at_capacity_gallons_meter_reading
    """
    ctx = setup_active_system(grain_capacity=32000, hardness_gpg=15)  # floor(32000/15)=2133
    sys_id = ctx["system"]["id"]
    th = ctx["tech_headers"]

    below = validate_success(api.meter_reading(sys_id, {"gallons_since_regen": 2132}, th), 200)
    assert below["regen_health"] == "NOMINAL", "2132 < 2133 stays NOMINAL"

    at = validate_success(api.meter_reading(sys_id, {"gallons_since_regen": 2133}, th), 200)
    assert at["regen_health"] == "DUE", "2133 == capacity_gallons flips DUE"
    assert at["gallons_since_regen"] == 2133


# ===========================================================================
# Boundary: warranty coverage inclusive at exactly the window edge
# ===========================================================================
def test_warranty_coverage_inclusive_at_window_edge(api):
    """PRD §3.9: "the claim's `covered` flag is set true when that age at report is
    at most the window for its defect class, and false otherwise. The boundary is
    inclusive — an age exactly equal to the window is still covered."
    PRD §3.9: "a UV ballast for 365 days."

    Design: Difficulty/boundary_precision_check/warranty_coverage_inclusive_window_boundary_on_triage
    """
    # install 2026-01-01, report exactly 2027-01-01 (365 days), UV_BALLAST window 365.
    ctx = setup_triaged_claim(defect_class="UV_BALLAST", install_at="2026-01-01T00:00:00Z",
                              reported_at="2027-01-01T00:00:00Z", triage_at="2027-01-01T00:00:00Z",
                              acquisition_mode="PURCHASE")
    assert ctx["claim"]["status"] == "TRIAGED"
    assert ctx["claim"]["covered"] is True


# ===========================================================================
# Temporal overlap #1: half-open window overlap on the same route
# ===========================================================================
def test_route_stop_half_open_window_overlap_rejected(api):
    """PRD §3.4: "`window_end` must be strictly after `window_start`, and the new
    window must not overlap any existing `SCHEDULED` stop already on the same route
    (the overlap check is buffer-aware); a window that is inverted or that collides
    with an existing scheduled stop on that route is rejected with
    `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/route_stop_window_half_open_overlap_same_route
    """
    ctx = setup_planned_route_with_active_system(capacity_stops=4)
    route_id = ctx["route"]["id"]
    get_success_data(api.add_route_stop(route_id, create_route_stop_payload(
        ctx["system"]["id"], stop_type="INSPECTION",
        window_start="2026-06-01T09:00:00Z", window_end="2026-06-01T10:00:00Z"), DISPATCHER))

    resp = api.add_route_stop(route_id, create_route_stop_payload(
        ctx["system"]["id"], stop_type="INSPECTION",
        window_start="2026-06-01T09:30:00Z", window_end="2026-06-01T10:30:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)
    route = validate_success(api.get_route(route_id, SM), 200)
    assert route["stop_count"] == 1


# ===========================================================================
# Temporal overlap #2: same-system service gap across different routes
# ===========================================================================
def test_same_system_service_gap_across_routes_rejected(api):
    """PRD §3.4: "The same system may not be serviced twice in close succession: if
    any two stops servicing the same system — across any route, not just this one —
    would fall within 24 hours of each other, the add is rejected with
    `ERR_SERVICE_GAP_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/same_system_min_service_gap_across_routes
    """
    ctx = setup_planned_route_with_active_system(capacity_stops=4)
    sys_id = ctx["system"]["id"]
    tech_id = ctx["tech"]["id"]
    get_success_data(api.add_route_stop(ctx["route"]["id"], create_route_stop_payload(
        sys_id, stop_type="INSPECTION",
        window_start="2026-06-01T09:00:00Z", window_end="2026-06-01T10:00:00Z"), DISPATCHER))

    route2 = get_success_data(api.create_route(
        create_route_payload(tech_id, service_zone="Z-NORTH", capacity_stops=4), DISPATCHER))
    resp = api.add_route_stop(route2["id"], create_route_stop_payload(
        sys_id, stop_type="INSPECTION",
        window_start="2026-06-01T15:00:00Z", window_end="2026-06-01T16:00:00Z"), DISPATCHER)  # 6h later
    validate_error(resp, ApiErrorId.ERR_SERVICE_GAP_VIOLATION.value)
    r2 = validate_success(api.get_route(route2["id"], SM), 200)
    assert r2["stop_count"] == 0


# ===========================================================================
# Priority pair: re-install of ACTIVE system -> state error beats capacity check
# ===========================================================================
def test_reinstall_active_system_returns_invalid_state(api):
    """PRD §2.6: "then — for state-changing operations — whether the target resource
    is in a legal state for the transition (`ERR_INVALID_STATE`), and only then the
    domain-specific business rules described throughout Section 3."
    PRD §3.3: "Installing the system advances `lifecycle_status` from `ORDERED` to
    `INSTALLED`."

    Design: Difficulty/priority_pair_validation_conflict/install_state_beats_capacity_mismatch
    """
    ctx = setup_active_system(grain_capacity=32000)  # already ACTIVE
    resp = api.install_system(ctx["system"]["id"], ctx["tech_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: install with mismatched grain capacity -> ERR_CAPACITY_MISMATCH
# ===========================================================================
def test_install_capacity_mismatch_returns_422(api):
    """PRD §3.3: "the system's `grain_capacity` must exactly equal the source test's
    `recommended_grain_capacity`. A capacity that does not match the source test's
    recommended capacity is rejected with `ERR_CAPACITY_MISMATCH`."

    Design: Corner/validations/install_capacity_mismatch_returns_422
    """
    base = setup_account_with_accepted_test(hardness_gpg=15)  # recommends 32000
    sys = get_success_data(api.create_system(
        create_system_payload(base["account"]["id"], base["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=24000), SM))
    resp = api.install_system(sys["id"], base["tech_headers"])
    validate_error(resp, ApiErrorId.ERR_CAPACITY_MISMATCH.value)


# ===========================================================================
# Corner: zone-mismatched stop -> ERR_ZONE_MISMATCH
# ===========================================================================
def test_route_stop_zone_mismatch_returns_422(api):
    """PRD §3.4: "The serviced system must be eligible for that route: the system
    must be `ACTIVE` and its account's `service_zone` must equal the route's
    `service_zone`, otherwise the add is rejected with `ERR_ZONE_MISMATCH`."

    Design: Corner/validations/route_stop_zone_mismatch_returns_422
    """
    # Active system on a Z-SOUTH account; route is Z-NORTH.
    ctx = setup_active_system(service_zone="Z-SOUTH")
    route = get_success_data(api.create_route(
        create_route_payload(ctx["tech"]["id"], service_zone="Z-NORTH", capacity_stops=4), DISPATCHER))
    resp = api.add_route_stop(route["id"], create_route_stop_payload(
        ctx["system"]["id"], stop_type="INSPECTION"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ZONE_MISMATCH.value)


# ===========================================================================
# Corner: window_end == window_start -> ERR_WINDOW_OVERLAP
# ===========================================================================
def test_window_end_not_after_start_returns_overlap(api):
    """PRD §3.4: "`window_end` must be strictly after `window_start` ... a window
    that is inverted or that collides with an existing scheduled stop on that route
    is rejected with `ERR_WINDOW_OVERLAP`."

    Design: Corner/errors/window_end_before_start_returns_overlap_error
    """
    ctx = setup_planned_route_with_active_system(capacity_stops=4)
    resp = api.add_route_stop(ctx["route"]["id"], create_route_stop_payload(
        ctx["system"]["id"], stop_type="INSPECTION",
        window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T10:00:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)


# ===========================================================================
# Corner (consistency): regenerate cascade visible in same response
# ===========================================================================
def test_regenerate_returns_updated_system_in_same_response(api):
    """PRD §3.3: "On a successful regeneration `regen_health` returns to `NOMINAL`,
    `gallons_since_regen` is reset to 0, the salt level is drawn down (Section 3.7),
    and a regeneration service visit is created automatically with no charge."
    PRD §3.7: "A successful regeneration consumes salt: it decrements
    `salt_level_pct` by 30 percentage points, floored at 0."

    Design: Corner/consistency_model/regenerate_cascade_visible_in_same_response
    """
    ctx = setup_active_system(grain_capacity=32000, hardness_gpg=15)
    sys_id = ctx["system"]["id"]
    th = ctx["tech_headers"]
    get_success_data(api.meter_reading(sys_id, {"gallons_since_regen": 2133}, th))  # -> DUE
    regen = validate_success(api.regenerate_system(sys_id, th), 200)
    assert regen["regen_health"] == "NOMINAL"
    assert regen["gallons_since_regen"] == 0
    assert regen["salt_level_pct"] == 70  # 100 - 30
