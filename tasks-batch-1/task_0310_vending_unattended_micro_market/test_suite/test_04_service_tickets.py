"""Service ticket lifecycle: the cyclic RESOLVED -> REOPENED -> IN_PROGRESS ->
RESOLVED loop that a linear pipeline cannot express.
"""
from test_helpers import validate_success, api_client
from test_helpers import set_clock, make_host, make_machine, make_ticket
from test_helpers.test_users import TEST_USERS

FIELD_OPS = TEST_USERS["field_ops_headers"]


def _resolved_jam_ticket():
    """Non-blocking JAM ticket started and resolved once. Returns (machine, ticket)."""
    set_clock("2026-06-09T00:00:00Z")
    host = make_host(name="Tk Host", contact_email="tk@x.com")
    machine = make_machine(host["id"], asset_tag="M-6", machine_type="SNACK_VENDOR")
    ticket = make_ticket(machine["id"], issue_type="JAM", blocking=False)
    validate_success(api_client.start_ticket(ticket["id"], FIELD_OPS), 200)
    resolved = validate_success(api_client.resolve_ticket(ticket["id"], FIELD_OPS), 200)
    assert resolved["status"] == "RESOLVED", resolved
    return machine, ticket


def test_reopen_moves_resolved_ticket_to_reopened():
    """PRD §3.8: "A FieldOps operator reopens a resolved ticket for a recurring
    fault, advancing it RESOLVED -> REOPENED; this requires the ticket to be
    RESOLVED, or it is rejected with ERR_TICKET_NOT_RESOLVED".

    Design: Difficulty/non_linear_state_machine/nlsm_service_ticket_resolved_reopen_cycle
    """
    machine, ticket = _resolved_jam_ticket()
    reopened = validate_success(api_client.reopen_ticket(ticket["id"], FIELD_OPS), 200)
    assert reopened["status"] == "REOPENED", reopened


def test_ticket_cycles_back_through_in_progress_to_resolved():
    """PRD §3.8: "The same start action also advances a reopened ticket REOPENED
    -> IN_PROGRESS; taken from the reopened path it requires the ticket to be
    REOPENED, or it is rejected with ERR_TICKET_NOT_REOPENED."
    PRD §3.8: "A FieldOps operator resolves an in-progress ticket, advancing it
    IN_PROGRESS -> RESOLVED; this requires the ticket to be IN_PROGRESS, or it is
    rejected with ERR_TICKET_NOT_IN_PROGRESS".

    Design: Difficulty/non_linear_state_machine/nlsm_service_ticket_resolved_reopen_cycle
    """
    machine, ticket = _resolved_jam_ticket()
    reopened = validate_success(api_client.reopen_ticket(ticket["id"], FIELD_OPS), 200)
    assert reopened["status"] == "REOPENED", reopened
    started = validate_success(api_client.start_ticket(ticket["id"], FIELD_OPS), 200)
    assert started["status"] == "IN_PROGRESS", started
    resolved_again = validate_success(api_client.resolve_ticket(ticket["id"], FIELD_OPS), 200)
    assert resolved_again["status"] == "RESOLVED", resolved_again
