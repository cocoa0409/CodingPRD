"""Validation ordering conflicts and cross-entity referential gating.

Difficulty queue A: priority_pair_validation_conflict, cross_entity_state_dependency.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    fixtures as fx,
    test_users as U,
    ApiErrorId,
)
from test_helpers.constants import MISSING_UUID


# ===========================================================================
# priority_pair_validation_conflict /
#   resolve_change_gating_beats_invalid_state_referential_vs_state
# ===========================================================================
def test_resolve_on_pending_change_ticket_reports_invalid_state_not_gating():
    """PRD §3.10: "Lifecycle-state legality is checked next, yielding
    ERR_INVALID_STATE, and then — on the two OCC-guarded writes — the version
    check ... Referential business rules come next — change-gated resolution
    (ERR_CHANGE_GATING_RESOLUTION) ..."
    PRD §3.6: "Resolving a ticket is an agent action available from IN_PROGRESS."

    Design: Difficulty/priority_pair_validation_conflict/resolve_change_gating_beats_invalid_state_referential_vs_state
    """
    _, _, _, ticket, _ = fx.setup_ticket_pending_change(
        risk="LOW", default_priority="P2", manager_id="cm-4",
        agent_id="agent-8", requester_id="req-8",
    )
    # Ticket is PENDING_CHANGE (not IN_PROGRESS) and change_request_id is set:
    # both the state precondition and the gating rule fail; state (pri 5) wins.
    resp = api_client.resolve_ticket(ticket["id"], U.agent("agent-8"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_resolve_on_pending_change_state_check_precedes_gating_check():
    """PRD §3.10: "When several checks could fire on one request, they are
    evaluated in a fixed priority order so the most fundamental failure is the one
    reported."
    PRD §3.6: "The platform refuses to resolve while a non-terminal change still
    gates the ticket — that is, while change_request_id is not null — rejecting
    the attempt with ERR_CHANGE_GATING_RESOLUTION."

    Design: Difficulty/priority_pair_validation_conflict/resolve_change_gating_beats_invalid_state_referential_vs_state
    """
    _, _, _, ticket, _ = fx.setup_ticket_pending_change(
        risk="LOW", default_priority="P2", manager_id="cm-4b",
        agent_id="agent-8b", requester_id="req-8b",
    )
    resp = api_client.resolve_ticket(ticket["id"], U.agent("agent-8b"))
    # State precondition (IN_PROGRESS required, priority 5) is reported, not the
    # gating referential rule (priority 9).
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ===========================================================================
# priority_pair_validation_conflict /
#   retire_asset_existence_beats_open_incidents_existence_vs_referential
# ===========================================================================
def test_retire_nonexistent_asset_reports_not_found_not_referential():
    """PRD §3.10: "Then path existence is checked left to right, yielding
    ERR_NOT_FOUND for a missing path target, followed by body foreign-key
    existence ... Referential business rules come next — ... then an asset with
    open incidents (ERR_ASSET_HAS_OPEN_INCIDENTS)."

    Design: Difficulty/priority_pair_validation_conflict/retire_asset_existence_beats_open_incidents_existence_vs_referential
    """
    # A real asset exists, but we retire a different, non-existent id.
    fx.create_asset(asset_tag="REAL-1", kind="LAPTOP")
    resp = api_client.retire_asset(MISSING_UUID, U.platform_admin())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_retire_missing_asset_path_existence_wins_over_open_incidents():
    """PRD §2.5: "The same ERR_NOT_FOUND governs any /{id} path whose target does
    not exist."
    PRD §3.8: "An asset may be retired by a PlatformAdmin only from OPERATIONAL
    and only when its open_incident_count is zero; a retire attempted while
    incidents remain open is rejected with ERR_ASSET_HAS_OPEN_INCIDENTS."

    Design: Difficulty/priority_pair_validation_conflict/retire_asset_existence_beats_open_incidents_existence_vs_referential
    """
    resp = api_client.retire_asset(MISSING_UUID, U.platform_admin())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


# ===========================================================================
# cross_entity_state_dependency /
#   ticket_resolve_blocked_by_open_change_ticket_to_changerequest
# ===========================================================================
def test_resolve_succeeds_once_change_cleared_gate_lifted():
    """PRD §3.5: "Whenever a vote drives the change to either APPROVED or
    REJECTED, a cascade bubbles up to the gated ticket: the linked ticket ...
    moves from PENDING_CHANGE back to IN_PROGRESS ... and the ticket's
    change_request_id is cleared to null."
    PRD §3.6: "The platform refuses to resolve while a non-terminal change still
    gates the ticket — that is, while change_request_id is not null — rejecting
    the attempt with ERR_CHANGE_GATING_RESOLUTION."

    Design: Difficulty/cross_entity_state_dependency/ticket_resolve_blocked_by_open_change_ticket_to_changerequest
    """
    _, _, _, ticket, change = fx.setup_ticket_pending_change(
        risk="LOW", default_priority="P2", manager_id="cm-5",
        agent_id="agent-10", requester_id="req-10",
    )
    tid = ticket["id"]
    # Approve clears the gate (change_request_id -> null, ticket -> IN_PROGRESS).
    validate_success(
        api_client.cast_vote(
            change["id"],
            {"decision": "APPROVE", "expected_change_request_version": change["version"]},
            U.cab_member("cab-5"),
        ),
        expected_status=201,
    )
    pre = validate_success(api_client.get_ticket(tid, U.agent("agent-10")))
    assert pre["change_request_id"] is None

    resolved = validate_success(api_client.resolve_ticket(tid, U.agent("agent-10")))
    assert resolved["lifecycle_state"] == "RESOLVED"
    assert resolved["change_request_id"] is None


def test_cleared_change_request_id_permits_resolution():
    """PRD §3.6: "The platform refuses to resolve while a non-terminal change
    still gates the ticket — that is, while change_request_id is not null —
    rejecting the attempt with ERR_CHANGE_GATING_RESOLUTION."

    Design: Difficulty/cross_entity_state_dependency/ticket_resolve_blocked_by_open_change_ticket_to_changerequest
    """
    _, _, _, ticket, change = fx.setup_ticket_pending_change(
        risk="LOW", default_priority="P2", manager_id="cm-5b",
        agent_id="agent-10b", requester_id="req-10b",
    )
    tid = ticket["id"]
    validate_success(
        api_client.cast_vote(
            change["id"],
            {"decision": "APPROVE", "expected_change_request_version": change["version"]},
            U.cab_member("cab-5b"),
        ),
        expected_status=201,
    )
    resolved = validate_success(api_client.resolve_ticket(tid, U.agent("agent-10b")))
    assert resolved["lifecycle_state"] == "RESOLVED"


# ===========================================================================
# cross_entity_state_dependency /
#   problem_resolve_blocked_by_linked_tickets_problem_to_ticket
# ===========================================================================
def test_problem_resolve_blocked_while_linked_ticket_open():
    """PRD §3.8: "resolving a problem moves it from KNOWN_ERROR to RESOLVED, but
    only once its linked_ticket_count has fallen to zero; an attempt while symptom
    tickets remain open is rejected with ERR_PROBLEM_HAS_OPEN_TICKETS."

    Design: Difficulty/cross_entity_state_dependency/problem_resolve_blocked_by_linked_tickets_problem_to_ticket
    """
    _, _, _, ticket, problem = fx.setup_known_error_with_linked_ticket(
        owner_id="agent-11", requester_id="req-11"
    )
    assert problem["state"] == "KNOWN_ERROR"
    assert problem["linked_ticket_count"] == 1

    resp = api_client.resolve_problem(problem["id"], U.agent("agent-11"))
    validate_error(resp, ApiErrorId.ERR_PROBLEM_HAS_OPEN_TICKETS.value, expected_status=409)


def test_problem_with_open_ticket_reports_open_tickets_error():
    """PRD §3.8: "an attempt while symptom tickets remain open is rejected with
    ERR_PROBLEM_HAS_OPEN_TICKETS, and one from the wrong state with
    ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/problem_resolve_blocked_by_linked_tickets_problem_to_ticket
    """
    _, _, _, ticket, problem = fx.setup_known_error_with_linked_ticket(
        owner_id="agent-11b", requester_id="req-11b"
    )
    resp = api_client.resolve_problem(problem["id"], U.agent("agent-11b"))
    validate_error(resp, ApiErrorId.ERR_PROBLEM_HAS_OPEN_TICKETS.value, expected_status=409)
    after = validate_success(api_client.get_problem(problem["id"], U.agent("agent-11b")))
    assert after["linked_ticket_count"] == 1
