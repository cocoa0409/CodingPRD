"""Validation precedence, cross-entity state gates, and cycle-close OCC.

Translates the difficulty priority_pair_validation_conflict instances (5.A/5.B),
the cross_entity_state_dependency instances (7.A/7.B), the corner OCC stale-version
instance, and the remaining corner temporal-gate validations.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    close_cycle_payload, create_time_entry_payload,
    setup_active_client_engagement, setup_active_client_with_active_addon,
    create_assigned_task, create_in_progress_task, create_task,
    log_time, open_cycle_for_client, close_open_cycle,
    TEST_USERS,
)

SM = TEST_USERS["staffing_manager_headers"]


# ─── Priority pair 5.A: state (p8) beats addon-required (p11) ───────────────
def test_assign_invalid_state_beats_addon_required(api):
    """PRD §2.7: "a state-machine violation (priority 8) is reported before the
    deeper business gates that assume the transition is at least structurally legal."
    PRD §2.7: "that the target resource is in a state from which the requested transition is defined — `ERR_INVALID_STATE".

    Design: Difficulty/priority_pair_validation_conflict/assign_invalid_state_beats_addon_required
    """
    # Specialized engagement with an ACTIVE addon, so the first assign succeeds and
    # the task becomes ASSIGNED; re-assigning is an undefined transition (priority 8).
    ctx = setup_active_client_with_active_addon(skill_code="LEGAL_PARALEGAL")
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Sp task",
                       as_headers=ctx["client_headers"])
    validate_success(api.assign_task(task["id"], SM), 200)  # now ASSIGNED
    res = api.assign_task(task["id"], SM)  # re-assign from ASSIGNED is undefined
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reassign_assigned_task_leaves_status_unchanged(api):
    """PRD §2.7: "a state-machine violation (priority 8) is reported before the
    deeper business gates that assume the transition is at least structurally legal."
    PRD §2.10: "Mutations are atomic: a single request either applies all of its effects — including effects that fan out to other entities — or none of them".

    Design: Difficulty/priority_pair_validation_conflict/assign_invalid_state_beats_addon_required
    """
    ctx = setup_active_client_with_active_addon(skill_code="LEGAL_PARALEGAL2")
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Sp task 2",
                       as_headers=ctx["client_headers"])
    validate_success(api.assign_task(task["id"], SM), 200)
    res = api.assign_task(task["id"], SM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    # The rejected re-assign left the task in its existing ASSIGNED state.
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["status"] == "ASSIGNED"


# NOTE — SKIPPED: Difficulty/priority_pair_validation_conflict/approve_no_open_cycle_beats_stale_version_pairing
# The recipe's precondition ("client whose only RetainerCycle is CLOSED, client itself
# still ACTIVE") is unreachable under faithful PRD semantics: PRD §3.8 states closing a
# cycle "then mints a successor cycle ... status is OPEN" unless the client is CLOSED.
# A PRD-only implementer therefore always has an OPEN cycle after a close on an
# ACTIVE/SUSPENDED client, so ERR_NO_OPEN_CYCLE is not uniquely-derivable here. No test
# emitted (per the PRD-first two-condition filter — unique-derivability fails).


# ─── Cross-entity 7.A: Task assign gated by Client.status (p9) ──────────────
def test_task_assign_blocked_by_non_active_client(api):
    """PRD §3.4: "Assignment may proceed only when the client is `ACTIVE` and has a non-null `active_engagement_id` (otherwise `ERR_CLIENT_NOT_ACTIVE".

    Design: Difficulty/cross_entity_state_dependency/task_assign_blocked_by_non_active_client
    """
    ctx = setup_active_client_engagement(skill_code="SOCIAL_MEDIA")
    # Suspend first, THEN create the task so it is QUEUED (not BLOCKED) at assign
    # time. PRD §3.2 moves a client's existing QUEUED/ASSIGNED tasks to BLOCKED on
    # suspension; a task created after suspension is QUEUED. Per §2.7 the state
    # gate (priority 8, ERR_INVALID_STATE) precedes the client-active gate
    # (priority 9), so only a QUEUED task reaches the priority-9 ERR_CLIENT_NOT_ACTIVE
    # this test is designed to exercise.
    validate_success(api.suspend_client(ctx["client"]["id"], SM), 200)  # ACTIVE -> SUSPENDED
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Susp task",
                       as_headers=ctx["client_headers"])
    res = api.assign_task(task["id"], SM)
    validate_error(res, "ERR_CLIENT_NOT_ACTIVE", expected_status=409)


def test_task_assign_on_suspended_client_leaves_task_queued(api):
    """PRD §3.4: "Assignment may proceed only when the client is `ACTIVE` and has a non-null `active_engagement_id` (otherwise `ERR_CLIENT_NOT_ACTIVE".
    PRD §3.2: "Once a client is `ACTIVE`, the StaffingManager may **suspend** it (`ACTIVE → SUSPENDED"

    Design: Difficulty/cross_entity_state_dependency/task_assign_blocked_by_non_active_client
    """
    ctx = setup_active_client_engagement(skill_code="SOCIAL_MEDIA2")
    # Suspend first, THEN create the task so it is QUEUED (not BLOCKED) at assign
    # time (PRD §3.2 / §2.7 — see test_task_assign_blocked_by_non_active_client).
    validate_success(api.suspend_client(ctx["client"]["id"], SM), 200)
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Susp task 2",
                       as_headers=ctx["client_headers"])
    res = api.assign_task(task["id"], SM)
    validate_error(res, "ERR_CLIENT_NOT_ACTIVE", expected_status=409)
    # The rejected assign did not move the task out of QUEUED.
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["status"] == "QUEUED"


# NOTE — SKIPPED: Difficulty/cross_entity_state_dependency/time_entry_approve_requires_open_retainer_cycle
# Same unreachable precondition as the 5.B skip above: PRD §3.8 mints a successor OPEN
# cycle on every close of a non-CLOSED client, so "the client's only RetainerCycle is
# CLOSED while the client is still ACTIVE" cannot be reached. ERR_NO_OPEN_CYCLE on
# approve is not uniquely-derivable from PRD; no test emitted.


# ─── OCC: stale expected_cycle_version on close (corner) ────────────────────
def test_cycle_close_stale_expected_version_returns_412(api):
    """PRD §2.9: "When `expected_cycle_version` does not equal the cycle's current `version`, the close is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), forcing the operator to re-read the true `consumed_hours` before sealing the cycle for invoicing"
    PRD §3.5: "Approving an entry also **increments the cycle's `version` by 1".

    Design: Corner/cross_cutting_complexity_layers/cycle_close_stale_expected_version_returns_412
    """
    ctx = setup_active_client_engagement(skill_code="STALE_SK")
    task = create_in_progress_task(ctx)
    entry = log_time(ctx, task["id"], 60)
    stale = open_cycle_for_client(ctx["client"]["id"])  # version captured BEFORE approval
    validate_success(api.approve_time_entry(entry["id"], ctx["client_headers"]), 200)  # bumps version
    res = api.close_cycle(stale["id"], close_cycle_payload(stale["version"]), SM)
    validate_error(res, "ERR_STALE_CYCLE_VERSION", expected_status=412)


# NOTE — SKIPPED: Corner/validations/time_entry_create_no_open_cycle_returns_cycle_not_open
# The recipe reaches "no OPEN cycle" by closing the client's only cycle while the client
# stays ACTIVE, then suspending. But PRD §3.8 mints a successor OPEN cycle on every close
# of a non-CLOSED client, and suspension does not close a cycle — so a faithful PRD
# implementer still has an OPEN cycle and the time-entry create would succeed. The
# asserted ERR_CYCLE_NOT_OPEN is not uniquely-derivable; no test emitted.
