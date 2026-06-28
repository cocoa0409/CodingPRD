"""Service-ticket lifecycle: reopen cycle, ownership gate, and invalid transitions.

Covers the queue-A difficulty instance (non_linear_state_machine reopen cycle) and queue-B
corner instances from the state_machines section (cancel-from-resolved, resolve-without-ack,
resolve-by-non-owner).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TECH_T1, TECH_T2,
    make_field_tech_headers,
    provision_network, open_ticket, acknowledge_ticket_as, resolve_ticket_as,
    setup_resolved_ticket, read_atm,
)

T1 = make_field_tech_headers(TECH_T1)
T2 = make_field_tech_headers(TECH_T2)


# ============================================================================
# non_linear_state_machine — reopen cycle (queue A)
# ============================================================================

def test_service_ticket_reopen_cycle(api):
    """PRD §3.8: "Because tickets are cyclic, a `RESOLVED` ticket can be **reopened** back to
    `OPEN`, which increments its `reopen_count` by one and re-faults the machine — to `FAULTED` for
    a minor ticket or `OUT_OF_SERVICE` for a major one."

    Design: Difficulty/non_linear_state_machine/service_ticket_reopen_cycle
    """
    atm_id = provision_network(jurisdiction_code="TX")["atm"]["id"]
    atm_id, ticket = setup_resolved_ticket(atm_id=atm_id, fault_kind="CASH_JAM",
                                           severity="MINOR", tech_id=TECH_T1)
    resp = api.reopen_ticket(ticket["id"], headers=T1)
    reopened = validate_success(resp)
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    atm = read_atm(atm_id)
    assert atm["operational_status"] == "FAULTED"  # re-faulted by reopen (MINOR)


# ============================================================================
# state_machines section — invalid transitions / ownership (queue B)
# ============================================================================

def test_cancel_ticket_from_resolved_returns_invalid_state(api):
    """PRD §3.8: "A ticket that is `OPEN` or `ACKNOWLEDGED` can instead be **cancelled** to its
    terminal `CANCELLED` status"
    PRD §2.6: "Among those, any attempt to drive an entity through a transition that is not
    defined from its current state — settling a run that is already `SETTLED`, acknowledging a
    ticket that is not `OPEN`, approving a disclosure that is not `DRAFT`, and the like — is
    rejected with `ERR_INVALID_STATE`, the generic guard that backs every state machine
    described below."

    Design: Corner/state_machines/cancel_ticket_from_resolved_returns_invalid_state
    """
    atm_id = provision_network(jurisdiction_code="CA")["atm"]["id"]
    atm_id, ticket = setup_resolved_ticket(atm_id=atm_id, fault_kind="NETWORK",
                                           severity="MINOR", tech_id=TECH_T1)
    # RESOLVED ticket cannot be cancelled.
    resp = api.cancel_ticket(ticket["id"], headers=T1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_resolve_open_ticket_skipping_acknowledge_returns_invalid_state(api):
    """PRD §3.8: "The same tech then **resolves** an `ACKNOWLEDGED` ticket, moving it to
    `RESOLVED`"
    PRD §2.6: "Among those, any attempt to drive an entity through a transition that is not
    defined from its current state — settling a run that is already `SETTLED`, acknowledging a
    ticket that is not `OPEN`, approving a disclosure that is not `DRAFT`, and the like — is
    rejected with `ERR_INVALID_STATE`, the generic guard that backs every state machine
    described below."

    Design: Corner/state_machines/resolve_open_ticket_skipping_acknowledge_returns_invalid_state
    """
    atm_id = provision_network(jurisdiction_code="CA")["atm"]["id"]
    ticket = open_ticket(atm_id, fault_kind="CARD_READER", severity="MINOR")  # OPEN, never acked
    resp = api.resolve_ticket(ticket["id"], headers=T1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_resolve_ticket_by_non_owner_returns_not_ticket_owner(api):
    """PRD §3.8: "resolution requires that the acting tech is the recorded `assigned_tech_id`, and
    an attempt by anyone else is rejected with `ERR_NOT_TICKET_OWNER`."

    Design: Corner/state_machines/resolve_ticket_by_non_owner_returns_not_ticket_owner
    """
    atm_id = provision_network(jurisdiction_code="CA")["atm"]["id"]
    ticket = open_ticket(atm_id, fault_kind="DISPENSER", severity="MINOR")
    acknowledge_ticket_as(ticket["id"], TECH_T1)  # assigned_tech_id := tech-T1
    # A different tech (tech-T2) attempts to resolve.
    resp = api.resolve_ticket(ticket["id"], headers=T2)
    validate_error(resp, ApiErrorId.ERR_NOT_TICKET_OWNER, expected_status=403)
