"""
Which returns a ballot will accept and when: one cast per seat, eligibility read
off the seat rather than the roster, the half-open window enforced against the
clock, the explanation a negative owes, the owner who alone may revise it, and
the early close the last returning seat unlocks.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestOneSeatOneVote:
    """A seat casts once, and only a seat that may vote casts at all."""

    def test_a_second_cast_by_the_same_seat_is_refused(self, api):
        """
        The acting seat must not already hold a vote on this ballot whose `status` is
        `CAST`, else `ERR_DUPLICATE_VOTE` — a vote previously withdrawn does not block a
        fresh cast, so a member who retracted may vote again.

        Design: Corner/validations/a_second_cast_by_the_same_seat_is_rejected_and_the_tally_is_untouched
        """
        scenario = fx.open_subcommittee_ballot(api)
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")

        response = api.cast_vote(
            scenario.ballot_id,
            f.vote_payload(scenario.mid("m1"), position="ABSTAIN"),
            scenario.chair,
        )
        validate_error(response, "ERR_DUPLICATE_VOTE", 409)

        first = scenario.get_vote("v1")
        assert first["position"] == "AFFIRMATIVE", (
            f"the first cast is not replaced, got {first['position']}"
        )
        assert first["status"] == "CAST", (
            f"status expected CAST, got {first['status']}"
        )
        votes, meta = validate_paginated(
            api.list_votes(scenario.staff, {"ballot_id": scenario.ballot_id})
        )
        a.assert_total_count(meta, 1)
        assert len(votes) == 1, (
            f"no second vote row was created, got {len(votes)}"
        )
        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=1,
            negative=0,
            abstain=0,
            returned=1,
            not_returned=2,
            eligible=3,
        )
        a.assert_seat_conservation(ballot)

    def test_an_observer_seat_may_not_cast(self, api):
        """
        The acting seat must be eligible: its `status` must be `ACTIVE` with `voting_rights`
        true on the ballot's committee, and when the ballot's `effective_ballot_kind` is
        `RECIRCULATION` the seat must additionally fall inside the narrowed recirculation
        eligible set described in §3.3; otherwise the response is `ERR_VOTER_NOT_ELIGIBLE`.

        Design: Corner/validations/a_non_voting_seat_may_not_cast_and_never_enters_the_frozen_denominator
        """
        scenario = fx.balanced_active_committee(api)
        scenario.register("p6")
        scenario.appoint("p6", "m6", voting_rights=False)
        scenario.propose_work_item("p1")
        scenario.approve_scope(designation="STD-1400")
        scenario.add_draft(total_clause_count=40, changed_clause_count=0)
        ballot = scenario.open_ballot()
        assert ballot["eligible_voter_count"] == 3, (
            "the observer was excluded from the frozen eligible set, got "
            f"{ballot['eligible_voter_count']}"
        )

        response = api.cast_vote(
            scenario.ballot_id,
            f.vote_payload(scenario.mid("m6")),
            scenario.member("p6"),
        )
        validate_error(response, "ERR_VOTER_NOT_ELIGIBLE", 409)

        seat = scenario.get_membership("m6")
        assert seat["status"] == "ACTIVE", (
            f"the observer holds an active seat, got {seat['status']}"
        )
        assert seat["voting_rights"] is False, (
            f"but carries no voting rights, got {seat['voting_rights']}"
        )
        after = scenario.get_ballot()
        assert after["eligible_voter_count"] == 3, (
            f"eligible_voter_count expected 3, got {after['eligible_voter_count']}"
        )
        assert after["returned_count"] == 0, (
            f"returned_count expected 0, got {after['returned_count']}"
        )
        assert after["not_returned_count"] == 3, (
            f"not_returned_count expected 3, got {after['not_returned_count']}"
        )
        votes, meta = validate_paginated(
            api.list_votes(scenario.staff, {"ballot_id": scenario.ballot_id})
        )
        a.assert_total_count(meta, 0)
        assert votes == [], f"the refused cast stored nothing, got {votes}"
        committee = scenario.get_committee()
        assert committee["roster_member_count"] == 4, (
            f"roster_member_count expected 4, got {committee['roster_member_count']}"
        )
        assert committee["balance_status"] == "BALANCED", (
            "the three voting seats still balance, got "
            f"{committee['balance_status']}"
        )


class TestTheHalfOpenVotingWindow:
    """An open ballot is not the same thing as a ballot in its voting window."""

    def test_voting_before_opens_at_is_refused_then_admitted(self, api):
        """
        And the logical clock must lie inside the half-open voting window — at or after
        `opens_at` and strictly before `closes_at` — else `ERR_BALLOT_NOT_IN_VOTING_WINDOW`;
        a vote arriving at exactly `closes_at` is too late.

        Design: Corner/validations/voting_before_opens_at_is_refused_and_the_same_vote_lands_inside_the_window
        """
        scenario = fx.work_item_with_draft(api)
        future = scenario.open_ballot(
            opens_at="2026-08-10T00:00:00Z", closes_at="2026-08-24T00:00:00Z"
        )
        assert future["status"] == "OPEN", (
            "a ballot with a future window is created OPEN all the same, got "
            f"{future['status']}"
        )

        too_early = api.cast_vote(
            scenario.ballot_id,
            f.vote_payload(scenario.mid("m2")),
            scenario.member("p2"),
        )
        validate_error(too_early, "ERR_BALLOT_NOT_IN_VOTING_WINDOW", 409)

        before = scenario.get_ballot()
        assert before["status"] == "OPEN", (
            f"the refusal left the ballot open, got {before['status']}"
        )
        assert before["returned_count"] == 0, (
            f"returned_count expected 0, got {before['returned_count']}"
        )

        scenario.set_clock("2026-08-10T00:00:00Z")
        vote = scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")

        assert vote["status"] == "CAST", (
            f"the identical payload now lands, got {vote['status']}"
        )
        assert vote["position"] == "AFFIRMATIVE", (
            f"position expected AFFIRMATIVE, got {vote['position']}"
        )
        assert vote["adjudication_status"] == "NOT_APPLICABLE", (
            f"adjudication_status expected NOT_APPLICABLE, got {vote['adjudication_status']}"
        )
        a.assert_same_instant(vote["cast_at"], "2026-08-10T00:00:00Z")
        after = scenario.get_ballot()
        assert after["affirmative_count"] == 1, (
            f"affirmative_count expected 1, got {after['affirmative_count']}"
        )
        assert after["returned_count"] == 1, (
            f"returned_count expected 1, got {after['returned_count']}"
        )


class TestAnUnexplainedNegative:
    """Only the negative owes an explanation, and only it spawns an objection."""

    def test_a_negative_needs_a_comment_where_an_abstain_does_not(self, api):
        """
        A vote cast with `position` `NEGATIVE` must supply a non-empty `comment_text`, or the
        request is rejected with `ERR_NEGATIVE_REQUIRES_COMMENT` (HTTP 400). When it does,
        the server itself creates the objection on file as a comment against the ballot's
        draft: that comment's `source_type` is `BALLOT_NEGATIVE`, its `source_vote_id` points
        back at the vote, its `ballot_id` names the ballot, and its `public_review_id` is
        null — which is precisely why a ballot objection never enters any public review's
        disposition ledger.

        Design: Corner/validations/an_unexplained_negative_is_rejected_while_an_unexplained_abstain_is_accepted
        """
        scenario = fx.open_subcommittee_ballot(api)

        unexplained = api.cast_vote(
            scenario.ballot_id,
            f.vote_payload(scenario.mid("m3"), position="NEGATIVE"),
            scenario.member("p3"),
        )
        validate_error(unexplained, "ERR_NEGATIVE_REQUIRES_COMMENT", 400)

        votes, meta = validate_paginated(
            api.list_votes(scenario.staff, {"ballot_id": scenario.ballot_id})
        )
        a.assert_total_count(meta, 0)
        assert votes == [], f"the rejected negative stored no vote, got {votes}"

        abstain = scenario.cast("m2", "ABSTAIN", vote_key="v2")
        assert abstain["position"] == "ABSTAIN", (
            f"an abstain needs no explanation, got {abstain['position']}"
        )
        _, abstain_comments = validate_paginated(
            api.list_comments(scenario.staff, {"source_vote_id": abstain["id"]})
        )
        a.assert_total_count(abstain_comments, 0)

        negative = scenario.cast_negative("m3", vote_key="v3")

        assert negative["position"] == "NEGATIVE", (
            f"the explained negative lands, got {negative['position']}"
        )
        objections, objection_meta = validate_paginated(
            api.list_comments(scenario.staff, {"source_vote_id": negative["id"]})
        )
        a.assert_total_count(objection_meta, 1)
        objection = objections[0]
        assert objection["source_type"] == "BALLOT_NEGATIVE", (
            f"source_type expected BALLOT_NEGATIVE, got {objection['source_type']}"
        )
        assert objection["status"] == "OPEN", (
            f"the objection opens OPEN, got {objection['status']}"
        )
        assert objection["public_review_id"] is None, (
            "a ballot objection stays outside every disposition ledger, got "
            f"{objection['public_review_id']}"
        )
        assert objection["ballot_id"] == scenario.ballot_id, (
            "the objection names the ballot it was raised on"
        )
        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=0,
            negative=1,
            abstain=1,
            returned=2,
            not_returned=1,
            eligible=3,
        )


class TestOnlyTheOwnerRevises:
    """Ownership is read off the seat behind the vote, not off committee standing."""

    def test_the_chair_may_not_change_another_seats_vote(self, api):
        """
        and only their own: the caller's identifier must equal the `participant_id` of the
        seat behind the vote, else `ERR_NOT_VOTE_OWNER`.

        Changing a position to `NEGATIVE` again demands an explanation: either a comment is
        already linked to this vote or a non-empty `comment_text` accompanies the change,
        failing which the response is `ERR_NEGATIVE_REQUIRES_COMMENT`.

        Design: Corner/validations/only_the_voter_who_cast_it_may_change_a_vote
        """
        scenario = fx.open_subcommittee_ballot(api)
        negative = scenario.cast_negative("m3", vote_key="v3")

        response = api.update_vote(
            negative["id"],
            f.vote_patch_payload(position="AFFIRMATIVE"),
            scenario.chair,
        )
        validate_error(response, "ERR_NOT_VOTE_OWNER", 403)

        untouched = scenario.get_vote("v3")
        assert untouched["position"] == "NEGATIVE", (
            f"the chair changed nothing, got {untouched['position']}"
        )
        assert untouched["position_change_count"] == 0, (
            f"position_change_count expected 0, got {untouched['position_change_count']}"
        )
        held = scenario.get_ballot()
        assert held["negative_count"] == 1, (
            f"negative_count expected 1, got {held['negative_count']}"
        )
        assert held["affirmative_count"] == 0, (
            f"affirmative_count expected 0, got {held['affirmative_count']}"
        )

        scenario.change_vote("v3", position="AFFIRMATIVE")

        revised = scenario.get_vote("v3")
        assert revised["position"] == "AFFIRMATIVE", (
            f"the owner's own revision lands, got {revised['position']}"
        )
        assert revised["position_change_count"] == 1, (
            f"position_change_count expected 1, got {revised['position_change_count']}"
        )
        ballot = scenario.get_ballot()
        assert ballot["affirmative_count"] == 1, (
            f"affirmative_count expected 1, got {ballot['affirmative_count']}"
        )
        assert ballot["negative_count"] == 0, (
            f"negative_count expected 0, got {ballot['negative_count']}"
        )
        assert ballot["returned_count"] == 1, (
            "the seat is still counted exactly once, got "
            f"{ballot['returned_count']}"
        )
        objections, meta = validate_paginated(
            api.list_comments(scenario.staff, {"source_vote_id": revised["id"]})
        )
        a.assert_total_count(meta, 1)
        assert objections[0]["status"] == "OPEN", (
            "the objection raised with the original negative stays on file, got "
            f"{objections[0]['status']}"
        )


class TestClosingEarly:
    """A ballot that has not ended closes only once every seat has returned."""

    def test_the_last_returning_seat_unlocks_the_early_close(self, api):
        """
        which lets a fully-returned ballot close early. Otherwise the response is
        `ERR_BALLOT_NOT_ENDED`.

        Design: Corner/validations/closing_early_is_refused_until_the_last_eligible_seat_has_returned
        """
        scenario = fx.open_subcommittee_ballot(api)
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")

        premature = api.close_ballot(scenario.ballot_id, scenario.chair)
        validate_error(premature, "ERR_BALLOT_NOT_ENDED", 409)

        open_still = scenario.get_ballot()
        assert open_still["status"] == "OPEN", (
            f"two of three returns is not enough, got {open_still['status']}"
        )
        assert open_still["closed_at"] is None, (
            f"closed_at expected null, got {open_still['closed_at']}"
        )
        assert open_still["consensus_result"] == "PENDING", (
            f"consensus_result expected PENDING, got {open_still['consensus_result']}"
        )

        scenario.cast("m3", "AFFIRMATIVE", vote_key="v3")
        scenario.close_ballot()

        closed = scenario.get_ballot()
        assert closed["status"] == "EVALUATED", (
            f"the identical call now succeeds, got {closed['status']}"
        )
        a.assert_same_instant(closed["closed_at"], "2026-08-01T00:00:00Z")
        a.assert_seat_ledger(
            closed,
            affirmative=3,
            negative=0,
            abstain=0,
            returned=3,
            not_returned=0,
            eligible=3,
        )
        a.assert_pct(closed["return_rate_pct"], 100.0)
        a.assert_pct(closed["provisional_approval_pct"], 100.0)
        assert closed["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {closed['consensus_result']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_READY", (
            f"the approved draft moves on, got {scenario.get_draft()['status']}"
        )
        assert scenario.get_membership("m3")["missed_ballot_streak"] == 0, (
            "the seat that returned late was not penalised, got "
            f"{scenario.get_membership('m3')['missed_ballot_streak']}"
        )
