"""Queue B (breadth) — installation window and room-turn task lifecycle:
completion guards, pool effects, and the conditional cancellation cascade.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    create_project, create_window, transition_window,
    setup_received_pipeline_with_window, complete_task, get_po_line,
    get_project,
    TEST_USERS,
)

IM = TEST_USERS["installation_manager_headers"]


def test_task_lifecycle_guards_and_pool_effects(api):
    """PRD §3.7: "Completing a task requires the task to be `SCHEDULED` (else
    `ERR_INVALID_TASK_TRANSITION`), its owning window to be `IN_PROGRESS` (else
    `ERR_WINDOW_NOT_IN_PROGRESS`), and the line's `qty_installable` to be at least
    the task `quantity` (else `ERR_INSUFFICIENT_INSTALLABLE_STOCK`)."
    PRD §3.7: "Completing a window — `IN_PROGRESS` to `COMPLETE` — requires every
    task of the window to be `COMPLETE` or `CANCELLED` (else
    `ERR_TASKS_OUTSTANDING`)"
    PRD §3.7: "Completion debits the line: `qty_installable` falls by the task
    quantity and `qty_installed` rises by it, the line's `version` bumps, and the
    spec's `attic_target_qty` is recomputed from the new installed count."
    Completion while RELEASED is rejected; each task debits the pool exactly
    once; the window completes only when both tasks are terminal.

    Design: Corner/endpoints/task_lifecycle_guards_and_pool_effects
    """
    scenario = setup_received_pipeline_with_window(
        line_qty=10, line_unit_price=10000, cube=5, received=10,
        floor_number=7, room_number="R-701", room_type="GUEST_DOUBLE",
        start_date="2026-08-01", end_date="2026-08-04", crew_count=1,
        task_quantities=(4, 2), start_window=False,
    )
    line_id = scenario["lines"][0]["id"]
    window_id = scenario["window"]["id"]
    t1, t2 = scenario["tasks"]

    res = api_client.complete_installation_task(t1["id"], IM)
    validate_error(res, ApiErrorId.ERR_WINDOW_NOT_IN_PROGRESS,
                   expected_status=409)

    transition_window(window_id, "IN_PROGRESS")

    completed = validate_success(
        api_client.complete_installation_task(t1["id"], IM), 200
    )
    assert completed["status"] == "COMPLETE"

    res = api_client.complete_installation_task(t1["id"], IM)
    validate_error(res, ApiErrorId.ERR_INVALID_TASK_TRANSITION,
                   expected_status=409)

    res = api_client.transition_installation_window(
        window_id, {"to_status": "COMPLETE"}, IM
    )
    validate_error(res, ApiErrorId.ERR_TASKS_OUTSTANDING, expected_status=409)

    complete_task(t2["id"])
    window = transition_window(window_id, "COMPLETE")
    assert window["status"] == "COMPLETE"

    line = get_po_line(line_id)
    assert line["qty_installed"] == 6
    assert line["qty_installable"] == 4, (
        "10 received minus 6 installed; each task debited the pool exactly once"
    )


def test_window_start_without_tasks_rejected(api):
    """PRD §3.7: "Starting work — `RELEASED` to `IN_PROGRESS` — requires at least
    one `SCHEDULED` task on the window (else `ERR_WINDOW_NO_TASKS`)"
    PRD §2.9: "Otherwise, when any installation window of the project is
    `IN_PROGRESS`, the posture is `SEALED`."
    A RELEASED window with zero tasks cannot start, and the failed start never
    seals the project.

    Design: Corner/state_machines/window_start_without_tasks_rejected
    """
    project = create_project(name="P-S7", hotel_name="H",
                             brand_program="MARQUEE_SELECT",
                             total_budget_cents=5_000_000)
    window = create_window(project["id"], floor_number=2,
                           start_date="2026-07-01", end_date="2026-07-05",
                           crew_count=1)
    transition_window(window["id"], "RELEASED")

    res = api_client.transition_installation_window(
        window["id"], {"to_status": "IN_PROGRESS"}, IM
    )
    validate_error(res, ApiErrorId.ERR_WINDOW_NO_TASKS, expected_status=409)

    after = validate_success(api_client.get_installation_window(window["id"], IM))
    assert after["status"] == "RELEASED"
    assert get_project(project["id"])["procurement_posture"] == "OPEN"


def test_window_release_repeat_invalid(api):
    """PRD §3.7: "Moves that are not legal from the current state — starting from
    `PLANNED`, completing from `RELEASED`, cancelling from `IN_PROGRESS` — are
    rejected with `ERR_INVALID_WINDOW_TRANSITION`."
    Releasing an already-RELEASED window is rejected, not silently idempotent.

    Design: Corner/state_machines/window_release_repeat_invalid
    """
    project = create_project(name="P-S14", hotel_name="H",
                             brand_program="MARQUEE_SELECT",
                             total_budget_cents=5_000_000)
    window = create_window(project["id"], floor_number=2,
                           start_date="2026-07-01", end_date="2026-07-05",
                           crew_count=1)
    transition_window(window["id"], "RELEASED")

    res = api_client.transition_installation_window(
        window["id"], {"to_status": "RELEASED"}, IM
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW_TRANSITION,
                   expected_status=409)

    after = validate_success(api_client.get_installation_window(window["id"], IM))
    assert after["status"] == "RELEASED"


def test_window_cancel_cascades_scheduled_tasks(api):
    """PRD §3.7: "Cancelling a window is legal from `PLANNED` or `RELEASED` and
    cascades conditionally: every task still `SCHEDULED` moves to `CANCELLED`,
    while tasks already terminal are untouched; the window's `version` bumps."
    Cancelling the RELEASED window cancels its SCHEDULED task but consumes no
    stock: the line's pools are untouched.

    Design: Corner/state_machines/window_cancel_cascades_scheduled_tasks
    """
    scenario = setup_received_pipeline_with_window(
        line_qty=10, line_unit_price=10000, cube=5, received=10,
        floor_number=8, room_number="R-802", room_type="GUEST_KING",
        start_date="2026-08-10", end_date="2026-08-12", crew_count=1,
        task_quantities=(3,), start_window=False,
    )
    window_id = scenario["window"]["id"]
    task_id = scenario["tasks"][0]["id"]
    line_id = scenario["lines"][0]["id"]

    cancelled = transition_window(window_id, "CANCELLED")
    assert cancelled["status"] == "CANCELLED"

    task = validate_success(api_client.get_installation_task(task_id, IM))
    assert task["status"] == "CANCELLED", (
        "the SCHEDULED task must cascade to CANCELLED with its window"
    )

    line = get_po_line(line_id)
    assert line["qty_installable"] == 10
    assert line["qty_installed"] == 0
