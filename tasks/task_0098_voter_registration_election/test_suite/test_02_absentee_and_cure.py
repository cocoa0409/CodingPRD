"""Absentee ballots and signature curing.

Covers the parallel request/cure dimensions on a ballot, the cross-entity gate
that issue requires an ACTIVE registration, the cure-deny depth-3 cascade and the
cure-approve positive path, accept-time cure guard, OCC on ballot creation, and
the cure-deadline boundary.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
    factories,
)
from test_helpers.test_users import OFF1, OFF2

ERR = ApiErrorId


# ---------------------------------------------------------------------------
# Parallel dimensions on one ballot (Difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------
def test_flag_cure_advances_cure_dim_while_request_stays_returned(api):
    """PRD §3.3: "The cure dimension begins when an ElectionOfficial flags a
    returned ballot. Flagging requires the request status to be RETURNED and the
    cure status to be NONE; it supplies a reason ..., moves the cure status
    NONE -> FLAGGED, opens a cure case for the ballot, and increments the ballot's
    version."

    Design: Difficulty/non_linear_state_machine/absentee_ballot_parallel_request_and_cure_dimensions
    """
    election, precinct, active, ballot = fixtures.setup_ballot_in_request_state("RETURNED")
    data = validate_success(api.flag_cure(ballot["id"], {"reason": "SIGNATURE_MISMATCH"}, OFF1), 200)
    assert data["cure_status"] == "FLAGGED", "cure dimension advances NONE -> FLAGGED"
    assert data["request_status"] == "RETURNED", "request dimension is unaffected by flagging"


def test_returned_ballot_carries_independent_status_dimensions(api):
    """PRD §3.3: "Each absentee ballot evolves along two independent dimensions on
    the same record: a request dimension (request_status, the logistics of issuing,
    returning, and accepting) and a cure dimension (cure_status, the
    signature-adjudication track driven by a cure case)."

    Design: Difficulty/non_linear_state_machine/absentee_ballot_parallel_request_and_cure_dimensions
    """
    election, precinct, active, ballot = fixtures.setup_ballot_in_request_state("RETURNED")
    assert ballot["request_status"] == "RETURNED"
    assert ballot["cure_status"] == "NONE", "cure dimension stays NONE until flagging"


# ---------------------------------------------------------------------------
# Cross-entity gate: issue requires ACTIVE registration (Difficulty)
# ---------------------------------------------------------------------------
def test_issue_ballot_with_active_registration_succeeds(api):
    """PRD §3.3: "Issuing moves the request REQUESTED -> ISSUED, permitted only
    while the linked registration is ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/ballot_issue_requires_registration_active
    """
    election, precinct, active, ballot = fixtures.setup_ballot_in_request_state("REQUESTED")
    data = validate_success(
        api.transition_absentee_ballot(ballot["id"], {"target_request_status": "ISSUED"}, OFF1), 200
    )
    assert data["request_status"] == "ISSUED"


def test_issued_ballot_return_stamps_returned_at(api):
    """PRD §3.3: "Returning moves it ISSUED -> RETURNED, permitted only while the
    clock is before the election's election_date, and it stamps returned_at with
    the current clock instant."

    Design: Difficulty/cross_entity_state_dependency/ballot_issue_requires_registration_active
    """
    election, precinct, active, ballot = fixtures.setup_ballot_in_request_state("ISSUED")
    data = validate_success(
        api.transition_absentee_ballot(ballot["id"], {"target_request_status": "RETURNED"}, OFF1), 200
    )
    assert data["request_status"] == "RETURNED"
    assert data["returned_at"] is not None, "RETURNED must stamp returned_at"


# ---------------------------------------------------------------------------
# Cure DENY depth-3 cascade (Difficulty: transitive_cascade)
# ---------------------------------------------------------------------------
def test_cure_deny_cascades_cure_failed_then_request_rejected(api):
    """PRD §3.4: "Denying with the decision value DENY is subject to the same
    separation-of-duties check (and the same ERR_SEGREGATION_OF_DUTIES on
    violation), records adjudicated_by_user_id, moves the case
    RESPONSE_SUBMITTED -> DENIED, and triggers the depth-three cascade: the linked
    ballot's cure status advances CURE_PENDING -> CURE_FAILED, which itself sets
    that ballot's request status to REJECTED."

    Design: Difficulty/transitive_cascade/cure_deny_cascades_cure_failed_then_request_rejected
    """
    election, precinct, active, ballot, cure_case = fixtures.setup_cure_response_submitted(reviewer_headers=OFF1)
    data = validate_success(api.transition_cure_case(cure_case["id"], {"decision": "DENY"}, OFF2), 200)
    assert data["status"] == "DENIED"
    b = validate_success(api.get_absentee_ballot(ballot["id"], OFF1), 200)
    assert b["cure_status"] == "CURE_FAILED", "deny advances cure_status to CURE_FAILED"
    assert b["request_status"] == "REJECTED", "the failed cure rejects the request (depth-3 hop)"


def test_cure_deny_records_adjudicator_and_terminal_denied(api):
    """PRD §3.4: "Denying with the decision value DENY is subject to the same
    separation-of-duties check (and the same ERR_SEGREGATION_OF_DUTIES on
    violation), records adjudicated_by_user_id, moves the case
    RESPONSE_SUBMITTED -> DENIED, and triggers the depth-three cascade: the linked
    ballot's cure status advances CURE_PENDING -> CURE_FAILED, which itself sets
    that ballot's request status to REJECTED."

    Design: Difficulty/transitive_cascade/cure_deny_cascades_cure_failed_then_request_rejected
    """
    election, precinct, active, ballot, cure_case = fixtures.setup_cure_response_submitted(reviewer_headers=OFF1)
    data = validate_success(api.transition_cure_case(cure_case["id"], {"decision": "DENY"}, OFF2), 200)
    assert data["status"] == "DENIED", "DENY drives the cure case to the terminal DENIED state"
    cc = validate_success(api.get_cure_case(cure_case["id"], OFF1), 200)
    assert cc["adjudicated_by_user_id"] == "off-2", "the deny records the adjudicating official"


def test_cure_approve_cascades_cured_and_accept_succeeds(api):
    """PRD §3.4: "Approval records the acting X-User-ID as adjudicated_by_user_id,
    moves the case RESPONSE_SUBMITTED -> APPROVED, and advances the linked ballot's
    cure status CURE_PENDING -> CURED."
    PRD §3.3: "Accepting moves it RETURNED -> ACCEPTED, but only when the cure
    status is either NONE or CURED."

    Design: Corner/state_machines/cure_approve_cascades_cured_and_accept_succeeds
    """
    election, precinct, active, ballot, cure_case = fixtures.setup_cure_response_submitted(reviewer_headers=OFF1)
    validate_success(api.transition_cure_case(cure_case["id"], {"decision": "APPROVE"}, OFF2), 200)
    cured = validate_success(api.get_absentee_ballot(ballot["id"], OFF1), 200)
    assert cured["cure_status"] == "CURED"
    accepted = validate_success(
        api.transition_absentee_ballot(ballot["id"], {"target_request_status": "ACCEPTED"}, OFF1), 200
    )
    assert accepted["request_status"] == "ACCEPTED", "a CURED ballot can be accepted"


# ---------------------------------------------------------------------------
# Accept-time cure guard (Corner: state_machines / validations)
# ---------------------------------------------------------------------------
def test_accept_while_flagged_returns_ballot_not_cured(api):
    """PRD §3.3: "a ballot whose cure status is FLAGGED, CURE_PENDING, or
    CURE_FAILED is blocked from acceptance with ERR_BALLOT_NOT_CURED."

    Design: Corner/state_machines/accept_ballot_while_flagged_returns_ballot_not_cured
    """
    election, precinct, active, ballot, cure_case = fixtures.setup_flagged_ballot(reason="MISSING_SIGNATURE")
    resp = api.transition_absentee_ballot(ballot["id"], {"target_request_status": "ACCEPTED"}, OFF1)
    validate_error(resp, ERR.ERR_BALLOT_NOT_CURED.value)
    b = validate_success(api.get_absentee_ballot(ballot["id"], OFF1), 200)
    assert b["request_status"] == "RETURNED", "a blocked accept leaves request_status RETURNED"


# ---------------------------------------------------------------------------
# Registration-not-active guard on ballot request (Corner: validations)
# ---------------------------------------------------------------------------
def test_ballot_request_on_pending_registration_returns_not_active(api):
    """PRD §3.3: "The referenced registration must be ACTIVE, or the request is
    refused with ERR_REGISTRATION_NOT_ACTIVE."

    Design: Corner/validations/ballot_request_on_inactive_registration_returns_registration_not_active
    """
    election = fixtures.create_registration_open_election()
    fixtures.create_precinct(election["id"])
    reg = fixtures.create_registration(election["id"])  # never approved -> PENDING
    payload = factories.create_absentee_ballot_payload(reg["id"], reg["version"])
    validate_error(api.create_absentee_ballot(payload, OFF1), ERR.ERR_REGISTRATION_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Cure-deadline boundary (Corner: validations) — strict < deadline
# ---------------------------------------------------------------------------
def test_cure_submit_at_deadline_returns_cure_deadline_passed(api):
    """PRD §3.4: "The voter (or an ElectionOfficial acting for them) submits a
    response with the decision value SUBMIT_RESPONSE, which is admissible only
    while the case is OPEN and the clock is before the election's cure_deadline.
    ... A submission at or after the cure deadline is refused with
    ERR_CURE_DEADLINE_PASSED."
    PRD §3.5: "while the clock is before the cure_deadline the window is open, and
    exactly at the cure_deadline it is already closed."

    Design: Corner/validations/cure_submit_after_deadline_returns_cure_deadline_passed
    """
    election, precinct, active, ballot, cure_case = fixtures.setup_flagged_ballot()
    fixtures.set_clock("2026-11-10T00:00:00Z")  # == cure_deadline -> closed
    resp = api.transition_cure_case(
        cure_case["id"], {"decision": "SUBMIT_RESPONSE", "voter_response_text": "late"}, OFF1
    )
    validate_error(resp, ERR.ERR_CURE_DEADLINE_PASSED.value)
    cc = validate_success(api.get_cure_case(cure_case["id"], OFF1), 200)
    assert cc["status"] == "OPEN", "a rejected late submission leaves the cure case OPEN"


# ---------------------------------------------------------------------------
# OCC on ballot creation (Corner: cross_cutting_complexity_layers)
# ---------------------------------------------------------------------------
def test_ballot_request_with_stale_registration_version_rejected(api):
    """PRD §2.8: "A request to create an absentee ballot must include
    expected_registration_version, carrying the version of the target
    VoterRegistration as the client last observed it. If that value does not match
    the registration's current version, the create is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_registration_version_on_ballot_request
    """
    election, precinct, active = fixtures.setup_active_registration()
    stale_version = active["version"] - 1
    payload = factories.create_absentee_ballot_payload(active["id"], stale_version)
    validate_error(api.create_absentee_ballot(payload, OFF1), ERR.ERR_STALE_VERSION.value)


def test_ballot_request_with_current_registration_version_succeeds(api):
    """PRD §3.3: "On creation the ballot copies its election_id and precinct_id from
    the registration, begins with a request status of REQUESTED and a cure status
    of NONE, and carries a null returned_at."

    Design: Corner/cross_cutting_complexity_layers/occ_current_registration_version_on_ballot_request_succeeds
    """
    election, precinct, active = fixtures.setup_active_registration()
    payload = factories.create_absentee_ballot_payload(active["id"], active["version"])
    data = validate_success(api.create_absentee_ballot(payload, OFF1), 201)
    assert data["request_status"] == "REQUESTED"
    assert data["cure_status"] == "NONE"
    assert data["election_id"] == election["id"], "election_id copied from the registration"
    assert data["precinct_id"] == precinct["id"], "precinct_id copied from the registration"
