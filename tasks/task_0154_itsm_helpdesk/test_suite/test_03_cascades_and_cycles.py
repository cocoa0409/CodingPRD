"""Transitive cascades (CAB approve -> ticket resume -> resolve-window recompute;
root cause -> asset degrade) and the cyclic reopen transition.

Difficulty queue A: transitive_cascade, non_linear_state_machine (reopen cycle).
"""
from test_helpers import (
    api_client,
    validate_success,
    fixtures as fx,
    test_users as U,
)


# ===========================================================================
# transitive_cascade / cab_approve_resumes_ticket_recomputes_resolve_window_depth3
# ===========================================================================
def test_cab_approve_resumes_ticket_and_adds_paused_delta_to_resolve_window():
    """PRD §3.5: "Whenever a vote drives the change to either APPROVED or
    REJECTED, a cascade bubbles up to the gated ticket: the linked ticket (named
    by the change's ticket_id) moves from PENDING_CHANGE back to IN_PROGRESS, its
    SLA resumes — the paused interval since pause_started_at is measured in whole
    minutes, added to paused_total_minutes, and added to resolve_due_at, with
    sla_state returning to RUNNING — and the ticket's change_request_id is cleared
    to null."

    Design: Difficulty/transitive_cascade/cab_approve_resumes_ticket_recomputes_resolve_window_depth3
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_in_progress_ticket(
        default_priority="P3", requester_id="req-6", agent_id="agent-6"
    )
    tid = ticket["id"]
    change = fx.create_and_submit_change(tid, risk="LOW", manager_id="cm-3")

    fx.advance_clock(30)  # 30 min run before pause
    validate_success(
        api_client.attach_change(tid, {"change_request_id": change["id"]}, U.agent("agent-6"))
    )
    fx.advance_clock(90)  # 90 min paused

    validate_success(
        api_client.cast_vote(
            change["id"],
            {"decision": "APPROVE", "expected_change_request_version": change["version"]},
            U.cab_member("cab-4"),
        ),
        expected_status=201,
    )
    cr_after = validate_success(api_client.get_change_request(change["id"], U.cab_member("cab-4")))
    assert cr_after["state"] == "APPROVED"

    tkt = validate_success(api_client.get_ticket(tid, U.agent("agent-6")))
    assert tkt["lifecycle_state"] == "IN_PROGRESS"
    assert tkt["paused_total_minutes"] == 90
    # opened+240 base, +90 paused -> opened+330 = 05:30.
    assert tkt["resolve_due_at"] == "2026-06-01T05:30:00.000Z", \
        f"expected opened+330 (240+90 paused), got {tkt['resolve_due_at']}"


def test_cab_approve_resume_clears_change_request_id_and_runs_sla():
    """PRD §3.5: "its SLA resumes ... with sla_state returning to RUNNING — and
    the ticket's change_request_id is cleared to null."

    Design: Difficulty/transitive_cascade/cab_approve_resumes_ticket_recomputes_resolve_window_depth3
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket, change = fx.setup_ticket_pending_change(
        risk="LOW", default_priority="P3", manager_id="cm-3b",
        agent_id="agent-6b", requester_id="req-6b",
    )
    validate_success(
        api_client.cast_vote(
            change["id"],
            {"decision": "APPROVE", "expected_change_request_version": change["version"]},
            U.cab_member("cab-4b"),
        ),
        expected_status=201,
    )
    tkt = validate_success(api_client.get_ticket(ticket["id"], U.agent("agent-6b")))
    assert tkt["lifecycle_state"] == "IN_PROGRESS"
    assert tkt["change_request_id"] is None
    assert tkt["sla_state"] == "RUNNING"


# ===========================================================================
# transitive_cascade / problem_root_cause_degrades_asset_depth2
# ===========================================================================
def test_identify_root_cause_with_asset_degrades_that_asset():
    """PRD §3.8: "Identifying the root cause moves the problem from OPEN to
    ROOT_CAUSE_IDENTIFIED; if the call supplies an asset_id, that asset is
    recorded on the problem and its status cascades from OPERATIONAL to DEGRADED."

    Design: Difficulty/transitive_cascade/problem_root_cause_degrades_asset_depth2
    """
    asset = fx.create_asset(asset_tag="SRV-001", kind="SERVER")
    problem = fx.create_problem(owner_id="agent-7")

    prob_after = validate_success(
        api_client.identify_root_cause(problem["id"], {"asset_id": asset["id"]}, U.agent("agent-7"))
    )
    assert prob_after["state"] == "ROOT_CAUSE_IDENTIFIED"
    assert prob_after["asset_id"] == asset["id"]

    asset_after = validate_success(api_client.get_asset(asset["id"], U.agent("agent-7")))
    assert asset_after["status"] == "DEGRADED", \
        "root-cause finding must cascade the referenced asset to DEGRADED"


def test_identify_root_cause_records_asset_on_problem():
    """PRD §3.8: "if the call supplies an asset_id, that asset is recorded on the
    problem and its status cascades from OPERATIONAL to DEGRADED."

    Design: Difficulty/transitive_cascade/problem_root_cause_degrades_asset_depth2
    """
    asset = fx.create_asset(asset_tag="SRV-002", kind="NETWORK_DEVICE")
    problem = fx.create_problem(owner_id="agent-7b")

    prob_after = validate_success(
        api_client.identify_root_cause(problem["id"], {"asset_id": asset["id"]}, U.agent("agent-7b"))
    )
    assert prob_after["asset_id"] == asset["id"]
    assert prob_after["state"] == "ROOT_CAUSE_IDENTIFIED"


# ===========================================================================
# non_linear_state_machine / ticket_reopen_cycle_resolved_to_in_progress
# ===========================================================================
def test_reopen_returns_ticket_to_in_progress_and_increments_count():
    """PRD §3.6: "A successful reopen moves lifecycle_state from RESOLVED back to
    IN_PROGRESS, increments reopen_count by one, sets sla_state to RUNNING,
    recomputes the owning group's queue_depth upward, and applies the reopen
    penalty."

    Design: Difficulty/non_linear_state_machine/ticket_reopen_cycle_resolved_to_in_progress
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-4", agent_id="agent-4"
    )
    reopened = validate_success(api_client.reopen_ticket(ticket["id"], U.requester("req-4")))

    assert reopened["lifecycle_state"] == "IN_PROGRESS"
    assert reopened["reopen_count"] == 1


def test_reopen_sets_sla_state_running():
    """PRD §3.6: "A successful reopen moves lifecycle_state from RESOLVED back to
    IN_PROGRESS, increments reopen_count by one, sets sla_state to RUNNING."

    Design: Difficulty/non_linear_state_machine/ticket_reopen_cycle_resolved_to_in_progress
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-4b", agent_id="agent-4b"
    )
    reopened = validate_success(api_client.reopen_ticket(ticket["id"], U.requester("req-4b")))

    assert reopened["sla_state"] == "RUNNING"
    assert reopened["lifecycle_state"] == "IN_PROGRESS"
