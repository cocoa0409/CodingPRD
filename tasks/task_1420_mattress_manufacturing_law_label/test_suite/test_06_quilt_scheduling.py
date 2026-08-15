"""Quilt panel scheduling: half-open machine windows and the run lifecycle (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_quilt_run,
    create_quilt_run_payload,
    setup_planned_order,
)

PM = TEST_USERS["plant_manager_headers"]
LS1 = TEST_USERS["line_supervisor_headers"]


def test_quilt_runs_allow_zero_gap_adjacency(api):
    """PRD §3.6: "Adjacency is explicitly allowed: a new run whose `start_at`
    equals an existing run's `end_at` may be booked back-to-back with zero
    gap."

    Design: Difficulty/resource_temporal_overlap/quilt_machine_half_open_overlap
    """
    ctx = setup_planned_order(quantity=4)
    order_id = ctx["order"]["id"]

    run_a = validate_success(api.create_quilt_run(
        create_quilt_run_payload(
            order_id=order_id, machine_id="M1", size="QUEEN",
            start_at="2026-08-03T08:00:00Z", end_at="2026-08-03T10:00:00Z",
        ),
        LS1,
    ), expected_status=201)
    assert_quilt_run(run_a)

    # start_at exactly equals the existing run's end_at: half-open adjacency.
    run_b = validate_success(api.create_quilt_run(
        create_quilt_run_payload(
            order_id=order_id, machine_id="M1", size="KING",
            start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T12:00:00Z",
        ),
        LS1,
    ), expected_status=201)
    assert run_b["status"] == "SCHEDULED"


def test_quilt_run_overlapping_existing_window_rejected(api):
    """PRD §3.6: "A new run conflicts with an existing one on the same
    `machine_id` — and is rejected with `ERR_MACHINE_TIME_CONFLICT` (409) —
    when the existing run is `SCHEDULED` or `RUNNING` and its `start_at` is
    strictly before the new run's `end_at` while the new run's `start_at` is
    strictly before the existing run's `end_at`."

    Design: Difficulty/resource_temporal_overlap/quilt_machine_half_open_overlap
    """
    ctx = setup_planned_order(quantity=4)
    order_id = ctx["order"]["id"]
    get_success_data(api.create_quilt_run(
        create_quilt_run_payload(
            order_id=order_id, machine_id="M1", size="QUEEN",
            start_at="2026-08-03T08:00:00Z", end_at="2026-08-03T10:00:00Z",
        ),
        LS1,
    ))
    get_success_data(api.create_quilt_run(
        create_quilt_run_payload(
            order_id=order_id, machine_id="M1", size="KING",
            start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T12:00:00Z",
        ),
        LS1,
    ))

    # [09:59, 11:00) overlaps both live windows.
    overlap = api.create_quilt_run(
        create_quilt_run_payload(
            order_id=order_id, machine_id="M1", size="TWIN",
            start_at="2026-08-03T09:59:00Z", end_at="2026-08-03T11:00:00Z",
        ),
        LS1,
    )
    validate_error(overlap, ApiErrorId.ERR_MACHINE_TIME_CONFLICT)


def test_quilt_run_with_degenerate_window_rejected(api):
    """PRD §3.6: "The window is half-open, with `end_at` exclusive, and
    `start_at` must be strictly before `end_at`; a degenerate or reversed
    window is rejected with `ERR_INVALID_TIME_RANGE` (400)."

    Design: Difficulty/resource_temporal_overlap/quilt_machine_half_open_overlap
    """
    ctx = setup_planned_order(quantity=4)
    resp = api.create_quilt_run(
        create_quilt_run_payload(
            order_id=ctx["order"]["id"], machine_id="M1", size="TWIN",
            start_at="2026-08-03T14:00:00Z", end_at="2026-08-03T14:00:00Z",
        ),
        LS1,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


def test_quilt_run_start_before_window_rejected(api):
    """PRD §3.6: "Starting it moves `SCHEDULED` → `RUNNING`, but only once the
    logical clock has reached `start_at` — an early start is rejected with
    `ERR_RUN_WINDOW_NOT_REACHED` (409), and a run not in `SCHEDULED` answers
    `ERR_RUN_NOT_SCHEDULED`."

    Design: Corner/validations/quilt_start_before_window_rejected
    """
    ctx = setup_planned_order(quantity=1)
    run = get_success_data(api.create_quilt_run(
        create_quilt_run_payload(
            order_id=ctx["order"]["id"], machine_id="M9", size="QUEEN",
            start_at="2026-08-03T08:00:00Z", end_at="2026-08-03T09:00:00Z",
        ),
        LS1,
    ))

    # Default clock 2026-08-01T00:00:00Z is before the window.
    early = api.start_quilt_run(run["id"], LS1)
    validate_error(early, ApiErrorId.ERR_RUN_WINDOW_NOT_REACHED)

    # At exactly start_at the start succeeds (clock must have reached start_at).
    get_success_data(api.set_clock("2026-08-03T08:00:00Z", PM))
    started = validate_success(api.start_quilt_run(run["id"], LS1))
    assert started["status"] == "RUNNING"
