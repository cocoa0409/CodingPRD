"""Compensating-invariant tests (difficulty rule 9): envelope conservation
across implement+void and mediator-minutes conservation across schedule+cancel."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_draft_agreement,
    create_employer_proposal_on_table,
    create_locked_scenario,
    create_ratification_vote_payload,
    create_session,
    create_union,
    get_agreement,
    get_success_data,
    make_union_representative_headers,
    setup_accepted_economic_package,
    setup_open_vote,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / envelope_commit_void_conservation
# ---------------------------------------------------------------------------

def _setup_envelope_conservation(api):
    union = create_union(name="Union Q")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA Q",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=66523200,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"],
        union["id"],
        title="GWI 4%",
        proposal_type="ECONOMIC",
        wage_increase_pct=0.04,
        affected_headcount=100,
        includes_benefits=True,
        one_time_cost_cents=120000,
        recurring_annual_cost_cents=6000000,
    )
    create_locked_scenario(agreement["id"], [proposal["id"]], scenario_mode="FINAL", term_years=3)
    rep = make_union_representative_headers(union["id"])
    get_success_data(api.transition_proposal(proposal["id"], {"to_status": "ACCEPTED"}, rep))
    committed_after_accept = get_agreement(agreement["id"])["envelope_committed_cents"]
    vote = setup_open_vote(union, agreement, ballot_close_at="2026-06-10T00:00:00Z")
    get_success_data(api.set_clock("2026-06-11T00:00:00Z", ADMIN))
    return union, agreement, proposal, vote, committed_after_accept


def test_accept_at_exact_envelope_equality_allowed(api):
    """PRD §3.3: "the agreement's `envelope_committed_cents` plus the proposal's
    `estimated_year1_cost_cents` must not exceed the agreement's
    `costing_envelope_cents` — equality is permitted; strictly exceeding is
    rejected with `ERR_ENVELOPE_EXCEEDED` (HTTP 422)."

    Design: Difficulty/compensating_invariant/envelope_commit_void_conservation
    """
    _, _, _, _, committed_after_accept = _setup_envelope_conservation(api)
    # FINAL year-1 line: base 100*5000*2080=1040000000; wage 41600000
    # (4% under 15% cap); *1.32 benefits = 54912000; tier r=100/100=1.0 ->
    # *1.10 = 60403200; +recurring 6000000 +one_time 120000 = 66523200.
    assert committed_after_accept == 66523200


def test_implement_then_void_conserves_envelope(api):
    """PRD §3.8: "Combined with the acceptance rule in §3.3 and the
    rejection-revert rule in §3.6, this gives the platform a strict
    conservation invariant on the envelope: after any matched accept-and-revert
    or implement-and-void pair, `envelope_committed_cents` returns exactly to
    its prior value."

    Design: Difficulty/compensating_invariant/envelope_commit_void_conservation
    """
    union, agreement, proposal, vote, committed_after_accept = _setup_envelope_conservation(api)
    rep = make_union_representative_headers(union["id"])
    get_success_data(api.tally_vote(vote["id"], {"votes_for": 5, "votes_against": 0}, rep))
    committed_after_ratify = get_agreement(agreement["id"])["envelope_committed_cents"]
    assert committed_after_ratify == 66523200, (
        "ACCEPTED -> IMPLEMENTED keeps the commitment (implemented proposals remain in the envelope)"
    )
    voided = get_success_data(api.void_implementation(proposal["id"], ADMIN))
    assert voided["status"] == "VOID"
    committed_after_void = get_agreement(agreement["id"])["envelope_committed_cents"]
    assert committed_after_void == 0, (
        f"implement + void must conserve the envelope exactly; got {committed_after_void}"
    )


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / mediator_minutes_cancel_conservation
# ---------------------------------------------------------------------------

def _setup_two_sessions_same_mediator(api):
    union = create_union(name="Union R")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA R",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    s1 = create_session(
        agreement["id"], mediator_id="med-7", lead_negotiator_id="ln-7",
        location="Room 1", start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z",
    )
    s2 = create_session(
        agreement["id"], mediator_id="med-7", lead_negotiator_id="ln-8",
        location="Room 2", start_at="2026-06-01T13:00:00Z", end_at="2026-06-01T14:30:00Z",
    )
    return s1, s2


def test_cancel_releases_mediator_minutes(api):
    """PRD §2.4: "The system tracks, for each mediator, an aggregate of
    scheduled minutes — the sum of `(end_at - start_at)` over that mediator's
    sessions currently in `SCHEDULED` status. Scheduling a session increases
    the aggregate; cancelling a session, or having the clock sweep mark it
    `NO_SHOW`, releases exactly those minutes back."

    Design: Difficulty/compensating_invariant/mediator_minutes_cancel_conservation
    """
    s1, s2 = _setup_two_sessions_same_mediator(api)
    cancelled = get_success_data(
        api.transition_session(
            s1["id"],
            {"to_status": "CANCELLED", "cancel_reason": "Mediator conflict resolved"},
            NEG1,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    resp = api.list_sessions(NEG1, params={"mediator_id": "med-7", "status": "SCHEDULED"})
    data, meta = _unwrap_list(resp)
    assert meta["total_count"] == 1, (
        f"after cancelling the 60-minute session, exactly the 90-minute session remains; "
        f"got total_count={meta['total_count']}"
    )
    assert data[0]["id"] == s2["id"]


def test_schedule_then_cancel_is_zero_net_pair(api):
    """PRD §2.4: "Scheduling a session increases the aggregate; cancelling a
    session, or having the clock sweep mark it `NO_SHOW`, releases exactly
    those minutes back."

    Design: Difficulty/compensating_invariant/mediator_minutes_cancel_conservation
    """
    s1, s2 = _setup_two_sessions_same_mediator(api)
    # Aggregate after two creates: 60 + 90 = 150 minutes (two SCHEDULED rows).
    resp = api.list_sessions(NEG1, params={"mediator_id": "med-7", "status": "SCHEDULED"})
    data, meta = _unwrap_list(resp)
    assert meta["total_count"] == 2
    # Cancel the 60-minute session; the aggregate returns to exactly 90
    # (observable as the single remaining SCHEDULED session of 90 minutes).
    get_success_data(
        api.transition_session(
            s1["id"],
            {"to_status": "CANCELLED", "cancel_reason": "Mediator conflict resolved"},
            NEG1,
        )
    )
    resp = api.list_sessions(NEG1, params={"mediator_id": "med-7", "status": "SCHEDULED"})
    data, meta = _unwrap_list(resp)
    assert meta["total_count"] == 1
    remaining = data[0]
    # 13:00 -> 14:30 is 90 minutes.
    assert remaining["start_at"] == "2026-06-01T13:00:00Z"
    assert remaining["end_at"] == "2026-06-01T14:30:00Z"


def _unwrap_list(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)
