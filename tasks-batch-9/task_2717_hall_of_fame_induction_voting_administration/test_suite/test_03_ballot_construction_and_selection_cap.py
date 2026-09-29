"""Printing the slate: the selection cap, the two fresh dimensions, appearances."""

from test_helpers import (
    build_election_world,
    read_candidacy,
    read_cycle,
    slot_of,
)

VETERANS_RULES = [{}, {"pathway": "VETERANS"}]

VETERANS_SLATE_CANDIDATES = [
    {
        "full_name": "Modern One",
        "retirement_year": 2018,
        "career_seasons": 15,
        "career_metric_value": 3000,
    },
    {
        "full_name": "Modern Two",
        "retirement_year": 2017,
        "career_seasons": 14,
        "career_metric_value": 2800,
    },
    {
        "full_name": "Old Timer",
        "retirement_year": 1995,
        "career_seasons": 20,
        "career_metric_value": 3500,
    },
]

VETERANS_SLATE_NOMINATIONS = [
    {"candidate_index": 0, "pathway": "MODERN"},
    {"candidate_index": 1, "pathway": "MODERN"},
    {"candidate_index": 2, "pathway": "VETERANS"},
]


class TestSelectionCapClampOrder:
    """A three-slot slate carrying one veterans-committee entry."""

    def _world(self, api):
        return build_election_world(
            api,
            stage="ballot_draft",
            rules=VETERANS_RULES,
            elector_count=3,
            candidate_specs=VETERANS_SLATE_CANDIDATES,
            nominations=VETERANS_SLATE_NOMINATIONS,
        )

    def test_veterans_bonus_adds_one_selection_to_the_clamped_half_slate(self, api):
        """Finally, if at least one of this ballot's `LISTED` slots has a `pathway_snapshot` of
        `VETERANS`, add one selection for the veterans committee, capped once more at 5.

        Design: Difficulty/combinatorial_formula/max_votes_per_elector_nested_clamp_order
        """
        world = self._world(api)
        assert world["ballot"]["slot_count"] == 3
        assert {slot["pathway_snapshot"] for slot in world["slot_list"]} == {
            "MODERN",
            "VETERANS",
        }
        assert world["ballot"]["max_votes_per_elector"] == 2

    def test_a_three_slot_slate_alone_yields_a_single_selection(self, api):
        """Clamp the result into the range from a floor of 1 to a ceiling of 5 selections — a
        nine-slot ballot yields four, a three-slot ballot yields one, and a twelve-slot ballot
        is capped at five.

        Design: Difficulty/combinatorial_formula/max_votes_per_elector_nested_clamp_order
        """
        world = build_election_world(
            api, stage="ballot_draft", elector_count=3, candidate_count=3
        )
        assert world["ballot"]["slot_count"] == 3
        assert {slot["pathway_snapshot"] for slot in world["slot_list"]} == {"MODERN"}
        assert world["ballot"]["max_votes_per_elector"] == 1

    def test_a_fresh_ballot_sits_at_the_start_of_both_dimensions(self, api):
        """A constructed ballot is in `DRAFT` on the voting dimension and `NOT_TALLIED` on the
        tabulation dimension, with `ballots_cast`, `total_selections_counted`,
        `credentialed_roster_at_close`, `threshold_votes_provisional`, `threshold_votes_final`
        and `elected_slot_count` all at 0, and `outcome`, `tallied_by_user_id` and `audit_note`
        unset.

        Design: Difficulty/combinatorial_formula/max_votes_per_elector_nested_clamp_order
        """
        ballot = self._world(api)["ballot"]
        assert ballot["voting_status"] == "DRAFT"
        assert ballot["tally_status"] == "NOT_TALLIED"
        for counter in (
            "ballots_cast",
            "total_selections_counted",
            "credentialed_roster_at_close",
            "threshold_votes_provisional",
            "threshold_votes_final",
            "elected_slot_count",
        ):
            assert ballot[counter] == 0, f"{counter} must start at 0"
        assert ballot["outcome"] is None
        assert ballot["tallied_by_user_id"] is None
        assert ballot["audit_note"] is None

    def test_printing_the_first_slate_drives_the_cycle_into_round_one(self, api):
        """For the **first ballot of a cycle** the cycle must be in `SCREENING` with
        `advanced_candidacy_count` of at least 1, and the slate is every candidacy of the cycle
        whose `status` is `ADVANCED`; the construction drives the cycle `SCREENING` →
        `BALLOTING` and sets its `current_round` to 1.

        Design: Difficulty/combinatorial_formula/max_votes_per_elector_nested_clamp_order
        """
        world = self._world(api)
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "BALLOTING"
        assert cycle["current_round"] == 1
        assert cycle["advanced_candidacy_count"] == 3
        assert world["ballot"]["round_number"] == 1

    def test_printing_the_slate_stamps_the_appearance_number(self, api):
        """On a first round each `ADVANCED` candidacy is simultaneously driven `ADVANCED` →
        `ON_BALLOT`, and that transition sets the candidacy's `appearance_number` to the
        candidate's `ballot_appearances_used` plus one — the appearance this printing
        represents.

        Design: Difficulty/combinatorial_formula/max_votes_per_elector_nested_clamp_order
        """
        world = self._world(api)
        for index in range(3):
            candidacy = read_candidacy(api, world["candidacies"][index]["id"])
            assert candidacy["status"] == "ON_BALLOT"
            assert candidacy["appearance_number"] == 1
            assert slot_of(world, index)["status"] == "LISTED"
