"""Committee governance: quorum auto-decision, reopen cycle, vote OCC, tallies."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_committee_review,
    cast_votes_sequential,
    create_vote_payload,
    list_votes,
    make_committee_member_headers,
    setup_deficient_review,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CHAIR = TEST_USERS["chair_headers"]


class TestVoteOcc:
    def test_vote_with_stale_review_version_rejected(self, api):
        """PRD §2.8: "The vote-casting endpoint (`POST /committee-reviews/{id}/votes`)
        requires a non-optional `expected_review_version` field carrying the
        client's last observed `version` of the review. If another member's vote has
        been recorded since (advancing the tally and the version), the cast is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/vote_with_stale_review_version_returns_412
        """
        env = setup_deficient_review()
        review = env["review"]
        observed = review["version"]

        accepted = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("MAINTAIN", observed),
                make_committee_member_headers("cm_1"),
            ),
            201,
        )
        assert accepted["tally_maintain"] == 1

        stale = api.cast_committee_vote(
            review["id"], create_vote_payload("REDUCE", observed),
            make_committee_member_headers("cm_2"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

        after = validate_success(api.get_committee_review(review["id"], ADMIN), 200)
        assert after["tally_maintain"] == 1
        assert after["tally_reduce"] == 0
        assert after["status"] == "OPEN"


class TestReviewStateGate:
    def _decided_maintain_review(self):
        env = setup_deficient_review(line_name="MIS")
        review = env["review"]
        decided = cast_votes_sequential(
            review["id"],
            [("cm_1", "MAINTAIN"), ("cm_2", "MAINTAIN"), ("cm_3", "MAINTAIN")],
            review["version"],
        )
        assert decided["status"] == "DECIDED"
        assert decided["decision"] == "MAINTAIN"
        return review, decided

    def test_vote_on_decided_review_rejected_with_current_version(self, api):
        """PRD §3.7: "A `CommitteeMember` casts a `vote` of `REDUCE`, `MAINTAIN`, or
        `ABSTAIN` against an `OPEN` review — voting against a review in any other
        status is `ERR_REVIEW_NOT_OPEN`".

        Design: Difficulty/cross_entity_state_dependency/vote_requires_review_open_state
        """
        review, decided = self._decided_maintain_review()

        res = api.cast_committee_vote(
            review["id"], create_vote_payload("REDUCE", decided["version"]),
            make_committee_member_headers("cm_4"),
        )
        validate_error(res, ApiErrorId.ERR_REVIEW_NOT_OPEN)
        assert res.status_code == 409

        after = validate_success(api.get_committee_review(review["id"], ADMIN), 200)
        assert after["status"] == "DECIDED"
        assert after["decision"] == "MAINTAIN"
        assert after["tally_reduce"] == 0  # fourth vote recorded nothing

    def test_state_check_precedes_version_check(self, api):
        """PRD §2.7: "When several checks could reject the same request, they are
        evaluated in the following fixed order, so an earlier failure masks every
        later check" — and item 8: "This check is evaluated after state
        preconditions and before any business rule."

        Design: Difficulty/cross_entity_state_dependency/vote_requires_review_open_state
        """
        review, decided = self._decided_maintain_review()

        # A deliberately wrong expected version still yields the state error, not
        # the OCC error, because state preconditions are evaluated first.
        res = api.cast_committee_vote(
            review["id"], create_vote_payload("REDUCE", decided["version"] + 99),
            make_committee_member_headers("cm_4"),
        )
        validate_error(res, ApiErrorId.ERR_REVIEW_NOT_OPEN)
        assert res.status_code == 409


class TestReopenCycle:
    def test_maintain_decision_reopens_and_decides_reduce(self, api):
        """PRD §3.7: "Reopening deletes every vote row of the review, zeroes all
        three tallies, returns `decision` to `NONE`, moves the review back to
        `OPEN`, and increments its `version` by 1."
        PRD §3.7: "`decision` becomes `REDUCE` when `tally_reduce` strictly exceeds
        `tally_maintain`, and `MAINTAIN` otherwise, so a tie maintains and
        abstentions count toward quorum only".

        Design: Difficulty/non_linear_state_machine/committee_review_reopen_cycle
        """
        env = setup_deficient_review(line_name="ENT")
        review = env["review"]

        first_round = cast_votes_sequential(
            review["id"],
            [("cm_1", "MAINTAIN"), ("cm_2", "MAINTAIN"), ("cm_3", "REDUCE")],
            review["version"],
        )
        assert first_round["status"] == "DECIDED"
        assert first_round["decision"] == "MAINTAIN"  # maintain 2 >= reduce 1

        reopened = validate_success(api.reopen_committee_review(review["id"], CHAIR), 200)
        assert_committee_review(reopened)
        assert reopened["status"] == "OPEN"
        assert reopened["decision"] == "NONE"
        assert reopened["tally_reduce"] == 0
        assert reopened["tally_maintain"] == 0
        assert reopened["tally_abstain"] == 0
        votes, votes_meta = list_votes(review["id"])
        assert votes_meta["total_count"] == 0
        assert votes == []

        second_round = cast_votes_sequential(
            review["id"],
            [("cm_1", "REDUCE"), ("cm_2", "REDUCE"), ("cm_3", "REDUCE")],
            reopened["version"],
        )
        assert second_round["status"] == "DECIDED"
        assert second_round["decision"] == "REDUCE"  # reduce 3 > maintain 0

    def test_reopen_restores_voting_and_zeroes_tallies(self, api):
        """PRD §3.7: "Reopening deletes every vote row of the review, zeroes all
        three tallies, returns `decision` to `NONE`, moves the review back to
        `OPEN`, and increments its `version` by 1."

        Design: Difficulty/non_linear_state_machine/committee_review_reopen_cycle
        """
        env = setup_deficient_review(line_name="ENT")
        review = env["review"]
        decided = cast_votes_sequential(
            review["id"],
            [("cm_1", "MAINTAIN"), ("cm_2", "MAINTAIN"), ("cm_3", "ABSTAIN")],
            review["version"],
        )
        assert decided["decision"] == "MAINTAIN"

        reopened = validate_success(api.reopen_committee_review(review["id"], CHAIR), 200)
        assert reopened["version"] > decided["version"]

        # The same member may vote again: their prior row was deleted.
        accepted = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("REDUCE", reopened["version"]),
                make_committee_member_headers("cm_1"),
            ),
            201,
        )
        assert accepted["status"] == "OPEN"  # total 1 < quorum 3
        assert accepted["tally_reduce"] == 1
        assert accepted["tally_maintain"] == 0
        votes, meta = list_votes(review["id"])
        assert meta["total_count"] == 1
        assert votes[0]["member_ref"] == "cm_1"
        assert votes[0]["vote"] == "REDUCE"


class TestVoteTallyConservation:
    def test_tally_conserved_through_recast_and_reopen(self, api):
        """PRD §3.7: "Each member holds at most one vote row per review: re-casting
        deletes the member's prior row and replaces it, and each row references its
        `review_id` and the caster's `member_ref`. Every accepted cast recomputes
        the three tallies as counts of non-voided rows and increments the review's
        `version` by 1."

        Design: Difficulty/compensating_invariant/vote_tally_conserved_through_recast_and_reopen
        """
        env = setup_deficient_review(line_name="CRS")
        review = env["review"]

        v1 = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("REDUCE", review["version"]),
                make_committee_member_headers("cm_1"),
            ),
            201,
        )
        v2 = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("MAINTAIN", v1["version"]),
                make_committee_member_headers("cm_2"),
            ),
            201,
        )
        assert v2["tally_reduce"] + v2["tally_maintain"] + v2["tally_abstain"] == 2
        _, meta = list_votes(review["id"])
        assert meta["total_count"] == 2

        # cm_1 re-casts: the row is replaced, not added.
        v3 = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("MAINTAIN", v2["version"]),
                make_committee_member_headers("cm_1"),
            ),
            201,
        )
        assert v3["tally_reduce"] == 0
        assert v3["tally_maintain"] == 2
        _, meta = list_votes(review["id"])
        assert meta["total_count"] == 2

        v4 = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("ABSTAIN", v3["version"]),
                make_committee_member_headers("cm_3"),
            ),
            201,
        )
        assert v4["status"] == "DECIDED"
        assert v4["decision"] == "MAINTAIN"  # maintain 2 > reduce 0

        reopened = validate_success(api.reopen_committee_review(review["id"], CHAIR), 200)
        assert reopened["tally_reduce"] == 0
        assert reopened["tally_maintain"] == 0
        assert reopened["tally_abstain"] == 0
        _, meta = list_votes(review["id"])
        assert meta["total_count"] == 0

    def test_recast_can_flip_the_eventual_decision(self, api):
        """PRD §3.7: "Quorum is three: the moment `tally_reduce`, `tally_maintain`,
        and `tally_abstain` sum to at least three, the review decides itself —
        `decision` becomes `REDUCE` when `tally_reduce` strictly exceeds
        `tally_maintain`, and `MAINTAIN` otherwise".
        PRD §3.7: "Each member holds at most one vote row per review: re-casting
        deletes the member's prior row and replaces it".

        Design: Difficulty/compensating_invariant/vote_tally_conserved_through_recast_and_reopen
        """
        env = setup_deficient_review(line_name="CRS")
        review = env["review"]

        v1 = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("REDUCE", review["version"]),
                make_committee_member_headers("cm_1"),
            ),
            201,
        )
        v2 = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("REDUCE", v1["version"]),
                make_committee_member_headers("cm_2"),
            ),
            201,
        )
        # Re-cast before quorum flips cm_1's row to MAINTAIN; still 2 rows total.
        v3 = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("MAINTAIN", v2["version"]),
                make_committee_member_headers("cm_1"),
            ),
            201,
        )
        assert v3["status"] == "OPEN"
        assert v3["tally_reduce"] == 1
        assert v3["tally_maintain"] == 1
        _, meta = list_votes(review["id"])
        assert meta["total_count"] == 2

        decided = validate_success(
            api.cast_committee_vote(
                review["id"], create_vote_payload("REDUCE", v3["version"]),
                make_committee_member_headers("cm_3"),
            ),
            201,
        )
        assert decided["status"] == "DECIDED"
        assert decided["decision"] == "REDUCE"  # reduce 2 > maintain 1
        assert decided["tally_reduce"] == 2
        assert decided["tally_maintain"] == 1
