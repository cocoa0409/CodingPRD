"""Ticket state machine, dispatch execution, and the dispatch-complete
depth-2 cascade to Contract.period_ticket_minutes."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_technician_headers,
    set_clock,
    create_client,
    create_contract,
    activate_contract,
    create_technician,
    create_ticket,
    assign_ticket,
    create_dispatch,
    complete_dispatch,
    arrive_dispatch,
    resolve_ticket,
    reopen_ticket,
    setup_active_contract,
    setup_active_contract_with_tech,
    setup_ticket_in_progress,
    setup_remote_dispatch_scheduled,
)


SM = "service_manager_headers"


# ---------------------------------------------------------------------------
# Queue B: state_machines / ticket_assign_second_time_returns_invalid_state
# ---------------------------------------------------------------------------

def test_assigning_already_in_progress_ticket_returns_invalid_state(api):
    """PRD §3.5: "A `Dispatcher` assigns a `NEW` ticket to a technician by
    naming the `technician_id`; assigning a ticket that is not `NEW` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/ticket_assign_second_time_returns_invalid_state
    """
    client, contract, tech, ticket = setup_ticket_in_progress()
    # Second assign on the IN_PROGRESS ticket.
    resp = api.assign_ticket(
        ticket["id"], {"technician_id": tech["id"]},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Queue B: state_machines / remote_dispatch_arrive_returns_invalid_state
# ---------------------------------------------------------------------------

def test_arrive_on_remote_dispatch_returns_invalid_state(api):
    """PRD §3.6: "An `ONSITE` dispatch is marked arrived first — that transition
    requires the dispatch to be `SCHEDULED` and its `mode` to be `ONSITE` (a
    `REMOTE` dispatch never enters the arrived state, and either violation is
    rejected with `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/remote_dispatch_arrive_returns_invalid_state
    """
    client, contract, tech, ticket = setup_ticket_in_progress()
    dispatch = create_dispatch(
        ticket["id"], tech["id"], mode="REMOTE",
        scheduled_start="2026-05-01T02:00:00Z",
        scheduled_end="2026-05-01T03:00:00Z",
    )
    resp = api.arrive_dispatch(dispatch["id"], make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / ticket_cyclic_resolve_reopen_resolve
# ---------------------------------------------------------------------------

def test_ticket_first_resolve_moves_to_resolved(api):
    """PRD §3.5: "On resolve the ticket moves `IN_PROGRESS` → `RESOLVED`,
    `resolved_at` is stamped from the clock, and the ticket's `billable_minutes`
    is finalized."

    Design: Difficulty/non_linear_state_machine/ticket_cyclic_resolve_reopen_resolve
    """
    _, _, _, ticket = setup_ticket_in_progress()
    resolved = resolve_ticket(ticket["id"])
    assert resolved["status"] == "RESOLVED"


def test_ticket_reopen_then_resolve_reaches_resolved_twice(api):
    """PRD §3.5: "A `Dispatcher` or `ClientContact` may reopen a `RESOLVED`
    ticket; reopening one that is not `RESOLVED` is rejected with
    `ERR_INVALID_STATE`. The ticket moves `RESOLVED` → `IN_PROGRESS`, its
    `resolved_at` returns to null"

    Design: Difficulty/non_linear_state_machine/ticket_cyclic_resolve_reopen_resolve
    """
    _, _, _, ticket = setup_ticket_in_progress()
    resolve_ticket(ticket["id"])
    reopened = reopen_ticket(ticket["id"])
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["resolved_at"] is None
    # Cycle: resolve again.
    resolved2 = resolve_ticket(ticket["id"])
    assert resolved2["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / dispatch_complete_depth2_ticket_contract_accrual
# ---------------------------------------------------------------------------

def test_dispatch_complete_cascades_ticket_to_resolved(api):
    """PRD §3.6: "If the dispatch's `resolves_ticket` flag is set, completing
    it also resolves the parent ticket, moving it `IN_PROGRESS` → `RESOLVED`
    and running the same resolve side effects — stamping `resolved_at` and
    accruing the ticket's `billable_minutes` into the contract's
    `period_ticket_minutes`."

    Design: Difficulty/transitive_cascade/dispatch_complete_depth2_ticket_contract_accrual
    """
    client, contract, tech, ticket, dispatch = setup_remote_dispatch_scheduled(
        priority="P2",
    )
    completed = complete_dispatch(dispatch["id"], tech["id"], logged_minutes=90)
    assert completed["status"] == "COMPLETED"
    ticket_after = validate_success(api.get_ticket(ticket["id"], TEST_USERS[SM]))
    assert ticket_after["status"] == "RESOLVED"


def test_dispatch_complete_accrues_billable_minutes_into_contract(api):
    """PRD §3.5: "That finalized labor is then added to the governing contract's
    `period_ticket_minutes`."
    PRD §3.5: "Once at least one dispatch on the ticket has completed, the
    value instead becomes the sum of `logged_minutes` across all of that
    ticket's completed dispatches."

    Design: Difficulty/transitive_cascade/dispatch_complete_depth2_ticket_contract_accrual
    """
    client, contract, tech, ticket, dispatch = setup_remote_dispatch_scheduled(
        priority="P2",
    )
    complete_dispatch(dispatch["id"], tech["id"], logged_minutes=90)
    contract_after = validate_success(api.get_contract(contract["id"], TEST_USERS[SM]))
    assert contract_after["period_ticket_minutes"] == 90


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / ticket_labor_estimated_vs_actual
# ---------------------------------------------------------------------------

def test_ticket_billable_minutes_estimated_from_priority_before_dispatch(api):
    """PRD §3.5: "If no dispatch on the ticket has reached `COMPLETED`, the
    value is the priority standard — 240 minutes for `P1`, 120 for `P2`, 60
    for `P3`, and 30 for `P4`."

    Design: Difficulty/dual_variant_calc/ticket_labor_estimated_vs_actual
    """
    client, contract, tech, ticket = setup_ticket_in_progress(priority="P2")
    fetched = validate_success(api.get_ticket(ticket["id"], TEST_USERS[SM]))
    assert fetched["billable_minutes"] == 120


def test_ticket_billable_minutes_actual_after_dispatch_completes(api):
    """PRD §3.5: "Once at least one dispatch on the ticket has completed, the
    value instead becomes the sum of `logged_minutes` across all of that
    ticket's completed dispatches."

    Design: Difficulty/dual_variant_calc/ticket_labor_estimated_vs_actual
    """
    client, contract, tech, ticket = setup_ticket_in_progress(priority="P2")
    dispatch = create_dispatch(
        ticket["id"], tech["id"], mode="REMOTE",
        scheduled_start="2026-05-01T02:00:00Z",
        scheduled_end="2026-05-01T03:00:00Z",
        resolves_ticket=False,
    )
    complete_dispatch(dispatch["id"], tech["id"], logged_minutes=200)
    fetched = validate_success(api.get_ticket(ticket["id"], TEST_USERS[SM]))
    assert fetched["billable_minutes"] == 200
