"""Network-disconnect / network-resume cycle on an ACTIVE attempt.

Covers the ACTIVE ⇄ SUSPENDED cycle from PRD §3.2 and the
ERR_EXAM_WINDOW_CLOSED override at end_time from PRD §3.5 / §2.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    attempt_active,
    cycle_suspend_resume,
    exam_ready_for_candidates,
    make_candidate_headers,
    validate_error,
    validate_success,
)


def test_network_disconnect_transitions_active_to_suspended(api):
    """PRD §3.2: "a network-disconnect call transitions the attempt
    ACTIVE → SUSPENDED and stamps current_suspend_started_at from the
    server clock."
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    advance_clock(1100)
    res = api.network_disconnect(exam["id"], attempt["id"], cand_headers)
    updated = validate_success(res, 200)
    assert updated["status"] == "SUSPENDED"
    assert updated["current_suspend_started_at"] == 1100


def test_network_resume_accumulates_suspended_seconds(api):
    """PRD §3.2: "on success it adds the elapsed suspension interval —
    the current instant minus current_suspend_started_at — to
    suspended_total_seconds, and clears current_suspend_started_at back
    to null."
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    # Suspend at 1100, resume at 1200.
    refreshed = cycle_suspend_resume(
        exam["id"], attempt["id"], cid,
        suspend_at=1100, resume_at=1200,
    )
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["suspended_total_seconds"] == 100
    assert refreshed["current_suspend_started_at"] in (None, 0)


def test_cyclic_suspend_resume_accumulates_total(api):
    """PRD §3.2: 'suspended_total_seconds += (clock - current_suspend_started_at)'
    accumulates across multiple cycles, demonstrating the ACTIVE ⇄
    SUSPENDED cycle.

    Difficulty design: non_linear_state_machine /
    exam_attempt_active_suspended_cycle.
    """
    # difficulty: non_linear_state_machine/exam_attempt_active_suspended_cycle
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    # cycle 1: 1100 → 1200, +100
    refreshed = cycle_suspend_resume(
        exam["id"], attempt["id"], cid,
        suspend_at=1100, resume_at=1200,
    )
    assert refreshed["suspended_total_seconds"] == 100
    # cycle 2: 1300 → 1450, +150 ⇒ total 250
    refreshed = cycle_suspend_resume(
        exam["id"], attempt["id"], cid,
        suspend_at=1300, resume_at=1450,
    )
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["suspended_total_seconds"] == 250


def test_network_resume_rejected_after_end_time(api):
    """PRD §3.5: "a network-resume, submit, or in-exam recheck arriving
    on or after end_time is rejected with ERR_EXAM_WINDOW_CLOSED, even
    if its other preconditions are valid."
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    # Suspend at 1100.
    advance_clock(1100)
    validate_success(
        api.network_disconnect(exam["id"], attempt["id"], cand_headers),
        200,
    )
    # Advance to end_time. Forced submit owns the transition; the
    # suspended attempt is forced to SUBMITTED.
    advance_clock(2000)
    res = api.network_resume(exam["id"], attempt["id"], cand_headers)
    from test_helpers import validate_error_is_one_of
    # PRD §3.5 names ERR_EXAM_WINDOW_CLOSED explicitly; once forced
    # submit fires, the attempt's status is SUBMITTED, in which case
    # priority 5 (ERR_INVALID_STATE) also applies. PRD §2.7 puts the
    # forced-submit override (priority 7) AFTER state (priority 5),
    # which means ERR_INVALID_STATE could win in some implementations.
    # We accept either.
    validate_error_is_one_of(
        res, ["ERR_EXAM_WINDOW_CLOSED", "ERR_INVALID_STATE"],
    )
