"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server is restarted (empty DB) before each test. Setup
calls go through get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" rather than a confusing assertion deep inside a test.

Identity threading: the only entity_backed role is Voter (backed by
VoterRegistration); ownership-gated voter calls would use make_voter_headers(reg_id).
Officials/canvassers/poll-workers are opaque, but distinct opaque ids are threaded
where separation-of-duties compares the acting id to a recorded prior actor.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .constants import ELECTION_DEFAULTS
from .test_users import ADMIN, OFF1, OFF2, PW1, CANV_TALLY, CANV_RECOUNT
from . import factories


# --------------------------------------------------------------------------
# Clock + election scaffolding
# --------------------------------------------------------------------------
def set_clock(current_utc: str):
    """Set the simulated server clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, ADMIN))


def create_election(clock="2026-06-01T00:00:00Z", **overrides):
    """Set the clock then create a SCHEDULED election. Returns the election dict."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(
        api_client.create_election(factories.create_election_payload(**overrides), ADMIN)
    )


def _transition_election(election_id, target_status):
    return get_success_data(
        api_client.transition_election(election_id, {"target_status": target_status}, ADMIN)
    )


def create_election_in_state(target_state, clock="2026-09-01T00:00:00Z", **overrides):
    """Create an election and walk it to target_state.

    Walks SCHEDULED -> REGISTRATION_OPEN -> VOTING_OPEN -> POLLS_CLOSED -> CERTIFIED
    as far as target_state requires. The caller controls the clock so the temporal
    preconditions for VOTING_OPEN (>= early_voting_start) and POLLS_CLOSED
    (>= election_date) are met; default clock suits REGISTRATION_OPEN.
    """
    election = create_election(clock=clock, **overrides)
    e_id = election["id"]
    order = ["SCHEDULED", "REGISTRATION_OPEN", "VOTING_OPEN", "POLLS_CLOSED", "CERTIFIED"]
    target_idx = order.index(target_state)
    for state in order[1:target_idx + 1]:
        election = _transition_election(e_id, state)
    return election


def create_registration_open_election(clock="2026-09-01T00:00:00Z", **overrides):
    """Create an election already in REGISTRATION_OPEN. Returns the election dict."""
    return create_election_in_state("REGISTRATION_OPEN", clock=clock, **overrides)


# --------------------------------------------------------------------------
# Precincts
# --------------------------------------------------------------------------
def create_precinct(election_id, **overrides):
    """Create one precinct under an election. Returns the precinct dict."""
    return get_success_data(
        api_client.create_precinct(
            factories.create_precinct_payload(election_id, **overrides), ADMIN
        )
    )


def setup_election_with_precinct(target_state="REGISTRATION_OPEN",
                                 clock="2026-09-01T00:00:00Z",
                                 election_overrides=None,
                                 precinct_overrides=None):
    """Election in target_state + one covering precinct. Returns (election, precinct)."""
    election = create_election_in_state(target_state, clock=clock, **(election_overrides or {}))
    precinct = create_precinct(election["id"], **(precinct_overrides or {}))
    return election, precinct


def tally_precinct(precinct_id, reported_vote_count=100, canvasser_headers=CANV_TALLY):
    """Record a precinct's in-person tally (PENDING -> TALLIED). Returns the precinct."""
    return get_success_data(
        api_client.tally_precinct(
            precinct_id, {"reported_vote_count": reported_vote_count}, canvasser_headers
        )
    )


# --------------------------------------------------------------------------
# Registrations
# --------------------------------------------------------------------------
def create_registration(election_id, official_headers=OFF1, **overrides):
    """Create a PENDING registration. Returns the registration dict."""
    return get_success_data(
        api_client.create_registration(
            factories.create_registration_payload(election_id, **overrides), official_headers
        )
    )


def approve_registration(registration_id, official_headers=OFF1):
    """Approve a PENDING registration -> ACTIVE. Returns the ACTIVE registration dict
    (carrying the post-approval version for OCC-gated ballot requests)."""
    return get_success_data(
        api_client.approve_registration(registration_id, official_headers)
    )


def create_active_registration(election_id, official_headers=OFF1, **reg_overrides):
    """Create a PENDING registration and approve it to ACTIVE under a matching
    precinct. Returns (registration_active, precinct). Caller may pass an
    existing precinct via precinct=... ; otherwise a covering one is created."""
    precinct = reg_overrides.pop("precinct", None)
    if precinct is None:
        precinct = create_precinct(election_id)
    reg = create_registration(election_id, official_headers=official_headers, **reg_overrides)
    active = approve_registration(reg["id"], official_headers)
    return active, precinct


def setup_active_registration(clock="2026-09-01T00:00:00Z",
                              election_overrides=None,
                              precinct_overrides=None,
                              reg_overrides=None,
                              official_headers=OFF1):
    """Full happy path to one ACTIVE registration in REGISTRATION_OPEN.

    Returns (election, precinct, active_registration). The active_registration
    dict carries the post-approval `version` used as expected_registration_version.
    """
    election, precinct = setup_election_with_precinct(
        "REGISTRATION_OPEN", clock=clock,
        election_overrides=election_overrides, precinct_overrides=precinct_overrides,
    )
    reg = create_registration(election["id"], official_headers=official_headers, **(reg_overrides or {}))
    active = approve_registration(reg["id"], official_headers)
    return election, precinct, active


# --------------------------------------------------------------------------
# Absentee ballots
# --------------------------------------------------------------------------
def request_absentee_ballot(registration_id, expected_registration_version,
                            official_headers=OFF1, **overrides):
    """Request an absentee ballot against an ACTIVE registration. Returns the ballot."""
    return get_success_data(
        api_client.create_absentee_ballot(
            factories.create_absentee_ballot_payload(
                registration_id, expected_registration_version, **overrides
            ),
            official_headers,
        )
    )


def _transition_ballot(ballot_id, target_request_status, official_headers=OFF1):
    return get_success_data(
        api_client.transition_absentee_ballot(
            ballot_id, {"target_request_status": target_request_status}, official_headers
        )
    )


def setup_ballot_in_request_state(target_request_status,
                                  clock="2026-09-01T00:00:00Z",
                                  official_headers=OFF1,
                                  reg_overrides=None):
    """Build an ACTIVE registration with an absentee ballot walked to
    target_request_status (REQUESTED / ISSUED / RETURNED / ACCEPTED).

    Returns (election, precinct, active_registration, ballot).
    """
    election, precinct, active = setup_active_registration(
        clock=clock, reg_overrides=reg_overrides, official_headers=official_headers
    )
    ballot = request_absentee_ballot(active["id"], active["version"], official_headers)
    order = ["REQUESTED", "ISSUED", "RETURNED", "ACCEPTED"]
    target_idx = order.index(target_request_status)
    for state in order[1:target_idx + 1]:
        ballot = _transition_ballot(ballot["id"], state, official_headers)
    return election, precinct, active, ballot


def flag_ballot_cure(ballot_id, reason="SIGNATURE_MISMATCH", official_headers=OFF1):
    """Flag a RETURNED ballot (cure_status NONE -> FLAGGED); opens a CureCase.
    Returns the updated ballot dict."""
    return get_success_data(
        api_client.flag_cure(ballot_id, {"reason": reason}, official_headers)
    )


def get_cure_case_for_ballot(ballot_id, official_headers=OFF1):
    """Fetch the CureCase opened for a flagged ballot. Returns the cure case dict."""
    resp = api_client.list_cure_cases(official_headers, params={"ballot_id": ballot_id})
    cases = resp.json()["data"]
    assert cases, f"Setup step failed: no cure case found for ballot {ballot_id}"
    return cases[0]


def setup_flagged_ballot(reason="SIGNATURE_MISMATCH",
                         clock="2026-09-01T00:00:00Z",
                         official_headers=OFF1):
    """RETURNED ballot, cure_status FLAGGED, with its OPEN CureCase.

    Returns (election, precinct, active_registration, ballot, cure_case).
    """
    election, precinct, active, ballot = setup_ballot_in_request_state(
        "RETURNED", clock=clock, official_headers=official_headers
    )
    ballot = flag_ballot_cure(ballot["id"], reason=reason, official_headers=official_headers)
    cure_case = get_cure_case_for_ballot(ballot["id"], official_headers=official_headers)
    return election, precinct, active, ballot, cure_case


def submit_cure_response(cure_case_id, voter_response_text="this is me", official_headers=OFF1):
    """Submit a cure response (OPEN -> RESPONSE_SUBMITTED); advances ballot
    cure_status FLAGGED -> CURE_PENDING. Returns the cure case dict."""
    return get_success_data(
        api_client.transition_cure_case(
            cure_case_id,
            {"decision": "SUBMIT_RESPONSE", "voter_response_text": voter_response_text},
            official_headers,
        )
    )


def setup_cure_response_submitted(clock="2026-09-01T00:00:00Z",
                                  reviewer_headers=OFF1):
    """A flagged ballot whose CureCase is RESPONSE_SUBMITTED (cure_status CURE_PENDING).

    The registration is reviewed by reviewer_headers (off-1 by default), so a
    DIFFERENT official may adjudicate the cure without tripping segregation.
    Returns (election, precinct, active_registration, ballot, cure_case).
    """
    election, precinct, active, ballot, cure_case = setup_flagged_ballot(
        clock=clock, official_headers=reviewer_headers
    )
    cure_case = submit_cure_response(cure_case["id"], official_headers=reviewer_headers)
    return election, precinct, active, ballot, cure_case


# --------------------------------------------------------------------------
# Voting machines + failures
# --------------------------------------------------------------------------
def create_voting_machine(precinct_id, **overrides):
    """Register a voting machine at a precinct. Returns the machine dict
    (carrying its creation `version` for OCC failure reports)."""
    return get_success_data(
        api_client.create_voting_machine(
            factories.create_voting_machine_payload(precinct_id, **overrides), ADMIN
        )
    )


def setup_precinct_with_primary(clock="2026-11-03T12:00:00Z", precinct_overrides=None):
    """A precinct with one OPERATIONAL PRIMARY machine (capacity 30).
    Returns (election, precinct, primary_machine)."""
    election, precinct = setup_election_with_precinct(
        "SCHEDULED", clock=clock, precinct_overrides=precinct_overrides
    )
    primary = create_voting_machine(precinct["id"], serial="M-1", role="PRIMARY", capacity=30)
    return election, precinct, primary


def report_machine_failure(machine_id, expected_machine_version, poll_worker_headers=PW1):
    """Report a PRIMARY machine failure; runs the backup selector. Returns the
    MachineFailure dict (resolution, backup_machine_id)."""
    return get_success_data(
        api_client.create_machine_failure(
            factories.create_machine_failure_payload(machine_id, expected_machine_version),
            poll_worker_headers,
        )
    )


def setup_failed_primary_with_backup(clock="2026-11-03T12:00:00Z", backup_capacity=25):
    """A precinct with a FAILED PRIMARY (M-1) covered by an activated BACKUP (M-2).

    Returns (election, precinct, primary, backup, failure). After this, the backup's
    backup_for_machine_id points at the primary and the primary is FAILED.
    """
    election, precinct, primary = setup_precinct_with_primary(clock=clock)
    backup = create_voting_machine(precinct["id"], serial="M-2", role="BACKUP", capacity=backup_capacity)
    failure = report_machine_failure(primary["id"], primary["version"])
    return election, precinct, primary, backup, failure


# --------------------------------------------------------------------------
# Tallies, recounts
# --------------------------------------------------------------------------
def open_recount(election_id, precinct_id):
    """Open a recount on a TALLIED precinct (snapshots original_count). Returns the recount."""
    return get_success_data(
        api_client.create_recount_case(
            factories.create_recount_case_payload(election_id, precinct_id), ADMIN
        )
    )


def submit_pass(recount_id, pass_type, count, canvasser_headers=CANV_RECOUNT):
    """Submit one recount pass (MACHINE or HAND). Returns the recount dict."""
    return get_success_data(
        api_client.submit_recount_pass(
            recount_id, {"pass": pass_type, "count": count}, canvasser_headers
        )
    )


def setup_recount_both_done(machine_count, hand_count,
                            reported_vote_count=100,
                            clock="2026-06-01T00:00:00Z",
                            recount_canvasser=CANV_RECOUNT):
    """A RecountCase in BOTH_DONE with both passes recorded, on a TALLIED precinct.

    The precinct tally is recorded by canvasser-tally-1; the recount passes are run
    by a DIFFERENT canvasser (recount_canvasser) to satisfy separation of duties.
    Returns (election, precinct, recount).
    """
    election, precinct = setup_election_with_precinct("SCHEDULED", clock=clock)
    precinct = tally_precinct(precinct["id"], reported_vote_count=reported_vote_count)
    recount = open_recount(election["id"], precinct["id"])
    submit_pass(recount["id"], "MACHINE", machine_count, recount_canvasser)
    recount = submit_pass(recount["id"], "HAND", hand_count, recount_canvasser)
    return election, precinct, recount


def certify_recount(recount_id):
    """Certify a BOTH_DONE recount (runs recount_certification; writes back to precinct).
    Returns the recount dict."""
    return get_success_data(
        api_client.transition_recount_case(recount_id, {"target_status": "CERTIFIED"}, ADMIN)
    )


def dismiss_recount(recount_id):
    """Dismiss a recount (precinct count left unchanged). Returns the recount dict."""
    return get_success_data(
        api_client.transition_recount_case(recount_id, {"target_status": "DISMISSED"}, ADMIN)
    )
