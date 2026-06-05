"""Corner queue B — state_machines section: invalid transitions, terminal-state
lockdown, and side-effect execution (known-error promotion, deflection,
response/resolve breach evaluation).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    fixtures as fx,
    factories as F,
    test_users as U,
    ApiErrorId,
)


# ===========================================================================
# Corner/state_machines/start_ticket_from_new_returns_invalid_state
# ===========================================================================
def test_start_new_ticket_invalid_state():
    """PRD §3.4: "Starting work against a ticket not in ASSIGNED, or one whose
    assignee_user_id is still null, is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/start_ticket_from_new_returns_invalid_state
    """
    _, _, category = fx.setup_catalog(default_priority="P3")
    ticket = fx.open_ticket(category["id"], requester_id="req-c5")
    resp = api_client.start_ticket(ticket["id"], U.agent("agent-c"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ===========================================================================
# Corner/state_machines/cancel_resolved_ticket_returns_invalid_state
# ===========================================================================
def test_cancel_resolved_ticket_invalid_state():
    """PRD §3.6: "A NEW ticket that the requester no longer needs can instead be
    cancelled by its own requester — X-User-ID matching requester_id — moving
    lifecycle_state from NEW to CANCELLED and recomputing the owning group's
    queue_depth downward."

    Design: Corner/state_machines/cancel_resolved_ticket_returns_invalid_state
    """
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-c6", agent_id="agent-c6"
    )
    resp = api_client.cancel_ticket(ticket["id"], U.requester("req-c6"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ===========================================================================
# Corner/state_machines/implement_change_from_pending_cab_returns_invalid_state
# ===========================================================================
def test_implement_change_from_pending_cab_invalid_state():
    """PRD §3.5: "A change can only be implemented or failed from the APPROVED
    state; any other starting state yields ERR_INVALID_STATE."

    Design: Corner/state_machines/implement_change_from_pending_cab_returns_invalid_state
    """
    _, _, _, _, change = fx.setup_submitted_change(risk="MEDIUM", default_priority="P2",
                                                   manager_id="cm-c7")
    resp = api_client.implement_change(change["id"], U.change_manager("cm-c7"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ===========================================================================
# Corner/state_machines/retire_already_retired_asset_terminal_lockdown
# ===========================================================================
def test_retire_already_retired_asset_invalid_state():
    """PRD §3.8: "An asset may be retired by a PlatformAdmin only from OPERATIONAL
    and only when its open_incident_count is zero ... moving status to the
    terminal RETIRED only when the count is clear."

    Design: Corner/state_machines/retire_already_retired_asset_terminal_lockdown
    """
    asset = fx.create_asset(asset_tag="RET-1", kind="NETWORK_DEVICE")
    validate_success(api_client.retire_asset(asset["id"], U.platform_admin()))
    resp = api_client.retire_asset(asset["id"], U.platform_admin())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ===========================================================================
# Corner/state_machines/known_errors_promotion_published_true_side_effect
# ===========================================================================
def test_known_error_promotion_publishes_and_advances_problem():
    """PRD §3.8: "Promoting to a known error creates a KnownError record —
    carrying the problem_id, a symptom, and a workaround, with published set to
    true so it can feed deflection — and moves the problem from
    ROOT_CAUSE_IDENTIFIED to KNOWN_ERROR."

    Design: Corner/state_machines/known_errors_promotion_published_true_side_effect
    """
    problem = fx.create_problem(owner_id="agent-c8")
    validate_success(
        api_client.identify_root_cause(problem["id"], {}, U.agent("agent-c8"))
    )
    ke = validate_success(
        api_client.create_known_error(
            problem["id"],
            {"symptom": "blue screen", "workaround": "rollback driver"},
            U.agent("agent-c8"),
        ),
        expected_status=201,
    )
    assert ke["published"] is True

    prob_after = validate_success(api_client.get_problem(problem["id"], U.agent("agent-c8")))
    assert prob_after["state"] == "KNOWN_ERROR"

    listing = validate_success(api_client.list_known_errors(problem["id"], U.agent("agent-c8")))
    ids = [k["id"] for k in listing]
    assert ke["id"] in ids


# ===========================================================================
# Corner/state_machines/deflection_at_open_cancels_ticket_and_bumps_counts
# ===========================================================================
def test_deflection_at_open_cancels_ticket_and_bumps_article_counts():
    """PRD §3.2: "When the open call carries accept_deflection set to true
    together with a valid kb_article_id, the ticket is opened and then immediately
    auto-cancelled: its lifecycle_state becomes CANCELLED, its deflected flag is
    set to true, and the referenced article's deflection_count and view_count are
    each incremented."

    Design: Corner/state_machines/deflection_at_open_cancels_ticket_and_bumps_counts
    """
    _, _, category = fx.setup_catalog(default_priority="P3")
    kb = validate_success(
        api_client.create_kb_article(
            {"title": "Reset password", "category_id": category["id"], "body": "Use the portal."},
            U.agent("agent-c9"),
        ),
        expected_status=201,
    )
    data = validate_success(
        api_client.create_ticket(
            {
                "short_description": "Forgot password",
                "category_id": category["id"],
                "kb_article_id": kb["id"],
                "accept_deflection": True,
            },
            U.requester("req-c9"),
        ),
        expected_status=201,
    )
    assert data["lifecycle_state"] == "CANCELLED"
    assert data["deflected"] is True

    kb_after = validate_success(api_client.get_kb_article(kb["id"], U.agent("agent-c9")))
    assert kb_after["deflection_count"] == 1
    assert kb_after["view_count"] == 1


# ===========================================================================
# Corner/state_machines/response_sla_breach_on_late_start
# ===========================================================================
def test_late_start_marks_response_breached():
    """PRD §3.4: "if the current clock is at or before the recorded
    response_due_at, the response target is met; if the current clock is strictly
    past it, the ticket's sla_state becomes RESPONSE_BREACHED."

    Design: Corner/state_machines/response_sla_breach_on_late_start
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, category = fx.setup_catalog(default_priority="P3")
    ticket = fx.open_ticket(category["id"], requester_id="req-c10")
    tid = ticket["id"]
    validate_success(
        api_client.assign_ticket(tid, {"assignee_user_id": "agent-c10"}, U.agent("agent-c10"))
    )
    fx.advance_clock(65)  # P3 response_due = +60; now +65, strictly past
    started = validate_success(api_client.start_ticket(tid, U.agent("agent-c10")))
    assert started["sla_state"] == "RESPONSE_BREACHED"
    assert started["lifecycle_state"] == "IN_PROGRESS"


# ===========================================================================
# Corner/state_machines/resolve_sla_breach_one_minute_past_due
# ===========================================================================
def test_resolve_one_minute_past_due_marks_resolve_breached():
    """PRD §3.6: "if the current clock is at or before resolve_due_at the
    sla_state becomes MET, and if it is strictly past it the sla_state becomes
    RESOLVE_BREACHED."

    Design: Corner/state_machines/resolve_sla_breach_one_minute_past_due
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_in_progress_ticket(
        default_priority="P3", requester_id="req-c11", agent_id="agent-c11"
    )
    fx.advance_clock(241)  # P3 resolve_due = +240; now +241, strictly past
    resolved = validate_success(api_client.resolve_ticket(ticket["id"], U.agent("agent-c11")))
    assert resolved["sla_state"] == "RESOLVE_BREACHED"
    assert resolved["lifecycle_state"] == "RESOLVED"
