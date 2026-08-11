"""Work order parallel axes: the QA fail rework loop cycles exec_status while
auth_status stays pinned at AUTHORIZED, and QA delay accrues either way."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, complete_current_wo, qa_current_wo,
    scenario_authorized_wo, set_clock, assign_slot_current_wo,
    start_current_wo, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]


def _rework_scenario() -> dict:
    """Authorized hose order; QA FAIL after a 2h review window, rework, then QA
    PASS after a second 2h review window."""
    ctx = scenario_authorized_wo()
    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    set_clock("2026-05-02T10:00:00Z")
    complete_current_wo(ctx, actual_hours=1.5)  # QA window opens 10:00
    set_clock("2026-05-02T12:00:00Z")
    qa_current_wo(ctx, result="FAIL")           # +2h shop delay, back to work
    set_clock("2026-05-02T13:00:00Z")
    complete_current_wo(ctx, actual_hours=2.0)  # QA window re-opens 13:00
    set_clock("2026-05-02T15:00:00Z")
    qa_current_wo(ctx, result="PASS")           # +2h more shop delay
    return ctx


def test_qa_fail_cycles_exec_status_while_auth_stays_authorized():
    """PRD §3.5: "A **fail** instead returns `exec_status` to `IN_PROGRESS` for
    rework, increments `rework_count`, and still accrues the QA interval into
    `shop_delay_hours` — the shop owns that delay either way."
    PRD §3.5: "Either outcome increments the work order's `version`, and the
    `QA_REVIEW` → `IN_PROGRESS` loop may repeat."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_axes_with_qa_rework_cycle
    """
    ctx = scenario_authorized_wo()
    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    set_clock("2026-05-02T10:00:00Z")
    complete_current_wo(ctx, actual_hours=1.5)
    set_clock("2026-05-02T12:00:00Z")
    qa_current_wo(ctx, result="FAIL")

    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["exec_status"] == "IN_PROGRESS", "rework returns execution to IN_PROGRESS"
    assert wo["auth_status"] == "AUTHORIZED", "the authorization axis does not move"
    assert wo["rework_count"] == 1


def test_qa_pass_after_rework_completes_and_accrues_delay():
    """PRD §3.5: "A **pass** stamps `completed_at`, accrues the hours from
    `qa_review_entered_at` to now into the railcar's `shop_delay_hours`, moves
    `exec_status` to `COMPLETED`".
    PRD §3.5: "when no sibling work order of the same railcar remains outside
    `COMPLETED` or `CANCELLED`, the car moves `IN_SHOP` →
    `READY_FOR_DEPARTURE`."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_axes_with_qa_rework_cycle
    """
    ctx = _rework_scenario()
    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["exec_status"] == "COMPLETED"
    assert wo["auth_status"] == "AUTHORIZED", "auth axis stayed pinned through the loop"
    assert wo["rework_count"] == 1

    car = validate_success(api_client.get_railcar(ctx["car"]["id"], ADMIN))
    assert car["shop_delay_hours"] == pytest.approx(4.0, abs=0.001), (
        "2h for the failed review window plus 2h for the passing window")
    assert car["status"] == "READY_FOR_DEPARTURE"
