"""Match proposal, fit-score computation, acceptance side effects, caseload
bubbling, the reassignment cycle, and license routing (PRD §3.2, §3.3, §3.4).

Covers combinatorial match_score, the non-linear reassignment state machine,
cross-entity caseload dependency, and matching corner probes.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, cleared_client, accepting_therapist, propose_match, accept_match,
    create_therapist, add_license, activate_therapist, get_therapist,
    active_match, get_match, get_match_version,
    api_client,
    make_client_headers,
)
from test_helpers import TEST_USERS


def _client(cid):
    return make_client_headers(cid)


def _clinical():
    return TEST_USERS["clinical_admin_headers"]


# ==========================================================================
# Difficulty: combinatorial_formula — match_score with three weighted inputs
# ==========================================================================
def test_match_score_three_input_weighted_sum(api):
    """PRD §3.3: "it adds 10 points for each specialty the therapist shares with the client (the
    size of the intersection between the intake's `presenting_concerns` and the therapist's
    `specialties`), plus 25 points if the therapist holds a `VALID` license covering the client's
    `state_code` and 0 otherwise, plus 2 points for each unit of the intake's `severity_score`."

    Design: Difficulty/combinatorial_formula/match_score_three_input_nonlinear_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA", severity_score=5,
                            presenting_concerns=["ANXIETY", "DEPRESSION"])
    therapist = accepting_therapist(state_code="CA",
                                    specialties=["ANXIETY", "DEPRESSION", "TRAUMA"])
    match = propose_match(client["id"], therapist["id"])
    # overlap 2 -> 20; license CA valid -> 25; severity 5 -> 10; total 55.
    assert match["match_score"] == 55, match
    assert match["status"] == "PROPOSED", match


def test_match_score_visible_immediately_in_create_response(api):
    """PRD §3.3: "The proposal creates a `Match` in `PROPOSED` status and computes its
    `match_score`."
    PRD §3.3: "it adds 10 points for each specialty the therapist shares with the client ... plus
    25 points if the therapist holds a `VALID` license covering the client's `state_code` and 0
    otherwise, plus 2 points for each unit of the intake's `severity_score`."

    Design: Corner/consistency_model/immediate_visibility_match_score_in_create_response
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA", severity_score=5, presenting_concerns=["ANXIETY"])
    therapist = accepting_therapist(state_code="CA", specialties=["ANXIETY", "TRAUMA"])
    match = propose_match(client["id"], therapist["id"])
    # overlap 1 -> 10; license CA valid -> 25; severity 5 -> 10; total 45.
    assert match["match_score"] == 45, match
    refetched = get_match(match["id"])
    assert refetched["match_score"] == 45, refetched


# ==========================================================================
# Difficulty: non_linear_state_machine — reassignment cycle
# ==========================================================================
def test_reassignment_ends_old_match_and_creates_active_successor(api):
    """PRD §3.4: "It creates a successor `Match` in `ACTIVE` for the selected new therapist ...
    On the old match, the system sets `superseded_by_match_id` to the successor's `id`, moves the
    old match to the terminal `ENDED` state, decrements the old therapist's `active_caseload` by
    one (possibly bubbling them from `FULL` back to `ACCEPTING`), and archives the old match's
    thread from `FROZEN` to `ARCHIVED`."

    Design: Difficulty/non_linear_state_machine/match_reassignment_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    ta = accepting_therapist(state_code="CA", full_name="T A")
    tb = accepting_therapist(state_code="CA", full_name="T B")
    proposed = propose_match(client["id"], ta["id"])
    match = accept_match(proposed["id"], client["id"])
    validate_success(api.request_switch(
        match["id"], {"switch_reason": "FIT"}, _client(client["id"])
    ))
    successor = validate_success(api.reassign_match(match["id"], _clinical()), 201)
    succ_id = successor["id"]
    old = get_match(match["id"])
    assert old["status"] == "ENDED", old
    assert old["superseded_by_match_id"] == succ_id, old
    assert successor["status"] == "ACTIVE", successor
    assert successor["therapist_id"] == tb["id"], successor


def test_no_eligible_therapist_rejects_reassign(api):
    """PRD §3.4: "If no candidate qualifies, the reassignment is rejected with
    `ERR_NO_ELIGIBLE_THERAPIST` (HTTP 409)."

    Design: Corner/errors/no_eligible_therapist_on_reassign
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    t = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], t["id"])
    match = accept_match(proposed["id"], client["id"])
    validate_success(api.request_switch(
        match["id"], {"switch_reason": "FIT"}, _client(client["id"])
    ))
    resp = api.reassign_match(match["id"], _clinical())
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_THERAPIST.value)


# ==========================================================================
# Difficulty: cross_entity_state_dependency — accept blocked at caseload cap
# ==========================================================================
def test_accept_blocked_when_therapist_full(api):
    """PRD §3.3: "Acceptance is allowed only when the match is in `PROPOSED`, the client's
    `risk_flag` is not `ACUTE`, the therapist is in `ACCEPTING`, the therapist's `active_caseload`
    is still below their `max_active_caseload`, and the therapist holds a `VALID` license for the
    client's `state_code`."
    PRD §3.2: "When a match becoming `ACTIVE` pushes a therapist's `active_caseload` up to equal
    `max_active_caseload`, an `ACCEPTING` therapist automatically flips to `FULL`."

    Design: Difficulty/cross_entity_state_dependency/match_accept_blocked_by_therapist_full_pair_match_therapist
    """
    set_clock("2026-06-01T00:00:00Z")
    therapist = accepting_therapist(state_code="CA", max_active_caseload=1)
    client_a = cleared_client(state_code="CA")
    proposed_a = propose_match(client_a["id"], therapist["id"])
    accept_match(proposed_a["id"], client_a["id"])  # caseload -> 1, therapist -> FULL
    client_b = cleared_client(state_code="CA")
    proposed_b = propose_match(client_b["id"], therapist["id"])
    resp = api.accept_match(proposed_b["id"], _client(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    t_after = get_therapist(therapist["id"])
    assert t_after["status"] == "FULL", t_after


def test_accept_bubbles_therapist_to_full_at_cap(api):
    """PRD §3.2: "When a match becoming `ACTIVE` pushes a therapist's `active_caseload` up to
    equal `max_active_caseload`, an `ACCEPTING` therapist automatically flips to `FULL`."

    Design: Corner/state_machines/bubble_up_therapist_full_at_caseload_cap
    """
    set_clock("2026-06-01T00:00:00Z")
    therapist = accepting_therapist(state_code="CA", max_active_caseload=1)
    client = cleared_client(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    accept_match(proposed["id"], client["id"])
    t_after = get_therapist(therapist["id"])
    assert t_after["status"] == "FULL", t_after
    assert t_after["active_caseload"] == 1, t_after


# ==========================================================================
# Corner: match starts PROPOSED (initial state)
# ==========================================================================
def test_new_match_starts_proposed(api):
    """PRD §3.3: "The proposal creates a `Match` in `PROPOSED` status and computes its
    `match_score`."

    Design: Corner/state_machines/initial_state_match_starts_proposed
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    match = validate_success(api.create_match(
        {"client_id": client["id"], "therapist_id": therapist["id"]}, _clinical()
    ), 201)
    assert match["status"] == "PROPOSED", match
    assert match["version"] == 1, match


# ==========================================================================
# Corner: license-state mismatch on propose
# ==========================================================================
def test_propose_rejected_when_no_license_for_client_state(api):
    """PRD §3.3: "a therapist with no `VALID` license for the client's `state_code` cannot be
    matched, which raises `ERR_LICENSE_STATE_MISMATCH` (HTTP 409)."

    Design: Corner/validations/license_state_mismatch_on_propose
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="TX")          # client in TX
    therapist = accepting_therapist(state_code="CA")  # licensed only in CA
    resp = api.create_match(
        {"client_id": client["id"], "therapist_id": therapist["id"]}, _clinical()
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_STATE_MISMATCH.value)
