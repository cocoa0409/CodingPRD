"""Voting: tally methods, cast/withdraw/re-cast cycle, eligibility, ballot validation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    scenario_multi_proposal_on_ballot, scenario_cast_allocation_ballot,
    scenario_voting_cycle, scenario_on_ballot_proposal,
    open_ballot, add_entry, cast_ballot,
    new_resident, verify_resident, new_proposal, submit_proposal, transition,
    new_cycle, new_category, set_clock, advance_to,
    make_resident_headers, TEST_USERS,
)

ADMIN = TEST_USERS["budget_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / vote_tally_ranked_vs_allocation_winner_flips
# ---------------------------------------------------------------------------

def test_ranked_tally_awards_borda_points_by_rank(api):
    """PRD §3.6: "an entry earns points equal to ten minus one less than its rank —
    equivalently, a first-choice entry (rank 1) earns 10 points, a rank-2 entry earns 9,
    and so on downward"
    PRD §3.6: "A proposal's ranked score is the sum of these `points` over all active
    entries on cast ballots that reference it."

    Design: Difficulty/dual_variant_calc/vote_tally_ranked_vs_allocation_winner_flips
    """
    sc = scenario_multi_proposal_on_ballot(api, 
        voting_method="RANKED", n_residents=2, per_voter_cap=0,
        proposal_specs=[{"title": "A_r"}, {"title": "B_r"}],
    )
    a, b = sc["proposals"]
    for rid in sc["residents"]:
        bid = open_ballot(api, sc["cyc"], rid)["id"]
        add_entry(api, bid, rid, a, rank=1)
        add_entry(api, bid, rid, b, rank=2)
        cast_ballot(api, bid, rid)
    pa = validate_success(api.get_proposal(a, ADMIN))
    pb = validate_success(api.get_proposal(b, ADMIN))
    assert pa["vote_score"] == 20, f"A ranked 1st by both => 10+10=20, got {pa['vote_score']}"
    assert pb["vote_score"] == 18, f"B ranked 2nd by both => 9+9=18, got {pb['vote_score']}"
    assert pa["vote_score"] > pb["vote_score"], "under RANKED, A wins"


def test_allocation_tally_sums_allocated_cents_flipping_the_winner(api):
    """PRD §3.6: "Under the allocation method the score is instead the sum of
    `allocated_cents` over all active entries on cast ballots that reference the proposal;
    ranks are ignored."

    Design: Difficulty/dual_variant_calc/vote_tally_ranked_vs_allocation_winner_flips
    """
    sc = scenario_multi_proposal_on_ballot(api, 
        voting_method="ALLOCATION", n_residents=2,
        proposal_specs=[{"title": "A_l"}, {"title": "B_l"}],
    )
    a, b = sc["proposals"]
    r1, r2 = sc["residents"]
    b1 = open_ballot(api, sc["cyc"], r1)["id"]
    add_entry(api, b1, r1, a, allocated_cents=1000)
    cast_ballot(api, b1, r1)
    b2 = open_ballot(api, sc["cyc"], r2)["id"]
    add_entry(api, b2, r2, b, allocated_cents=9000)
    cast_ballot(api, b2, r2)
    pa = validate_success(api.get_proposal(a, ADMIN))
    pb = validate_success(api.get_proposal(b, ADMIN))
    assert pa["vote_score"] == 1000, f"A allocated 1000, got {pa['vote_score']}"
    assert pb["vote_score"] == 9000, f"B allocated 9000, got {pb['vote_score']}"
    assert pb["vote_score"] > pa["vote_score"], "under ALLOCATION, B wins (winner flips)"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / ballot_cast_withdraw_recast_cycle
# ---------------------------------------------------------------------------

def test_ballot_returns_to_cast_after_withdraw_then_recast(api):
    """PRD §3.6: "re-casting a `WITHDRAWN` ballot re-activates its entries, re-adds their
    contribution to the referenced proposals' scores, refreshes `cast_at`, and again
    increments the ballot's `version`."

    Design: Difficulty/non_linear_state_machine/ballot_cast_withdraw_recast_cycle
    """
    sc = scenario_cast_allocation_ballot(api, allocated_cents=4000)
    validate_success(api.withdraw_ballot(sc["bid"], make_resident_headers(sc["rid"])))
    recast = validate_success(api.cast_ballot(sc["bid"], make_resident_headers(sc["rid"])))
    assert recast["status"] == "CAST"
    assert recast["total_allocated_cents"] == 4000


def test_vote_score_restored_after_withdraw_then_recast(api):
    """PRD §3.6: "re-casting a `WITHDRAWN` ballot re-activates its entries, re-adds their
    contribution to the referenced proposals' scores"

    Design: Difficulty/non_linear_state_machine/ballot_cast_withdraw_recast_cycle
    """
    sc = scenario_cast_allocation_ballot(api, allocated_cents=4000)
    validate_success(api.withdraw_ballot(sc["bid"], make_resident_headers(sc["rid"])))
    validate_success(api.cast_ballot(sc["bid"], make_resident_headers(sc["rid"])))
    prop = validate_success(api.get_proposal(sc["pid"], ADMIN))
    assert prop["vote_score"] == 4000, f"net of withdraw+recast the score returns to 4000, got {prop['vote_score']}"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / vote_mass_conservation_cast_then_withdraw
# ---------------------------------------------------------------------------

def test_withdraw_zeroes_ballot_total_allocated(api):
    """PRD §3.6: "It also resets the ballot's `total_allocated_cents` to zero and increments
    the ballot's `version` by one."

    Design: Difficulty/compensating_invariant/vote_mass_conservation_cast_then_withdraw
    """
    sc = scenario_cast_allocation_ballot(api, allocated_cents=5000)
    withdrawn = validate_success(api.withdraw_ballot(sc["bid"], make_resident_headers(sc["rid"])))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["total_allocated_cents"] == 0


def test_withdraw_subtracts_contribution_back_out_of_vote_score(api):
    """PRD §3.6: "Withdrawal deactivates every entry — setting each entry's `active` flag off
    — and subtracts this ballot's contribution back out of every referenced proposal's
    `vote_score`, so that the reversal precisely undoes what the cast added."

    Design: Difficulty/compensating_invariant/vote_mass_conservation_cast_then_withdraw
    """
    sc = scenario_cast_allocation_ballot(api, allocated_cents=5000)
    before = validate_success(api.get_proposal(sc["pid"], ADMIN))
    assert before["vote_score"] == 5000
    validate_success(api.withdraw_ballot(sc["bid"], make_resident_headers(sc["rid"])))
    after = validate_success(api.get_proposal(sc["pid"], ADMIN))
    assert after["vote_score"] == 0, f"withdraw must reverse the 5000 contribution, got {after['vote_score']}"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / voter_age_exactly_min_is_eligible
# ---------------------------------------------------------------------------

def test_resident_exactly_min_age_is_computed_as_16(api):
    """PRD §3.1: "It is computed as the difference between the clock's current year and the
    birth year, reduced by one when the current month-and-day falls before the birth
    month-and-day (that is, when the resident has not yet had their birthday this year)."

    Design: Difficulty/boundary_precision_check/voter_age_exactly_min_is_eligible
    """
    sc = scenario_voting_cycle(api, dob="2010-04-15", min_voter_age=16, resident_state="verified")
    res = validate_success(api.get_resident(sc["rid"], ADMIN))
    assert res["age"] == 16, f"born 2010-04-15 at 2026-04-15 clock is exactly 16, got {res['age']}"


def test_ballot_opens_when_age_exactly_equals_min_voter_age(api):
    """PRD §3.5: "the resident's derived `age` must be at least the cycle's `min_voter_age`,
    evaluated inclusively so that a resident whose age exactly equals the floor is eligible
    while one a single year short is not"

    Design: Difficulty/boundary_precision_check/voter_age_exactly_min_is_eligible
    """
    sc = scenario_voting_cycle(api, dob="2010-04-15", min_voter_age=16, resident_state="verified")
    ballot = validate_success(api.create_ballot(sc["cyc"], make_resident_headers(sc["rid"])), expected_status=201)
    assert ballot["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / ballot_create_requires_resident_verified
# ---------------------------------------------------------------------------

def test_pending_resident_cannot_open_ballot(api):
    """PRD §3.5: "The voter must be verified: a resident whose `eligibility_status` is
    anything other than `VERIFIED` is turned away with `ERR_RESIDENT_NOT_ELIGIBLE`
    (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/ballot_create_requires_resident_verified
    """
    sc = scenario_voting_cycle(api, dob="1990-01-01", resident_state="pending")
    resp = api.create_ballot(sc["cyc"], make_resident_headers(sc["rid"]))
    validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ELIGIBLE.value)


def test_verified_resident_of_the_same_cycle_may_open_ballot(api):
    """PRD §3.5: "The voter must be verified: a resident whose `eligibility_status` is
    anything other than `VERIFIED` is turned away with `ERR_RESIDENT_NOT_ELIGIBLE`
    (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/ballot_create_requires_resident_verified
    """
    sc = scenario_voting_cycle(api, dob="1990-01-01", resident_state="verified")
    ballot = validate_success(api.create_ballot(sc["cyc"], make_resident_headers(sc["rid"])), expected_status=201)
    assert ballot["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: calculations / corner_ballot_create_under_age_rejected
# ---------------------------------------------------------------------------

def test_ballot_create_under_age_rejected(api):
    """PRD §3.5: "The voter must also clear the age floor — the resident's derived `age`
    must be at least the cycle's `min_voter_age`, evaluated inclusively so that a resident
    whose age exactly equals the floor is eligible while one a single year short is not —
    and failing this yields `ERR_UNDER_AGE` (HTTP 422)."

    Design: Corner/calculations/corner_ballot_create_under_age_rejected
    """
    sc = scenario_voting_cycle(api, dob="2010-04-16", min_voter_age=16, resident_state="verified")
    res = validate_success(api.get_resident(sc["rid"], ADMIN))
    assert res["age"] == 15, f"born 2010-04-16 at 2026-04-15 clock is 15, got {res['age']}"
    resp = api.create_ballot(sc["cyc"], make_resident_headers(sc["rid"]))
    validate_error(resp, ApiErrorId.ERR_UNDER_AGE.value)


# ---------------------------------------------------------------------------
# Corner: validations / corner_duplicate_ballot_rejected
# ---------------------------------------------------------------------------

def test_second_ballot_in_same_cycle_rejected_as_duplicate(api):
    """PRD §3.5: "if the resident already has a ballot in `DRAFT` or `CAST` status in this
    cycle, a second creation is a duplicate and is rejected with `ERR_DUPLICATE_BALLOT`
    (HTTP 409)."

    Design: Corner/validations/corner_duplicate_ballot_rejected
    """
    sc = scenario_voting_cycle(api, dob="1990-01-01", resident_state="verified")
    validate_success(api.create_ballot(sc["cyc"], make_resident_headers(sc["rid"])), expected_status=201)
    resp = api.create_ballot(sc["cyc"], make_resident_headers(sc["rid"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT.value)


# ---------------------------------------------------------------------------
# Corner: validations / corner_duplicate_rank_on_cast_rejected
# ---------------------------------------------------------------------------

def test_ranked_cast_with_two_entries_at_same_rank_rejected(api):
    """PRD §3.6: "Under the ranked method, the ballot's active entries must all carry
    distinct ranks, each within 1 to 10; two active entries sharing a rank are rejected with
    `ERR_DUPLICATE_RANK` (HTTP 422)."

    Design: Corner/validations/corner_duplicate_rank_on_cast_rejected
    """
    sc = scenario_multi_proposal_on_ballot(api, 
        voting_method="RANKED", n_residents=1, per_voter_cap=0,
        proposal_specs=[{"title": "A"}, {"title": "B"}],
    )
    a, b = sc["proposals"]
    rid = sc["residents"][0]
    bid = open_ballot(api, sc["cyc"], rid)["id"]
    add_entry(api, bid, rid, a, rank=1)
    add_entry(api, bid, rid, b, rank=1)
    resp = api.cast_ballot(bid, make_resident_headers(rid))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RANK.value)


# ---------------------------------------------------------------------------
# Corner: validations / corner_entry_for_non_on_ballot_proposal_rejected
# ---------------------------------------------------------------------------

def test_entry_referencing_non_on_ballot_proposal_rejected(api):
    """PRD §3.5: "An entry may only reference a proposal that is actually on the ballot —
    its `proposal_id` must resolve to a proposal whose status is `ON_BALLOT`, and otherwise
    the entry is rejected with `ERR_PROPOSAL_NOT_ON_BALLOT` (HTTP 409)."

    Design: Corner/validations/corner_entry_for_non_on_ballot_proposal_rejected
    """
    set_clock(api, "2026-04-15T00:00:00Z")
    cyc = new_cycle(api, name="PBnb", voting_method="ALLOCATION", min_voter_age=16)
    cat = new_category(api, cyc["id"])
    res = new_resident(api)
    verify_resident(api, res["id"])
    transition(api, cyc["id"], "SUBMISSION")
    # A proposal that stays in DRAFT (never submitted / costed) — never reaches ON_BALLOT.
    draft = new_proposal(api, cyc["id"], cat["id"], res["id"], title="Draft")
    transition(api, cyc["id"], "DEVELOPMENT")
    transition(api, cyc["id"], "VOTING")
    bid = open_ballot(api, cyc["id"], res["id"])["id"]
    resp = api.add_ballot_entry(bid, {"proposal_id": draft["id"], "allocated_cents": 1000}, make_resident_headers(res["id"]))
    validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_ON_BALLOT.value)
