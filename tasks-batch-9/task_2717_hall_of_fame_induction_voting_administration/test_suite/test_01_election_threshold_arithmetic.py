"""The two election thresholds: turnout-based provisional, roster-based final."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    build_election_world,
    read_ballot,
    read_candidacy,
    read_slot,
    slot_of,
)


class TestTurnoutVersusRosterThresholds:
    """A three-of-five turnout makes the two denominators diverge."""

    @pytest.fixture
    def world(self, api):
        """Five credentialed electors, a two-slot ballot, only three voters."""
        return build_election_world(
            api,
            stage="audited",
            elector_count=5,
            candidate_count=2,
            votes=[(0, [0]), (1, [0]), (2, [0])],
        )

    def test_provisional_threshold_counts_only_the_votes_actually_cast(self, api, world):
        """Take the `election_threshold_pct` of the house threshold row (the eligibility rule
        for `PLAYER` paired with `MODERN`, per §3.1), multiply it by the ballot's
        `ballots_cast`, and round the product up to the next whole vote; the result is stored
        as `threshold_votes_provisional`.

        Design: Difficulty/dual_variant_calc/threshold_turnout_vs_roster_divergence
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["ballots_cast"] == 3
        assert ballot["threshold_votes_provisional"] == 3

    def test_final_threshold_counts_the_whole_frozen_roster(self, api, world):
        """Take the same house `election_threshold_pct`, multiply it by the ballot's frozen
        `credentialed_roster_at_close`, round the product up to the next whole vote, and store
        it as `threshold_votes_final`.

        Design: Difficulty/dual_variant_calc/threshold_turnout_vs_roster_divergence
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["credentialed_roster_at_close"] == 5
        assert ballot["threshold_votes_final"] == 4
        assert ballot["threshold_votes_final"] > ballot["threshold_votes_provisional"]

    def test_slot_at_the_provisional_bar_still_misses_the_final_bar(self, api, world):
        """Because the denominator is the full credentialed roster rather than turnout,
        non-voters now count against every candidate: the final threshold is always at least
        as large as the provisional one, and a slot can sit exactly at the provisional
        threshold and still fall short of the final one.

        Design: Difficulty/dual_variant_calc/threshold_turnout_vs_roster_divergence
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        slot = read_slot(api, slot_of(world, 0)["id"])
        assert slot["votes_received"] == 3
        assert slot["votes_received"] == ballot["threshold_votes_provisional"]
        assert slot["votes_received"] < ballot["threshold_votes_final"]
        assert slot["vote_pct"] == pytest.approx(1.0, abs=0.01)
        assert slot["status"] == "NOT_ELECTED"
        assert ballot["elected_slot_count"] == 0

    def test_lone_runoff_contender_resolves_no_election_on_a_closed_ballot(self, api, world):
        """In every other case the `outcome` is `NO_ELECTION`; note in particular that a round
        in which exactly one slot cleared the runoff floor and nobody was elected resolves
        `NO_ELECTION`, because a runoff needs at least two contenders to be a contest.

        Design: Difficulty/dual_variant_calc/threshold_turnout_vs_roster_divergence
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["outcome"] == "NO_ELECTION"
        assert ballot["tally_status"] == "AUDIT_CERTIFIED"
        assert ballot["voting_status"] == "CLOSED"


class TestRosterThresholdExactEquality:
    """A four-elector roster puts one slot exactly on the final threshold."""

    @pytest.fixture
    def world(self, api):
        """Four credentialed electors: three back the first slot, one backs the second."""
        return build_election_world(
            api,
            stage="audited",
            elector_count=4,
            candidate_count=2,
            votes=[(0, [0]), (1, [0]), (2, [0]), (3, [1])],
        )

    def test_slot_exactly_at_the_final_threshold_is_elected(self, api, world):
        """The qualifying slots are those whose `votes_received` is greater than or equal to
        `threshold_votes_final`.

        Design: Difficulty/boundary_precision_check/roster_threshold_exact_equality_elects_slot
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["credentialed_roster_at_close"] == 4
        assert ballot["threshold_votes_final"] == 3
        slot = read_slot(api, slot_of(world, 0)["id"])
        assert slot["votes_received"] == 3
        assert slot["vote_pct"] == pytest.approx(0.75, abs=0.01)
        assert slot["status"] == "ELECTED"

    def test_slot_one_vote_short_is_not_elected(self, api, world):
        """Both thresholds are compared against a slot's `votes_received` inclusively, and both
        denominators are frozen values on the ballot row that are never recomputed at read
        time.

        Design: Difficulty/boundary_precision_check/roster_threshold_exact_equality_elects_slot
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        loser = read_slot(api, slot_of(world, 1)["id"])
        assert loser["votes_received"] == 1
        assert loser["vote_pct"] == pytest.approx(0.25, abs=0.01)
        assert loser["status"] == "NOT_ELECTED"
        assert ballot["elected_slot_count"] == 1
        assert ballot["outcome"] == "ELECTION_COMPLETE"

    def test_certification_copies_the_slot_figures_onto_the_candidacy(self, api, world):
        """Certification then copies each scored candidacy's figures back onto the candidacy
        itself: `latest_round_votes` takes its slot's `votes_received` and `latest_round_pct`
        takes its slot's `vote_pct`, rounded to two decimal places, so that the carryover
        machinery in §3.8 can read a candidacy's last result without re-reading the ballot.

        Design: Difficulty/boundary_precision_check/roster_threshold_exact_equality_elects_slot
        """
        winner = read_candidacy(api, world["candidacies"][0]["id"], ADMIN_HEADERS)
        assert winner["latest_round_votes"] == 3
        assert winner["latest_round_pct"] == pytest.approx(0.75, abs=0.01)
        loser = read_candidacy(api, world["candidacies"][1]["id"], ADMIN_HEADERS)
        assert loser["latest_round_votes"] == 1
        assert loser["latest_round_pct"] == pytest.approx(0.25, abs=0.01)
