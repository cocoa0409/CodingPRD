"""TradeRequest lifecycle: PROPOSED, COUNTER_PROPOSED cycle, APPROVED ->
EXECUTED with the conservation invariant on cumulative_block_minutes_30d.

PRD §3.8 names every transition.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_trade_as,
    approve_trade,
    assert_block_minutes_conserved_across_trade,
    counter_trade_as,
    create_crew_member,
    create_trade_request,
    crew_role_headers,
    get_assignment,
    get_crew_member,
    get_trade_request,
    pilot_headers_for,
    raise_cumulative_block_30d,
    release_assignment,
    setup_pairing_admin_assigned,
    setup_two_pilots_with_assignments,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestTradeProposal:

    def test_create_trade_request_is_proposed(self, api):
        """PRD §3.8: "A trade request is initiated by a Pilot or
        FlightAttendant who supplies their own assignment as
        initiator_assignment_id, the counterparty's assignment as
        counterparty_assignment_id, and the counterparty's crew member
        id as counterparty_id ... The trade is born in PROPOSED with
        revision_count of zero."
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        tr = create_trade_request(m1, m2, a1, a2)
        assert tr["state"] == "PROPOSED"
        assert tr["revision_count"] == 0
        assert tr["initiator_id"] == m1["id"]
        assert tr["counterparty_id"] == m2["id"]


class TestCounterPropose:

    def test_counter_cycle_up_to_3_rounds(self, api):
        """PRD §3.8: "A counter-proposal ... is allowed only while
        revision_count is strictly less than 3 and the current state is
        PROPOSED or COUNTER_PROPOSED; the action swaps the two
        assignment ids in the trade, swaps the initiator_id and
        counterparty_id roles (the prior counterparty becomes the new
        proposer), and increments revision_count by one ... the cycle
        is allowed up to three total rounds, after which any further
        counter is rejected with ERR_INVALID_TRADE_STATE."

        # difficulty: non_linear_state_machine/trade_request_cyclic_counter_loop
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        tr = create_trade_request(m1, m2, a1, a2)
        # Round 1: m2 counters → state COUNTER_PROPOSED, rev=1.
        tr1 = counter_trade_as(m2, tr["id"], a2["id"], a1["id"])
        assert tr1["state"] == "COUNTER_PROPOSED"
        assert tr1["revision_count"] == 1
        # Round 2: m1 counters (m1 is now the counterparty) → state PROPOSED,
        # rev=2.
        tr2 = counter_trade_as(m1, tr["id"], a1["id"], a2["id"])
        assert tr2["state"] == "PROPOSED"
        assert tr2["revision_count"] == 2
        # Round 3: m2 counters → state COUNTER_PROPOSED, rev=3.
        tr3 = counter_trade_as(m2, tr["id"], a2["id"], a1["id"])
        assert tr3["state"] == "COUNTER_PROPOSED"
        assert tr3["revision_count"] == 3
        # Round 4: must be rejected.
        from test_helpers import counter_trade_payload
        resp = api.counter_trade_request(
            tr["id"],
            counter_trade_payload(a1["id"], a2["id"]),
            crew_role_headers(m1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRADE_STATE.value)


class TestApproveAndExecute:

    def test_approve_swaps_crew_member_ids_and_conserves_block_30d(self, api):
        """PRD §3.8: "the CrewScheduler approves it, which runs the
        legality check, transitions the trade ACCEPTED -> APPROVED ->
        EXECUTED within the same request, and atomically swaps
        Assignment.crew_member_id between the two assignments
        referenced by initiator_assignment_id and
        counterparty_assignment_id. After the swap, both crew members'
        cumulative_block_minutes_30d and cumulative_duty_minutes_7d are
        recomputed; the conservation invariant guarantees their sum
        across the two members is unchanged."

        # difficulty: compensating_invariant/trade_execution_conserves_total_block_30d
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        # Snapshot baseline cumulative_block_minutes_30d.
        m1 = get_crew_member(m1["id"])
        m2 = get_crew_member(m2["id"])
        block_before = (
            int(m1["cumulative_block_minutes_30d"])
            + int(m2["cumulative_block_minutes_30d"])
        )
        tr = create_trade_request(m1, m2, a1, a2)
        # m2 accepts.
        accept_trade_as(m2, tr["id"])
        # Scheduler approves.
        approve_trade(tr["id"])

        # Re-read assignments → crew_member_id swapped.
        a1_after = get_assignment(a1["id"])
        a2_after = get_assignment(a2["id"])
        assert a1_after["crew_member_id"] == m2["id"]
        assert a2_after["crew_member_id"] == m1["id"]
        # Re-read crew members → conservation holds.
        m1_after = get_crew_member(m1["id"])
        m2_after = get_crew_member(m2["id"])
        block_after = (
            int(m1_after["cumulative_block_minutes_30d"])
            + int(m2_after["cumulative_block_minutes_30d"])
        )
        assert_block_minutes_conserved_across_trade(
            int(m1["cumulative_block_minutes_30d"]),
            int(m2["cumulative_block_minutes_30d"]),
            int(m1_after["cumulative_block_minutes_30d"]),
            int(m2_after["cumulative_block_minutes_30d"]),
        )
        assert block_after == block_before

    def test_approve_rejected_when_assignment_released_in_between(self, api):
        """PRD §3.8: "Approval is rejected with
        ERR_INVALID_ASSIGNMENT_STATE if either assignment is no longer
        SCHEDULED at approval time — for instance, if a sick call beat
        the approval to the assignment, the trade approver receives
        that error and the sick call wins."

        # difficulty: cross_entity_state_dependency/trade_approve_requires_both_assignments_scheduled
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        tr = create_trade_request(m1, m2, a1, a2)
        accept_trade_as(m2, tr["id"])
        # Release m2's assignment first.
        release_assignment(a2["id"])
        from test_helpers import scheduler_headers as _sch
        resp = api.approve_trade_request(tr["id"], _sch())
        validate_error(resp, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value)
