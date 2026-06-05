"""CAB voting: optimistic approve-quorum vs pessimistic veto, the PENDING_CAB
fork to APPROVED/REJECTED, and the OCC version guard on votes.

Difficulty queue A: dual_variant_calc (cab tally), non_linear_state_machine
(CAB fork).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    fixtures as fx,
    test_users as U,
    ApiErrorId,
)


# ===========================================================================
# dual_variant_calc / cab_tally_optimistic_approve_vs_pessimistic_veto_on_change
# ===========================================================================
def test_medium_change_approves_only_when_second_distinct_approve_reaches_quorum():
    """PRD §3.5: "On an approve vote, approve quorum is checked first: if
    approve_count has reached required_approvals, the change moves from
    PENDING_CAB to APPROVED."
    PRD §3.5: "derives the required_approvals quorum from its risk — one approval
    for LOW, two for MEDIUM, three for HIGH."

    Design: Difficulty/dual_variant_calc/cab_tally_optimistic_approve_vs_pessimistic_veto_on_change
    """
    _, _, _, _, change = fx.setup_submitted_change(risk="MEDIUM", default_priority="P2")
    cr_id = change["id"]
    assert change["required_approvals"] == 2

    # First distinct APPROVE: not yet quorum 2 -> stays PENDING_CAB.
    validate_success(
        api_client.cast_vote(
            cr_id,
            {"decision": "APPROVE", "expected_change_request_version": change["version"]},
            U.cab_member("cab-1"),
        ),
        expected_status=201,
    )
    after1 = validate_success(api_client.get_change_request(cr_id, U.cab_member("cab-1")))
    assert after1["state"] == "PENDING_CAB"
    assert after1["approve_count"] == 1

    # Second distinct APPROVE reaches quorum -> APPROVED.
    validate_success(
        api_client.cast_vote(
            cr_id,
            {"decision": "APPROVE", "expected_change_request_version": after1["version"]},
            U.cab_member("cab-2"),
        ),
        expected_status=201,
    )
    after2 = validate_success(api_client.get_change_request(cr_id, U.cab_member("cab-2")))
    assert after2["state"] == "APPROVED"
    assert after2["approve_count"] == 2


def test_single_reject_vetoes_change_regardless_of_quorum():
    """PRD §3.5: "On a reject vote, the veto is checked: a single reject is enough
    — the veto threshold is one — so any reject moves the change from PENDING_CAB
    to REJECTED. The veto dominates once a reject is present."

    Design: Difficulty/dual_variant_calc/cab_tally_optimistic_approve_vs_pessimistic_veto_on_change
    """
    _, _, _, _, change = fx.setup_submitted_change(risk="MEDIUM", default_priority="P2")
    cr_id = change["id"]
    assert change["required_approvals"] == 2

    validate_success(
        api_client.cast_vote(
            cr_id,
            {"decision": "REJECT", "expected_change_request_version": change["version"]},
            U.cab_member("cab-veto"),
        ),
        expected_status=201,
    )
    after = validate_success(api_client.get_change_request(cr_id, U.cab_member("cab-veto")))
    assert after["state"] == "REJECTED", \
        "a single reject must veto even with quorum 2 and zero approvals"
    assert after["reject_count"] == 1


# ===========================================================================
# non_linear_state_machine / change_request_cab_fork_to_approved_or_rejected
# ===========================================================================
def test_cab_reject_branch_rejects_change_and_resumes_linked_ticket():
    """PRD §3.5: "On a reject vote, the veto is checked: a single reject is enough
    — the veto threshold is one — so any reject moves the change from PENDING_CAB
    to REJECTED."
    PRD §3.5: "Whenever a vote drives the change to either APPROVED or REJECTED, a
    cascade bubbles up to the gated ticket: the linked ticket (named by the
    change's ticket_id) moves from PENDING_CHANGE back to IN_PROGRESS ... and the
    ticket's change_request_id is cleared to null."

    Design: Difficulty/non_linear_state_machine/change_request_cab_fork_to_approved_or_rejected
    """
    _, _, _, ticket, change = fx.setup_ticket_pending_change(
        risk="LOW", default_priority="P2", manager_id="cm-2",
        agent_id="agent-5", requester_id="req-5",
    )
    cr_id = change["id"]
    tid = ticket["id"]

    validate_success(
        api_client.cast_vote(
            cr_id,
            {"decision": "REJECT", "expected_change_request_version": change["version"]},
            U.cab_member("cab-3"),
        ),
        expected_status=201,
    )
    cr_after = validate_success(api_client.get_change_request(cr_id, U.cab_member("cab-3")))
    assert cr_after["state"] == "REJECTED"

    tkt_after = validate_success(api_client.get_ticket(tid, U.agent("agent-5")))
    assert tkt_after["lifecycle_state"] == "IN_PROGRESS", \
        "rejected change must bubble the ticket back to IN_PROGRESS"
    assert tkt_after["change_request_id"] is None


def test_cab_approve_branch_approves_change_for_low_risk_quorum_one():
    """PRD §3.5: "On an approve vote, approve quorum is checked first: if
    approve_count has reached required_approvals, the change moves from
    PENDING_CAB to APPROVED."
    PRD §3.5: "derives the required_approvals quorum from its risk — one approval
    for LOW, two for MEDIUM, three for HIGH."

    Design: Difficulty/non_linear_state_machine/change_request_cab_fork_to_approved_or_rejected
    """
    _, _, _, ticket, change = fx.setup_ticket_pending_change(
        risk="LOW", default_priority="P2", manager_id="cm-2b",
        agent_id="agent-5b", requester_id="req-5b",
    )
    cr_id = change["id"]
    assert change["required_approvals"] == 1

    validate_success(
        api_client.cast_vote(
            cr_id,
            {"decision": "APPROVE", "expected_change_request_version": change["version"]},
            U.cab_member("cab-3b"),
        ),
        expected_status=201,
    )
    cr_after = validate_success(api_client.get_change_request(cr_id, U.cab_member("cab-3b")))
    assert cr_after["state"] == "APPROVED", \
        "a single approve reaches the LOW-risk quorum of one"

    tkt_after = validate_success(api_client.get_ticket(ticket["id"], U.agent("agent-5b")))
    assert tkt_after["lifecycle_state"] == "IN_PROGRESS"
    assert tkt_after["change_request_id"] is None
