"""Task queue lifecycle, the suspension cycle, and the SLA clock.

Translates difficulty instances task_block_then_unblock (non-linear state
machine), the SLA boundary/interval instances (boundary_precision_check 6.A,
resource_temporal_overlap 8.A/8.B), and the corner task / SLA instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_skill_tag_payload, create_client_payload, create_task_payload,
    setup_active_client_engagement, create_assigned_task, create_in_progress_task,
    create_task, log_and_approve_time,
    assert_task,
    TEST_USERS, make_client_headers,
)

SM = TEST_USERS["staffing_manager_headers"]


# ─── Task initial state + invalid transitions (corner) ──────────────────────
def test_new_task_starts_in_queued_initial_state(api):
    """PRD §3.4: "A new task is `QUEUED`, and creating it recomputes the client's `open_task_count` — the number of that client's tasks not in a terminal state"

    Design: Corner/state_machines/new_task_starts_in_queued_initial_state
    """
    skill = validate_success(api.create_skill_tag(
        create_skill_tag_payload(code="QUEUE_SK", name="Queue Skill"), SM), 201)
    client = validate_success(api.create_client(create_client_payload(company_name="Qsc"), SM), 201)
    res = api.create_task(
        create_task_payload(client["id"], title="Q task", required_skill_tag_id=skill["id"]),
        make_client_headers(client["id"]))
    data = validate_success(res, 201)
    assert_task(data)
    assert data["status"] == "QUEUED"


def test_cancel_already_cancelled_task_returns_invalid_state(api):
    """PRD §3.4: "Any transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE"
    PRD §3.4: "A non-terminal task may also be **cancelled** (`QUEUED`, `ASSIGNED`, `IN_PROGRESS`, or `BLOCKED` → `CANCELLED`) by the client or StaffingManager".

    Design: Corner/state_machines/cancel_already_cancelled_task_returns_invalid_state
    """
    skill = validate_success(api.create_skill_tag(
        create_skill_tag_payload(code="CANC_SK", name="Cancel Skill"), SM), 201)
    client = validate_success(api.create_client(create_client_payload(company_name="Cnc"), SM), 201)
    ch = make_client_headers(client["id"])
    task = validate_success(api.create_task(
        create_task_payload(client["id"], title="Cnc task", required_skill_tag_id=skill["id"]),
        ch), 201)
    validate_success(api.cancel_task(task["id"], ch), 200)
    res = api.cancel_task(task["id"], ch)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Suspension cycle (corner side effects) ─────────────────────────────────
def test_suspend_active_client_blocks_assigned_tasks_side_effect(api):
    """PRD §3.2: "Suspension moves every `QUEUED` or `ASSIGNED` task of that client into `BLOCKED`, stamping each one's `blocked_reason` to the value `CLIENT_SUSPENDED"

    Design: Corner/state_machines/suspend_active_client_blocks_assigned_tasks_side_effect
    """
    ctx = setup_active_client_engagement(skill_code="SUSP_SK")
    task = create_assigned_task(ctx)
    validate_success(api.suspend_client(ctx["client"]["id"], SM), 200)
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["status"] == "BLOCKED"
    assert after["blocked_reason"] == "CLIENT_SUSPENDED"


def test_resume_suspended_client_reverts_blocked_tasks(api):
    """PRD §3.2: "Resuming** a suspended client (`SUSPENDED → ACTIVE`) reverts exactly those tasks: a task blocked for the suspension reason that had previously been assigned returns to `ASSIGNED`, one that had never been assigned returns to `QUEUED`, and the `blocked_reason` is cleared in both cases"

    Design: Corner/state_machines/resume_suspended_client_reverts_blocked_tasks
    """
    ctx = setup_active_client_engagement(skill_code="RESM_SK")
    task = create_assigned_task(ctx)
    validate_success(api.suspend_client(ctx["client"]["id"], SM), 200)
    validate_success(api.resume_client(ctx["client"]["id"], SM), 200)
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["status"] == "ASSIGNED"
    assert after["blocked_reason"] is None


# ─── Block/unblock revert (difficulty: non_linear_state_machine 3.B) ────────
def test_task_block_then_unblock_reverts_into_work_loop(api):
    """PRD §3.4: "From either `ASSIGNED` or `IN_PROGRESS` the VA may **block** the task (`→ BLOCKED`), capturing a `blocked_reason` from the request and likewise stamping `first_action_at_iso` if it is still null."
    PRD §3.4: "A blocked task is **unblocked** by the VA (`BLOCKED → IN_PROGRESS`), which clears `blocked_reason`, but only while the client is `ACTIVE` (not `SUSPENDED"

    Design: Difficulty/non_linear_state_machine/task_block_then_unblock_reverts_into_work_loop
    """
    ctx = setup_active_client_engagement(skill_code="INBOX_MGMT")
    task = create_in_progress_task(ctx)
    validate_success(api.block_task(task["id"], {"blocked_reason": "waiting-on-client"},
                                    ctx["va_headers"]), 200)
    res = api.unblock_task(task["id"], ctx["va_headers"])
    data = validate_success(res, 200)
    assert data["status"] == "IN_PROGRESS"
    assert data["blocked_reason"] is None


def test_blocked_task_remains_blocked_until_unblocked(api):
    """PRD §3.4: "A blocked task is **unblocked** by the VA (`BLOCKED → IN_PROGRESS`), which clears `blocked_reason`, but only while the client is `ACTIVE` (not `SUSPENDED"

    Design: Difficulty/non_linear_state_machine/task_block_then_unblock_reverts_into_work_loop
    """
    ctx = setup_active_client_engagement(skill_code="INBOX_MGMT2")
    task = create_in_progress_task(ctx)
    blocked = validate_success(api.block_task(
        task["id"], {"blocked_reason": "awaiting-docs"}, ctx["va_headers"]), 200)
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "awaiting-docs"
    # Re-reading without an unblock keeps it BLOCKED.
    again = validate_success(api.get_task(task["id"], SM), 200)
    assert again["status"] == "BLOCKED"


# ─── SLA: immediate due-date computation (corner consistency_model) ─────────
def test_assign_response_reflects_sla_due_in_same_request(api):
    """PRD §3.4: "On assignment the task's `assigned_at_iso` is stamped from the clock, its `sla_state` is set to `ON_TRACK`, and its two due dates are computed: `response_due_iso` is `assigned_at_iso` advanced by the policy's `response_minutes` minutes, and `resolution_due_iso` is `assigned_at_iso` advanced by the policy's `resolution_hours` hours"

    Design: Corner/consistency_model/assign_response_reflects_sla_due_in_same_request
    """
    ctx = setup_active_client_engagement(skill_code="IMM_SK")  # clock at default 2026-03-01T00:00:00Z
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Imm task",
                       as_headers=ctx["client_headers"])
    assigned = validate_success(api.assign_task(task["id"], SM), 200)
    assert assigned["response_due_iso"] == "2026-03-01T01:00:00Z"
    assert assigned["resolution_due_iso"] == "2026-03-02T00:00:00Z"
    assert assigned["sla_state"] == "ON_TRACK"


# ─── SLA resolution boundary (difficulty: boundary_precision_check 6.A) ─────
def test_sla_resolution_boundary_strict_greater_than(api):
    """PRD §3.4: "The task's `sla_state` is re-evaluated on every read and on every transition, against the current clock, using a strict greater-than boundary — a clock value exactly equal to a due instant is still `ON_TRACK`, and only one second past it counts as breached"

    Design: Difficulty/boundary_precision_check/sla_resolution_boundary_strict_greater_than
    """
    ctx = setup_active_client_engagement(skill_code="CALENDAR")
    # Start the task within the response window (at the default clock) so
    # first_action_at_iso is stamped and the response branch is disabled — this
    # isolates the resolution boundary under test. Per PRD §3.4 the SLA standing
    # is priority-ordered: with first_action null and the clock past response_due,
    # the standing would be RESPONSE_BREACHED, masking the resolution boundary.
    task = create_in_progress_task(ctx)
    assert task["resolution_due_iso"] == "2026-03-02T00:00:00Z"
    # Clock exactly at resolution_due_iso: still ON_TRACK.
    validate_success(api.set_clock("2026-03-02T00:00:00Z", SM), 200)
    at_boundary = validate_success(api.get_task(task["id"], SM), 200)
    assert at_boundary["sla_state"] == "ON_TRACK"
    # One second past: RESOLUTION_BREACHED.
    validate_success(api.set_clock("2026-03-02T00:00:01Z", SM), 200)
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["sla_state"] == "RESOLUTION_BREACHED"


def test_sla_resolution_due_iso_is_assigned_plus_resolution_hours(api):
    """PRD §3.4: "resolution_due_iso` is `assigned_at_iso` advanced by the policy's `resolution_hours` hours"
    PRD §3.4: "Otherwise, if the clock now stands strictly after `resolution_due_iso`, the standing is `RESOLUTION_BREACHED".

    Design: Difficulty/boundary_precision_check/sla_resolution_boundary_strict_greater_than
    """
    ctx = setup_active_client_engagement(skill_code="CALENDAR2")
    # Start within the response window so first_action_at_iso is stamped and the
    # response branch is disabled, isolating the resolution window (PRD §3.4
    # priority order — otherwise the open response window would breach at 12:00).
    task = create_in_progress_task(ctx)
    # STANDARD resolution_hours=24, assigned at 2026-03-01T00:00:00Z.
    assert task["resolution_due_iso"] == "2026-03-02T00:00:00Z"
    # Well before the deadline: ON_TRACK.
    validate_success(api.set_clock("2026-03-01T12:00:00Z", SM), 200)
    mid = validate_success(api.get_task(task["id"], SM), 200)
    assert mid["sla_state"] == "ON_TRACK"


# ─── SLA response window (difficulty: resource_temporal_overlap 8.A) ────────
def test_sla_response_window_point_deadline_latches_on_first_action(api):
    """PRD §3.4: "else if the task has not yet taken a first action (its `first_action_at_iso` is still null) and the clock stands strictly after `response_due_iso`, the standing is `RESPONSE_BREACHED".

    Design: Difficulty/resource_temporal_overlap/sla_response_window_point_deadline_latches_on_first_action
    """
    ctx = setup_active_client_engagement(skill_code="RESEARCH")
    task = create_assigned_task(ctx)
    assert task["response_due_iso"] == "2026-03-01T01:00:00Z"
    validate_success(api.set_clock("2026-03-01T01:00:01Z", SM), 200)
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["first_action_at_iso"] is None
    assert after["sla_state"] == "RESPONSE_BREACHED"


def test_sla_response_window_cleared_once_first_action_taken(api):
    """PRD §3.4: "else if the task has not yet taken a first action (its `first_action_at_iso` is still null) and the clock stands strictly after `response_due_iso`, the standing is `RESPONSE_BREACHED".
    PRD §3.4: "The engagement's VA **starts** an assigned task (`ASSIGNED → IN_PROGRESS`), which stamps `first_action_at_iso` from the clock if it is still null"

    Design: Difficulty/resource_temporal_overlap/sla_response_window_point_deadline_latches_on_first_action
    """
    ctx = setup_active_client_engagement(skill_code="RESEARCH2")
    task = create_assigned_task(ctx)
    # Start within the response window so first_action is stamped before the deadline.
    started = validate_success(api.start_task(task["id"], ctx["va_headers"]), 200)
    assert started["first_action_at_iso"] is not None
    # Advance past the response deadline: the response window no longer applies.
    validate_success(api.set_clock("2026-03-01T01:00:01Z", SM), 200)
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["sla_state"] == "ON_TRACK"


# ─── SLA response boundary (corner: rate_threshold_triggers) ────────────────
def test_sla_response_breach_at_boundary_rate_threshold(api):
    """PRD §3.4: "a clock value exactly equal to a due instant is still `ON_TRACK`, and only one second past it counts as breached"

    Design: Corner/cross_cutting_complexity_layers/sla_response_breach_at_boundary_rate_threshold
    """
    ctx = setup_active_client_engagement(skill_code="RTT_SK")
    task = create_assigned_task(ctx)
    validate_success(api.set_clock("2026-03-01T01:00:00Z", SM), 200)
    at_boundary = validate_success(api.get_task(task["id"], SM), 200)
    assert at_boundary["sla_state"] == "ON_TRACK"
    validate_success(api.set_clock("2026-03-01T01:00:01Z", SM), 200)
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["sla_state"] == "RESPONSE_BREACHED"


# ─── SLA resolution latch at completion (difficulty 8.B) ────────────────────
def test_sla_resolution_window_cumulative_latches_at_completion(api):
    """PRD §3.4: "If the task has reached `DONE`, the standing is latched: it is `RESOLUTION_BREACHED` when its `completed_at_iso` fell strictly after `resolution_due_iso`, otherwise `ON_TRACK"
    PRD §3.4: "completion stamps `completed_at_iso`, latches `sla_state` as described above, and recomputes the client's `open_task_count"

    Design: Difficulty/resource_temporal_overlap/sla_resolution_window_cumulative_latches_at_completion
    """
    ctx = setup_active_client_engagement(skill_code="BOOKING_MGMT")
    task = create_in_progress_task(ctx)
    log_and_approve_time(ctx, task["id"], 60)
    validate_success(api.set_clock("2026-03-02T00:00:01Z", SM), 200)
    done = validate_success(api.complete_task(task["id"], ctx["va_headers"]), 200)
    assert done["status"] == "DONE"
    assert done["completed_at_iso"] == "2026-03-02T00:00:01Z"
    assert done["sla_state"] == "RESOLUTION_BREACHED"


def test_sla_resolution_latch_on_time_completion_stays_on_track(api):
    """PRD §3.4: "If the task has reached `DONE`, the standing is latched: it is `RESOLUTION_BREACHED` when its `completed_at_iso` fell strictly after `resolution_due_iso`, otherwise `ON_TRACK"

    Design: Difficulty/resource_temporal_overlap/sla_resolution_window_cumulative_latches_at_completion
    """
    ctx = setup_active_client_engagement(skill_code="BOOKING_MGMT2")
    task = create_in_progress_task(ctx)
    log_and_approve_time(ctx, task["id"], 60)
    # Complete before resolution_due (still within the 24h window).
    validate_success(api.set_clock("2026-03-01T12:00:00Z", SM), 200)
    done = validate_success(api.complete_task(task["id"], ctx["va_headers"]), 200)
    assert done["status"] == "DONE"
    assert done["sla_state"] == "ON_TRACK"
    # Latch holds even after the clock passes resolution_due.
    validate_success(api.set_clock("2026-03-05T00:00:00Z", SM), 200)
    later = validate_success(api.get_task(task["id"], SM), 200)
    assert later["sla_state"] == "ON_TRACK"
