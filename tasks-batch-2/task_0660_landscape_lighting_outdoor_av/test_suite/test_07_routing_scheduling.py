"""Crew routing and smart-control scheduling: the route-complete cascade, the
half-open visit-overlap rule, the closed-with-buffer scene rule, route-date
matching, lazy MISSED transition, and window validity.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_installed_project,
    setup_active_service_plan,
    request_service_visit,
    create_schedule_program,
    activate_schedule_program,
    create_customer,
    create_project,
    set_clock,
    api_client,
    TEST_USERS,
)
import test_helpers.factories as F

DESIGNER = TEST_USERS["lighting_designer_headers"]
TECH = TEST_USERS["install_tech_headers"]
PROGRAMMER = TEST_USERS["control_programmer_headers"]


# ---------------------------------------------------------------------------
# Route-complete depth-2 cascade (difficulty: transitive_cascade)
# ---------------------------------------------------------------------------
def _dispatched_route_with_two_routed_visits():
    """Active plan, two adjacent ROUTED visits on 2026-05-01, route DISPATCHED.
    Returns (ctx, route_id, [visit_ids])."""
    ctx = setup_active_service_plan(plan_overrides={"tier": "BASIC", "annual_fee_cents": 12000})
    v1 = request_service_visit(ctx, visit_date="2026-05-01", window_start_min=540, window_end_min=600)
    v2 = request_service_visit(ctx, visit_date="2026-05-01", window_start_min=600, window_end_min=660)
    route = validate_success(api_client.create_crew_route(
        F.create_crew_route_payload(technician_id="tech-7", route_date="2026-05-01"), TECH),
        expected_status=201)
    validate_success(api_client.add_visit_to_route(route["id"], F.add_visit_payload(v1["id"]), TECH))
    validate_success(api_client.add_visit_to_route(route["id"], F.add_visit_payload(v2["id"]), TECH))
    validate_success(api_client.dispatch_route(route["id"], TECH))
    return ctx, route["id"], [v1["id"], v2["id"]]


def test_route_complete_marks_route_completed(api):
    """PRD §3.10: "Completing a dispatched route moves it from `DISPATCHED` to
    `COMPLETED` (terminal)".

    Link 1 of the cascade: the route reaches COMPLETED.

    Design: Difficulty/transitive_cascade/route_complete_depth2_cascade
    """
    ctx, route_id, visit_ids = _dispatched_route_with_two_routed_visits()
    route = validate_success(api.complete_route(route_id, TECH))
    assert route["status"] == "COMPLETED", route["status"]
    assert route["visit_count"] == 2, route["visit_count"]


def test_route_complete_bubbles_visits_to_completed(api):
    """PRD §3.10: "Completing a dispatched route moves it from `DISPATCHED` to
    `COMPLETED` (terminal) and, as a cascade, transitions every visit on the route
    that is still `ROUTED` to `COMPLETED`."

    Link 2 of the cascade: both ROUTED visits bubble to COMPLETED.

    Design: Difficulty/transitive_cascade/route_complete_depth2_cascade
    """
    ctx, route_id, visit_ids = _dispatched_route_with_two_routed_visits()
    validate_success(api.complete_route(route_id, TECH))
    for vid in visit_ids:
        visit = validate_success(api.get_service_visit(vid, TECH))
        assert visit["status"] == "COMPLETED", visit["status"]


# ---------------------------------------------------------------------------
# Half-open visit overlap (difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------
def _active_plan_route_with_first_visit():
    """Active plan; visits A[540,600), B[600,660) adjacent, C[580,640) overlapping
    A; an OPEN route dated 2026-05-01 with A already ROUTED.
    Returns (ctx, route_id, vb_id, vc_id)."""
    ctx = setup_active_service_plan(plan_overrides={"tier": "BASIC", "annual_fee_cents": 12000})
    va = request_service_visit(ctx, visit_date="2026-05-01", window_start_min=540, window_end_min=600)
    vb = request_service_visit(ctx, visit_date="2026-05-01", window_start_min=600, window_end_min=660)
    vc = request_service_visit(ctx, visit_date="2026-05-01", window_start_min=580, window_end_min=640)
    route = validate_success(api_client.create_crew_route(
        F.create_crew_route_payload(technician_id="tech-1", route_date="2026-05-01"), TECH),
        expected_status=201)
    validate_success(api_client.add_visit_to_route(route["id"], F.add_visit_payload(va["id"]), TECH))
    return ctx, route["id"], vb["id"], vc["id"]


def test_adjacent_visit_window_routes_successfully(api):
    """PRD §3.10: "the visit's window must not overlap any already-`ROUTED`
    visit's window on the same route, applying the half-open overlap rule of §2.8:
    windows that merely touch at a boundary are fine, but any genuine overlap is
    rejected with `ERR_VISIT_WINDOW_OVERLAP`."

    A second visit [600,660) merely touching the routed [540,600) at the boundary
    routes successfully.

    Design: Difficulty/resource_temporal_overlap/crew_route_half_open_visit_overlap
    """
    ctx, route_id, vb_id, vc_id = _active_plan_route_with_first_visit()
    routed = validate_success(api.add_visit_to_route(route_id, F.add_visit_payload(vb_id), TECH))
    assert routed["status"] == "ROUTED", routed["status"]


def test_overlapping_visit_window_rejected(api):
    """PRD §3.10: "the visit's window must not overlap any already-`ROUTED`
    visit's window on the same route, applying the half-open overlap rule of §2.8:
    windows that merely touch at a boundary are fine, but any genuine overlap is
    rejected with `ERR_VISIT_WINDOW_OVERLAP`."

    A visit [580,640) genuinely overlapping the routed [540,600) is rejected and
    stays REQUESTED.

    Design: Difficulty/resource_temporal_overlap/crew_route_half_open_visit_overlap
    """
    ctx, route_id, vb_id, vc_id = _active_plan_route_with_first_visit()
    # Route the adjacent visit first (it is compatible), then attempt the overlapping one.
    validate_success(api.add_visit_to_route(route_id, F.add_visit_payload(vb_id), TECH))
    validate_error(
        api.add_visit_to_route(route_id, F.add_visit_payload(vc_id), TECH),
        ApiErrorId.ERR_VISIT_WINDOW_OVERLAP.value,
    )
    visit = validate_success(api.get_service_visit(vc_id, TECH))
    assert visit["status"] == "REQUESTED", visit["status"]


# ---------------------------------------------------------------------------
# Scene window buffer (difficulty: boundary_precision_check + resource_temporal_overlap)
# ---------------------------------------------------------------------------
def _installed_project_with_active_program(first=(540, 600)):
    """Installed project with one ACTIVE program over the given window."""
    ctx = setup_installed_project()
    p1 = create_schedule_program(ctx, scene_label="Evening",
                                 window_start_min=first[0], window_end_min=first[1])
    activate_schedule_program(p1["id"])
    return ctx


def test_scene_window_gap_exactly_buffer_allowed(api):
    """PRD §3.7: "the new program's window must be separated by at least five
    minutes on both sides from the window of any other program on the same project
    that is already `ACTIVE`."

    A second program [605,660) starts exactly 5 minutes after the first window's
    end of 600 (gap == buffer), which satisfies the >= 5 rule and activates.

    Design: Difficulty/boundary_precision_check/schedule_program_buffer_gap_exactly_five_minutes
    """
    ctx = _installed_project_with_active_program(first=(540, 600))
    p2 = create_schedule_program(ctx, scene_label="Late", window_start_min=605, window_end_min=660)
    activated = validate_success(api.activate_schedule_program(p2["id"], PROGRAMMER))
    assert activated["status"] == "ACTIVE", activated["status"]


def test_scene_window_gap_below_buffer_rejected(api):
    """PRD §3.7: "If any active program's window sits within five minutes of this
    one — including the case where the windows merely touch — activation is
    rejected with `ERR_SCENE_WINDOW_TOO_CLOSE`."

    A second program [602,660) leaves only a 2-minute gap after the active [540,600),
    below the 5-minute buffer; activation is rejected and the program stays DRAFT.

    Design: Difficulty/boundary_precision_check/schedule_program_buffer_gap_exactly_five_minutes
    """
    ctx = _installed_project_with_active_program(first=(540, 600))
    p2 = create_schedule_program(ctx, scene_label="Late", window_start_min=602, window_end_min=660)
    validate_error(api.activate_schedule_program(p2["id"], PROGRAMMER),
                   ApiErrorId.ERR_SCENE_WINDOW_TOO_CLOSE.value)
    prog = validate_success(api.get_schedule_program(p2["id"], PROGRAMMER))
    assert prog["status"] == "DRAFT", prog["status"]


def test_scene_window_two_minute_gap_rejected_distinct_from_visit_rule(api):
    """PRD §3.7: "If any active program's window sits within five minutes of this
    one — including the case where the windows merely touch — activation is
    rejected with `ERR_SCENE_WINDOW_TOO_CLOSE`."

    The closed-with-buffer scene rule rejects a 2-minute gap [602,660) against an
    active [540,600) — a separation the half-open visit rule would have allowed.

    Design: Difficulty/resource_temporal_overlap/schedule_program_buffered_window_overlap
    """
    ctx = _installed_project_with_active_program(first=(540, 600))
    p2 = create_schedule_program(ctx, scene_label="Late", window_start_min=602, window_end_min=660)
    validate_error(api.activate_schedule_program(p2["id"], PROGRAMMER),
                   ApiErrorId.ERR_SCENE_WINDOW_TOO_CLOSE.value)


def test_scene_window_touching_active_rejected(api):
    """PRD §3.7: "If any active program's window sits within five minutes of this
    one — including the case where the windows merely touch — activation is
    rejected with `ERR_SCENE_WINDOW_TOO_CLOSE`."

    A program [600,660) touching the active [540,600) at the boundary (gap 0 < 5)
    is rejected — touching is not enough for scene windows, unlike visit windows.

    Design: Difficulty/resource_temporal_overlap/schedule_program_buffered_window_overlap
    """
    ctx = _installed_project_with_active_program(first=(540, 600))
    p2 = create_schedule_program(ctx, scene_label="Touch", window_start_min=600, window_end_min=660)
    validate_error(api.activate_schedule_program(p2["id"], PROGRAMMER),
                   ApiErrorId.ERR_SCENE_WINDOW_TOO_CLOSE.value)
    prog = validate_success(api.get_schedule_program(p2["id"], PROGRAMMER))
    assert prog["status"] == "DRAFT", prog["status"]


# ---------------------------------------------------------------------------
# Route date mismatch (corner: validations)
# ---------------------------------------------------------------------------
def test_add_visit_with_date_mismatch_rejected(api):
    """PRD §3.10: "the visit's `visit_date` must equal the route's `route_date` —
    a mismatch is rejected with `ERR_ROUTE_DATE_MISMATCH`."

    A visit dated 2026-05-02 cannot be added to a route dated 2026-05-01.

    Design: Corner/validations/route_date_mismatch_on_add_visit
    """
    ctx = setup_active_service_plan(plan_overrides={"tier": "BASIC", "annual_fee_cents": 12000})
    visit = request_service_visit(ctx, visit_date="2026-05-02", window_start_min=540, window_end_min=600)
    route = validate_success(api.create_crew_route(
        F.create_crew_route_payload(technician_id="t-9", route_date="2026-05-01"), TECH),
        expected_status=201)
    validate_error(
        api.add_visit_to_route(route["id"], F.add_visit_payload(visit["id"]), TECH),
        ApiErrorId.ERR_ROUTE_DATE_MISMATCH.value,
    )
    visit_now = validate_success(api.get_service_visit(visit["id"], TECH))
    assert visit_now["status"] == "REQUESTED", visit_now["status"]


# ---------------------------------------------------------------------------
# Lazy MISSED (corner: state_machines)
# ---------------------------------------------------------------------------
def test_unrouted_visit_lazily_missed_when_date_passes(api):
    """PRD §3.10: "If the logical clock's date moves past a visit's `visit_date`
    while the visit is still `REQUESTED` and unrouted, the visit lazily transitions
    to `MISSED` (terminal); this is evaluated when the visit is read."

    Design: Corner/state_machines/service_visit_lazy_missed_when_date_passed
    """
    ctx = setup_active_service_plan(plan_overrides={"tier": "BASIC", "annual_fee_cents": 12000})
    visit = request_service_visit(ctx, visit_date="2026-05-01", window_start_min=540, window_end_min=600)
    set_clock("2026-05-02T00:00:00Z")
    visit_now = validate_success(api.get_service_visit(visit["id"], TECH))
    assert visit_now["status"] == "MISSED", visit_now["status"]


# ---------------------------------------------------------------------------
# Invalid window (corner: validations)
# ---------------------------------------------------------------------------
def test_schedule_program_window_end_not_after_start_rejected(api):
    """PRD §2.8: "in both cases `window_end_min` must be strictly greater than
    `window_start_min`, and a window failing that condition (or falling outside the
    valid minute range) is rejected with `ERR_INVALID_WINDOW`."

    A schedule program with window_end_min == window_start_min (600 == 600) is
    rejected.

    Design: Corner/validations/invalid_window_end_not_after_start
    """
    cust = create_customer()
    project = create_project(cust["id"])
    resp = api.create_schedule_program(
        F.create_schedule_program_payload(project["id"], scene_label="Bad",
                                          window_start_min=600, window_end_min=600), PROGRAMMER)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)
