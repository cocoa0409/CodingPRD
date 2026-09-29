"""The two bounded rework loops: screening information requests and audit rejection."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    build_election_world,
    elector_headers,
    read_candidacy,
    read_cycle,
    read_ballot,
    read_slot,
    read_submission,
    screening_headers,
    slot_of,
    validate_error,
    validate_success,
)


class TestInformationRequestLoop:
    """A candidacy queried twice, then advanced."""

    @pytest.fixture
    def world(self, api):
        """One nominated candidacy sitting in `SCREENING`, nothing advanced yet."""
        return build_election_world(
            api, stage="screened", elector_count=3, candidate_count=1, advance=[]
        )

    def _decide(self, api, world, decision):
        return api.create_screening_decision(
            world["candidacies"][0]["id"], {"decision": decision}, screening_headers(world)
        )

    def _supplement(self, api, world, note):
        return api.create_supplement(
            world["candidacies"][0]["id"],
            {"supplement_note": note},
            elector_headers(world, 0),
        )

    def test_request_info_moves_the_candidacy_out_of_screening_and_counts_it(self, api, world):
        """It moves the candidacy from `SCREENING` to `INFO_REQUESTED` and increments its
        `info_request_count` by 1.

        Design: Difficulty/non_linear_state_machine/candidacy_info_request_revision_cycle_bounded
        """
        candidacy = validate_success(self._decide(api, world, "REQUEST_INFO"), 200)
        assert candidacy["status"] == "INFO_REQUESTED"
        assert candidacy["info_request_count"] == 1

    def test_the_nominators_supplement_closes_the_loop_back_to_screening(self, api, world):
        """The supplement note is appended to the candidacy's `screening_notes` and the candidacy
        returns to `SCREENING`, where the committee may advance, reject, defer or — if it has a
        request left in the budget — query it again.

        Design: Difficulty/non_linear_state_machine/candidacy_info_request_revision_cycle_bounded
        """
        validate_success(self._decide(api, world, "REQUEST_INFO"), 200)
        candidacy = validate_success(self._supplement(api, world, "Statistics attached"), 200)
        assert candidacy["status"] == "SCREENING"
        assert "Statistics attached" in (candidacy["screening_notes"] or "")

    def test_a_third_information_request_is_refused_at_the_bound(self, api, world):
        """The loop it opens — `SCREENING` → `INFO_REQUESTED` → `SCREENING` — is bounded: the
        committee may request information at most twice on the same candidacy, so a
        `REQUEST_INFO` decision on a candidacy whose `info_request_count` has already reached
        two is refused with `ERR_INFO_REQUEST_LIMIT` (HTTP 409).

        Design: Difficulty/non_linear_state_machine/candidacy_info_request_revision_cycle_bounded
        """
        validate_success(self._decide(api, world, "REQUEST_INFO"), 200)
        validate_success(self._supplement(api, world, "First supplement"), 200)
        validate_success(self._decide(api, world, "REQUEST_INFO"), 200)
        validate_success(self._supplement(api, world, "Second supplement"), 200)
        validate_error(self._decide(api, world, "REQUEST_INFO"), "ERR_INFO_REQUEST_LIMIT", 409)
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["info_request_count"] == 2
        assert candidacy["status"] == "SCREENING"

    def test_advance_after_the_loop_lifts_the_cycle_counter(self, api, world):
        """Advancing increments the cycle's `advanced_candidacy_count` by 1, and that counter
        change increments the cycle's `version` by 1, which is precisely how a late advance
        invalidates an administrator's in-flight ballot construction.

        Design: Difficulty/non_linear_state_machine/candidacy_info_request_revision_cycle_bounded
        """
        validate_success(self._decide(api, world, "REQUEST_INFO"), 200)
        validate_success(self._supplement(api, world, "First supplement"), 200)
        before = read_cycle(api, world["cycle"]["id"])
        assert before["advanced_candidacy_count"] == 0
        candidacy = validate_success(self._decide(api, world, "ADVANCE"), 200)
        assert candidacy["status"] == "ADVANCED"
        after = read_cycle(api, world["cycle"]["id"])
        assert after["advanced_candidacy_count"] == 1
        assert after["version"] == before["version"] + 1
        assert after["status"] == "SCREENING"

    def test_every_decision_records_the_acting_screener(self, api, world):
        """Whichever decision is recorded, the candidacy's `screened_by_elector_id` is set to the
        acting `X-User-ID`, so the record always shows who last touched it.

        Design: Difficulty/non_linear_state_machine/candidacy_info_request_revision_cycle_bounded
        """
        screener_id = world["electors"][1]["id"]
        candidacy = validate_success(self._decide(api, world, "REQUEST_INFO"), 200)
        assert candidacy["screened_by_elector_id"] == screener_id
        validate_success(self._supplement(api, world, "Statistics attached"), 200)
        advanced = validate_success(self._decide(api, world, "ADVANCE"), 200)
        assert advanced["screened_by_elector_id"] == screener_id


class TestAuditRejectionLoop:
    """A rejected tally, a re-tally, and a second certification."""

    AUDIT_NOTE = "Elector was not on the roster"

    @pytest.fixture
    def world(self, api):
        """Four credentialed electors, three of whom voted, with a draft tally in hand."""
        return build_election_world(
            api,
            stage="tallied",
            elector_count=4,
            candidate_count=2,
            votes=[(0, [0]), (1, [0]), (2, [0])],
        )

    def _reject(self, api, world):
        return api.create_audit_decision(
            world["ballot"]["id"],
            {
                "decision": "REJECT",
                "invalidate_submission_ids": [world["submissions"][0]["id"]],
                "audit_note": self.AUDIT_NOTE,
            },
            AUDITOR_HEADERS,
        )

    def test_audit_rejection_leaves_the_voting_dimension_at_closed(self, api, world):
        """The two dimensions are genuinely independent: `voting_status` runs `DRAFT` → `OPEN` →
        `CLOSED` (or `OPEN` → `EXPIRED`, which is terminal), while `tally_status` runs
        `NOT_TALLIED` → `PENDING_AUDIT` → `AUDIT_CERTIFIED`, with `PENDING_AUDIT` →
        `AUDIT_REJECTED` → `PENDING_AUDIT` as its rework loop, and the tabulation dimension
        advances while the voting dimension sits still at `CLOSED`.

        Design: Difficulty/non_linear_state_machine/ballot_parallel_dimensions_with_audit_rejection_cycle
        """
        assert world["ballot"]["voting_status"] == "CLOSED"
        assert world["ballot"]["tally_status"] == "PENDING_AUDIT"
        ballot = validate_success(self._reject(api, world), 200)
        assert ballot["tally_status"] == "AUDIT_REJECTED"
        assert ballot["voting_status"] == "CLOSED"

    def test_invalidated_submission_stores_the_audit_note_as_its_reason(self, api, world):
        """Every submission whose identifier appears in `invalidate_submission_ids` moves
        `COUNTED` → `INVALIDATED` and stores the auditor's `audit_note` as its
        `invalidated_reason`.

        Design: Difficulty/non_linear_state_machine/ballot_parallel_dimensions_with_audit_rejection_cycle
        """
        validate_success(self._reject(api, world), 200)
        submission = read_submission(api, world["submissions"][0]["id"])
        assert submission["status"] == "INVALIDATED"
        assert submission["invalidated_reason"] == self.AUDIT_NOTE

    def test_each_invalidation_rolls_the_ballot_counters_back(self, api, world):
        """Each invalidation decrements the ballot's `ballots_cast` by 1 and reduces its
        `total_selections_counted` by that submission's `selection_count`.

        Design: Difficulty/non_linear_state_machine/ballot_parallel_dimensions_with_audit_rejection_cycle
        """
        ballot = validate_success(self._reject(api, world), 200)
        assert ballot["ballots_cast"] == 2
        assert ballot["total_selections_counted"] == 2

    def test_rejection_resets_the_provisional_threshold_and_frees_the_count(self, api, world):
        """The rejection then resets `threshold_votes_provisional` to 0 and clears
        `tallied_by_user_id`, which is what allows a re-tally — possibly by a different
        administrator — to claim the count afresh.

        Design: Difficulty/non_linear_state_machine/ballot_parallel_dimensions_with_audit_rejection_cycle
        """
        assert world["ballot"]["threshold_votes_provisional"] == 3
        ballot = validate_success(self._reject(api, world), 200)
        assert ballot["threshold_votes_provisional"] == 0
        assert ballot["tallied_by_user_id"] is None

    def test_the_retally_recomputes_every_figure_from_the_survivors(self, api, world):
        """A re-tally over the surviving counted submissions closes the loop `PENDING_AUDIT` →
        `AUDIT_REJECTED` → `PENDING_AUDIT`, recomputing every slot figure and the provisional
        threshold from scratch and writing the new `tallied_by_user_id`.

        Design: Difficulty/non_linear_state_machine/ballot_parallel_dimensions_with_audit_rejection_cycle
        """
        validate_success(self._reject(api, world), 200)
        ballot = validate_success(api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        assert ballot["tally_status"] == "PENDING_AUDIT"
        assert ballot["threshold_votes_provisional"] == 2
        assert ballot["tallied_by_user_id"] is not None
        slot = read_slot(api, slot_of(world, 0)["id"])
        assert slot["votes_received"] == 2
        assert slot["vote_pct"] == pytest.approx(1.0, abs=0.01)

    def test_the_second_certification_closes_the_tabulation_dimension(self, api, world):
        """Take the same house `election_threshold_pct`, multiply it by the ballot's frozen
        `credentialed_roster_at_close`, round the product up to the next whole vote, and store
        it as `threshold_votes_final`.

        Design: Difficulty/non_linear_state_machine/ballot_parallel_dimensions_with_audit_rejection_cycle
        """
        validate_success(self._reject(api, world), 200)
        validate_success(api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        ballot = validate_success(
            api.create_audit_decision(
                world["ballot"]["id"],
                {"decision": "CERTIFY", "audit_note": "Count accepted"},
                AUDITOR_HEADERS,
            ),
            200,
        )
        assert ballot["tally_status"] == "AUDIT_CERTIFIED"
        assert ballot["voting_status"] == "CLOSED"
        assert ballot["credentialed_roster_at_close"] == 4
        assert ballot["threshold_votes_final"] == 3
        assert ballot["outcome"] == "NO_ELECTION"
        assert read_slot(api, slot_of(world, 0)["id"])["status"] == "NOT_ELECTED"
        assert read_ballot(api, world["ballot"]["id"])["elected_slot_count"] == 0
