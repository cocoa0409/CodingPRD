"""Election lifecycle, time windows, early voting, and the close-polls cure sweep.

Covers the half-open early-voting window boundary, the double-vote guard, the
withdraw-blocked guard, the close-polls cure sweep cascade, and the
state-beats-segregation precedence pair on a recount pass.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
)
from test_helpers.test_users import OFF1, ADMIN, PW1, CANV_TALLY

ERR = ApiErrorId


# ---------------------------------------------------------------------------
# Early-voting window half-open [start, end) (Difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------
def test_early_vote_at_window_end_returns_window_closed(api):
    """PRD §3.7: "The check-in is admissible only while the referenced registration
    is ACTIVE (otherwise ERR_REGISTRATION_NOT_ACTIVE) and only while the simulated
    clock falls within the window — at or after early_voting_start and strictly
    before early_voting_end — failing which it is refused with ERR_WINDOW_CLOSED."

    Design: Difficulty/resource_temporal_overlap/early_voting_window_half_open_at_end
    """
    election, precinct, active = fixtures.setup_active_registration()
    fixtures.set_clock("2026-11-02T00:00:00Z")  # == early_voting_end (exclusive upper bound)
    resp = api.create_early_vote_checkin({"registration_id": active["id"]}, PW1)
    validate_error(resp, ERR.ERR_WINDOW_CLOSED.value)
    reg = validate_success(api.get_registration(active["id"], OFF1), 200)
    assert reg["early_voted_at"] is None, "a rejected check-in must not stamp early_voted_at"


def test_early_vote_inside_window_succeeds_and_stamps(api):
    """PRD §3.7: "A successful check-in copies the precinct_id from the
    registration, stamps the check-in's checked_in_at with the current clock
    instant, and stamps the registration's early_voted_at with the same instant."

    Design: Difficulty/resource_temporal_overlap/early_voting_window_half_open_at_end
    """
    election, precinct, active = fixtures.setup_active_registration()
    fixtures.set_clock("2026-10-20T00:00:00Z")  # inside [early_voting_start, early_voting_end)
    data = validate_success(api.create_early_vote_checkin({"registration_id": active["id"]}, PW1), 201)
    assert data["registration_id"] == active["id"]
    assert data["precinct_id"] == precinct["id"], "check-in copies precinct_id from the registration"
    reg = validate_success(api.get_registration(active["id"], OFF1), 200)
    assert reg["early_voted_at"] is not None, "a successful check-in stamps early_voted_at"


# ---------------------------------------------------------------------------
# Double-vote guard (Corner: validations)
# ---------------------------------------------------------------------------
def test_early_vote_after_accepted_absentee_returns_already_voted(api):
    """PRD §3.7: "the voter must have no prior early-vote instant recorded and no
    absentee ballot whose request status is ISSUED, RETURNED, or ACCEPTED;
    otherwise the check-in is refused with ERR_ALREADY_VOTED."

    Design: Corner/validations/early_vote_double_after_accepted_absentee_returns_already_voted
    """
    election, precinct, active, ballot = fixtures.setup_ballot_in_request_state("ACCEPTED")
    fixtures.set_clock("2026-10-20T00:00:00Z")  # inside the early-voting window
    resp = api.create_early_vote_checkin({"registration_id": active["id"]}, PW1)
    validate_error(resp, ERR.ERR_ALREADY_VOTED.value)
    reg = validate_success(api.get_registration(active["id"], OFF1), 200)
    assert reg["early_voted_at"] is None


# ---------------------------------------------------------------------------
# Withdraw guard (Corner: validations)
# ---------------------------------------------------------------------------
def test_withdraw_blocked_by_issued_ballot(api):
    """PRD §3.2: "Withdrawal applies only to an ACTIVE registration and moves it
    ACTIVE -> WITHDRAWN, but it is blocked when the voter holds an absentee ballot
    in flight — that is, when any absentee ballot for the registration has a
    request status of ISSUED, RETURNED, or ACCEPTED — in which case the request is
    refused with ERR_BALLOT_BLOCKS_WITHDRAW."

    Design: Corner/validations/withdraw_blocked_by_issued_ballot_returns_conflict
    """
    election, precinct, active, ballot = fixtures.setup_ballot_in_request_state("ISSUED")
    resp = api.transition_registration(active["id"], {"target_status": "WITHDRAWN"}, OFF1)
    validate_error(resp, ERR.ERR_BALLOT_BLOCKS_WITHDRAW.value)
    reg = validate_success(api.get_registration(active["id"], OFF1), 200)
    assert reg["status"] == "ACTIVE", "a blocked withdraw leaves the registration ACTIVE"


# ---------------------------------------------------------------------------
# Close-polls cure sweep cascade (Corner: state_machines)
# ---------------------------------------------------------------------------
def test_close_polls_sweeps_open_cure_to_failed_and_rejected(api):
    """PRD §3.5: "The sweep examines every cure case of the election that is still
    in OPEN or RESPONSE_SUBMITTED and whose governing window has lapsed ... Each
    such case is moved to EXPIRED. Expiry is not silent: an expired case advances
    its linked ballot's cure status to CURE_FAILED, which in turn sets that
    ballot's request status to REJECTED — the same depth-three cascade a denial
    produces."

    Design: Corner/state_machines/close_polls_sweeps_open_cure_to_failed_and_rejected
    """
    election, precinct, active, ballot, cure_case = fixtures.setup_flagged_ballot(
        clock="2026-09-01T00:00:00Z",
    )
    e_id = election["id"]
    # Move to VOTING_OPEN (clock must be >= early_voting_start).
    fixtures.set_clock("2026-10-20T00:00:00Z")
    fixtures._transition_election(e_id, "VOTING_OPEN")
    # Advance past both election_date (2026-11-03) and the default cure_deadline
    # (2026-11-10) so close-polls finds the OPEN cure case's window lapsed.
    fixtures.set_clock("2026-11-11T00:00:00Z")
    data = validate_success(api.transition_election(e_id, {"target_status": "POLLS_CLOSED"}, ADMIN), 200)
    assert data["status"] == "POLLS_CLOSED"
    b = validate_success(api.get_absentee_ballot(ballot["id"], OFF1), 200)
    assert b["cure_status"] == "CURE_FAILED", "the swept cure case fails the ballot's cure"
    assert b["request_status"] == "REJECTED", "the failed cure rejects the request (cascade)"


# ---------------------------------------------------------------------------
# Precedence: invalid state beats segregation on recount pass (Difficulty)
# ---------------------------------------------------------------------------
def test_invalid_state_beats_segregation_on_recount_pass(api):
    """PRD §2.9: "then whether the target resource is in a legal state for the
    requested transition (ERR_INVALID_STATE). Only after these does the system
    evaluate separation-of-duties (ERR_SEGREGATION_OF_DUTIES) ..."
    PRD §3.8: "A pass that does not match a legal source status is refused with
    ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_recount_pass
    """
    # A CERTIFIED (terminal) recount; the precinct tally was recorded by canvasser-tally-1.
    election, precinct, recount = fixtures.setup_recount_both_done(
        machine_count=100, hand_count=100, reported_vote_count=100
    )
    fixtures.certify_recount(recount["id"])
    # The same canvasser who recorded the tally now submits a pass on the CERTIFIED case:
    # both the state precondition AND segregation are violated; state must win.
    resp = api.submit_recount_pass(recount["id"], {"pass": "MACHINE", "count": 100}, CANV_TALLY)
    validate_error(resp, ERR.ERR_INVALID_STATE.value)
    after = validate_success(api.get_recount_case(recount["id"], ADMIN), 200)
    assert after["status"] == "CERTIFIED"


def test_recount_pass_by_tally_recorder_blocked_in_open_case(api):
    """PRD §3.8: "Every pass submission requires that the acting X-User-ID differ
    from the precinct's tally_recorded_by_user_id — a canvasser may not recount a
    precinct whose original tally they recorded — and a violation is refused with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_recount_pass
    """
    # A fresh REQUESTED recount (legal state for a pass) so only segregation can fail.
    election, precinct = fixtures.setup_election_with_precinct("SCHEDULED", clock="2026-06-01T00:00:00Z")
    precinct = fixtures.tally_precinct(precinct["id"], reported_vote_count=100, canvasser_headers=CANV_TALLY)
    recount = fixtures.open_recount(election["id"], precinct["id"])
    resp = api.submit_recount_pass(recount["id"], {"pass": "MACHINE", "count": 100}, CANV_TALLY)
    validate_error(resp, ERR.ERR_SEGREGATION_OF_DUTIES.value)
    after = validate_success(api.get_recount_case(recount["id"], ADMIN), 200)
    assert after["status"] == "REQUESTED", "the blocked pass leaves the recount REQUESTED"
