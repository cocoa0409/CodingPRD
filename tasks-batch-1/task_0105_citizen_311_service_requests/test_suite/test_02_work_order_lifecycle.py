"""Work-order lifecycle, cross-aggregate cascades, and backlog conservation.

Queue A (Difficulty): the WorkOrder cyclic reopen loop, the depth-3 complete
cascade (work order -> request RESOLVED -> survey SENT + escalation resolve), the
depth-3 reopen cascade (request REOPENED -> work order re-activated + survey
expired + backlog increment), department-backlog conservation across
complete-then-reopen, and open-escalation-count conservation across
breach-then-resolve. Queue B (Corner): cancelling an OPEN work order decrements
backlog, and the inclusive congestion threshold.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    fixtures as fx,
    TEST_USERS,
    make_agent_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Queue A — Difficulty: WorkOrder cyclic reopen loop
# ---------------------------------------------------------------------------
def test_reopen_returns_work_order_to_in_progress(api):
    """PRD §3.5: "It drives the request's work order through `COMPLETED → REOPENED`
    and then immediately `REOPENED → IN_PROGRESS`; the first leg raises the
    department's `open_work_order_count` and recomputes `congested`, and the second
    leg bubbles the request back up `REOPENED → IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/workorder_cyclic_reopen_loop
    """
    env = fx.setup_resolved_request()
    citizen_id = env["citizen"]["id"]
    fx.api_client.reopen_service_request(
        env["request"]["id"], fx.make_citizen_headers(citizen_id)
    )
    wo = validate_success(api.get_work_order(env["work_order"]["id"], DISPATCHER), 200)
    assert wo["status"] == "IN_PROGRESS"


def test_reopen_increments_reopen_count_and_request_in_progress(api):
    """PRD §3.5: "A successful reopen does several things in cascade. It increments
    the request's `reopen_count` by one and clears `resolved_at` back to null."
    PRD §3.5: "the second leg bubbles the request back up `REOPENED → IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/workorder_cyclic_reopen_loop
    """
    env = fx.setup_resolved_request()
    citizen_id = env["citizen"]["id"]
    data = validate_success(
        api.reopen_service_request(env["request"]["id"], fx.make_citizen_headers(citizen_id)),
        200,
    )
    assert data["reopen_count"] == 1
    after = fx.get_request(env["request"]["id"])
    assert after["status"] == "IN_PROGRESS"
    assert after["resolved_at"] is None


# ---------------------------------------------------------------------------
# Queue A — Difficulty: depth-3 complete cascade
# ---------------------------------------------------------------------------
def test_complete_cascade_resolves_request_and_creates_survey(api):
    """PRD §3.4: "and bubbles up to the request, which advances
    `IN_PROGRESS → RESOLVED`. That cross-aggregate cascade does several things at
    once: it stamps the request's `resolved_at` with the current instant, synthesizes
    an `IN_PROGRESS → RESOLVED` notification, creates a satisfaction survey in the
    `SENT` state for the request if none exists yet, and resolves any still-open
    escalation on the request as a compensating side effect."

    Design: Difficulty/transitive_cascade/complete_cascade_request_resolved_survey_and_escalation
    """
    env = fx.setup_started_request()
    fx.advance_clock(27)  # breach -> one OPEN escalation on the request
    agent_id = env["agent"]["id"]
    validate_success(
        api.complete_work_order(
            env["work_order"]["id"], {"completion_note": "fixed"}, make_agent_headers(agent_id)
        ),
        200,
    )
    request = fx.get_request(env["request"]["id"])
    assert request["status"] == "RESOLVED"
    surveys, meta = validate_paginated(
        api.list_surveys(DISPATCHER, params={"request_id": env["request"]["id"]})
    )
    sent = [s for s in surveys if s["status"] == "SENT"]
    assert len(sent) == 1, "exactly one SENT survey synthesized on RESOLVED"


def test_complete_cascade_resolves_open_escalation(api):
    """PRD §3.4: "and resolves any still-open escalation on the request as a
    compensating side effect (each such `Escalation` moves `OPEN → RESOLVED` with
    `resolved_by_role` recorded as the system)."

    Design: Difficulty/transitive_cascade/complete_cascade_request_resolved_survey_and_escalation
    """
    env = fx.setup_started_request()
    fx.advance_clock(27)  # breach fires one OPEN escalation
    agent_id = env["agent"]["id"]
    validate_success(
        api.complete_work_order(
            env["work_order"]["id"], {"completion_note": "fixed"}, make_agent_headers(agent_id)
        ),
        200,
    )
    escalations = fx.get_escalations_for_request(env["request"]["id"])
    assert escalations, "the breach must have created an escalation"
    assert all(e["status"] == "RESOLVED" for e in escalations)


# ---------------------------------------------------------------------------
# Queue A — Difficulty: depth-3 reopen cascade
# ---------------------------------------------------------------------------
def test_reopen_cascade_expires_survey(api):
    """PRD §3.5: "It expires the request's satisfaction survey if that survey is still
    in `SENT` (moving the survey `SENT → EXPIRED`)."

    Design: Difficulty/transitive_cascade/reopen_cascade_workorder_backlog_survey
    """
    env = fx.setup_resolved_request()
    survey = fx.get_survey_for_request(env["request"]["id"])
    citizen_id = env["citizen"]["id"]
    fx.api_client.reopen_service_request(env["request"]["id"], fx.make_citizen_headers(citizen_id))
    after = validate_success(api.get_survey(survey["id"], DISPATCHER), 200)
    assert after["status"] == "EXPIRED"


def test_reopen_cascade_raises_department_backlog(api):
    """PRD §3.5: "the first leg raises the department's `open_work_order_count` and
    recomputes `congested`."
    PRD §2.10: "The `open_work_order_count` is the number of `WorkOrder` rows
    belonging to that department whose `status` is `OPEN`, `IN_PROGRESS`, or
    `REOPENED`; work orders in `COMPLETED` or `CANCELLED` do not count."

    Design: Difficulty/transitive_cascade/reopen_cascade_workorder_backlog_survey
    """
    env = fx.setup_resolved_request()
    dept_id = env["dept"]["id"]
    # After completion the count is 0 (work order COMPLETED).
    assert fx.get_department(dept_id)["open_work_order_count"] == 0
    citizen_id = env["citizen"]["id"]
    fx.api_client.reopen_service_request(env["request"]["id"], fx.make_citizen_headers(citizen_id))
    after = fx.get_department(dept_id)
    assert after["open_work_order_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — Difficulty: department backlog conserved (complete then reopen)
# ---------------------------------------------------------------------------
def test_backlog_conserved_across_complete_then_reopen(api):
    """PRD §2.10: "A department is `congested` exactly when its `open_work_order_count`
    is greater than or equal to its `backlog_threshold` (an inclusive comparison)."
    PRD §3.5: "the first leg raises the department's `open_work_order_count` and
    recomputes `congested`."

    Design: Difficulty/compensating_invariant/department_backlog_conserved_across_complete_then_reopen
    """
    env = fx.setup_resolved_request(backlog_threshold=5)
    dept_id = env["dept"]["id"]
    citizen_id = env["citizen"]["id"]
    fx.api_client.reopen_service_request(env["request"]["id"], fx.make_citizen_headers(citizen_id))
    after = fx.get_department(dept_id)
    assert after["open_work_order_count"] == 1
    assert after["congested"] is False


def test_backlog_decrements_then_increments_back_to_one(api):
    """PRD §3.4: "On completion the system records the `completion_note`, decrements
    the department's `open_work_order_count` and recomputes `congested`."
    PRD §3.5: "the first leg raises the department's `open_work_order_count` and
    recomputes `congested`."

    Design: Difficulty/compensating_invariant/department_backlog_conserved_across_complete_then_reopen
    """
    env = fx.setup_resolved_request(backlog_threshold=5)
    dept_id = env["dept"]["id"]
    # complete already decremented 1 -> 0
    assert fx.get_department(dept_id)["open_work_order_count"] == 0
    citizen_id = env["citizen"]["id"]
    fx.api_client.reopen_service_request(env["request"]["id"], fx.make_citizen_headers(citizen_id))
    assert fx.get_department(dept_id)["open_work_order_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — Difficulty: open-escalation count conserved (breach then resolve)
# ---------------------------------------------------------------------------
def test_open_escalation_count_returns_to_zero_after_resolve(api):
    """PRD §3.4: "and resolves any still-open escalation on the request as a
    compensating side effect (each such `Escalation` moves `OPEN → RESOLVED` with
    `resolved_by_role` recorded as the system)."
    PRD §3.9: "if the overdue hours are at least `escalation_tier1_hours` and the
    request has no open escalation at all, it creates a `TIER1` escalation with a
    similar reason."

    Design: Difficulty/compensating_invariant/open_escalation_count_conserved_across_breach_then_resolve
    """
    env = fx.setup_started_request()
    fx.advance_clock(27)  # overdue 3h -> one OPEN TIER1 escalation
    open_before = [e for e in fx.get_escalations_for_request(env["request"]["id"])
                   if e["status"] == "OPEN"]
    assert len(open_before) == 1
    agent_id = env["agent"]["id"]
    validate_success(
        api.complete_work_order(
            env["work_order"]["id"], {"completion_note": "fixed"}, make_agent_headers(agent_id)
        ),
        200,
    )
    open_after = [e for e in fx.get_escalations_for_request(env["request"]["id"])
                  if e["status"] == "OPEN"]
    assert len(open_after) == 0


def test_resolved_request_after_breach_resolve_is_resolved(api):
    """PRD §3.4: "and bubbles up to the request, which advances
    `IN_PROGRESS → RESOLVED`."

    Design: Difficulty/compensating_invariant/open_escalation_count_conserved_across_breach_then_resolve
    """
    env = fx.setup_started_request()
    fx.advance_clock(27)
    agent_id = env["agent"]["id"]
    validate_success(
        api.complete_work_order(
            env["work_order"]["id"], {"completion_note": "fixed"}, make_agent_headers(agent_id)
        ),
        200,
    )
    request = fx.get_request(env["request"]["id"])
    assert request["status"] == "RESOLVED"
    escalations = fx.get_escalations_for_request(env["request"]["id"])
    assert all(e["status"] == "RESOLVED" for e in escalations)


# ---------------------------------------------------------------------------
# Queue B — Corner: cancel OPEN work order decrements backlog
# ---------------------------------------------------------------------------
def test_cancel_open_work_order_decrements_backlog(api):
    """PRD §3.4: "A dispatcher may cancel an `OPEN` work order, moving it
    `OPEN → CANCELLED`, when the underlying request is being marked a duplicate or
    otherwise withdrawn. Cancellation decrements the department's
    `open_work_order_count` and recomputes `congested`."

    Design: Corner/endpoints/cancel_open_work_order_decrements_backlog
    """
    env = fx.setup_routed_request()
    wo_id = env["work_order"]["id"]
    data = validate_success(api.cancel_work_order(wo_id, DISPATCHER), 200)
    assert data["status"] == "CANCELLED"
    dept = fx.get_department(env["dept"]["id"])
    assert dept["open_work_order_count"] == 0


# ---------------------------------------------------------------------------
# Queue B — Corner: inclusive congestion threshold
# ---------------------------------------------------------------------------
def test_department_congested_at_threshold_inclusive(api):
    """PRD §2.10: "A department is `congested` exactly when its `open_work_order_count`
    is greater than or equal to its `backlog_threshold` (an inclusive comparison)."

    Design: Corner/calculations/department_congested_at_threshold_inclusive
    """
    env = fx.setup_routed_request(backlog_threshold=1)
    dept = fx.get_department(env["dept"]["id"])
    assert dept["open_work_order_count"] == 1
    assert dept["congested"] is True
