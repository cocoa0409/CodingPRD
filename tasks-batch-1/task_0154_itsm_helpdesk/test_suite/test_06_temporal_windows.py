"""Temporal interval semantics: the inclusive reopen window vs the hard CSAT
window, and the link-then-close reference-counter invariant.

Difficulty queue A: resource_temporal_overlap, compensating_invariant (linked
count).
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
# resource_temporal_overlap / reopen_window_inclusive_vs_csat_window_distinct_semantics
# ===========================================================================
def test_reopen_exactly_at_window_far_boundary_is_allowed():
    """PRD §3.6: "Reopening is permitted only while the current clock is at or
    before resolved_at plus the reopen window of twenty-four hours (1440 minutes),
    and only when the caller's X-User-ID matches the ticket's requester_id."

    Design: Difficulty/resource_temporal_overlap/reopen_window_inclusive_vs_csat_window_distinct_semantics
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-12", agent_id="agent-12"
    )
    fx.advance_clock(1440)  # exactly at resolved_at + 1440
    reopened = validate_success(api_client.reopen_ticket(ticket["id"], U.requester("req-12")))

    assert reopened["lifecycle_state"] == "IN_PROGRESS", \
        "reopen at exactly +1440 is within the inclusive window"
    assert reopened["reopen_count"] == 1


def test_reopen_within_window_returns_to_in_progress():
    """PRD §3.6: "Reopening is permitted only while the current clock is at or
    before resolved_at plus the reopen window of twenty-four hours (1440
    minutes)."

    Design: Difficulty/resource_temporal_overlap/reopen_window_inclusive_vs_csat_window_distinct_semantics
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-12b", agent_id="agent-12b"
    )
    fx.advance_clock(1439)  # one minute inside the window
    reopened = validate_success(api_client.reopen_ticket(ticket["id"], U.requester("req-12b")))
    assert reopened["lifecycle_state"] == "IN_PROGRESS"
    assert reopened["reopen_count"] == 1


# ===========================================================================
# resource_temporal_overlap / csat_window_closed_after_hard_boundary_distinct_from_reopen
# ===========================================================================
def test_csat_survey_past_hard_window_is_rejected():
    """PRD §3.7: "A survey submitted past that hard window is rejected outright
    with ERR_CSAT_WINDOW_CLOSED; a survey within the window is stored with
    counts_toward_index set to true."

    Design: Difficulty/resource_temporal_overlap/csat_window_closed_after_hard_boundary_distinct_from_reopen
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-13", agent_id="agent-13"
    )
    fx.advance_clock(2881)  # one minute past the 2880 hard window
    resp = api_client.create_csat_survey(
        {"ticket_id": ticket["id"], "score": 5}, U.requester("req-13")
    )
    validate_error(resp, ApiErrorId.ERR_CSAT_WINDOW_CLOSED.value, expected_status=409)


def test_csat_survey_one_minute_past_window_closed():
    """PRD §3.7: "The survey records whether it counts_toward_index: this is true
    only when the survey is filed within the CSAT eligibility window of
    forty-eight hours (2880 minutes) after the ticket's resolved_at. A survey
    submitted past that hard window is rejected outright with
    ERR_CSAT_WINDOW_CLOSED."

    Design: Difficulty/resource_temporal_overlap/csat_window_closed_after_hard_boundary_distinct_from_reopen
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-13b", agent_id="agent-13b"
    )
    fx.advance_clock(2881)
    resp = api_client.create_csat_survey(
        {"ticket_id": ticket["id"], "score": 4}, U.requester("req-13b")
    )
    validate_error(resp, ApiErrorId.ERR_CSAT_WINDOW_CLOSED.value, expected_status=409)


# ===========================================================================
# compensating_invariant / link_then_close_conserves_problem_linked_ticket_count
# ===========================================================================
def test_link_then_close_returns_linked_ticket_count_to_zero():
    """PRD §3.8: "Tickets are attached to a problem as symptoms via the link
    action, which writes the ticket's problem_id and recomputes the problem's
    linked_ticket_count, counting only those linked tickets whose lifecycle_state
    is not CLOSED or CANCELLED."

    Design: Difficulty/compensating_invariant/link_then_close_conserves_problem_linked_ticket_count
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_in_progress_ticket(
        default_priority="P3", requester_id="req-15", agent_id="agent-15"
    )
    tid = ticket["id"]
    problem = fx.create_problem(owner_id="agent-15")

    validate_success(
        api_client.link_problem(tid, {"problem_id": problem["id"]}, U.agent("agent-15"))
    )
    # resolve then close (CLOSED is excluded from the count). PRD §3.6: closing is
    # allowed once the reopen window has elapsed — the current clock is strictly
    # past resolved_at plus the 1440-minute reopen window — so advance past it.
    validate_success(api_client.resolve_ticket(tid, U.agent("agent-15")))
    fx.advance_clock(1441)
    closed = validate_success(api_client.close_ticket(tid, U.agent("agent-15")))
    assert closed["lifecycle_state"] == "CLOSED"

    prob_after = validate_success(api_client.get_problem(problem["id"], U.agent("agent-15")))
    assert prob_after["linked_ticket_count"] == 0, \
        "link (+1) then resolve/close (-1) must return linked_ticket_count to 0"


# DELETED test_resolve_excludes_ticket_from_problem_linked_count — unique-derivability
# collapse (STEP 1b). The test asserted that resolving a linked ticket drops the
# problem's linked_ticket_count to 0, but PRD §3.8 defines that counter verbatim as
# "counting only those linked tickets whose lifecycle_state is not CLOSED or
# CANCELLED" — RESOLVED is NOT in the exclusion set, so a faithful PRD-only
# implementer keeps the RESOLVED ticket counted (count stays 1). The test's own
# docstring quotes that exclusion set yet asserts the opposite outcome. PRD covers
# linked_ticket_count but does NOT uniquely determine RESOLVED-exclusion; it
# admits both readings (count=1 verbatim vs count=0), so the test is deleted.
# (Scaffold rule: Difficulty/compensating_invariant/link_then_close_conserves_problem_linked_ticket_count.)
