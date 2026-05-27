"""Non-linear state-machine shape tests (PRD §3.6 ACC cyclic, §3.7 BoardElection
branching)."""
from test_helpers import (
    bootstrap_acc_request_on_compliant_property,
    bootstrap_election_open_with_voters,
    cast_vote,
    get_election,
    set_clock,
    validate_success,
)
from test_helpers.test_users import (
    make_acc_member_headers,
    make_board_secretary_headers,
    make_homeowner_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Rule 3 instance 1: ACCRequest cyclic revision loop
# ─────────────────────────────────────────────────────────────────────────────

def test_acc_request_revision_cycle_returns_to_submitted_with_count_one(api):
    """PRD §3.6: "Or they may ask for changes, transitioning from `SUBMITTED`
    to `REVISION_REQUESTED` and incrementing `revision_count`."
    PRD §3.6: "From `REVISION_REQUESTED`, the owner may resubmit, sending
    the request back to `SUBMITTED` for another review pass. Resubmission
    does NOT increment `revision_count`; only the request-revision step
    bumps it."

    Setup: ACCRequest submitted on a COMPLIANT property. ACC requests
    revision (count → 1, status → REVISION_REQUESTED), then owner resubmits
    (status → SUBMITTED, count unchanged).

    Design: Difficulty/non_linear_state_machine/acc_request_cyclic_revision_loop
    """
    _community, owner, _prop, acc = bootstrap_acc_request_on_compliant_property(
        community_name="Cyclic HOA",
    )
    rev_resp = api.request_revision_acc(acc["id"], make_acc_member_headers())
    rev_data = validate_success(rev_resp, expected_status=200)
    assert rev_data["status"] == "REVISION_REQUESTED"
    assert rev_data["revision_count"] == 1

    resub_resp = api.resubmit_acc_request(
        acc["id"], make_homeowner_headers(owner["id"]),
    )
    resub_data = validate_success(resub_resp, expected_status=200)
    assert resub_data["status"] == "SUBMITTED", (
        f"expected SUBMITTED after resubmit, got {resub_data['status']}"
    )
    assert resub_data["revision_count"] == 1, (
        f"resubmit must NOT increment revision_count; got {resub_data['revision_count']}"
    )


def test_acc_request_revision_count_caps_at_three(api):
    """PRD §3.6: "Request-revision is itself capped: if the existing
    `revision_count` is already 3, the request-revision action is refused
    with `ERR_ACC_REVISION_LIMIT` — meaning the revision cycle can be
    entered at most three times in the lifetime of a single request."

    Setup: drive three full request-revision/resubmit cycles. After cycle
    three, revision_count == 3 and status == SUBMITTED — a fourth
    request-revision must yield ERR_ACC_REVISION_LIMIT (asserted in
    test_05 corner; here we anchor the CYCLE shape by counting up to 3).

    Design: Difficulty/non_linear_state_machine/acc_request_cyclic_revision_loop
    """
    _community, owner, _prop, acc = bootstrap_acc_request_on_compliant_property(
        community_name="Cyclic HOA",
    )
    acc_id = acc["id"]
    ho_headers = make_homeowner_headers(owner["id"])
    acc_headers = make_acc_member_headers()
    for cycle in range(3):
        rv = validate_success(
            api.request_revision_acc(acc_id, acc_headers), expected_status=200,
        )
        assert rv["status"] == "REVISION_REQUESTED"
        assert rv["revision_count"] == cycle + 1, (
            f"after cycle {cycle + 1} request-revision count should be {cycle + 1}, "
            f"got {rv['revision_count']}"
        )
        rs = validate_success(
            api.resubmit_acc_request(acc_id, ho_headers), expected_status=200,
        )
        assert rs["status"] == "SUBMITTED"
        assert rs["revision_count"] == cycle + 1, (
            f"resubmit must NOT re-increment; expected {cycle + 1}, "
            f"got {rs['revision_count']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 3 instance 2: BoardElection branching at close
# ─────────────────────────────────────────────────────────────────────────────

def test_election_close_branches_to_quorum_met_when_threshold_reached(api):
    """PRD §3.7: "The close branches deterministically: when `votes_cast`
    multiplied by 100 is at least `eligible_voter_count` multiplied by the
    community's `election_quorum_pct`, the election lands in
    `CLOSED_QUORUM_MET`; otherwise it lands in `CLOSED_NO_QUORUM`."

    Setup: 3 eligible voters, quorum=33, 1 vote cast. 1*100 = 100 ≥
    3*33 = 99 → branch CLOSED_QUORUM_MET.

    Design: Difficulty/non_linear_state_machine/board_election_branching_at_close
    """
    _community, owners, election = bootstrap_election_open_with_voters(
        community_name="VoteVille",
        eligible_owner_count=3,
        cycle_label="FY2026",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
        election_quorum_pct=33,
    )
    cast_vote(election["id"], owners[0]["id"], candidate_name="Alice")
    set_clock("2026-02-17T00:00:00Z")
    closed_resp = api.close_election(election["id"], make_board_secretary_headers())
    closed = validate_success(closed_resp, expected_status=200)
    assert closed["eligible_voter_count"] == 3, (
        f"eligible_voter_count snapshot must be 3, got {closed['eligible_voter_count']}"
    )
    assert closed["votes_cast"] == 1, (
        f"votes_cast must be 1, got {closed['votes_cast']}"
    )
    assert closed["status"] == "CLOSED_QUORUM_MET", (
        f"branch must be CLOSED_QUORUM_MET (1*100 >= 3*33), got {closed['status']}"
    )


def test_election_close_branches_to_no_quorum_when_threshold_not_reached(api):
    """PRD §3.7: "The close branches deterministically: when `votes_cast`
    multiplied by 100 is at least `eligible_voter_count` multiplied by the
    community's `election_quorum_pct`, the election lands in
    `CLOSED_QUORUM_MET`; otherwise it lands in `CLOSED_NO_QUORUM`."

    Setup: 3 eligible voters, quorum=50, 1 vote cast. 1*100 = 100 < 3*50 = 150
    → branch CLOSED_NO_QUORUM (alternative branch of the same fork).

    Design: Difficulty/non_linear_state_machine/board_election_branching_at_close
    """
    _community, owners, election = bootstrap_election_open_with_voters(
        community_name="NoQuorumVille",
        eligible_owner_count=3,
        cycle_label="FY2026-NQ",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
        election_quorum_pct=50,
    )
    cast_vote(election["id"], owners[0]["id"], candidate_name="Alice")
    set_clock("2026-02-17T00:00:00Z")
    closed = validate_success(
        api.close_election(election["id"], make_board_secretary_headers()),
        expected_status=200,
    )
    refreshed = get_election(election["id"])
    assert closed["status"] == "CLOSED_NO_QUORUM", (
        f"branch must be CLOSED_NO_QUORUM (1*100 < 3*50), got {closed['status']}"
    )
    assert refreshed["status"] == "CLOSED_NO_QUORUM"
