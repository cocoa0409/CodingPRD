"""Queue A (depth) — resource temporal overlap: half-open room-adjacency
semantics and per-day floor crew-capacity summation.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    run_pipeline, setup_window_with_tasks, create_procurement_project,
    create_window, create_task, transition_window,
    TEST_USERS,
)

IM = TEST_USERS["installation_manager_headers"]


# ── rule: resource_temporal_overlap (room half-open) ───────

def _released_w1_on_room():
    """Line with 100 good units received; room R-401; W1 [2026-07-10,
    2026-07-15) crew 1 with a task on R-401, RELEASED."""
    scenario = run_pipeline(
        name="P-TO1", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 5, "room_count": 20,
            "unit_budget_cents": 1000, "unit_price_cents": 1000,
            "lead_time_days": 10,
            "quantity_ordered": 100, "declared_cube_m3": 10,
        }],
        receipts=[[(0, 100, 0)]],
    )
    line_id = scenario["lines"][0]["id"]
    wt = setup_window_with_tasks(
        scenario["project"]["id"],
        floor_number=4, room_number="R-401", room_type="GUEST_DOUBLE",
        start_date="2026-07-10", end_date="2026-07-15", crew_count=1,
        tasks=[(line_id, 1)], release=True,
    )
    scenario.update(wt)
    return scenario


def test_room_adjacent_window_releases_under_halfopen_semantics(api):
    """PRD §3.7: "The room-overlap guard: for every task of this window, no other
    window in `RELEASED` or `IN_PROGRESS` may hold a task on the same room over an
    intersecting half-open date range — intersection meaning the other window
    starts before this one ends and this one starts before the other ends — while
    pure adjacency, one window's `end_date` equal to the other's `start_date`, is
    allowed; a violation is `ERR_ROOM_WINDOW_OVERLAP` (409)."
    W2 [2026-07-15, 2026-07-20) starts exactly when W1 ends: adjacency, not
    intersection, so the release succeeds.

    Design: Difficulty/resource_temporal_overlap/room_halfopen_adjacency_allowed_overlap_rejected
    """
    scenario = _released_w1_on_room()
    line_id = scenario["lines"][0]["id"]
    room_id = scenario["room"]["id"]

    w2 = create_window(
        scenario["project"]["id"], floor_number=4,
        start_date="2026-07-15", end_date="2026-07-20", crew_count=1,
    )
    create_task(w2["id"], room_id, line_id, 1)
    released = validate_success(
        api_client.transition_installation_window(
            w2["id"], {"to_status": "RELEASED"}, IM
        ),
        200,
    )
    assert released["status"] == "RELEASED"


def test_room_overlapping_window_release_rejected(api):
    """PRD §3.7: "The room-overlap guard: for every task of this window, no other
    window in `RELEASED` or `IN_PROGRESS` may hold a task on the same room over an
    intersecting half-open date range — intersection meaning the other window
    starts before this one ends and this one starts before the other ends — while
    pure adjacency, one window's `end_date` equal to the other's `start_date`, is
    allowed; a violation is `ERR_ROOM_WINDOW_OVERLAP` (409)."
    W3 [2026-07-14, 2026-07-16) intersects W1 [2026-07-10, 2026-07-15) by one
    day: the release is rejected and W3 stays PLANNED.

    Design: Difficulty/resource_temporal_overlap/room_halfopen_adjacency_allowed_overlap_rejected
    """
    scenario = _released_w1_on_room()
    line_id = scenario["lines"][0]["id"]
    room_id = scenario["room"]["id"]

    w3 = create_window(
        scenario["project"]["id"], floor_number=4,
        start_date="2026-07-14", end_date="2026-07-16", crew_count=1,
    )
    create_task(w3["id"], room_id, line_id, 1)
    res = api_client.transition_installation_window(
        w3["id"], {"to_status": "RELEASED"}, IM
    )
    validate_error(res, ApiErrorId.ERR_ROOM_WINDOW_OVERLAP, expected_status=409)

    w3_after = validate_success(
        api_client.get_installation_window(w3["id"], IM)
    )
    assert w3_after["status"] == "PLANNED"


# ── rule: resource_temporal_overlap (crew capacity) ────────

def _floor_at_seven_of_eight():
    """Project with default_crew_capacity_per_floor_day 8 in PROCUREMENT; W1
    crew 5 and W2 crew 2, both floor 3, both [2026-08-10, 2026-08-15), both
    RELEASED — a running sum of 7."""
    base = create_procurement_project(
        name="P-TO2", total_budget_cents=10_000_000, budgeted_cents=1000,
        default_crew_capacity_per_floor_day=8,
    )
    project = base["project"]
    w1 = create_window(project["id"], floor_number=3,
                       start_date="2026-08-10", end_date="2026-08-15",
                       crew_count=5)
    transition_window(w1["id"], "RELEASED")
    w2 = create_window(project["id"], floor_number=3,
                       start_date="2026-08-10", end_date="2026-08-15",
                       crew_count=2)
    transition_window(w2["id"], "RELEASED")
    return project


def test_crew_sum_landing_exactly_on_capacity_is_allowed(api):
    """PRD §3.7: "The crew-capacity guard: for every calendar day of this window,
    the summed `crew_count` over windows of the same project and floor in
    `RELEASED` or `IN_PROGRESS` covering that day, plus this window's own
    `crew_count`, must be at most the project's
    `default_crew_capacity_per_floor_day`; a strictly greater sum is
    `ERR_FLOOR_CREW_CAPACITY_EXCEEDED` (409), and a sum landing exactly on
    capacity is allowed."
    W3 crew 1 on 2026-08-12 brings the floor-3 sum to 5 + 2 + 1 = 8 == capacity:
    the release succeeds.

    Design: Difficulty/resource_temporal_overlap/floor_crew_capacity_equality_allowed
    """
    project = _floor_at_seven_of_eight()
    w3 = create_window(project["id"], floor_number=3,
                       start_date="2026-08-12", end_date="2026-08-13",
                       crew_count=1)
    released = validate_success(
        api_client.transition_installation_window(
            w3["id"], {"to_status": "RELEASED"}, IM
        ),
        200,
    )
    assert released["status"] == "RELEASED"


def test_crew_sum_above_capacity_is_rejected(api):
    """PRD §3.7: "The crew-capacity guard: for every calendar day of this window,
    the summed `crew_count` over windows of the same project and floor in
    `RELEASED` or `IN_PROGRESS` covering that day, plus this window's own
    `crew_count`, must be at most the project's
    `default_crew_capacity_per_floor_day`; a strictly greater sum is
    `ERR_FLOOR_CREW_CAPACITY_EXCEEDED` (409), and a sum landing exactly on
    capacity is allowed."
    With the floor already at 8 of 8 on 2026-08-12, one more crew pushes the sum
    to 9 > 8 and the release fails, leaving the window PLANNED.

    Design: Difficulty/resource_temporal_overlap/floor_crew_capacity_equality_allowed
    """
    project = _floor_at_seven_of_eight()
    w3 = create_window(project["id"], floor_number=3,
                       start_date="2026-08-12", end_date="2026-08-13",
                       crew_count=1)
    transition_window(w3["id"], "RELEASED")

    w4 = create_window(project["id"], floor_number=3,
                       start_date="2026-08-12", end_date="2026-08-13",
                       crew_count=1)
    res = api_client.transition_installation_window(
        w4["id"], {"to_status": "RELEASED"}, IM
    )
    validate_error(res, ApiErrorId.ERR_FLOOR_CREW_CAPACITY_EXCEEDED,
                   expected_status=409)

    w4_after = validate_success(api_client.get_installation_window(w4["id"], IM))
    assert w4_after["status"] == "PLANNED"
