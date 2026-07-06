"""Selection: candidate vetting, the strike/rank list, and the appoint selector."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_party_headers, make_neutral_headers,
    create_ranking_payload, add_candidate_payload,
)
from test_helpers.fixtures import (
    ADMIN, create_case, create_neutral, add_two_parties, add_party,
    open_selection, case_version, find_party,
    setup_selection_with_candidate, setup_selection_two_cleared_candidates,
    setup_selection_two_proposed_candidates,
)

ADM = ADMIN


def _candidate(api, case_id, candidate_id):
    for c in validate_success(api.list_case_candidates(case_id, ADM), 200):
        if c["id"] == candidate_id:
            return c
    raise AssertionError("candidate not found")


# ---- Difficulty: appoint cascade ----------------------------------------

def test_appoint_promotes_winner_and_sweeps_siblings(api):
    """PRD 3.5: "The winning candidate moves from `CLEARED` to `APPOINTED`." PRD 3.5:
    "Every other candidate still open on the case — those in `PROPOSED`, `DISCLOSED`,
    `CLEARED`, or `OBJECTED` — is swept to `NOT_SELECTED`." PRD 3.5: "the winner is the
    eligible candidate with the highest `aggregate_rank_score`".

    Design: Difficulty/transitive_cascade/appoint_sets_winner_and_cascades_siblings_not_selected
    """
    ctx = setup_selection_two_cleared_candidates(api, rank_first=True)
    validate_success(api.appoint_case(ctx["case"]["id"],
                                      {"expected_case_version": case_version(api, ctx["case"]["id"])}, ADM), 200)
    assert _candidate(api, ctx["case"]["id"], ctx["cand1"]["id"])["status"] == "APPOINTED"
    assert _candidate(api, ctx["case"]["id"], ctx["cand2"]["id"])["status"] == "NOT_SELECTED"


def test_appoint_sets_case_appointed_and_neutral_reference(api):
    """PRD 3.5: "a `CaseAdministrator` appoints a neutral, moving the case from
    `SELECTION` to `APPOINTED`." PRD 3.5: "The case's `appointed_neutral_id` is set to
    that candidate's `neutral_id`".

    Design: Difficulty/transitive_cascade/appoint_sets_winner_and_cascades_siblings_not_selected
    """
    ctx = setup_selection_two_cleared_candidates(api, rank_first=True)
    data = validate_success(api.appoint_case(ctx["case"]["id"],
                                             {"expected_case_version": case_version(api, ctx["case"]["id"])}, ADM), 200)
    assert data["status"] == "APPOINTED"
    assert data["appointed_neutral_id"] == ctx["n1"]["id"]


# ---- Corner: appoint tie-break (unranked -> earliest created_at) ---------

def test_appoint_tie_break_earliest_created_at_wins(api):
    """PRD 3.5: "ties are broken in favor of the earliest-created candidate (by
    `created_at` ascending), and because a wholly unranked pool ties at a score of zero,
    the earliest candidate wins by default. The candidate's `id` is never used as a
    tiebreaker."

    Design: Corner/calculations/appoint_tie_break_earliest_created_at_wins
    """
    ctx = setup_selection_two_cleared_candidates(api, rank_first=False)
    data = validate_success(api.appoint_case(ctx["case"]["id"],
                                             {"expected_case_version": case_version(api, ctx["case"]["id"])}, ADM), 200)
    assert data["appointed_neutral_id"] == ctx["n1"]["id"]
    assert _candidate(api, ctx["case"]["id"], ctx["cand1"]["id"])["status"] == "APPOINTED"
    assert _candidate(api, ctx["case"]["id"], ctx["cand2"]["id"])["status"] == "NOT_SELECTED"


# ---- Difficulty: appoint with empty eligible set -------------------------

def test_appoint_with_no_cleared_candidate_rejected(api):
    """PRD 3.5: "The eligible set is every candidate whose status is `CLEARED` and whose
    `is_struck` is false. If that set is empty, the appointment is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATE`."

    Design: Difficulty/boundary_precision_check/appoint_with_empty_eligible_set_rejected
    """
    ctx = setup_selection_with_candidate(api, disclose_it=False)  # candidate stays PROPOSED
    resp = api.appoint_case(ctx["case"]["id"],
                            {"expected_case_version": case_version(api, ctx["case"]["id"])}, ADM)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CANDIDATE.value)


def test_appoint_with_only_struck_cleared_candidate_rejected(api):
    """PRD 3.5: "The eligible set is every candidate whose status is `CLEARED` and whose
    `is_struck` is false. If that set is empty, the appointment is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATE`." PRD 3.4: "A candidate's `is_struck` is true whenever any
    active `STRIKE` ranking targets it."

    Design: Difficulty/boundary_precision_check/appoint_with_empty_eligible_set_rejected
    """
    ctx = setup_selection_with_candidate(api, disclose_it=True, clear_it=True)
    validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["candidate"]["id"], party_id=ctx["pA"]["id"], action="STRIKE"),
        make_party_headers(ctx["pA"]["id"])), 201)
    resp = api.appoint_case(ctx["case"]["id"],
                            {"expected_case_version": case_version(api, ctx["case"]["id"])}, ADM)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CANDIDATE.value)


# ---- Difficulty: disclosure gated on neutral roster ACTIVE ---------------

def test_disclose_blocked_when_neutral_suspended(api):
    """PRD 3.3: "the disclosing neutral's `roster_status` must be `ACTIVE`, else the
    disclosure is rejected with `ERR_NEUTRAL_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/disclose_blocked_when_neutral_suspended
    """
    ctx = setup_selection_with_candidate(api, disclose_it=False)
    validate_success(api.transition_neutral(ctx["neutral"]["id"], {"roster_status": "SUSPENDED"}, ADM), 200)
    resp = api.disclose_candidate(ctx["candidate"]["id"],
                                  {"disclosure_text": "none", "has_conflict": False},
                                  make_neutral_headers(ctx["neutral"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NEUTRAL_NOT_ACTIVE.value)


def test_disclose_blocked_when_neutral_retired(api):
    """PRD 3.3: "the disclosing neutral's `roster_status` must be `ACTIVE`, else the
    disclosure is rejected with `ERR_NEUTRAL_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/disclose_blocked_when_neutral_suspended
    """
    ctx = setup_selection_with_candidate(api, disclose_it=False)
    validate_success(api.transition_neutral(ctx["neutral"]["id"], {"roster_status": "RETIRED"}, ADM), 200)
    resp = api.disclose_candidate(ctx["candidate"]["id"],
                                  {"disclosure_text": "none", "has_conflict": False},
                                  make_neutral_headers(ctx["neutral"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NEUTRAL_NOT_ACTIVE.value)


# ---- Difficulty: strike withdrawal restores the allowance ----------------

def test_strike_withdraw_restores_allowance(api):
    """PRD 3.4: "Withdrawal is compensating: it recomputes the target candidate's
    `aggregate_rank_score` and `is_struck`, and recomputes the party's `strikes_used`
    and `strikes_remaining` — a withdrawn strike returns its allowance to the party."

    Design: Difficulty/compensating_invariant/strike_withdraw_restores_allowance
    """
    ctx = setup_selection_two_proposed_candidates(api, strikes_per_party=2)
    r1 = validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["cand1"]["id"], party_id=ctx["pA"]["id"], action="STRIKE"),
        make_party_headers(ctx["pA"]["id"])), 201)
    validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["cand2"]["id"], party_id=ctx["pA"]["id"], action="STRIKE"),
        make_party_headers(ctx["pA"]["id"])), 201)
    validate_success(api.withdraw_ranking(r1["id"], make_party_headers(ctx["pA"]["id"])), 200)
    party = find_party(api, ctx["case"]["id"], ctx["pA"]["id"])
    assert party["strikes_used"] == 1
    assert party["strikes_remaining"] == 1


def test_strike_accumulation_then_withdraw_conserves_allowance(api):
    """PRD 3.4: "A party's `strikes_used` counts that party's active `STRIKE` rankings,
    and its `strikes_remaining` is the case's `strikes_per_party` less that count." PRD
    3.4: "a withdrawn strike returns its allowance to the party."

    Design: Difficulty/compensating_invariant/strike_withdraw_restores_allowance
    """
    ctx = setup_selection_two_proposed_candidates(api, strikes_per_party=2)
    r1 = validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["cand1"]["id"], party_id=ctx["pA"]["id"], action="STRIKE"),
        make_party_headers(ctx["pA"]["id"])), 201)
    validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["cand2"]["id"], party_id=ctx["pA"]["id"], action="STRIKE"),
        make_party_headers(ctx["pA"]["id"])), 201)
    before = find_party(api, ctx["case"]["id"], ctx["pA"]["id"])
    assert before["strikes_used"] == 2 and before["strikes_remaining"] == 0
    validate_success(api.withdraw_ranking(r1["id"], make_party_headers(ctx["pA"]["id"])), 200)
    after = find_party(api, ctx["case"]["id"], ctx["pA"]["id"])
    assert after["strikes_used"] == 1 and after["strikes_remaining"] == 1


# ---- Corner: ranking and selection validation gates ----------------------

def test_open_selection_without_respondent_returns_parties_incomplete(api):
    """PRD 3.1: "Opening candidate selection advances the case from `FILED` to
    `SELECTION`, but only if the case already has at least one party whose `role` is
    `CLAIMANT` and at least one whose `role` is `RESPONDENT`; otherwise the transition is
    rejected with `ERR_PARTIES_INCOMPLETE`."

    Design: Corner/validations/open_selection_without_respondent_returns_parties_incomplete
    """
    case = create_case(api, claim_amount_cents=500_000)
    add_party(api, case["id"], "CLAIMANT", "A", 100)
    resp = api.transition_case(case["id"], {"to_status": "SELECTION"}, ADM)
    validate_error(resp, ApiErrorId.ERR_PARTIES_INCOMPLETE.value)


def test_add_mediator_candidate_to_arbitration_returns_type_mismatch(api):
    """PRD 3.3: "an `ARBITRATION` case admits only a neutral whose `neutral_type` is
    `ARBITRATOR` or `BOTH` ... an incompatible pairing is rejected with
    `ERR_NEUTRAL_TYPE_MISMATCH`."

    Design: Corner/validations/add_mediator_candidate_to_arbitration_returns_type_mismatch
    """
    neutral = create_neutral(api, neutral_type="MEDIATOR")
    case = create_case(api, claim_amount_cents=500_000)
    add_two_parties(api, case["id"])
    open_selection(api, case["id"])
    resp = api.add_candidate(case["id"], add_candidate_payload(
        neutral_id=neutral["id"], expected_case_version=case_version(api, case["id"])), ADM)
    validate_error(resp, ApiErrorId.ERR_NEUTRAL_TYPE_MISMATCH.value)


def test_clear_candidate_with_conflict_returns_candidate_has_conflict(api):
    """PRD 3.3: "a candidate whose `has_conflict` is true cannot be cleared and the
    attempt is rejected with `ERR_CANDIDATE_HAS_CONFLICT`."

    Design: Corner/validations/clear_candidate_with_conflict_returns_candidate_has_conflict
    """
    ctx = setup_selection_with_candidate(api, disclose_it=True, has_conflict=True)
    resp = api.transition_candidate(ctx["candidate"]["id"], {"to_status": "CLEARED"}, ADM)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_HAS_CONFLICT.value)


def test_strike_over_allowance_returns_strike_budget_exceeded(api):
    """PRD 3.4: "if casting a strike would push the party's `strikes_used` beyond the
    case's `strikes_per_party`, it is rejected with `ERR_STRIKE_BUDGET_EXCEEDED`."

    Design: Corner/validations/strike_over_allowance_returns_strike_budget_exceeded
    """
    ctx = setup_selection_two_proposed_candidates(api, strikes_per_party=1)
    validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["cand1"]["id"], party_id=ctx["pA"]["id"], action="STRIKE"),
        make_party_headers(ctx["pA"]["id"])), 201)
    resp = api.create_ranking(create_ranking_payload(
        candidate_id=ctx["cand2"]["id"], party_id=ctx["pA"]["id"], action="STRIKE"),
        make_party_headers(ctx["pA"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STRIKE_BUDGET_EXCEEDED.value)


def test_duplicate_ranking_on_same_candidate_returns_duplicate_ranking(api):
    """PRD 3.4: "A party may not hold two active rankings on the same candidate; a second
    active ranking on a candidate the party has already ranked or struck is rejected with
    `ERR_DUPLICATE_RANKING`."

    Design: Corner/validations/duplicate_ranking_on_same_candidate_returns_duplicate_ranking
    """
    ctx = setup_selection_with_candidate(api, disclose_it=False)
    validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["candidate"]["id"], party_id=ctx["pA"]["id"], action="RANK", rank_value=5),
        make_party_headers(ctx["pA"]["id"])), 201)
    resp = api.create_ranking(create_ranking_payload(
        candidate_id=ctx["candidate"]["id"], party_id=ctx["pA"]["id"], action="RANK", rank_value=3),
        make_party_headers(ctx["pA"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RANKING.value)


def test_ranking_party_from_other_case_returns_not_case_party(api):
    """PRD 3.4: "The acting party must belong to the same case as the targeted candidate;
    if the ranking's `party_id` is not a party of the candidate's case, the request is
    rejected with `ERR_NOT_CASE_PARTY`."

    Design: Corner/validations/ranking_party_from_other_case_returns_not_case_party
    """
    ctx = setup_selection_with_candidate(api, disclose_it=False)
    other_case = create_case(api, claim_amount_cents=500_000)
    p2 = add_party(api, other_case["id"], "CLAIMANT", "A2", 100)
    resp = api.create_ranking(create_ranking_payload(
        candidate_id=ctx["candidate"]["id"], party_id=p2["id"], action="RANK", rank_value=1),
        make_party_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_CASE_PARTY.value)
