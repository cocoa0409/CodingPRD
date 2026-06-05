"""The matching engine: scoring, tie-breaking, candidate pool, proposal OCC,
supersede cascade, and the per-child offered-proposal invariant.

Mostly queue-A (Difficulty) translations plus queue-B proposal/OCC corners.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    fixtures as fx,
)

COORD = fx.COORD
SCREENER = fx.SCREENER
SPECIALIST = fx.SPECIALIST


def test_interest_score_three_component_value(api):
    """PRD §3.3: "The volunteer's score is the interest component weighted by
    0.6, plus the geo component weighted by 0.25, plus the capacity component
    weighted by 0.15. The three weighted terms are summed first and the single
    resulting sum is then rounded half-up to two decimal places".

    Design: Difficulty/combinatorial_formula/interest_score_three_input_nonlinear_mode_a
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V Mode A", home_zip="02101",
        interest_tags=["SPORTS", "STEM", "MUSIC"], max_weekly_hours=8,
    )
    _g, child = fx.create_consented_child(
        set_clock_first=False,
        child_overrides={"first_name": "Noah", "age": 11, "home_zip": "02109",
                         "interest_tags": ["SPORTS", "STEM", "ARTS"]},
        guardian_overrides={"full_name": "G MA"},
    )
    proposal = fx.propose_match(child["id"])
    # shared 2 / union 4 = 0.5 interest; geo match 1.0; capacity 8/10 = 0.8.
    # 0.6*0.5 + 0.25*1.0 + 0.15*0.8 = 0.30 + 0.25 + 0.12 = 0.67
    assert proposal["compatibility_score"] == pytest.approx(0.67, abs=0.001)
    assert proposal["volunteer_id"] == vol["id"]


def test_interest_score_stored_on_proposal_is_two_decimals(api):
    """PRD §3.3: "The three weighted terms are summed first and the single
    resulting sum is then rounded half-up to two decimal places — the rounding is
    applied once to the final sum, never to the individual components. The
    volunteer with the highest rounded score is selected, and that rounded value
    is stored as the proposal's `compatibility_score`."

    Design: Difficulty/combinatorial_formula/interest_score_three_input_nonlinear_mode_a
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V Mode A2", home_zip="02101",
        interest_tags=["SPORTS", "STEM", "MUSIC"], max_weekly_hours=8,
    )
    _g, child = fx.create_consented_child(
        set_clock_first=False,
        child_overrides={"first_name": "Noah2", "age": 11, "home_zip": "02109",
                         "interest_tags": ["SPORTS", "STEM", "ARTS"]},
        guardian_overrides={"full_name": "G MA2"},
    )
    proposal = fx.propose_match(child["id"])
    stored = validate_success(api.get_proposal(proposal["id"], SPECIALIST), 200)
    assert stored["compatibility_score"] == 0.67, "rounded sum stored verbatim"
    assert stored["volunteer_id"] == vol["id"]


def test_tie_break_selects_earliest_created_volunteer(api):
    """PRD §3.3: "When two or more volunteers tie on the rounded score, the
    volunteer with the earliest `created_at` is selected; ties are never broken
    by `id`."

    Design: Difficulty/dual_variant_calc/interest_score_ranking_vs_tiebreak_on_proposal
    """
    fx.set_clock(fx.REF_CLOCK)
    v1 = fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V One", home_zip="10001",
        interest_tags=["SPORTS", "READING"], max_weekly_hours=10,
    )
    v2 = fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V Two", home_zip="10002",
        interest_tags=["SPORTS", "READING"], max_weekly_hours=10,
    )
    _g, child = fx.create_consented_child(
        set_clock_first=False,
        child_overrides={"first_name": "Liam", "home_zip": "10010",
                         "interest_tags": ["SPORTS", "READING", "STEM"]},
        guardian_overrides={"full_name": "G One"},
    )
    proposal = fx.propose_match(child["id"])
    # Both volunteers score 0.80 (interest 2/3*0.6 + geo 0.25 + capacity 0.15).
    assert proposal["compatibility_score"] == pytest.approx(0.80, abs=0.001)
    assert proposal["volunteer_id"] == v1["id"], "earliest-created volunteer wins the tie"
    assert proposal["candidate_pool_size"] == 2
    assert v2["id"] != v1["id"]


def test_tie_break_score_value_and_pool_size(api):
    """PRD §3.3: "the number of tags present in both `interest_tags` lists
    divided by the number of distinct tags present in either list ... The geo
    component is 1.0 when the volunteer's geo cluster equals the child's geo
    cluster ... `candidate_pool_size` (the number of eligible volunteers the
    engine considered)".

    Design: Difficulty/dual_variant_calc/interest_score_ranking_vs_tiebreak_on_proposal
    """
    fx.set_clock(fx.REF_CLOCK)
    v1 = fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V One2", home_zip="10001",
        interest_tags=["SPORTS", "READING"], max_weekly_hours=10,
    )
    fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V Two2", home_zip="10002",
        interest_tags=["SPORTS", "READING"], max_weekly_hours=10,
    )
    _g, child = fx.create_consented_child(
        set_clock_first=False,
        child_overrides={"first_name": "Liam2", "home_zip": "10010",
                         "interest_tags": ["SPORTS", "READING", "STEM"]},
        guardian_overrides={"full_name": "G One2"},
    )
    proposal = fx.propose_match(child["id"])
    # interest 2/3 → 0.667; *0.6 = 0.40; geo 0.25; capacity 0.15 → 0.80.
    assert proposal["compatibility_score"] == pytest.approx(0.80, abs=0.001)
    assert proposal["candidate_pool_size"] == 2
    assert proposal["volunteer_id"] == v1["id"]


def test_propose_with_empty_candidate_pool_rejected(api):
    """PRD §3.3: "the candidate pool of eligible volunteers must be non-empty,
    failing which the request is rejected with `ERR_NO_ELIGIBLE_VOLUNTEER` (HTTP
    409)."

    Design: Difficulty/boundary_precision_check/propose_empty_candidate_pool_zero_count
    """
    fx.set_clock(fx.REF_CLOCK)
    # A volunteer exists but is only APPLIED (never screened) → not ELIGIBLE.
    fx.create_volunteer(set_clock_first=False, full_name="V Unscreened", home_zip="20001")
    _g, child = fx.create_consented_child(
        set_clock_first=False,
        child_overrides={"first_name": "Ben", "home_zip": "20001"},
        guardian_overrides={"full_name": "G Bd2"},
    )
    child = validate_success(api.get_child(child["id"], SPECIALIST), 200)
    resp = api.propose_match(
        child["id"], {"expected_child_version": child["version"]}, SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_VOLUNTEER.value, 409)


def test_propose_empty_pool_leaves_child_waitlisted(api):
    """PRD §3.3: "the candidate pool of eligible volunteers must be non-empty,
    failing which the request is rejected with `ERR_NO_ELIGIBLE_VOLUNTEER` (HTTP
    409)."
    PRD §3.3: "the child transitions `WAITLISTED → PROPOSED` and its
    `open_proposal_id` is set to the new proposal's `id`." (So when the proposal
    fails, the child remains `WAITLISTED` with no `open_proposal_id`.)

    Design: Difficulty/boundary_precision_check/propose_empty_candidate_pool_zero_count
    """
    fx.set_clock(fx.REF_CLOCK)
    # No volunteer is ever created → candidate pool cardinality is exactly 0.
    _g, child = fx.create_consented_child(
        set_clock_first=False,
        child_overrides={"first_name": "Ben2", "home_zip": "20001"},
        guardian_overrides={"full_name": "G Bd3"},
    )
    resp = api.propose_match(
        child["id"], {"expected_child_version": child["version"]}, SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_VOLUNTEER.value, 409)
    after = validate_success(api.get_child(child["id"], SPECIALIST), 200)
    assert after["status"] == "WAITLISTED"
    assert after["open_proposal_id"] is None


def test_propose_requires_guardian_consent_then_succeeds(api):
    """PRD §3.3: "the child's guardian must have `consent_on_file` set to true,
    failing which the request is rejected with `ERR_CONSENT_NOT_ON_FILE` (HTTP
    409)."
    PRD §3.3: "On success the engine creates a `MatchProposal` in `OFFERED`".

    Design: Difficulty/cross_entity_state_dependency/propose_match_requires_guardian_consent
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V Ce2", home_zip="40201",
        interest_tags=["EVENT", "SPORTS"],
    )
    guardian = fx.create_guardian(consent_on_file=False, full_name="G Ce2")
    child = fx.create_child(guardian["id"], first_name="Cole", home_zip="40201",
                           interest_tags=["SPORTS"])
    # First attempt: consent missing.
    resp1 = api.propose_match(
        child["id"], {"expected_child_version": child["version"]}, SPECIALIST
    )
    validate_error(resp1, ApiErrorId.ERR_CONSENT_NOT_ON_FILE.value, 409)
    # Record consent, then re-propose against the (unchanged) child version.
    validate_success(
        api.update_guardian(
            guardian["id"],
            {"consent_on_file": True, "expected_guardian_version": guardian["version"]},
            COORD,
        ),
        200,
    )
    resp2 = api.propose_match(
        child["id"], {"expected_child_version": child["version"]}, SPECIALIST
    )
    proposal = validate_success(resp2, 201)
    assert proposal["status"] == "OFFERED"


def test_propose_match_requires_guardian_consent_error_only(api):
    """PRD §3.3: "the child's guardian must have `consent_on_file` set to true,
    failing which the request is rejected with `ERR_CONSENT_NOT_ON_FILE` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/propose_match_requires_guardian_consent
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V Ce2b", home_zip="40201",
        interest_tags=["SPORTS"],
    )
    guardian = fx.create_guardian(consent_on_file=False, full_name="G Ce2b")
    child = fx.create_child(guardian["id"], first_name="Cole2", home_zip="40201",
                           interest_tags=["SPORTS"])
    resp = api.propose_match(
        child["id"], {"expected_child_version": child["version"]}, SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ON_FILE.value, 409)


def test_propose_with_stale_child_version_rejected(api):
    """PRD §2.5: "if another writer has already advanced the child's `version`
    since the specialist last observed it, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/errors/error_stale_version_propose_triggerable
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(set_clock_first=False, full_name="V Sv")
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Sv")
    child = fx.create_child(guardian["id"], first_name="Sv")
    v0 = child["version"]
    # First propose advances the child's version.
    fx.propose_match(child["id"])
    current = validate_success(api.get_child(child["id"], SPECIALIST), 200)["version"]
    assert current > v0
    resp = api.propose_match(
        child["id"], {"expected_child_version": current - 1}, SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_accept_with_stale_volunteer_version_rejected(api):
    """PRD §2.5: "the accept must also carry `expected_volunteer_version`
    matching the volunteer's current `version` ... the accept is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/errors/error_stale_version_accept_triggerable
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_eligible_volunteer(set_clock_first=False, full_name="V Sva")
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Sva")
    child = fx.create_child(guardian["id"], first_name="Sva")
    proposal = fx.propose_match(child["id"])
    current = validate_success(api.get_volunteer(vol["id"], SPECIALIST), 200)["version"]
    resp = api.accept_proposal(
        proposal["id"], {"expected_volunteer_version": current - 1}, SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_repropose_supersedes_prior_offer(api):
    """PRD §3.3: "If the child already had an `OFFERED` proposal, that prior
    proposal is moved `OFFERED → SUPERSEDED` and the child momentarily reverts
    toward the waitlist before being re-attached to the fresh proposal ... and it
    increments the child's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/cascade_supersede_proposal_on_repropose
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(
        set_clock_first=False, full_name="V Su1",
        interest_tags=["SPORTS", "STEM"], max_weekly_hours=9,
    )
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Su")
    child = fx.create_child(guardian["id"], first_name="Su",
                           interest_tags=["SPORTS", "STEM"])
    prop1 = fx.propose_match(child["id"])
    prop2 = fx.propose_match(child["id"])
    assert prop2["id"] != prop1["id"]
    refreshed = validate_success(api.get_proposal(prop1["id"], SPECIALIST), 200)
    assert refreshed["status"] == "SUPERSEDED"
    child_now = validate_success(api.get_child(child["id"], SPECIALIST), 200)
    assert child_now["open_proposal_id"] == prop2["id"]
    assert child_now["status"] == "PROPOSED"


def test_propose_then_decline_returns_child_to_waitlist_no_open_offer(api):
    """PRD §3.3: "the child transitions `WAITLISTED → PROPOSED` and its
    `open_proposal_id` is set to the new proposal's `id`."
    PRD §3.4: "it moves the proposal `OFFERED → DECLINED` and bubbles the child
    `PROPOSED → WAITLISTED`, clearing the child's `open_proposal_id`."

    Design: Difficulty/compensating_invariant/child_offered_proposal_count_conserved_across_propose_decline
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(set_clock_first=False, full_name="V Inv2",
                                interest_tags=["MUSIC"], home_zip="33101")
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Inv2")
    child = fx.create_child(guardian["id"], first_name="Nia", gender="FEMALE",
                           home_zip="33101", interest_tags=["MUSIC"])
    proposal = fx.propose_match(child["id"])
    after_propose = validate_success(api.get_child(child["id"], SPECIALIST), 200)
    assert after_propose["status"] == "PROPOSED"
    assert after_propose["open_proposal_id"] == proposal["id"]

    validate_success(
        api.decline_proposal(proposal["id"], {"decline_reason": "GUARDIAN_DECLINED"}, SPECIALIST),
        200,
    )
    after_decline = validate_success(api.get_child(child["id"], SPECIALIST), 200)
    assert after_decline["status"] == "WAITLISTED"
    assert after_decline["open_proposal_id"] is None
    # No OFFERED proposal remains for the child.
    proposals, _meta = validate_paginated(api.list_child_proposals(child["id"], SPECIALIST))
    offered = [p for p in proposals if p["status"] == "OFFERED"]
    assert len(offered) == 0


def test_child_proposal_count_invariant_via_proposals_list(api):
    """PRD §3.4: "it moves the proposal `OFFERED → DECLINED` and bubbles the
    child `PROPOSED → WAITLISTED`, clearing the child's `open_proposal_id`."

    Design: Difficulty/compensating_invariant/child_offered_proposal_count_conserved_across_propose_decline
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(set_clock_first=False, full_name="V Inv2b",
                                interest_tags=["MUSIC"], home_zip="33101")
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Inv2b")
    child = fx.create_child(guardian["id"], first_name="Nia2", gender="FEMALE",
                           home_zip="33101", interest_tags=["MUSIC"])
    proposal = fx.propose_match(child["id"])
    validate_success(
        api.decline_proposal(proposal["id"], {"decline_reason": "POOR_FIT"}, SPECIALIST),
        200,
    )
    proposals, _meta = validate_paginated(api.list_child_proposals(child["id"], SPECIALIST))
    offered_count = sum(1 for p in proposals if p["status"] == "OFFERED")
    assert offered_count == 0
    declined = [p for p in proposals if p["id"] == proposal["id"]]
    assert declined and declined[0]["status"] == "DECLINED"
