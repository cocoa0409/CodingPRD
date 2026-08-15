"""The reconsideration process: filing windows and target eligibility, vote
integrity gates, quorum, decisions and their cascades, the appeal loop, and
case closure."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_challenge_to_committee_review,
    assert_committee_vote,
    assert_inventory_unit_conservation,
    cast_vote,
    cast_votes,
    create_cycle,
    create_distribution_order,
    create_framework,
    create_material,
    create_supplemental_request,
    decide_challenge,
    file_material_challenge,
    get_challenge,
    get_cycle,
    get_distribution_order,
    get_lot,
    get_material,
    make_committee_member_headers,
    make_community_member_headers,
    set_clock,
    setup_cycle_adopted,
    setup_cycle_distributing,
    setup_decided_material_challenge,
    transition_challenge,
    transition_distribution_order,
    transition_supplemental_request,
    validate_error,
    validate_paginated,
)

DIRECTOR = TEST_USERS["curriculum_director_headers"]


class TestChallengeFiling:
    def test_challenge_window_boundary_inclusive(self, api):
        """PRD §3.9: "Timeliness is enforced against the logical clock: a
        challenge must be filed no later than ninety days after the target's
        `adopted_at` or `approved_at` instant, and a filing more than ninety
        days after it is rejected with `ERR_CHALLENGE_WINDOW_CLOSED`."
        PRD §3.9: "Filing also freezes the target: a `USABLE` material moves
        to `UNDER_CHALLENGE` — its `adoption_status` untouched, per §2.9"

        Design: Corner/validations/challenge_window_boundary_inclusive
        """
        # adopted_at == 2026-09-01T00:00:00Z (the clock position at the board
        # decision), so the 90-day window closes at 2026-11-30T00:00:00Z.
        ctx = setup_cycle_adopted()

        set_clock("2026-12-01T00:00:00Z")  # 91 days after adopted_at
        validate_error(
            api.create_challenge(
                {"target_type": "MATERIAL",
                 "target_id": ctx["material"]["id"],
                 "grounds": "CONTENT_OBJECTION"},
                make_community_member_headers("cm1")),
            ApiErrorId.ERR_CHALLENGE_WINDOW_CLOSED)

        set_clock("2026-11-30T00:00:00Z")  # exactly adopted_at + 90 days
        resp = api.create_challenge(
            {"target_type": "MATERIAL", "target_id": ctx["material"]["id"],
             "grounds": "CONTENT_OBJECTION"},
            make_community_member_headers("cm1"))
        assert resp.status_code == 201
        assert resp.json()["data"]["status"] == "FILED"
        assert get_material(ctx["material"]["id"])["availability_status"] == \
            "UNDER_CHALLENGE"

    def test_second_open_challenge_rejected(self, api):
        """PRD §3.9: "Finally, one open challenge per target: if the target
        already has a challenge in any non-terminal status — `FILED` through
        `APPEALED` — the new filing fails with `ERR_OPEN_CHALLENGE_EXISTS`."

        Design: Corner/validations/second_open_challenge_rejected
        """
        ctx = setup_cycle_adopted()
        file_material_challenge(ctx["material"]["id"], filer_id="cm1")
        validate_error(
            api.create_challenge(
                {"target_type": "MATERIAL",
                 "target_id": ctx["material"]["id"],
                 "grounds": "AGE_APPROPRIATENESS"},
                make_community_member_headers("cm2")),
            ApiErrorId.ERR_OPEN_CHALLENGE_EXISTS)

    def test_challenge_target_ineligible(self, api):
        """PRD §3.9: "a material is challengeable only when its
        `adoption_status` is `ADOPTED`, and a supplemental request only in
        `APPROVED` or `REAFFIRMED`; anything else fails with
        `ERR_CHALLENGE_TARGET_INVALID`."

        Design: Corner/validations/challenge_target_ineligible
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        material = create_material(cycle["id"])  # SUBMITTED, never adopted
        request = create_supplemental_request(cycle["id"], "t1",
                                              estimated_cost=100.00)
        transition_supplemental_request(request["id"], "VETTING")
        transition_supplemental_request(request["id"], "DENIED")

        validate_error(
            api.create_challenge(
                {"target_type": "MATERIAL", "target_id": material["id"],
                 "grounds": "CONTENT_OBJECTION"},
                make_community_member_headers("cm1")),
            ApiErrorId.ERR_CHALLENGE_TARGET_INVALID)
        validate_error(
            api.create_challenge(
                {"target_type": "SUPPLEMENTAL_REQUEST",
                 "target_id": request["id"], "grounds": "CONTENT_OBJECTION"},
                make_community_member_headers("cm1")),
            ApiErrorId.ERR_CHALLENGE_TARGET_INVALID)


class TestCommitteeVotes:
    def test_committee_vote_immutable(self, api):
        """PRD §2.5: "One exception exists: a committee vote is immutable
        once cast. A vote record carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it."
        PRD §3.9: "Filing stamps the case with the filer's identity as
        `filer_user_id`, the logical clock as `filed_at`, a `vote_round` of
        1, and `appeal_used` of false, and opens in `FILED` status."

        Design: Corner/entities/committee_vote_immutable
        """
        ctx = setup_cycle_adopted()
        challenge = file_material_challenge(ctx["material"]["id"],
                                            grounds="ALIGNMENT_DISPUTE")
        advance_challenge_to_committee_review(challenge["id"])

        resp = api.cast_vote(challenge["id"], {"vote": "UPHOLD"},
                             make_committee_member_headers("v1"))
        assert resp.status_code == 201
        vote = resp.json()["data"]
        assert_committee_vote(vote)
        assert vote["vote_round"] == 1, "the challenge's current round is pinned"

    def test_vote_gates_filer_exclusion_and_duplicate(self, api):
        """PRD §3.9: "Two integrity rules guard the ballot box: the case's
        filer may not vote on their own case (`ERR_SEGREGATION_OF_DUTIES`,
        HTTP 403), and each member casts at most one vote per round — a
        second vote in the same `vote_round` fails with
        `ERR_DUPLICATE_VOTE`."

        Design: Corner/validations/vote_gates_filer_exclusion_and_duplicate
        """
        ctx = setup_cycle_adopted()
        challenge = file_material_challenge(ctx["material"]["id"],
                                            filer_id="cm1")
        advance_challenge_to_committee_review(challenge["id"])

        # The filer may not vote, even while acting as a CommitteeMember.
        validate_error(
            api.cast_vote(challenge["id"], {"vote": "REMOVE"},
                          make_committee_member_headers("cm1")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        cast_vote(challenge["id"], "v1", "UPHOLD")
        validate_error(
            api.cast_vote(challenge["id"], {"vote": "REMOVE"},
                          make_committee_member_headers("v1")),
            ApiErrorId.ERR_DUPLICATE_VOTE)

        votes, meta = validate_paginated(api.list_votes(challenge["id"],
                                                        DIRECTOR))
        v1_votes = [v for v in votes if v["voter_user_id"] == "v1"]
        assert len(v1_votes) == 1, "the accepted vote remains the only v1 vote"


class TestDecisionQuorum:
    def test_decide_requires_quorum(self, api):
        """PRD §3.9: "Decision day requires quorum. A `CommitteeMember`
        issues the decision from `COMMITTEE_REVIEW` or `HEARING`, and at
        least three votes must exist in the current `vote_round` — exactly
        three passes, fewer fails with `ERR_QUORUM_NOT_MET`."

        Design: Corner/validations/decide_requires_quorum
        """
        ctx = setup_cycle_adopted()
        challenge = file_material_challenge(ctx["material"]["id"],
                                            grounds="ALIGNMENT_DISPUTE")
        advance_challenge_to_committee_review(challenge["id"])
        transition_challenge(challenge["id"], "HEARING")
        cast_vote(challenge["id"], "v1", "UPHOLD")
        cast_vote(challenge["id"], "v2", "UPHOLD")

        validate_error(
            api.transition_challenge(challenge["id"], {"to_state": "DECIDED"},
                                     make_committee_member_headers("v1")),
            ApiErrorId.ERR_QUORUM_NOT_MET)

        cast_vote(challenge["id"], "v3", "REMOVE")  # third vote: quorum met
        decided = decide_challenge(challenge["id"])
        assert decided["status"] == "DECIDED"
        assert decided["decision"] == "UPHELD", "2 UPHOLD vs 1 REMOVE"


class TestMaterialParallelDimensions:
    def test_challenge_freezes_availability_not_adoption(self, api):
        """PRD §2.9: "the two move independently, so a material can
        legitimately be `ADOPTED` and `UNDER_CHALLENGE` at the same time."
        PRD §3.9: "Filing also freezes the target: a `USABLE` material moves
        to `UNDER_CHALLENGE` — its `adoption_status` untouched, per §2.9"

        Design: Difficulty/non_linear_state_machine/material_parallel_adoption_vs_availability
        """
        ctx = setup_cycle_adopted()
        file_material_challenge(ctx["material"]["id"], filer_id="cm1")
        material = get_material(ctx["material"]["id"])
        assert material["adoption_status"] == "ADOPTED"
        assert material["availability_status"] == "UNDER_CHALLENGE"

    def test_upheld_decision_restores_availability_only(self, api):
        """PRD §3.9: "The recorded `decision` is the plurality of the current
        round's ballots: `UPHOLD` ballots produce `UPHELD`, `RESTRICT`
        ballots produce `RESTRICTED`, `REMOVE` ballots produce `REMOVED`, and
        any tie for the top count resolves to `UPHELD`."
        PRD §3.9: "For a material target: `UPHELD` returns availability from
        `UNDER_CHALLENGE` to `USABLE`"

        Design: Difficulty/non_linear_state_machine/material_parallel_adoption_vs_availability
        """
        ctx = setup_decided_material_challenge(
            votes=(("v1", "UPHOLD"), ("v2", "UPHOLD"), ("v3", "REMOVE")))
        assert ctx["challenge"]["decision"] == "UPHELD"
        material = ctx["material"]
        assert material["availability_status"] == "USABLE"
        assert material["adoption_status"] == "ADOPTED", (
            "the adoption dimension is untouched by the challenge outcome")


class TestAppealRoundCycle:
    def test_appeal_opens_fresh_vote_round(self, api):
        """PRD §3.9: "Appealing sets `appeal_used` to true and increments
        `vote_round`, so the returning committee votes in a fresh round under
        the same one-vote-per-member-per-round rule; the case flows
        `APPEALED` back into `COMMITTEE_REVIEW` and onward to a second
        decision, which is final because `appeal_used` blocks any further
        appeal."

        Design: Difficulty/non_linear_state_machine/challenge_appeal_round_cycle
        """
        ctx = setup_decided_material_challenge(
            votes=(("v1", "UPHOLD"), ("v2", "UPHOLD"), ("v3", "REMOVE")))
        assert ctx["challenge"]["decision"] == "UPHELD"

        appealed = transition_challenge(
            ctx["challenge"]["id"], "APPEALED",
            make_community_member_headers("cm1"))
        assert appealed["status"] == "APPEALED"
        assert appealed["vote_round"] == 2, "appeal increments the vote round"
        assert appealed["appeal_used"] is True

        # The returning committee votes in the fresh round; round-1 voters
        # may vote again.
        transition_challenge(ctx["challenge"]["id"], "COMMITTEE_REVIEW")
        resp = api.cast_vote(ctx["challenge"]["id"], {"vote": "REMOVE"},
                             make_committee_member_headers("v1"))
        assert resp.status_code == 201
        assert resp.json()["data"]["vote_round"] == 2

    def test_second_decision_final_and_second_appeal_rejected(self, api):
        """PRD §3.9: "provided `appeal_used` is still false (a second appeal
        fails with `ERR_INVALID_STATE`)"
        PRD §3.9: "`REMOVED` moves it to `REMOVED` — reachable from
        `UNDER_CHALLENGE` and from `RESTRICTED` alike, since a
        restricted-but-still-adopted material remains challengeable"

        Design: Difficulty/non_linear_state_machine/challenge_appeal_round_cycle
        """
        ctx = setup_decided_material_challenge(
            votes=(("v1", "UPHOLD"), ("v2", "UPHOLD"), ("v3", "REMOVE")))
        transition_challenge(ctx["challenge"]["id"], "APPEALED",
                             make_community_member_headers("cm1"))
        transition_challenge(ctx["challenge"]["id"], "COMMITTEE_REVIEW")
        transition_challenge(ctx["challenge"]["id"], "HEARING")
        cast_votes(ctx["challenge"]["id"],
                   (("v1", "REMOVE"), ("v2", "REMOVE"), ("v3", "REMOVE")))
        decided = decide_challenge(ctx["challenge"]["id"])
        assert decided["decision"] == "REMOVED", "round 2 votes 3-0 REMOVE"
        assert get_material(ctx["material"]["id"])["availability_status"] == \
            "REMOVED"

        # appeal_used blocks any further appeal.
        validate_error(
            api.transition_challenge(ctx["challenge"]["id"],
                                     {"to_state": "APPEALED"},
                                     make_community_member_headers("cm1")),
            ApiErrorId.ERR_INVALID_STATE)


class TestAppealWindowAndOwnership:
    def test_appeal_window_and_ownership(self, api):
        """PRD §3.9: "From `DECIDED`, the original filer — and only the
        filer, or `ERR_INSUFFICIENT_PERMISSIONS` — may appeal the case to
        `APPEALED`, provided `appeal_used` is still false (a second appeal
        fails with `ERR_INVALID_STATE`) and the logical clock is no later
        than fourteen days after `decided_at`, with an appeal at exactly the
        fourteen-day mark admitted and a later one rejected as
        `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/validations/appeal_window_and_ownership
        """
        # decided_at == 2026-09-01T00:00:00Z; decision RESTRICTED (2 vs 1).
        ctx = setup_decided_material_challenge(
            votes=(("v1", "RESTRICT"), ("v2", "RESTRICT"), ("v3", "UPHOLD")),
            grounds="PROCEDURAL_IRREGULARITY")
        assert ctx["challenge"]["decision"] == "RESTRICTED"
        assert get_material(ctx["material"]["id"])["availability_status"] == \
            "RESTRICTED"

        # Only the filer may appeal.
        validate_error(
            api.transition_challenge(ctx["challenge"]["id"],
                                     {"to_state": "APPEALED"},
                                     make_community_member_headers("cm2")),
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        # 2026-09-16T00:00:01Z is past decided_at + 14 days.
        set_clock("2026-09-16T00:00:01Z")
        validate_error(
            api.transition_challenge(ctx["challenge"]["id"],
                                     {"to_state": "APPEALED"},
                                     make_community_member_headers("cm1")),
            ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

        # Exactly the fourteen-day mark is admitted.
        set_clock("2026-09-15T00:00:00Z")
        appealed = transition_challenge(ctx["challenge"]["id"], "APPEALED",
                                        make_community_member_headers("cm1"))
        assert appealed["status"] == "APPEALED"
        assert appealed["vote_round"] == 2


class TestChallengeClosure:
    def test_challenge_close_before_appeal_window_rejected(self, api):
        """PRD §3.9: "a `DECIDED` case moves to `CLOSED`, terminal, once
        either the appeal has been used or the appeal window has lapsed —
        that is, the logical clock has passed fourteen days after
        `decided_at`. Closing while an appeal is still available fails with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/challenge_close_before_appeal_window_rejected
        """
        ctx = setup_decided_material_challenge(
            votes=(("v1", "UPHOLD"), ("v2", "UPHOLD"), ("v3", "UPHOLD")))

        # Appeal unused and the window (until decided_at + 14 days) is open.
        validate_error(
            api.transition_challenge(ctx["challenge"]["id"],
                                     {"to_state": "CLOSED"}, DIRECTOR),
            ApiErrorId.ERR_INVALID_STATE)

        # Past the window the close succeeds.
        set_clock("2026-09-16T00:00:01Z")
        closed = transition_challenge(ctx["challenge"]["id"], "CLOSED")
        assert closed["status"] == "CLOSED"


class TestChallengeRemovalCascade:
    def _setup_cascade(self, api):
        """DISTRIBUTING cycle; lot on_hand 10; DO1 qty 4 APPROVED; DO2 qty 2
        REQUESTED; a challenge at COMMITTEE_REVIEW carrying REMOVE/REMOVE/
        UPHOLD votes."""
        ctx = setup_cycle_distributing()
        material_id = ctx["material"]["id"]
        do1 = create_distribution_order(material_id, school_code="SCH-A",
                                        classroom_label="RM-101", quantity=4,
                                        need_priority=3)
        transition_distribution_order(do1["id"], "APPROVED")
        do2 = create_distribution_order(material_id, school_code="SCH-B",
                                        classroom_label="RM-202", quantity=2,
                                        need_priority=1)
        challenge = file_material_challenge(material_id, filer_id="cm9")
        advance_challenge_to_committee_review(challenge["id"])
        cast_votes(challenge["id"],
                   (("v1", "REMOVE"), ("v2", "REMOVE"), ("v3", "UPHOLD")))
        return ctx, do1, do2, challenge

    def test_removal_cancels_open_distribution_orders(self, api):
        """PRD §3.9: "removal carries the full cascade: every distribution
        order for the material in `REQUESTED`, `APPROVED`, or `BACKORDERED`
        is cancelled, approved orders release their allocations from the lot,
        the lot's derived figures are recomputed, and when the removed
        material is its cycle's `adopted_material_id`, that cycle's
        `replacement_due` flag is set to true."

        Design: Difficulty/transitive_cascade/challenge_removal_cascade
        """
        ctx, do1, do2, challenge = self._setup_cascade(api)
        decided = decide_challenge(challenge["id"])
        assert decided["decision"] == "REMOVED"

        material_id = ctx["material"]["id"]
        assert get_material(material_id)["availability_status"] == "REMOVED"
        # The cascade fires from the material transition: both the APPROVED
        # and the REQUESTED order are cancelled.
        assert get_distribution_order(do1["id"], material_id)["status"] == \
            "CANCELLED"
        assert get_distribution_order(do2["id"], material_id)["status"] == \
            "CANCELLED"

    def test_removal_releases_allocations_and_sets_replacement_due(self, api):
        """PRD §3.9: "approved orders release their allocations from the lot,
        the lot's derived figures are recomputed, and when the removed
        material is its cycle's `adopted_material_id`, that cycle's
        `replacement_due` flag is set to true."

        Design: Difficulty/transitive_cascade/challenge_removal_cascade
        """
        ctx, do1, do2, challenge = self._setup_cascade(api)
        decide_challenge(challenge["id"])

        lot = get_lot(ctx["material"]["id"])
        assert lot["allocated_units"] == 0, "the approved order's allocation released"
        assert lot["available_units"] == 10
        assert lot["on_hand_units"] == 10
        assert_inventory_unit_conservation(lot)

        assert get_cycle(ctx["cycle"]["id"])["replacement_due"] is True
