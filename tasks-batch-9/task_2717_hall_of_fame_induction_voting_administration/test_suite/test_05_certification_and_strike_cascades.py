"""Multi-hop cascades: election certification, and the permanent-ineligibility strike."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    build_election_world,
    create_vote_submission_payload,
    elector_headers,
    read_ballot,
    read_candidacy,
    read_candidate,
    read_cycle,
    read_elector,
    read_induction,
    read_slot,
    read_submission,
    slot_of,
    validate_error,
    validate_success,
)

TWIN_CANDIDATES = [
    {
        "full_name": "Elected Player",
        "retirement_year": 2018,
        "career_seasons": 15,
        "career_metric_value": 3000,
    },
    {
        "full_name": "Rejected Player",
        "retirement_year": 2018,
        "career_seasons": 14,
        "career_metric_value": 2800,
    },
]


class TestElectionCertificationCascade:
    """One elected slot pays out three hops: candidacy, candidate, induction."""

    @pytest.fixture
    def world(self, api):
        """Four credentialed electors, all backing the first of two slots."""
        return build_election_world(
            api,
            stage="certified",
            elector_count=4,
            candidate_specs=TWIN_CANDIDATES,
            votes=[(index, [0]) for index in range(4)],
        )

    def test_the_elected_slot_inducts_its_candidate(self, api, world):
        """That transition sets the candidate's `hof_status` to `INDUCTED`, increments the
        candidate's `ballot_appearances_used` by 1, and creates exactly one `Induction`.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["status"] == "ELECTED"
        candidate = read_candidate(api, world["candidates"][0]["id"])
        assert candidate["hof_status"] == "INDUCTED"
        assert candidate["ballot_appearances_used"] == 1
        assert len(world["inductions"]) == 1

    def test_the_induction_freezes_its_provenance_and_delegation_type(self, api, world):
        """Each new induction records the `cycle_id` that elected it, the `candidacy_id` that won
        and the `candidate_id` of the person, and it freezes a `delegation_type` derived from
        the candidate's `is_deceased` flag as read at certification: `LIVING` when the candidate
        was not deceased, `POSTHUMOUS_DELEGATION` when they were.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        induction = world["inductions"][world["candidacies"][0]["id"]]
        assert induction["cycle_id"] == world["cycle"]["id"]
        assert induction["candidacy_id"] == world["candidacies"][0]["id"]
        assert induction["candidate_id"] == world["candidates"][0]["id"]
        assert induction["delegation_type"] == "LIVING"

    def test_the_fresh_induction_sits_at_the_start_of_all_three_dimensions(self, api, world):
        """A fresh induction sits at `ANNOUNCED` / `PENDING` / `AWAITED` / `NOT_PLANNED` with
        `artifact_count` at 0 and `ceremony_ready` false.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        induction = read_induction(
            api, world["inductions"][world["candidacies"][0]["id"]]["id"]
        )
        assert induction["status"] == "ANNOUNCED"
        assert induction["travel_status"] == "PENDING"
        assert induction["artifact_status"] == "AWAITED"
        assert induction["exhibit_status"] == "NOT_PLANNED"
        assert induction["artifact_count"] == 0
        assert induction["ceremony_ready"] is False

    def test_induction_creation_moves_the_cycle_counters(self, api, world):
        """Each induction creation increments the cycle's `induction_count` by 1 and recomputes
        the cycle's `ceremony_ready_count`.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["induction_count"] == 1
        assert cycle["ceremony_ready_count"] == 0

    def test_certification_closes_the_balloting_phase(self, api, world):
        """On success the cycle moves `BALLOTING` → `CERTIFIED` and its `version` increments by 1.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "CERTIFIED"
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["outcome"] == "ELECTION_COMPLETE"
        assert ballot["elected_slot_count"] == 1

    def test_the_unelected_candidacy_spends_its_appearance_and_expires(self, api, world):
        """The rule increments the candidate's `ballot_appearances_used` by 1 first, because the
        appearance was in fact used, and only then compares.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        candidacy = read_candidacy(api, world["candidacies"][1]["id"])
        assert candidacy["status"] == "EXPIRED"
        candidate = read_candidate(api, world["candidates"][1]["id"])
        assert candidate["ballot_appearances_used"] == 1
        assert read_slot(api, slot_of(world, 1)["id"])["status"] == "NOT_ELECTED"

    def test_expiration_writes_the_veterans_committee_floor(self, api, world):
        """The candidate's `veterans_eligible_from_year` becomes the later of two years: the
        candidate's `retirement_year` plus twenty-five years, and this cycle's `cycle_year` plus
        three years.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        candidate = read_candidate(api, world["candidates"][1]["id"])
        assert candidate["veterans_eligible_from_year"] == 2043

    def test_roster_maintenance_credits_every_participating_elector(self, api, world):
        """A participating elector has `consecutive_missed_cycles` reset to 0 and
        `last_participated_cycle_year` set to this cycle's `cycle_year`.

        Design: Difficulty/transitive_cascade/certify_election_three_hop_induction_cascade
        """
        for elector in world["electors"]:
            row = read_elector(api, elector["id"])
            assert row["status"] == "CREDENTIALED"
            assert row["consecutive_missed_cycles"] == 0
            assert row["last_participated_cycle_year"] == 2026


class TestPermanentIneligibilityStrike:
    """Barring a candidate reverses a vote already recorded against their slot."""

    REASON = "Rules violation established by the review panel"

    @pytest.fixture
    def world(self, api):
        """An open two-slot ballot carrying exactly one submission for the first slot."""
        return build_election_world(
            api,
            stage="voted",
            elector_count=3,
            candidate_specs=TWIN_CANDIDATES,
            votes=[(0, [0])],
        )

    def _bar(self, api, world):
        return api.declare_permanent_ineligibility(
            world["candidates"][0]["id"],
            {"permanently_ineligible_reason": self.REASON},
            ADMIN_HEADERS,
        )

    def test_barring_a_candidate_strikes_their_live_candidacy(self, api, world):
        """Every candidacy of that candidate whose `status` is `SUBMITTED`, `SCREENING`,
        `INFO_REQUESTED`, `ADVANCED` or `ON_BALLOT` is driven to `STRUCK`.

        Design: Difficulty/transitive_cascade/permanent_ineligibility_strike_two_hop_vote_reversal
        """
        candidate = validate_success(self._bar(api, world), 200)
        assert candidate["hof_status"] == "PERMANENTLY_INELIGIBLE"
        assert candidate["permanently_ineligible_reason"] == self.REASON
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "STRUCK"

    def test_the_printed_slot_is_struck_and_shrinks_the_slate(self, api, world):
        """Every ballot slot printed for those candidacies — which is to say every slot whose
        ballot is still in `DRAFT` or `OPEN` — is set to `STRUCK` as well, which decrements that
        ballot's `slot_count` and increments the ballot's `version` by 1.

        Design: Difficulty/transitive_cascade/permanent_ineligibility_strike_two_hop_vote_reversal
        """
        assert world["ballot"]["slot_count"] == 2
        assert world["ballot"]["version"] == 3
        validate_success(self._bar(api, world), 200)
        assert read_slot(api, slot_of(world, 0)["id"])["status"] == "STRUCK"
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["slot_count"] == 1
        assert ballot["version"] == 4
        assert ballot["voting_status"] == "OPEN"

    def test_struck_selections_stop_counting_but_the_submission_survives(self, api, world):
        """Because a struck slot no longer counts, every selection of that slot in an
        already-counted submission stops counting: the slot's `votes_received` freezes at 0 and
        the ballot's `total_selections_counted` is reduced by exactly the selections the struck
        slots had accumulated.

        Design: Difficulty/transitive_cascade/permanent_ineligibility_strike_two_hop_vote_reversal
        """
        validate_success(self._bar(api, world), 200)
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["ballots_cast"] == 1
        assert ballot["total_selections_counted"] == 0
        assert read_slot(api, slot_of(world, 0)["id"])["votes_received"] == 0
        submission = read_submission(api, world["submissions"][0]["id"])
        assert submission["status"] == "COUNTED"
        assert submission["selection_count"] == 1

    def test_the_version_bump_turns_away_an_elector_holding_the_old_slate(self, api, world):
        """The `version` bump on the ballot is the intended serialization point — any elector
        holding an `expected_ballot_version` read before the strike will be turned away and
        forced to re-read the slate.

        Design: Difficulty/transitive_cascade/permanent_ineligibility_strike_two_hop_vote_reversal
        """
        stale_version = world["ballot"]["version"]
        validate_success(self._bar(api, world), 200)
        payload = create_vote_submission_payload(
            world["ballot"]["id"], [slot_of(world, 1)["id"]], stale_version
        )
        validate_error(
            api.create_vote_submission(payload, elector_headers(world, 2)),
            "ERR_STALE_BALLOT_VERSION",
            412,
        )
