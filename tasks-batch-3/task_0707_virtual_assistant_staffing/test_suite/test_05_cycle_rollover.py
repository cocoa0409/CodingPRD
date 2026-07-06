"""Retainer cycle close, the successor mint, and rollover carry.

Translates the difficulty instances retainer_cycle_close_mints_successor (cyclic
state machine 3.A) and rollover_carry_cap_binding (dual-variant 1.B), plus the
corner cycle-close-pending-entries validation and the version-bump-on-approval
OCC instance.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_invoice_payload, close_cycle_payload,
    setup_active_client_engagement, create_in_progress_task,
    log_time, log_and_approve_time, open_cycle_for_client,
    assert_retainer_cycle,
    TEST_USERS,
)

SM = TEST_USERS["staffing_manager_headers"]


def _open_cycle(api, client_id):
    cyc = open_cycle_for_client(client_id)
    return validate_success(api.get_cycle(cyc["id"], SM), 200)


# ─── Cyclic state machine: close mints successor OPEN cycle (difficulty 3.A) ─
def test_retainer_cycle_close_mints_successor_open_cycle(api):
    """PRD §3.8: "Unless the owning client is itself `CLOSED`, the close then mints a successor cycle: its `sequence_no` is the closing cycle's plus one, its `status` is `OPEN`, its `granted_hours` is the client's current `monthly_retainer_hours`, its `opened_at_iso` is the clock, and its `rolled_in_hours` is the rollover carry"

    Design: Difficulty/non_linear_state_machine/retainer_cycle_close_mints_successor_open_cycle
    """
    ctx = setup_active_client_engagement(skill_code="SCHEDULING", monthly_retainer_hours=10)
    cyc1 = _open_cycle(api, ctx["client"]["id"])
    closed = validate_success(api.close_cycle(
        cyc1["id"], close_cycle_payload(cyc1["version"]), SM), 200)
    assert closed["status"] == "CLOSED"
    cyc2 = open_cycle_for_client(ctx["client"]["id"])
    assert_retainer_cycle(cyc2)
    assert cyc2["status"] == "OPEN"
    assert cyc2["sequence_no"] == 2


def test_close_cycle_marks_closing_cycle_closed_and_keeps_sequence(api):
    """PRD §3.8: "On close the cycle moves to `CLOSED`, its `closed_at_iso` is stamped from the clock, and its `version` increments by 1"

    Design: Difficulty/non_linear_state_machine/retainer_cycle_close_mints_successor_open_cycle
    """
    ctx = setup_active_client_engagement(skill_code="SCHEDULING2", monthly_retainer_hours=10)
    cyc1 = _open_cycle(api, ctx["client"]["id"])
    assert cyc1["sequence_no"] == 1
    validate_success(api.close_cycle(cyc1["id"], close_cycle_payload(cyc1["version"]), SM), 200)
    reread = validate_success(api.get_cycle(cyc1["id"], SM), 200)
    assert reread["status"] == "CLOSED"
    assert reread["sequence_no"] == 1


# ─── Rollover carry CAP_BINDING (difficulty 1.B) ────────────────────────────
def test_rollover_carry_cap_binding_forfeits_surplus(api):
    """PRD §3.8: "The amount that carries forward is the smaller of that unused figure and the client's `rollover_cap_hours`: when unused exceeds the cap, only the cap carries and the surplus above the cap is forfeited; when unused is at most the cap, the entire remainder carries and nothing is forfeited"
    PRD §3.8: "its `granted_hours` is the client's current `monthly_retainer_hours`, its `opened_at_iso` is the clock, and its `rolled_in_hours` is the rollover carry"

    Design: Difficulty/dual_variant_calc/rollover_carry_cap_binding_forfeits_surplus
    """
    ctx = setup_active_client_engagement(
        skill_code="CRM_ADMIN", monthly_retainer_hours=10, rollover_cap_hours=5)
    task = create_in_progress_task(ctx, estimated_hours=2)
    log_and_approve_time(ctx, task["id"], 120)  # APPROVED 2.0h consumed
    cyc1 = _open_cycle(api, ctx["client"]["id"])
    validate_success(api.close_cycle(cyc1["id"], close_cycle_payload(cyc1["version"]), SM), 200)
    cyc2 = open_cycle_for_client(ctx["client"]["id"])
    # unused = 10 - 2 = 8 > cap 5 -> carry exactly 5, surplus 3 forfeited.
    assert cyc2["sequence_no"] == 2
    assert cyc2["granted_hours"] == pytest.approx(10, abs=1e-9)
    assert cyc2["rolled_in_hours"] == pytest.approx(5, abs=1e-9)


def test_rollover_carry_cap_slack_carries_entire_remainder(api):
    """PRD §3.8: "when unused is at most the cap, the entire remainder carries and
    nothing is forfeited."

    Design: Difficulty/dual_variant_calc/rollover_carry_cap_binding_forfeits_surplus
    """
    ctx = setup_active_client_engagement(
        skill_code="CRM_ADMIN2", monthly_retainer_hours=10, rollover_cap_hours=20)
    task = create_in_progress_task(ctx, estimated_hours=2)
    log_and_approve_time(ctx, task["id"], 120)  # APPROVED 2.0h consumed
    cyc1 = _open_cycle(api, ctx["client"]["id"])
    validate_success(api.close_cycle(cyc1["id"], close_cycle_payload(cyc1["version"]), SM), 200)
    cyc2 = open_cycle_for_client(ctx["client"]["id"])
    # unused = 10 - 2 = 8 <= cap 20 -> whole 8 carries.
    assert cyc2["rolled_in_hours"] == pytest.approx(8, abs=1e-9)


# ─── Cycle close blocked by pending LOGGED entry (corner validation) ────────
def test_close_cycle_with_pending_logged_entry_rejected(api):
    """PRD §3.8: "A close is permitted only when the cycle is `OPEN`, when no `LOGGED` (un-approved) time entry still charges it (otherwise `ERR_CYCLE_HAS_PENDING_ENTRIES` — every entry must be approved or rejected first".

    Design: Corner/validations/close_cycle_with_pending_logged_entry_rejected
    """
    ctx = setup_active_client_engagement(skill_code="CHP_SK")
    task = create_in_progress_task(ctx)
    log_time(ctx, task["id"], 60)  # LOGGED, charges the OPEN cycle
    cyc = _open_cycle(api, ctx["client"]["id"])
    res = api.close_cycle(cyc["id"], close_cycle_payload(cyc["version"]), SM)
    validate_error(res, "ERR_CYCLE_HAS_PENDING_ENTRIES", expected_status=409)


# ─── Approval bumps cycle version (corner OCC layer) ────────────────────────
def test_time_entry_approve_increments_cycle_version(api):
    """PRD §3.5: "Approving an entry also **increments the cycle's `version` by 1** — this is the version bump that the cycle-close concurrency guard in §2.9 watches for"

    Design: Corner/cross_cutting_complexity_layers/time_entry_approve_increments_cycle_version
    """
    ctx = setup_active_client_engagement(skill_code="OCC_SK")
    task = create_in_progress_task(ctx)
    entry = log_time(ctx, task["id"], 60)
    cyc_before = _open_cycle(api, ctx["client"]["id"])
    validate_success(api.approve_time_entry(entry["id"], ctx["client_headers"]), 200)
    cyc_after = validate_success(api.get_cycle(cyc_before["id"], SM), 200)
    assert cyc_after["version"] == cyc_before["version"] + 1
    assert cyc_after["consumed_hours"] == pytest.approx(1.0, abs=1e-9)
