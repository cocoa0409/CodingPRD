"""Ticket resolve / reopen / close lifecycle and SLA-status boundary reads."""
from test_helpers import validate_success, validate_error
from test_helpers.constants import CLOCK_DEFAULT
from test_helpers.fixtures import (
    set_clock, new_intersection, new_device, new_crew, new_ticket, new_work_order,
    triage, schedule_work_order, dispatch_work_order, complete_work_order,
    setup_resolved_ticket, get_ticket,
)


# ── Difficulty: RESOLVED -> TRIAGED reopen cycle ──────────────────────────────
def test_reopen_returns_ticket_to_triaged(api, dispatcher_headers):
    """PRD §3.3: "A resolved ticket can be reopened by a dispatcher, which returns
    it from `RESOLVED` back to `TRIAGED` and re-enters the active pipeline."

    Design: Difficulty/non_linear_state_machine/ticket_resolved_to_triaged_reopen_cycle
    """
    ctx = setup_resolved_ticket()
    assert ctx["ticket"]["status"] == "RESOLVED"
    res = api.reopen_ticket(ctx["ticket"]["id"], dispatcher_headers)
    reopened = validate_success(res, 200)
    assert reopened["status"] == "TRIAGED", f"expected TRIAGED, got {reopened['status']}"


def test_reopen_increments_count_and_clears_resolved_at(api, dispatcher_headers):
    """PRD §3.3: "A successful reopen increments `reopen_count` by one and clears
    `resolved_at`."

    Design: Difficulty/non_linear_state_machine/ticket_resolved_to_triaged_reopen_cycle
    """
    ctx = setup_resolved_ticket()
    res = api.reopen_ticket(ctx["ticket"]["id"], dispatcher_headers)
    reopened = validate_success(res, 200)
    assert reopened["reopen_count"] == 1, f"expected reopen_count 1, got {reopened['reopen_count']}"
    assert reopened["resolved_at"] is None, f"expected resolved_at cleared, got {reopened['resolved_at']}"


# ── Difficulty: SLA breach at exact response_due (inclusive boundary) ──────────
def test_sla_response_breached_at_exact_due(api, dispatcher_headers):
    """PRD §3.2: "Once triaged, if the ticket is not yet resolved or closed it is
    `BREACHED` when the logical clock has reached or passed `response_due` — the
    boundary is inclusive, so at exactly `response_due` the ticket is already
    `BREACHED` — and `ON_TRACK` otherwise."

    Design: Difficulty/boundary_precision_check/sla_response_breached_at_exact_due
    """
    set_clock("2026-03-01T00:00:00Z")
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_CONTROLLER",
                        criticality="CRITICAL", model="C3", replacement_cost=5000.00)
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=4,
                        description="signal conflict", hazard_flag=True)
    triage(ticket["id"])
    set_clock("2026-03-01T01:00:00Z")  # exactly response_due for a P1 (60-minute SLA)
    fetched = get_ticket(ticket["id"])
    assert fetched["sla_response_status"] == "BREACHED", \
        f"expected BREACHED at exact due, got {fetched['sla_response_status']}"


def test_sla_p1_response_due_is_sixty_minutes_after_triage(api, dispatcher_headers):
    """PRD §3.2: "Response deadlines are 60 minutes for `P1`, 240 minutes for `P2`,
    1440 minutes for `P3`, and 4320 minutes for `P4`; resolution deadlines are 240
    minutes for `P1`, 1440 minutes for `P2`, 4320 minutes for `P3`, and 10080
    minutes for `P4`. `response_due` is `triaged_at` plus the band's response
    minutes and `resolution_due` is `triaged_at` plus the band's resolution
    minutes."

    Design: Difficulty/boundary_precision_check/sla_response_breached_at_exact_due
    """
    set_clock("2026-03-01T00:00:00Z")
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_CONTROLLER",
                        criticality="CRITICAL", model="C3", replacement_cost=5000.00)
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=4,
                        description="signal conflict", hazard_flag=True)
    triaged = triage(ticket["id"])
    assert triaged["priority_band"] == "P1"
    assert triaged["response_due"].startswith("2026-03-01T01:00:00"), \
        f"expected response_due at 01:00, got {triaged['response_due']}"


def test_sla_on_track_one_minute_before_due(api, dispatcher_headers):
    """PRD §3.2: "Once triaged, if the ticket is not yet resolved or closed it is
    `BREACHED` when the logical clock has reached or passed `response_due` — the
    boundary is inclusive, so at exactly `response_due` the ticket is already
    `BREACHED` — and `ON_TRACK` otherwise."

    Design: Corner/calculations/sla_on_track_one_minute_before_due
    """
    set_clock("2026-03-01T00:00:00Z")
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_CONTROLLER",
                        criticality="CRITICAL", model="C9", replacement_cost=5000.00)
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=4,
                        description="x", hazard_flag=True)
    triage(ticket["id"])
    set_clock("2026-03-01T00:59:00Z")  # one minute before the P1 response_due
    fetched = get_ticket(ticket["id"])
    assert fetched["sla_response_status"] == "ON_TRACK", \
        f"expected ON_TRACK before due, got {fetched['sla_response_status']}"


# ── Corner: resolve from wrong state ─────────────────────────────────────────
def test_resolve_from_open_invalid_state(api, dispatcher_headers):
    """PRD §3.3: "Once repair work has landed, a dispatcher resolves the ticket,
    moving it from `IN_PROGRESS` to `RESOLVED`."
    PRD §2.9: "State — the target resource is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/resolve_from_open_invalid_state
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=3, description="x")
    res = api.resolve_ticket(ticket["id"], dispatcher_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    fetched = get_ticket(ticket["id"])
    assert fetched["status"] == "OPEN"


# ── Corner: reopen after window expired ──────────────────────────────────────
def test_reopen_after_window_expired(api, dispatcher_headers):
    """PRD §3.3: "Reopening is allowed only while the logical clock is within 72
    hours of `resolved_at`; once more than 72 hours have elapsed the reopen is
    rejected with `ERR_REOPEN_WINDOW_EXPIRED`."

    Design: Corner/validations/reopen_after_window_expired
    """
    ctx = setup_resolved_ticket(clock="2026-03-01T00:00:00Z")
    set_clock("2026-03-04T01:00:00Z")  # 73 hours after resolved_at
    res = api.reopen_ticket(ctx["ticket"]["id"], dispatcher_headers)
    validate_error(res, "ERR_REOPEN_WINDOW_EXPIRED", expected_status=409)
    fetched = get_ticket(ctx["ticket"]["id"])
    assert fetched["status"] == "RESOLVED"


# ── Corner: close blocked by open work ───────────────────────────────────────
def test_ticket_close_blocked_by_open_work(api, dispatcher_headers):
    """PRD §3.3: "Alternatively a resolved ticket is closed, moving it from
    `RESOLVED` to the terminal `CLOSED` state, but only when no work order linked
    to it by `ticket_id` is still in `DRAFT`, `SCHEDULED`, or `DISPATCHED`; an
    attempt to close while such open work remains is rejected with
    `ERR_TICKET_HAS_OPEN_WORK`."

    Design: Corner/validations/ticket_close_blocked_by_open_work
    """
    ctx = setup_resolved_ticket()
    # A second DRAFT work order linked to the same ticket keeps close blocked.
    new_work_order(ctx["device"]["id"], work_type="PM_LAMP",
                   estimated_labor_hours=1.0, ticket_id=ctx["ticket"]["id"])
    res = api.close_ticket(ctx["ticket"]["id"], dispatcher_headers)
    validate_error(res, "ERR_TICKET_HAS_OPEN_WORK", expected_status=409)
    fetched = get_ticket(ctx["ticket"]["id"])
    assert fetched["status"] == "RESOLVED"
