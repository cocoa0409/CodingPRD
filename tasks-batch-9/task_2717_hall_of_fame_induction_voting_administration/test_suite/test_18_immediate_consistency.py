"""Write responses that must already carry everything a follow-up read would report."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    build_election_world,
    create_vote_submission_payload,
    elector_headers,
    read_candidacy,
    read_candidate,
    read_cycle,
    slot_of,
    validate_paginated,
    validate_success,
)


class TestCertificationPaysOutInsideOneRequest:
    """The certify-election body, and then the reads that must agree with it."""

    @pytest.fixture
    def world(self, api):
        """A certified count on a one-slot ballot, with no induction row written yet."""
        world = build_election_world(
            api, stage="audited", elector_count=2, candidate_count=1, votes=[(0, [0]), (1, [0])]
        )
        _, meta = validate_paginated(
            api.list_inductions(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0
        return world

    def test_the_write_response_already_counts_the_induction_it_created(self, api, world):
        """Election certification is a single administrator action that closes out the balloting phase and
        pays out every consequence at once.

        Design: Corner/consistency_model/certification_response_carries_every_derived_counter_immediately
        """
        certified = validate_success(
            api.certify_election(world["cycle"]["id"], ADMIN_HEADERS), 200
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["induction_count"] == 1
        assert certified["ceremony_ready_count"] == 0

    def test_the_induction_is_listable_in_the_same_sequence(self, api, world):
        """Each new induction records the `cycle_id` that elected it, the `candidacy_id` that won and the
        `candidate_id` of the person, and it freezes a `delegation_type` derived from the candidate's
        `is_deceased` flag as read at certification: `LIVING` when the candidate was not deceased,
        `POSTHUMOUS_DELEGATION` when they were.

        Design: Corner/consistency_model/certification_response_carries_every_derived_counter_immediately
        """
        validate_success(api.certify_election(world["cycle"]["id"], ADMIN_HEADERS), 200)
        rows, meta = validate_paginated(
            api.list_inductions(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 1
        assert rows[0]["candidacy_id"] == world["candidacies"][0]["id"]
        assert rows[0]["delegation_type"] == "LIVING"
        assert rows[0]["status"] == "ANNOUNCED"

    def test_the_candidacy_and_the_candidate_move_in_the_same_breath(self, api, world):
        """That transition sets the candidate's `hof_status` to `INDUCTED`, increments the candidate's
        `ballot_appearances_used` by 1, and creates exactly one `Induction`.

        Design: Corner/consistency_model/certification_response_carries_every_derived_counter_immediately
        """
        validate_success(api.certify_election(world["cycle"]["id"], ADMIN_HEADERS), 200)
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "ELECTED"
        candidate = read_candidate(api, world["candidates"][0]["id"])
        assert candidate["hof_status"] == "INDUCTED"
        assert candidate["ballot_appearances_used"] == 1

    def test_the_cycle_re_read_repeats_the_write_response(self, api, world):
        """Each induction creation increments the cycle's `induction_count` by 1 and recomputes the cycle's
        `ceremony_ready_count`.

        Design: Corner/consistency_model/certification_response_carries_every_derived_counter_immediately
        """
        certified = validate_success(
            api.certify_election(world["cycle"]["id"], ADMIN_HEADERS), 200
        )
        reread = read_cycle(api, world["cycle"]["id"])
        assert reread["induction_count"] == certified["induction_count"]
        assert reread["ceremony_ready_count"] == certified["ceremony_ready_count"]
        assert reread["status"] == certified["status"]


class TestTheSubmissionCarriesItsParentsNewVersion:
    """The one confidential write whose parent the caller cannot always re-read."""

    @pytest.fixture
    def world(self, api):
        """An open one-slot ballot with the certification version captured and nothing cast."""
        world = build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=1
        )
        world["certify_version"] = world["ballot_version"]
        return world

    def _cast(self, api, world):
        return validate_success(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"],
                    [slot_of(world, 0)["id"]],
                    world["certify_version"],
                ),
                elector_headers(world, 0),
            ),
            201,
        )

    def test_the_mirror_matches_a_separate_read_of_the_ballot(self, api, world):
        """Two convenience mirrors exist so that a client does not have to re-read a parent after a write:
        a vote submission reports `ballot_version_after`, the ballot's `version` immediately after that
        submission was recorded.

        Design: Corner/consistency_model/vote_submission_response_carries_the_post_write_ballot_version
        """
        submission = self._cast(api, world)
        ballot = validate_success(
            api.get_ballot(world["ballot"]["id"], elector_headers(world, 0)), 200
        )
        assert submission["ballot_version_after"] == ballot["version"]

    def test_the_mirror_is_exactly_one_step_past_certification(self, api, world):
        """The ballot's `version` increments by 1, and the new value is echoed back on the submission as
        `ballot_version_after` so that the next elector can supply a fresh `expected_ballot_version`
        without re-reading the ballot.

        Design: Corner/consistency_model/vote_submission_response_carries_the_post_write_ballot_version
        """
        submission = self._cast(api, world)
        assert submission["ballot_version_after"] == world["certify_version"] + 1

    def test_the_submission_row_is_counted_the_moment_it_is_written(self, api, world):
        """An accepted submission moves three counters and refreshes one derived figure.

        Design: Corner/consistency_model/vote_submission_response_carries_the_post_write_ballot_version
        """
        submission = self._cast(api, world)
        assert submission["status"] == "COUNTED"
        assert submission["selection_count"] == 1
        ballot = validate_success(api.get_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        assert ballot["ballots_cast"] == 1
        assert ballot["total_selections_counted"] == 1
        assert ballot["voting_status"] == "OPEN"
