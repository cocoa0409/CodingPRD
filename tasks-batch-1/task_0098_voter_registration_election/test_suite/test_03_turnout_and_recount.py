"""Turnout reporting and recount certification.

Covers the dual turnout variants (final vs projected), recount certification's
within/outside-tolerance branches, the fork-join over two passes, terminal-state
lockdown, and the recount preconditions guarding election certification.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
)
from test_helpers.test_users import OFF1, ADMIN

ERR = ApiErrorId


# ---------------------------------------------------------------------------
# Turnout dual variant (Difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------
def test_turnout_projected_vs_final_diverge(api):
    """PRD §3.8: "The final turnout, reported as turnout_pct, counts only absentee
    ballots whose request status is ACCEPTED. The projected turnout, reported as
    projected_turnout_pct, counts absentee ballots whose request status is RETURNED
    or ACCEPTED — that is, ballots physically in hand even if not yet adjudicated —
    so for identical data the projected figure is at least as large as the final
    figure whenever any ballot is returned but not yet accepted."

    Design: Difficulty/dual_variant_calc/turnout_projected_vs_final_diverge
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    e_id = election["id"]
    r1 = fixtures.create_registration(e_id, national_id="N1", first_name="A", street_number=10)
    r2 = fixtures.create_registration(e_id, national_id="N2", first_name="B", last_name="B", street_number=20)
    a1 = fixtures.approve_registration(r1["id"], OFF1)
    a2 = fixtures.approve_registration(r2["id"], OFF1)
    b1 = fixtures.request_absentee_ballot(a1["id"], a1["version"], OFF1)
    b2 = fixtures.request_absentee_ballot(a2["id"], a2["version"], OFF1)
    # b1 -> ACCEPTED; b2 -> RETURNED only.
    for st in ("ISSUED", "RETURNED", "ACCEPTED"):
        validate_success(api.transition_absentee_ballot(b1["id"], {"target_request_status": st}, OFF1), 200)
    for st in ("ISSUED", "RETURNED"):
        validate_success(api.transition_absentee_ballot(b2["id"], {"target_request_status": st}, OFF1), 200)
    e = validate_success(api.get_election(e_id, ADMIN), 200)
    assert e["turnout_pct"] == pytest.approx(50.00, abs=0.001), "final counts only ACCEPTED (1/2)"
    assert e["projected_turnout_pct"] == pytest.approx(100.00, abs=0.001), "projected counts RETURNED+ACCEPTED (2/2)"


def test_total_ballots_accepted_recomputed_on_accept(api):
    """PRD §3.8: "The separately reported total_ballots_accepted is the count of
    the election's absentee ballots whose request status is ACCEPTED."
    PRD §3.3: "Acceptance recomputes the election's total_ballots_accepted."

    Design: Difficulty/dual_variant_calc/turnout_projected_vs_final_diverge
    """
    election, precinct, active, ballot = fixtures.setup_ballot_in_request_state("ACCEPTED")
    e = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert e["total_ballots_accepted"] == 1


# ---------------------------------------------------------------------------
# Recount certification dual variant (Difficulty: dual_variant_calc + combinatorial)
# ---------------------------------------------------------------------------
def test_recount_outside_tolerance_certifies_min(api):
    """PRD §3.9: "Compute the absolute difference between machine_recount and
    hand_recount. If that difference is at most the discrepancy tolerance of 5
    votes, the hand count governs and certified_count is set to hand_recount. If
    the difference exceeds 5 votes, the system takes the conservative lower of the
    two and sets certified_count to the smaller of machine_recount and hand_recount."
    PRD §3.8: "Certifying moves it BOTH_DONE -> CERTIFIED, runs the
    recount-certification calculation in §3.9 to set certified_count, and writes
    that certified count back into the precinct's reported_vote_count."

    Design: Difficulty/dual_variant_calc/recount_certification_within_vs_outside_tolerance
    """
    election, precinct, recount = fixtures.setup_recount_both_done(machine_count=100, hand_count=90, reported_vote_count=100)
    data = validate_success(api.transition_recount_case(recount["id"], {"target_status": "CERTIFIED"}, ADMIN), 200)
    assert data["status"] == "CERTIFIED"
    assert data["certified_count"] == 90, "delta 10 > 5 -> min(100, 90) = 90"
    p = validate_success(api.get_precinct(precinct["id"], ADMIN), 200)
    assert p["reported_vote_count"] == 90, "certified count writes back to the precinct"


def test_recount_within_tolerance_certifies_hand_count(api):
    """PRD §3.9: "If that difference is at most the discrepancy tolerance of 5
    votes, the hand count governs and certified_count is set to hand_recount."

    Design: Difficulty/dual_variant_calc/recount_certification_within_vs_outside_tolerance
    """
    election, precinct, recount = fixtures.setup_recount_both_done(machine_count=100, hand_count=96, reported_vote_count=100)
    data = validate_success(api.transition_recount_case(recount["id"], {"target_status": "CERTIFIED"}, ADMIN), 200)
    assert data["certified_count"] == 96, "delta 4 <= 5 -> hand_recount governs"


def test_recount_exactly_at_tolerance_certifies_hand_count(api):
    """PRD §3.9: "A difference of exactly 5 is within tolerance, so the hand count
    governs at the boundary."

    Design: Difficulty/combinatorial_formula/recount_certification_conditional_min_three_inputs
    """
    election, precinct, recount = fixtures.setup_recount_both_done(machine_count=100, hand_count=95, reported_vote_count=100)
    data = validate_success(api.transition_recount_case(recount["id"], {"target_status": "CERTIFIED"}, ADMIN), 200)
    assert data["certified_count"] == 95, "delta exactly 5 is within tolerance -> hand_recount (95)"


def test_recount_just_outside_tolerance_certifies_min(api):
    """PRD §3.9: "If the difference exceeds 5 votes, the system takes the
    conservative lower of the two and sets certified_count to the smaller of
    machine_recount and hand_recount."

    Design: Difficulty/combinatorial_formula/recount_certification_conditional_min_three_inputs
    """
    election, precinct, recount = fixtures.setup_recount_both_done(machine_count=100, hand_count=94, reported_vote_count=100)
    data = validate_success(api.transition_recount_case(recount["id"], {"target_status": "CERTIFIED"}, ADMIN), 200)
    assert data["certified_count"] == 94, "delta 6 > 5 -> min(100, 94) = 94"


# ---------------------------------------------------------------------------
# Recount terminal-state lockdown + preconditions (Corner)
# ---------------------------------------------------------------------------
def test_dismissed_recount_then_certify_invalid_state(api):
    """PRD §3.8: "Dismissing may be applied from any of REQUESTED, MACHINE_DONE,
    HAND_DONE, or BOTH_DONE, moving the case to the terminal DISMISSED and leaving
    the precinct's count at its original_count unchanged."
    PRD §2.9: "then whether the target resource is in a legal state for the
    requested transition (ERR_INVALID_STATE)."

    Design: Corner/state_machines/terminal_recount_dismissed_then_certify_returns_invalid_state
    """
    election, precinct = fixtures.setup_election_with_precinct("SCHEDULED", clock="2026-06-01T00:00:00Z")
    precinct = fixtures.tally_precinct(precinct["id"], reported_vote_count=100)
    recount = fixtures.open_recount(election["id"], precinct["id"])
    fixtures.dismiss_recount(recount["id"])
    resp = api.transition_recount_case(recount["id"], {"target_status": "CERTIFIED"}, ADMIN)
    validate_error(resp, ERR.ERR_INVALID_STATE.value)
    after = validate_success(api.get_recount_case(recount["id"], ADMIN), 200)
    assert after["status"] == "DISMISSED"


def test_certify_succeeds_when_all_precincts_tallied_and_no_open_recount(api):
    """PRD §3.1: "The final transition POLLS_CLOSED -> CERTIFIED is the terminal
    state and is gated by two conditions beyond being in POLLS_CLOSED: every
    precinct of the election must have a tally status of TALLIED (otherwise
    ERR_PRECINCTS_NOT_TALLIED), and no recount case of the election may still be in
    any of REQUESTED, MACHINE_DONE, HAND_DONE, or BOTH_DONE (otherwise
    ERR_RECOUNT_IN_PROGRESS)."

    Design: Difficulty/cross_entity_state_dependency/election_certify_blocked_by_untallied_precinct
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "SCHEDULED", clock="2026-11-03T21:00:00Z",
        election_overrides={"cure_deadline": "2026-11-02T00:00:00Z"},
    )
    fixtures.tally_precinct(precinct["id"], reported_vote_count=100)
    fixtures._transition_election(election["id"], "REGISTRATION_OPEN")
    fixtures._transition_election(election["id"], "VOTING_OPEN")
    fixtures._transition_election(election["id"], "POLLS_CLOSED")
    data = validate_success(api.transition_election(election["id"], {"target_status": "CERTIFIED"}, ADMIN), 200)
    assert data["status"] == "CERTIFIED", "certification succeeds once every precinct is TALLIED"


def test_recount_on_pending_precinct_returns_not_tallied(api):
    """PRD §3.8: "the precinct must already be TALLIED, or the open is refused with
    ERR_PRECINCT_NOT_TALLIED."

    Design: Corner/validations/recount_on_pending_precinct_returns_not_tallied
    """
    election, precinct = fixtures.setup_election_with_precinct("SCHEDULED", clock="2026-06-01T00:00:00Z")
    resp = api.create_recount_case({"election_id": election["id"], "precinct_id": precinct["id"]}, ADMIN)
    validate_error(resp, ERR.ERR_PRECINCT_NOT_TALLIED.value)


def test_certify_blocked_by_open_recount_returns_recount_in_progress(api):
    """PRD §3.1: "and no recount case of the election may still be in any of
    REQUESTED, MACHINE_DONE, HAND_DONE, or BOTH_DONE (otherwise
    ERR_RECOUNT_IN_PROGRESS)."

    Design: Corner/validations/certify_blocked_by_open_recount_returns_recount_in_progress
    """
    # election_date must be reached to close polls; cure_deadline before election_date
    # so the cure sweep has nothing pending; clock at 2026-11-03T21:00 is past both.
    election, precinct = fixtures.setup_election_with_precinct(
        "SCHEDULED", clock="2026-11-03T21:00:00Z",
        election_overrides={"cure_deadline": "2026-11-02T00:00:00Z"},
    )
    precinct = fixtures.tally_precinct(precinct["id"], reported_vote_count=100)
    fixtures.open_recount(election["id"], precinct["id"])  # leaves a REQUESTED recount
    fixtures._transition_election(election["id"], "REGISTRATION_OPEN")
    fixtures._transition_election(election["id"], "VOTING_OPEN")
    fixtures._transition_election(election["id"], "POLLS_CLOSED")
    resp = api.transition_election(election["id"], {"target_status": "CERTIFIED"}, ADMIN)
    validate_error(resp, ERR.ERR_RECOUNT_IN_PROGRESS.value)
    after = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert after["status"] == "POLLS_CLOSED"


def test_election_certify_blocked_by_untallied_precinct(api):
    """PRD §3.1: "every precinct of the election must have a tally status of
    TALLIED (otherwise ERR_PRECINCTS_NOT_TALLIED)."

    Design: Difficulty/cross_entity_state_dependency/election_certify_blocked_by_untallied_precinct
    """
    election, precinct1 = fixtures.setup_election_with_precinct(
        "SCHEDULED", clock="2026-11-03T21:00:00Z",
        election_overrides={"cure_deadline": "2026-11-02T00:00:00Z"},
    )
    # A second precinct left PENDING.
    fixtures.create_precinct(election["id"], code="P2", street_low=1000, street_high=1999)
    fixtures.tally_precinct(precinct1["id"], reported_vote_count=100)
    fixtures._transition_election(election["id"], "REGISTRATION_OPEN")
    fixtures._transition_election(election["id"], "VOTING_OPEN")
    fixtures._transition_election(election["id"], "POLLS_CLOSED")
    resp = api.transition_election(election["id"], {"target_status": "CERTIFIED"}, ADMIN)
    validate_error(resp, ERR.ERR_PRECINCTS_NOT_TALLIED.value)
    after = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert after["status"] == "POLLS_CLOSED"
