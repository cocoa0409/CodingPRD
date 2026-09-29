"""Sequencing the trades: overlap rules, release gates and delay propagation."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_money_equals,
    assert_schedule_task,
    create_schedule_task,
    create_schedule_task_payload,
    read_allowance_item,
    read_schedule_task,
    run_task_to_completion,
    setup_exclusive_use_slab,
    setup_job,
    setup_job_with_material_driven_task,
    setup_locked_allowance,
    setup_two_project_schedule,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Overlap rules ────────────────────────────────────────────────────────
def test_crew_task_starting_exactly_when_the_previous_one_finishes_is_accepted(api):
    """PRD §3.4: "The **crew-capacity rule** treats every interval as half-open —
    `planned_start` included, `planned_finish` excluded — so that a crew finishing one task
    exactly when it starts the next is not double-booked; touching intervals do not intersect."

    Design: Difficulty/resource_temporal_overlap/crew_capacity_halfopen_interval_allows_adjacency_rejects_overlap
    """
    ctx = setup_job(with_lender=False, start_construction=False, frame_crew_capacity=1)

    response = api.create_schedule_task(
        create_schedule_task_payload(
            ctx["project"]["id"],
            ctx["sub_frame"]["id"],
            task_name="Frame punch adjacent",
            planned_start="2026-10-15T00:00:00.000Z",
            planned_finish="2026-11-01T00:00:00.000Z",
        ),
        ctx["pm_headers"],
    )
    adjacent = validate_success(response, 201)

    assert_schedule_task(adjacent)
    assert adjacent["status"] == "PLANNED"


def test_crew_task_overlapping_the_previous_one_breaches_crew_capacity(api):
    """PRD §3.4: "The server counts the existing schedule tasks for the same
    `subcontractor_id` whose status is `PLANNED`, `RELEASED`, or `IN_PROGRESS` and whose
    half-open interval intersects the new task's half-open interval, and that count must be
    strictly less than the trade's `crew_capacity`; otherwise the creation is refused with
    `ERR_CREW_CAPACITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_capacity_halfopen_interval_allows_adjacency_rejects_overlap
    """
    ctx = setup_job(with_lender=False, start_construction=False, frame_crew_capacity=1)
    create_schedule_task(
        ctx["project"]["id"],
        ctx["sub_frame"]["id"],
        ctx["pm_headers"],
        task_name="Frame punch adjacent",
        planned_start="2026-10-15T00:00:00.000Z",
        planned_finish="2026-11-01T00:00:00.000Z",
    )

    response = api.create_schedule_task(
        create_schedule_task_payload(
            ctx["project"]["id"],
            ctx["sub_frame"]["id"],
            task_name="Frame punch overlapping",
            planned_start="2026-10-14T00:00:00.000Z",
            planned_finish="2026-11-01T00:00:00.000Z",
        ),
        ctx["pm_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CREW_CAPACITY_CONFLICT, 409)

    rows, meta = validate_paginated(
        api.list_schedule_tasks(
            ADMIN, params={"subcontractor_id": ctx["sub_frame"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, "only the two non-colliding bookings may survive"


def test_exclusive_task_starting_inside_the_cure_buffer_is_refused(api):
    """PRD §3.4: "The **jobsite exclusive-use rule** applies only when the new task's
    `exclusive_use` is true, and it is deliberately stricter: the occupied interval runs from
    `planned_start` through `planned_finish` extended by a one-day jobsite cure buffer, and both
    ends of that buffered interval are closed, so that touching endpoints *do* intersect."
    PRD §3.4: "If that closed buffered interval intersects the equally buffered interval of any
    existing `exclusive_use` task on the same project whose status is `PLANNED`, `RELEASED`, or
    `IN_PROGRESS`, the creation is refused with `ERR_JOBSITE_EXCLUSIVE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/jobsite_exclusive_closed_interval_plus_cure_buffer_rejects_adjacency
    """
    ctx = setup_exclusive_use_slab()

    response = api.create_schedule_task(
        create_schedule_task_payload(
            ctx["project"]["id"],
            ctx["sub_concrete"]["id"],
            task_name="Driveway pour touching the cure buffer",
            planned_start="2026-09-11T00:00:00.000Z",
            planned_finish="2026-09-20T00:00:00.000Z",
            exclusive_use=True,
        ),
        ctx["pm_headers"],
    )
    validate_error(response, ApiErrorId.ERR_JOBSITE_EXCLUSIVE_CONFLICT, 409)


def test_exclusive_task_clear_of_the_cure_buffer_is_accepted(api):
    """PRD §3.4: "The **jobsite exclusive-use rule** applies only when the new task's
    `exclusive_use` is true, and it is deliberately stricter: the occupied interval runs from
    `planned_start` through `planned_finish` extended by a one-day jobsite cure buffer, and both
    ends of that buffered interval are closed, so that touching endpoints *do* intersect."
    PRD §3.4: "A fourth optional input, `exclusive_use`, defaults to false and declares that
    the activity takes over the whole jobsite."

    Design: Difficulty/resource_temporal_overlap/jobsite_exclusive_closed_interval_plus_cure_buffer_rejects_adjacency
    """
    ctx = setup_exclusive_use_slab()

    response = api.create_schedule_task(
        create_schedule_task_payload(
            ctx["project"]["id"],
            ctx["sub_concrete"]["id"],
            task_name="Driveway pour clear of the cure buffer",
            planned_start="2026-09-12T00:00:00.000Z",
            planned_finish="2026-09-20T00:00:00.000Z",
            exclusive_use=True,
        ),
        ctx["pm_headers"],
    )
    driveway = validate_success(response, 201)

    assert driveway["exclusive_use"] is True
    rows, meta = validate_paginated(
        api.list_schedule_tasks(
            ADMIN, params={"project_id": ctx["project"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, "the slab pour and the clear driveway pour both stand"


def test_cross_project_predecessor_is_reported_before_the_crew_conflict(api):
    """PRD §2.10: "Many requests in this system are capable of failing more than one way at
    once, and the benchmark for correctness is not merely *that* such a request is refused but
    *which* refusal it earns. Checks are evaluated in the following strict order, and the first
    check that fails ends the request; no later check may mask an earlier one."
    PRD §2.10: "**Predecessor in the same project.** A supplied `predecessor_task_id` must name
    a schedule task belonging to the same project as the task being created, or
    `ERR_PREDECESSOR_CROSS_PROJECT` (422)."
    PRD §2.10: "**Crew capacity.** A new schedule task must not exceed the trade's crew capacity
    as defined in §3.4, or `ERR_CREW_CAPACITY_CONFLICT` (409)."

    Design: Difficulty/priority_pair_validation_conflict/predecessor_referential_error_precedes_crew_overlap_error
    """
    ctx = setup_two_project_schedule()

    response = api.create_schedule_task(
        create_schedule_task_payload(
            ctx["project_1"]["id"],
            ctx["sub_frame"]["id"],
            task_name="P1 frame punch",
            planned_start="2026-09-15T00:00:00.000Z",
            planned_finish="2026-10-01T00:00:00.000Z",
            predecessor_task_id=ctx["task_a"]["id"],
        ),
        ctx["pm_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PREDECESSOR_CROSS_PROJECT, 422)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_CREW_CAPACITY_CONFLICT.value


def test_task_refused_for_a_cross_project_predecessor_is_not_stored(api):
    """PRD §3.4: "`predecessor_task_id`, which is null for a schedule root and otherwise names
    the task that must finish first and must belong to the same project (a cross-project
    reference is refused with `ERR_PREDECESSOR_CROSS_PROJECT`)"
    PRD §3.4: "Tasks can be read individually — the read surfaces material readiness and float
    — and listed with filters on `project_id`, `subcontractor_id`, `predecessor_task_id`,
    `driving_allowance_item_id`, and `status`."

    Design: Difficulty/priority_pair_validation_conflict/predecessor_referential_error_precedes_crew_overlap_error
    """
    ctx = setup_two_project_schedule()

    response = api.create_schedule_task(
        create_schedule_task_payload(
            ctx["project_1"]["id"],
            ctx["sub_frame"]["id"],
            task_name="P1 frame punch",
            planned_start="2026-09-15T00:00:00.000Z",
            planned_finish="2026-10-01T00:00:00.000Z",
            predecessor_task_id=ctx["task_a"]["id"],
        ),
        ctx["pm_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PREDECESSOR_CROSS_PROJECT, 422)

    rows, meta = validate_paginated(
        api.list_schedule_tasks(
            ADMIN, params={"project_id": ctx["project_1"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, "the refused task must not join project 1's schedule"


# ─── Release gates ────────────────────────────────────────────────────────
def test_release_is_blocked_while_the_driving_allowance_line_is_open(api):
    """PRD §3.4: "If the task names a `driving_allowance_item_id`, that allowance line must be
    `LOCKED` or `RECONCILED`, and a line still `OPEN`, `FROZEN`, or `SELECTED` earns
    `ERR_ALLOWANCE_NOT_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/task_release_gated_by_driving_allowance_item_lock
    """
    ctx = setup_job_with_material_driven_task()
    assert read_allowance_item(ctx["allowance_item"]["id"])["status"] == "OPEN"

    response = api.release_schedule_task(ctx["task_cabinet"]["id"], ctx["pm_headers"])
    validate_error(response, ApiErrorId.ERR_ALLOWANCE_NOT_LOCKED, 409)

    task = read_schedule_task(ctx["task_cabinet"]["id"])
    assert task["status"] == "PLANNED"
    assert task["released_at"] is None


def test_release_clears_once_the_allowance_line_locks_and_material_lands_in_time(api):
    """PRD §3.2: "It also reaches sideways into the schedule: for every schedule task whose
    `driving_allowance_item_id` names this line, the server computes `material_ready_at` as the
    line's `locked_at` advanced by the accepted proposal's `lead_time_days` plus a further three
    days of fabrication buffer."
    PRD §3.4: "If the task carries a computed `material_ready_at`, that instant must be no later
    than the task's `planned_start`; material landing after the crew is due on site earns
    `ERR_MATERIAL_NOT_READY`."
    PRD §3.2: "Finally, if the line locked with a `provisional_variance_amount` strictly greater
    than zero, the server automatically opens a change order in `DRAFT` with `origin` of
    `ALLOWANCE_OVERAGE`, `source_allowance_item_id` pointing back at this line, `direct_cost`
    equal to the `provisional_variance_amount`, and `schedule_impact_days` of zero — the overrun
    becomes a priced, client-approvable document rather than a silent budget leak."

    Design: Difficulty/cross_entity_state_dependency/task_release_gated_by_driving_allowance_item_lock
    """
    ctx = setup_job_with_material_driven_task()
    locked = setup_locked_allowance(
        ctx,
        vendor_name="Northwood Millwork",
        vendor_quote_amount=21000.00,
        freight_amount=1500.00,
        install_amount=1500.00,
        lead_time_days=20,
    )

    assert locked["status"] == "LOCKED"
    assert_money_equals(
        locked["provisional_variance_amount"], -1000.00, "provisional_variance_amount"
    )

    task = read_schedule_task(ctx["task_cabinet"]["id"])
    assert_instant_equals(
        task["material_ready_at"], "2026-08-24T00:00:00.000Z", "material_ready_at"
    )

    released = validate_success(
        api.release_schedule_task(ctx["task_cabinet"]["id"], ctx["pm_headers"]), 200
    )
    assert released["status"] == "RELEASED"

    rows, meta = validate_paginated(
        api.list_change_orders(
            ADMIN, params={"project_id": ctx["project"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        "a negative provisional variance opens no allowance-overage change order"
    )


def test_release_before_material_readiness_is_refused(api):
    """PRD §3.4: "If the task carries a computed `material_ready_at`, that instant must be no
    later than the task's `planned_start`; material landing after the crew is due on site earns
    `ERR_MATERIAL_NOT_READY`."
    PRD §3.2: "It also reaches sideways into the schedule: for every schedule task whose
    `driving_allowance_item_id` names this line, the server computes `material_ready_at` as the
    line's `locked_at` advanced by the accepted proposal's `lead_time_days` plus a further three
    days of fabrication buffer."

    Design: Corner/errors/release_before_material_ready_returns_material_not_ready
    """
    ctx = setup_job_with_material_driven_task()
    setup_locked_allowance(
        ctx,
        vendor_name="Northwood Millwork",
        vendor_quote_amount=21000.00,
        freight_amount=1500.00,
        install_amount=1500.00,
        lead_time_days=40,
    )

    response = api.release_schedule_task(ctx["task_cabinet"]["id"], ctx["pm_headers"])
    validate_error(response, ApiErrorId.ERR_MATERIAL_NOT_READY, 409)

    task = read_schedule_task(ctx["task_cabinet"]["id"])
    assert_instant_equals(
        task["material_ready_at"], "2026-09-13T00:00:00.000Z", "material_ready_at"
    )
    assert task["status"] == "PLANNED"
    assert read_allowance_item(ctx["allowance_item"]["id"])["status"] == "LOCKED"


def test_release_with_an_incomplete_predecessor_is_refused(api):
    """PRD §3.4: "If the task names a `predecessor_task_id`, that predecessor must be
    `COMPLETE`, and anything else earns `ERR_PREDECESSOR_INCOMPLETE`."

    Design: Corner/state_machines/release_task_with_incomplete_predecessor_is_rejected
    """
    ctx = setup_job(with_lender=False, with_plumbing=True)
    successor = create_schedule_task(
        ctx["project"]["id"],
        ctx["sub_plumb"]["id"],
        ctx["pm_headers"],
        task_name="Rough plumbing",
        planned_start="2026-10-16T00:00:00.000Z",
        planned_finish="2026-11-30T00:00:00.000Z",
        predecessor_task_id=ctx["task_frame"]["id"],
    )

    response = api.release_schedule_task(successor["id"], ctx["pm_headers"])
    validate_error(response, ApiErrorId.ERR_PREDECESSOR_INCOMPLETE, 409)

    task = read_schedule_task(successor["id"])
    assert task["status"] == "PLANNED"
    assert task["released_at"] is None


# ─── Progress and delay propagation ───────────────────────────────────────
def test_late_completion_pushes_the_direct_successor_and_recomputes_its_float(api):
    """PRD §3.4: "Completing advances `IN_PROGRESS → COMPLETE`, stamps `actual_finish` with the
    logical clock now, and computes `delay_days` as the number of whole days between
    `planned_finish` and `actual_finish`, floored at zero — a crew that finishes early or on time
    records a delay of zero, never a negative number."
    PRD §3.4: "Every direct successor — every task whose `predecessor_task_id` names the
    completed task — that is still in `PLANNED` or `RELEASED` has both its `planned_start` and
    its `planned_finish` pushed later by that many days, processed in order of `planned_start`
    ascending with `created_at` ascending as the tie-break."
    PRD §3.4: "Each shifted successor then has its `float_days` recomputed from its new
    `planned_start` against the completed task's `actual_finish` advanced by that successor's
    `lag_days`."

    Design: Corner/state_machines/late_task_completion_shifts_direct_successor_planned_dates
    """
    ctx = setup_job(with_lender=False, with_plumbing=True)
    successor = create_schedule_task(
        ctx["project"]["id"],
        ctx["sub_plumb"]["id"],
        ctx["pm_headers"],
        task_name="Rough plumbing",
        planned_start="2026-10-16T00:00:00.000Z",
        planned_finish="2026-11-30T00:00:00.000Z",
        predecessor_task_id=ctx["task_frame"]["id"],
        lag_days=0,
    )

    completed = run_task_to_completion(
        ctx,
        ctx["task_frame"]["id"],
        ctx["sub_frame_headers"],
        "2026-10-20T00:00:00.000Z",
    )

    assert completed["status"] == "COMPLETE"
    assert_instant_equals(
        completed["actual_finish"], "2026-10-20T00:00:00.000Z", "actual_finish"
    )
    assert completed["delay_days"] == 5

    shifted = read_schedule_task(successor["id"])
    assert_instant_equals(
        shifted["planned_start"], "2026-10-21T00:00:00.000Z", "successor planned_start"
    )
    assert_instant_equals(
        shifted["planned_finish"], "2026-12-05T00:00:00.000Z", "successor planned_finish"
    )
    assert shifted["float_days"] == 1
    assert shifted["status"] == "PLANNED"


def test_successor_is_discoverable_through_the_predecessor_filter(api):
    """PRD §3.4: "Tasks can be read individually — the read surfaces material readiness and
    float — and listed with filters on `project_id`, `subcontractor_id`, `predecessor_task_id`,
    `driving_allowance_item_id`, and `status`."
    PRD §3.4: "A new task lands in `PLANNED` with `material_ready_at`, `actual_start`,
    `actual_finish`, `float_days`, and `released_at` null and `delay_days` at zero."

    Design: Corner/entities/schedule_task_self_referential_predecessor_edge_is_readable
    """
    ctx = setup_job(
        with_lender=False, with_plumbing=True, start_construction=False, create_allowance=False
    )
    successor = create_schedule_task(
        ctx["project"]["id"],
        ctx["sub_plumb"]["id"],
        ctx["pm_headers"],
        task_name="Rough plumbing",
        planned_start="2026-10-16T00:00:00.000Z",
        planned_finish="2026-11-30T00:00:00.000Z",
        predecessor_task_id=ctx["task_frame"]["id"],
        lag_days=0,
    )

    rows, meta = validate_paginated(
        api.list_schedule_tasks(
            ADMIN,
            params={"predecessor_task_id": ctx["task_frame"]["id"], "limit": 100},
        )
    )

    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == successor["id"]
    assert read_schedule_task(successor["id"])["predecessor_task_id"] == ctx["task_frame"]["id"]
