"""Optimistic concurrency control and race conditions.

PRD §2.5, §3.4.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    cast_vote_payload,
    create_application,
    create_submission,
    create_submission_payload,
    declare_conflict,
    make_applicant_headers,
    make_committee_member_headers,
    run_race,
    seed_committee,
    setup_application_pending_review,
    setup_open_agenda_item,
    submit_application,
    validate_error,
    assert_exactly_one_succeeds,
    assert_race_outcome,
)


# ===========================================================================
# Optimistic concurrency (PRD §2.5)
# ===========================================================================
class TestOptimisticConcurrency:
    """PRD §2.5: 'When version is present, the server compares it to the
    persisted entity's current version; a mismatch yields
    ERR_VERSION_CONFLICT with HTTP 409. When version is omitted, the
    concurrency check is skipped and the mutation proceeds against the
    current state.'"""

    def test_stale_version_on_submit_rejected(self, api):
        """PRD §2.5: 'a mismatch yields ERR_VERSION_CONFLICT with HTTP
        409.'"""
        from test_helpers import create_application_with_submission
        app, _ = create_application_with_submission()
        # Use a stale version (the app's current version - 1 or some bogus
        # very low number). Versions begin at 1; passing version=0 will
        # never match.
        res = api.submit_application(
            app["id"],
            make_applicant_headers(app["applicant_id"]),
            {"version": 0},
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# Duplicate-vote race (PRD §3.4)
# ===========================================================================
class TestDuplicateVoteRace:
    """PRD §3.4: 'when the same member tries to insert two votes
    simultaneously on the same agenda item, the database's uniqueness
    constraint on (agenda_item_id, member_id) ensures exactly one wins
    and the loser receives ERR_DUPLICATE_VOTE (HTTP 409).'"""

    def test_concurrent_votes_same_member_exactly_one_succeeds(self, api):
        """PRD §3.4: 'exactly one wins and the loser receives
        ERR_DUPLICATE_VOTE (HTTP 409).'"""
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        voter = members[1]

        def vote_a():
            return api.cast_vote(
                item["id"], cast_vote_payload(vote_mode="APPROVE"),
                make_committee_member_headers(voter["id"]),
            )

        def vote_b():
            return api.cast_vote(
                item["id"], cast_vote_payload(vote_mode="REJECT"),
                make_committee_member_headers(voter["id"]),
            )

        results = run_race(vote_a, vote_b)
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        # The loser must be ERR_DUPLICATE_VOTE per PRD §3.4.
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_DUPLICATE_VOTE.value, (
            f"PRD §3.4: 'the loser receives ERR_DUPLICATE_VOTE'; got "
            f"{body['data']['error_id']!r}"
        )


# ===========================================================================
# Recused-vs-non-recused vote race (PRD §3.4)
# ===========================================================================
class TestRecusedVsNonRecusedRace:
    """PRD §3.4: 'when two simultaneous votes arrive for the same agenda
    item and one of them is from a recused member, the recused vote is
    rejected with ERR_MEMBER_RECUSED (HTTP 403) while the non-recused
    vote is accepted.'"""

    def test_recused_vote_rejected_other_accepted(self, api):
        """PRD §3.4: 'the recused vote is rejected with
        ERR_MEMBER_RECUSED (HTTP 403) while the non-recused vote is
        accepted.'"""
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        non_recused = members[1]
        recused = members[2]
        declare_conflict(recused, app["id"])

        def vote_clean():
            return api.cast_vote(
                item["id"], cast_vote_payload(vote_mode="APPROVE"),
                make_committee_member_headers(non_recused["id"]),
            )

        def vote_recused():
            return api.cast_vote(
                item["id"], cast_vote_payload(vote_mode="APPROVE"),
                make_committee_member_headers(recused["id"]),
            )

        results = run_race(vote_clean, vote_recused)
        outcome = assert_race_outcome(results, 1, 1)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == \
            ApiErrorId.ERR_MEMBER_RECUSED.value, (
            f"PRD §3.4: 'the recused vote is rejected with "
            f"ERR_MEMBER_RECUSED'; got {loser_body['data']['error_id']!r}"
        )


# ===========================================================================
# Concurrent submissions on same application (PRD §3.4)
# ===========================================================================
class TestConcurrentSubmissions:
    """PRD §3.4: 'Two simultaneous attempts to insert new submission
    rows on the same application also serialize on the uniqueness of
    (application_id, version_number): the server assigns version_number
    = max(existing) + 1 inside a transaction, and the loser receives
    ERR_VERSION_CONFLICT.'"""

    def test_two_simultaneous_submissions_one_wins(self, api):
        """PRD §3.4: 'the server assigns version_number = max(existing)
        + 1 inside a transaction, and the loser receives
        ERR_VERSION_CONFLICT.'"""
        app = create_application()
        headers = make_applicant_headers(app["applicant_id"])

        def sub_a():
            return api.create_submission(
                app["id"], create_submission_payload(), headers,
            )

        def sub_b():
            return api.create_submission(
                app["id"], create_submission_payload(), headers,
            )

        results = run_race(sub_a, sub_b)
        outcome = assert_race_outcome(results, 1, 1)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == \
            ApiErrorId.ERR_VERSION_CONFLICT.value, (
            f"PRD §3.4: 'the loser receives ERR_VERSION_CONFLICT'; got "
            f"{loser_body['data']['error_id']!r}"
        )
