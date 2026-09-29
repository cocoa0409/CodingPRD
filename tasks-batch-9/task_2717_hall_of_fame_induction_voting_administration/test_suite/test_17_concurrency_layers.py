"""Version tokens that go stale between a read and a write, and one cumulative-spend boundary."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CURATOR_HEADERS,
    build_election_world,
    create_ballot_payload,
    create_travel_grant_payload,
    create_vote_submission_payload,
    elector_headers,
    induction_of,
    read_candidacy,
    read_cycle,
    read_grant,
    read_induction,
    read_slot,
    screening_headers,
    slot_of,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestABallotPrintedFromAStaleSlate:
    """A screening decision lands between the read and the construction."""

    @pytest.fixture
    def world(self, api):
        """A screening cycle whose version was captured before the only ADVANCE."""
        world = build_election_world(
            api, stage="screened", elector_count=2, candidate_count=1, advance=[]
        )
        world["stale_cycle_version"] = world["cycle_version"]
        validate_success(
            api.create_screening_decision(
                world["candidacies"][0]["id"], {"decision": "ADVANCE"}, screening_headers(world)
            ),
            200,
        )
        return world

    def test_the_pre_advance_version_is_refused(self, api, world):
        """The slate a ballot prints is derived from the cycle's advanced candidacies, so if another
        writer has advanced the cycle's `version` since the administrator last read it — a screening
        `ADVANCE` that landed after the read, or another round's ballot that already superseded this one —
        the construction is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412) rather than printing a
        slate that no longer matches the record.

        Design: Corner/cross_cutting_complexity_layers/ballot_construction_against_a_superseded_cycle_version_rejected
        """
        validate_error(
            api.create_ballot(
                create_ballot_payload(world["cycle"]["id"], world["stale_cycle_version"]),
                ADMIN_HEADERS,
            ),
            "ERR_STALE_CYCLE_VERSION",
            412,
        )

    def test_the_refused_construction_prints_nothing(self, api, world):
        """For the **first ballot of a cycle** the cycle must be in `SCREENING` with
        `advanced_candidacy_count` of at least 1, and the slate is every candidacy of the cycle whose
        `status` is `ADVANCED`; the construction drives the cycle `SCREENING` → `BALLOTING` and sets its
        `current_round` to 1.

        Design: Corner/cross_cutting_complexity_layers/ballot_construction_against_a_superseded_cycle_version_rejected
        """
        api.create_ballot(
            create_ballot_payload(world["cycle"]["id"], world["stale_cycle_version"]),
            ADMIN_HEADERS,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "SCREENING"
        assert cycle["advanced_candidacy_count"] == 1
        assert cycle["current_round"] == 0
        _, meta = validate_paginated(
            api.list_ballots(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0

    def test_the_current_version_prints_the_slate_and_moves_the_cycle(self, api, world):
        """Each construction increments the cycle's `version` by 1.

        Design: Corner/cross_cutting_complexity_layers/current_cycle_version_is_accepted_and_the_write_increments_it
        """
        fresh = read_cycle(api, world["cycle"]["id"])
        assert fresh["version"] > world["stale_cycle_version"]
        ballot = validate_success(
            api.create_ballot(
                create_ballot_payload(world["cycle"]["id"], fresh["version"]), ADMIN_HEADERS
            ),
            201,
        )
        assert ballot["round_number"] == 1
        assert ballot["slot_count"] == 1
        assert ballot["voting_status"] == "DRAFT"
        assert read_cycle(api, world["cycle"]["id"])["version"] == fresh["version"] + 1

    def test_the_accepted_construction_moves_the_cycle_into_balloting(self, api, world):
        """The new ballot's `round_number` records the round it serves. For a cycle's first ballot that is
        round 1, reached from a `current_round` of 0.

        Design: Corner/cross_cutting_complexity_layers/current_cycle_version_is_accepted_and_the_write_increments_it
        """
        fresh = read_cycle(api, world["cycle"]["id"])
        validate_success(
            api.create_ballot(
                create_ballot_payload(world["cycle"]["id"], fresh["version"]), ADMIN_HEADERS
            ),
            201,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "BALLOTING"
        assert cycle["current_round"] == 1
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "ON_BALLOT"


class TestTheVersionTheFirstVoteConsumed:
    """One accepted submission invalidates every client's copy of the ballot version."""

    @pytest.fixture
    def world(self, api):
        """An open one-slot ballot with the certify-time version captured and one vote cast on it."""
        world = build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=1
        )
        world["certify_version"] = world["ballot_version"]
        validate_success(
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
        return world

    def test_the_second_elector_replaying_that_version_is_refused(self, api, world):
        """Each recorded submission, each withdrawal and each struck slot advances the ballot's `version`,
        so a value that no longer matches means the elector's client is voting a slate that is not the
        slate now printed on the ballot; the submission is rejected with `ERR_STALE_BALLOT_VERSION` (HTTP
        412) and the elector must re-read the ballot before submitting.

        Design: Corner/cross_cutting_complexity_layers/second_vote_replaying_the_version_the_first_vote_consumed_rejected
        """
        validate_error(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"],
                    [slot_of(world, 0)["id"]],
                    world["certify_version"],
                ),
                screening_headers(world),
            ),
            "ERR_STALE_BALLOT_VERSION",
            412,
        )

    def test_only_the_first_submission_survives_the_race(self, api, world):
        """The ballot's `ballots_cast` increases by 1 and its `total_selections_counted` increases by that
        submission's `selection_count`, so an abstention raises turnout without adding a single slot vote.

        Design: Corner/cross_cutting_complexity_layers/second_vote_replaying_the_version_the_first_vote_consumed_rejected
        """
        api.create_vote_submission(
            create_vote_submission_payload(
                world["ballot"]["id"], [slot_of(world, 0)["id"]], world["certify_version"]
            ),
            screening_headers(world),
        )
        ballot = validate_success(api.get_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        assert ballot["ballots_cast"] == 1
        assert ballot["total_selections_counted"] == 1
        _, meta = validate_paginated(
            api.list_vote_submissions(
                ADMIN_HEADERS, {"ballot_id": world["ballot"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1

    def test_the_slot_tally_is_still_untouched_while_voting_runs(self, api, world):
        """A slot is born `LISTED` with `votes_received` and `vote_pct` at 0.

        Design: Corner/cross_cutting_complexity_layers/second_vote_replaying_the_version_the_first_vote_consumed_rejected
        """
        api.create_vote_submission(
            create_vote_submission_payload(
                world["ballot"]["id"], [slot_of(world, 0)["id"]], world["certify_version"]
            ),
            screening_headers(world),
        )
        slot = read_slot(api, slot_of(world, 0)["id"])
        assert slot["votes_received"] == 0
        assert slot["status"] == "LISTED"

    def test_the_refreshed_token_lets_the_second_elector_in(self, api, world):
        """The `ballot_version_after` value returned with each accepted submission exists precisely so
        that the next elector can supply a fresh `expected_ballot_version` without an extra read.

        Design: Corner/cross_cutting_complexity_layers/second_vote_replaying_the_version_the_first_vote_consumed_rejected
        """
        current = validate_success(api.get_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        second = validate_success(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"], [slot_of(world, 0)["id"]], current["version"]
                ),
                screening_headers(world),
            ),
            201,
        )
        assert second["status"] == "COUNTED"
        assert validate_success(api.get_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)[
            "ballots_cast"
        ] == 2


class TestAGrantPricedAgainstASupersededBudget:
    """The concurrency rule that guards money rather than a slate."""

    @pytest.fixture
    def world(self, api):
        """A planned ceremony with two inductions, the first grant approved and 18333 committed."""
        world = build_election_world(
            api,
            stage="ceremony",
            rules=[{"election_threshold_pct": 0.5}],
            elector_count=2,
            candidate_count=2,
            votes=[(0, [0]), (1, [1])],
        )
        world["captured_version"] = world["cycle_version"]
        world["first_grant"] = validate_success(
            api.create_travel_grant(
                create_travel_grant_payload(
                    induction_of(world, 0)["id"],
                    world["captured_version"],
                    nights=1,
                    requested_airfare_cents=0,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        validate_success(
            api.approve_travel_grant(world["first_grant"]["id"], ADMIN_HEADERS), 200
        )
        return world

    def test_the_pre_approval_version_no_longer_prices_a_grant(self, api, world):
        """The award is frozen at creation from the pre-commitment budget ratio, so a stale cycle view
        means the grant would be priced against a budget position that another approved grant has already
        superseded; that request is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412).

        Design: Corner/cross_cutting_complexity_layers/travel_grant_priced_against_a_superseded_budget_position_rejected
        """
        validate_error(
            api.create_travel_grant(
                create_travel_grant_payload(
                    induction_of(world, 1)["id"],
                    world["captured_version"],
                    nights=1,
                    requested_airfare_cents=0,
                ),
                CURATOR_HEADERS,
            ),
            "ERR_STALE_CYCLE_VERSION",
            412,
        )

    def test_the_committed_position_is_exactly_the_first_award(self, api, world):
        """Approval then increases the cycle's `travel_committed_cents` by `award_cents`, which recomputes
        the cycle's `austerity_tier` from the new ratio and increments the cycle's `version` by 1.

        Design: Corner/cross_cutting_complexity_layers/travel_grant_priced_against_a_superseded_budget_position_rejected
        """
        api.create_travel_grant(
            create_travel_grant_payload(
                induction_of(world, 1)["id"],
                world["captured_version"],
                nights=1,
                requested_airfare_cents=0,
            ),
            CURATOR_HEADERS,
        )
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 18333
        assert read_grant(api, world["first_grant"]["id"])["status"] == "APPROVED"

    def test_the_refused_grant_leaves_the_second_inductee_unfunded(self, api, world):
        """The grant requires the induction's `travel_status` to be `PENDING`, and it drives that
        dimension `PENDING` → `REQUESTED`, which recomputes `ceremony_ready` (still false, since a merely
        requested grant funds nothing).

        Design: Corner/cross_cutting_complexity_layers/travel_grant_priced_against_a_superseded_budget_position_rejected
        """
        api.create_travel_grant(
            create_travel_grant_payload(
                induction_of(world, 1)["id"],
                world["captured_version"],
                nights=1,
                requested_airfare_cents=0,
            ),
            CURATOR_HEADERS,
        )
        second_id = induction_of(world, 1)["id"]
        assert read_induction(api, second_id)["travel_status"] == "PENDING"
        _, meta = validate_paginated(
            api.list_travel_grants(ADMIN_HEADERS, {"induction_id": second_id, "limit": 100})
        )
        assert meta["total_count"] == 0


class TestTheMinimalTierAtItsExactBoundary:
    """Four fifths committed to the cent, and the next award priced at six tenths."""

    @pytest.fixture
    def world(self, api):
        """A 91665-cent ceremony budget with 73332 already committed by an approved four-night grant."""
        world = build_election_world(
            api,
            stage="ceremony",
            rules=[{"election_threshold_pct": 0.5}],
            elector_count=2,
            candidate_count=2,
            votes=[(0, [0]), (1, [1])],
            ceremony_overrides={"travel_budget_cents": 91665},
        )
        world["first_grant"] = validate_success(
            api.create_travel_grant(
                create_travel_grant_payload(
                    induction_of(world, 0)["id"],
                    world["cycle_version"],
                    nights=4,
                    requested_airfare_cents=0,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        validate_success(
            api.approve_travel_grant(world["first_grant"]["id"], ADMIN_HEADERS), 200
        )
        world["cycle"] = read_cycle(api, world["cycle"]["id"])
        world["cycle_version"] = world["cycle"]["version"]
        return world

    def _second_grant(self, api, world):
        return validate_success(
            api.create_travel_grant(
                create_travel_grant_payload(
                    induction_of(world, 1)["id"],
                    world["cycle_version"],
                    nights=1,
                    requested_airfare_cents=0,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

    def test_the_first_award_is_priced_at_the_full_factor(self, api, world):
        """The nightly per-diem allowance is 18,333 cents — one hundred eighty-three dollars and
        thirty-three cents a night — and one traveller's per-diem is that allowance multiplied by
        `nights`, multiplied by the tier's spending factor, multiplied by the variant's per-diem factor,
        then rounded half-up to whole cents.

        Design: Corner/cross_cutting_complexity_layers/austerity_minimal_tier_triggers_exactly_at_the_cumulative_boundary
        """
        assert world["first_grant"]["award_cents"] == 73332
        assert world["first_grant"]["austerity_tier_applied"] == "FULL"

    def test_a_ratio_of_exactly_four_fifths_reads_as_minimal(self, api, world):
        """Both tier boundaries are inclusive at their lower edge — a cycle exactly half-committed is
        `REDUCED`, and a cycle exactly four-fifths committed is `MINIMAL`.

        Design: Corner/cross_cutting_complexity_layers/austerity_minimal_tier_triggers_exactly_at_the_cumulative_boundary
        """
        assert world["cycle"]["travel_committed_cents"] == 73332
        assert world["cycle"]["austerity_tier"] == "MINIMAL"

    def test_the_next_award_uses_the_six_tenths_factor(self, api, world):
        """The tier selects a spending factor: one for `FULL`, eight tenths for `REDUCED`, six tenths for
        `MINIMAL`.

        Design: Corner/cross_cutting_complexity_layers/austerity_minimal_tier_triggers_exactly_at_the_cumulative_boundary
        """
        second = self._second_grant(api, world)
        assert second["austerity_tier_applied"] == "MINIMAL"
        assert second["award_cents"] == 11000
        assert second["traveler_count"] == 1

    def test_the_reduced_award_still_fits_the_remaining_budget(self, api, world):
        """That same fit test is also applied at creation time, so an award that could never be funded is
        rejected before it is ever recorded.

        Design: Corner/cross_cutting_complexity_layers/austerity_minimal_tier_triggers_exactly_at_the_cumulative_boundary
        """
        second = self._second_grant(api, world)
        assert second["status"] == "REQUESTED"
        assert read_induction(api, induction_of(world, 1)["id"])["travel_status"] == "REQUESTED"
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 73332
