"""Boundary precision tests (difficulty rule 6): quorum/approval thresholds
and the strictly-greater-than overdue boundary."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_draft_agreement,
    create_employer_proposal_on_table,
    create_information_request_payload,
    create_locked_scenario,
    create_ratification_vote_payload,
    create_union,
    get_success_data,
    make_union_representative_headers,
    setup_accepted_economic_package,
    setup_open_vote,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
MGR = TEST_USERS["lr_manager_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / ratification_quorum_approval_boundary
# ---------------------------------------------------------------------------

def _setup_vote_with_package(api, eligible_voter_count, ballot_close_at):
    union = create_union(name="Union K")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA K",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"],
        union["id"],
        title="Allowance",
        proposal_type="ECONOMIC",
        recurring_annual_cost_cents=100,
    )
    create_locked_scenario(agreement["id"], [proposal["id"]], scenario_mode="FINAL", term_years=3)
    get_success_data(
        api.transition_proposal(
            proposal["id"], {"to_status": "ACCEPTED"},
            make_union_representative_headers(union["id"]),
        )
    )
    vote = get_success_data(
        api.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=agreement["id"],
                eligible_voter_count=eligible_voter_count,
                ballot_close_at=ballot_close_at,
            ),
            CHIEF,
        )
    )
    get_success_data(api.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF))
    return union, agreement, proposal, vote


def test_tie_ballot_at_exact_quorum_is_rejected(api):
    """PRD §3.6: "`quorum_met` is true when `votes_cast` is at least half of
    `eligible_voter_count` rounded up — exactly half is sufficient; `approved`
    is true when twice `votes_for` is strictly greater than `votes_cast` — an
    exact tie fails."

    Design: Difficulty/boundary_precision_check/ratification_quorum_approval_boundary
    """
    union, _, proposal, vote = _setup_vote_with_package(api, 100, "2026-06-01T00:00:00Z")
    get_success_data(api.set_clock("2026-06-02T00:00:00Z", ADMIN))
    result = get_success_data(
        api.tally_vote(
            vote["id"], {"votes_for": 25, "votes_against": 25},
            make_union_representative_headers(union["id"]),
        )
    )
    assert result["status"] == "REJECTED"
    assert result["quorum_met"] is True, "exactly 50 of 100 meets the >= quorum"
    # The tie fails approval because votes_for * 2 > votes_cast is strict
    assert 25 * 2 <= 50
    # Compensation revert: the ACCEPTED proposal reverts to ON_TABLE.
    proposal_after = get_success_data(api.get_proposal(proposal["id"], NEG1))
    assert proposal_after["status"] == "ON_TABLE"


def test_crossing_both_thresholds_ratifies(api):
    """PRD §3.6: "When both quorum and approval hold, the vote becomes
    `RATIFIED`; otherwise it becomes `REJECTED`."

    Design: Difficulty/boundary_precision_check/ratification_quorum_approval_boundary
    """
    union, agreement, proposal, vote = _setup_vote_with_package(api, 100, "2026-06-01T00:00:00Z")
    rep = make_union_representative_headers(union["id"])
    get_success_data(api.set_clock("2026-06-02T00:00:00Z", ADMIN))
    # V1: 25-25 tie -> REJECTED; proposal reverts to ON_TABLE.
    get_success_data(api.tally_vote(vote["id"], {"votes_for": 25, "votes_against": 25}, rep))
    # Re-accept the reverted package, then run V2 at 26-24.
    get_success_data(api.transition_proposal(proposal["id"], {"to_status": "ACCEPTED"}, rep))
    vote2 = get_success_data(
        api.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=agreement["id"],
                eligible_voter_count=100,
                ballot_close_at="2026-06-03T00:00:00Z",
            ),
            CHIEF,
        )
    )
    get_success_data(api.transition_ratification_vote(vote2["id"], {"to_status": "OPEN"}, CHIEF))
    get_success_data(api.set_clock("2026-06-04T00:00:00Z", ADMIN))
    result2 = get_success_data(
        api.tally_vote(vote2["id"], {"votes_for": 26, "votes_against": 24}, rep)
    )
    assert result2["status"] == "RATIFIED"
    assert result2["quorum_met"] is True


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / info_request_overdue_instant_boundary
# ---------------------------------------------------------------------------

def _setup_business_mode_request(api):
    union = create_union(name="Union L")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA L",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
        deadline_mode="BUSINESS",
    )
    request = get_success_data(
        api.create_information_request(
            create_information_request_payload(
                union_id=union["id"],
                agreement_id=agreement["id"],
                subject="Overtime records",
                received_at="2026-05-01T09:00:00Z",
            ),
            make_union_representative_headers(union["id"]),
        )
    )
    return union, agreement, request


def test_overdue_flag_strictly_greater_than_due(api):
    """PRD §3.11: "The `is_overdue` flag becomes true when the clock is
    strictly later than `due_at` while the request is in `RECEIVED`,
    `ACKNOWLEDGED`, `IN_PROGRESS`, or `OBJECTED` — at the exact `due_at`
    instant the request is not yet overdue."

    Design: Difficulty/boundary_precision_check/info_request_overdue_instant_boundary
    """
    _, _, request = _setup_business_mode_request(api)
    assert request["due_at"] == "2026-05-15T17:00:00Z", (
        f"BUSINESS due_at mismatch: {request['due_at']}"
    )
    get_success_data(api.set_clock("2026-05-15T17:00:00Z", ADMIN))
    at_due = get_success_data(api.get_information_request(request["id"], MGR))
    assert at_due["is_overdue"] is False, "clock == due_at must NOT be overdue"
    get_success_data(api.set_clock("2026-05-15T17:00:01Z", ADMIN))
    after_due = get_success_data(api.get_information_request(request["id"], MGR))
    assert after_due["is_overdue"] is True, "one second past the deadline flips the flag"


def test_overdue_boundary_preserves_union_open_count(api):
    """PRD §3.11: "The request is born `RECEIVED`, the union's
    `open_information_request_count` increments, and the union's `version`
    increments." (The count holds while the request remains unresolved across
    the overdue boundary.)

    Design: Difficulty/boundary_precision_check/info_request_overdue_instant_boundary
    """
    union, _, request = _setup_business_mode_request(api)
    get_success_data(api.set_clock("2026-05-15T17:00:00Z", ADMIN))
    get_success_data(api.set_clock("2026-05-15T17:00:01Z", ADMIN))
    union_after = get_success_data(api.get_union(union["id"], MGR))
    assert union_after["open_information_request_count"] == 1
