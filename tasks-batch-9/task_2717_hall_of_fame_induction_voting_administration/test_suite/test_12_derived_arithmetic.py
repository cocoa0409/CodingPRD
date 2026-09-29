"""Derived figures: awards, tiers, percentages, waterfalls and participation decay."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OMIT,
    approve_travel_grant,
    build_election_world,
    cast_vote,
    create_audit_decision_payload,
    create_ballot_payload,
    create_candidacy_payload,
    create_screening_decision_payload,
    create_vote_submission_payload,
    elector_headers,
    induction_of,
    read_ballot,
    read_bloc,
    read_candidacy,
    read_cycle,
    read_elector,
    read_grant,
    read_induction,
    read_slot,
    request_travel_grant,
    screening_headers,
    setup_artifact_intake,
    setup_candidate,
    setup_cycle,
    slot_of,
    validate_paginated,
    validate_success,
)

DECEASED_LATE = {
    "full_name": "Late Contributor",
    "retirement_year": 2020,
    "career_seasons": 12,
    "career_metric_value": 2500,
    "is_deceased": True,
    "death_year": 2025,
}

ABSTAINING_BODY = [(0, [0])] + [
    {"elector": index, "is_abstention": True} for index in range(1, 8)
]

WATERFALL_VOTES = [(0, [0, 1]), (1, [0, 1]), (2, [0])]


class TestTravelAwardWithBindingAirfareCap:
    """Three nights, a nine-hundred-fifty-dollar cap and a full-tier cycle."""

    @pytest.fixture
    def world(self, api):
        """A ceremony-planned cycle whose single living inductee has no grant yet."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        return world

    def test_the_cap_absorbs_the_larger_request(self, api, world):
        """One traveller's airfare is the lesser of `requested_airfare_cents` and the airfare cap of
        95,000 cents, so a nine-hundred-fifty-dollar cap silently absorbs any larger request. Those
        two figures are added to give one traveller's total, and `award_cents` is that per-traveller
        total multiplied by `traveler_count`.

        Design: Corner/calculations/travel_award_correct_result_with_airfare_cap_binding
        """
        grant = request_travel_grant(
            world, world["induction"]["id"], nights=3, requested_airfare_cents=120000
        )
        assert grant["award_cents"] == 54999 + 95000
        assert grant["requested_airfare_cents"] == 120000
        assert grant["traveler_count"] == 1
        assert grant["variant"] == "LIVING_INDUCTEE"

    def test_the_grant_freezes_the_pre_commitment_tier(self, api, world):
        """That tier is written onto the grant as `austerity_tier_applied` and never revisited.

        Design: Corner/calculations/travel_award_correct_result_with_airfare_cap_binding
        """
        grant = request_travel_grant(
            world, world["induction"]["id"], nights=3, requested_airfare_cents=120000
        )
        assert grant["austerity_tier_applied"] == "FULL"
        assert grant["status"] == "REQUESTED"
        assert grant["cycle_id"] == world["cycle"]["id"]

    def test_a_mere_request_commits_no_money(self, api, world):
        """The grant requires the induction's `travel_status` to be `PENDING`, and it drives that
        dimension `PENDING` → `REQUESTED`, which recomputes `ceremony_ready` (still false, since a
        merely requested grant funds nothing).

        Design: Corner/calculations/travel_award_correct_result_with_airfare_cap_binding
        """
        request_travel_grant(
            world, world["induction"]["id"], nights=3, requested_airfare_cents=120000
        )
        assert read_induction(api, world["induction"]["id"])["travel_status"] == "REQUESTED"
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 0
        assert cycle["austerity_tier"] == "FULL"


class TestTallyExcludesWithdrawnSubmission:
    """A withdrawn ballot contributes to nothing the tally reports."""

    @pytest.fixture
    def world(self, api):
        """An open single-slot ballot with two credentialed electors."""
        return build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=1
        )

    def _cast_withdraw_and_recast(self, api, world):
        first = cast_vote(world, (0, [0]))
        withdrawn = validate_success(
            api.withdraw_vote_submission(first["id"], elector_headers(world, 0)), 200
        )
        world["ballot_version"] = withdrawn["ballot_version_after"]
        cast_vote(world, (1, [0]))
        validate_success(api.close_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        return withdrawn, validate_success(
            api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200
        )

    def test_only_counted_submissions_feed_the_turnout_figures(self, api, world):
        """Counting itself considers only submissions whose `status` is `COUNTED`; `WITHDRAWN` and
        `INVALIDATED` submissions are excluded from every figure.

        Design: Corner/calculations/tally_excludes_withdrawn_submission_from_counts
        """
        withdrawn, ballot = self._cast_withdraw_and_recast(api, world)
        assert withdrawn["status"] == "WITHDRAWN"
        assert ballot["ballots_cast"] == 1
        assert ballot["total_selections_counted"] == 1
        assert ballot["credentialed_roster_at_close"] == 2
        assert ballot["tally_status"] == "PENDING_AUDIT"

    def test_the_surviving_ballot_alone_sets_the_slot_score(self, api, world):
        """The ballot's `ballots_cast` is the number of such submissions and its
        `total_selections_counted` is the sum of their `selection_count` values.

        Design: Corner/calculations/tally_excludes_withdrawn_submission_from_counts
        """
        _, ballot = self._cast_withdraw_and_recast(api, world)
        slot = read_slot(api, world["slot_list"][0]["id"])
        assert slot["votes_received"] == 1
        assert slot["vote_pct"] == pytest.approx(1.0, abs=0.005)
        assert ballot["threshold_votes_provisional"] == 1


class TestPosthumousWaitingConstant:
    """The posthumous branch ignores the rule's own waiting figure."""

    @pytest.fixture
    def world(self, api):
        """An open 2026 cycle with a posthumous rule and one deceased candidate."""
        return build_election_world(
            api,
            stage="nominations_open",
            rules=[{"pathway": "POSTHUMOUS", "waiting_period_years": 5}],
            elector_count=1,
            candidate_specs=[DECEASED_LATE],
        )

    def _file(self, api, world):
        return api.create_candidacy(
            create_candidacy_payload(
                world["cycle"]["id"],
                world["candidates"][0]["id"],
                world["electors"][0]["id"],
                pathway="POSTHUMOUS",
            ),
            ADMIN_HEADERS,
        )

    def test_the_baseline_is_the_later_year_plus_a_single_year(self, api, world):
        """For such a nomination the baseline year is the later of the candidate's `retirement_year`
        and their `death_year`, and the effective waiting period is a single year rather than the
        rule's own figure.

        Design: Corner/calculations/posthumous_waiting_constant_sets_eligible_from_year
        """
        candidacy = validate_success(self._file(api, world), 201)
        assert candidacy["eligible_from_year"] == 2025 + 1
        assert candidacy["pathway"] == "POSTHUMOUS"
        assert candidacy["status"] == "SUBMITTED"

    def test_the_cycle_year_at_the_boundary_is_accepted(self, api, world):
        """Waiting is checked inclusively: the cycle's `cycle_year` must be greater than or equal to
        the computed `eligible_from_year`, and a cycle running earlier than that is refused with
        `ERR_WAITING_PERIOD_NOT_MET` (HTTP 422).

        Design: Corner/calculations/posthumous_waiting_constant_sets_eligible_from_year
        """
        candidacy = validate_success(self._file(api, world), 201)
        assert candidacy["eligible_from_year"] == world["cycle"]["cycle_year"]
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["nomination_count"] == 1
        assert cycle["special_election_used"] == 0


class TestVotePercentageRoundsHalfUp:
    """One vote in eight is 0.125, and half-up makes that 0.13."""

    @pytest.fixture
    def world(self, api):
        """An eight-elector body where one elector votes and seven abstain."""
        return build_election_world(
            api,
            stage="voting_closed",
            elector_count=8,
            candidate_count=1,
            votes=ABSTAINING_BODY,
        )

    def test_the_percentage_rounds_up_at_the_exact_half(self, api, world):
        """Then, for each slot of the ballot whose `status` is `LISTED`, `votes_received` becomes the
        number of counted submissions whose `selected_slot_ids` contains that slot's identifier, and
        `vote_pct` becomes `votes_received` divided by `ballots_cast`, rounded half-up to two
        decimal places — or exactly 0 when `ballots_cast` is 0.

        Design: Corner/calculations/vote_pct_rounds_half_up_to_two_decimals
        """
        validate_success(api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        slot = read_slot(api, world["slot_list"][0]["id"])
        assert slot["votes_received"] == 1
        assert slot["vote_pct"] == pytest.approx(0.13, abs=0.005)

    def test_the_abstentions_raise_the_denominator_for_everyone(self, api, world):
        """An abstention raises `ballots_cast`, and therefore raises every slot's denominator, while
        contributing no votes to any slot — abstaining is a way of voting against the whole field.

        Design: Corner/calculations/vote_pct_rounds_half_up_to_two_decimals
        """
        ballot = validate_success(api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        assert ballot["ballots_cast"] == 8
        assert ballot["total_selections_counted"] == 1
        assert ballot["credentialed_roster_at_close"] == 8
        assert ballot["threshold_votes_provisional"] == 6
        assert ballot["max_votes_per_elector"] == 1


class TestSeatWaterfallStopsAtMaxInductees:
    """Two slots qualify, one seat exists, and the cap decides."""

    @pytest.fixture
    def world(self, api):
        """An audited four-slot ballot on a cycle capped at one inductee."""
        return build_election_world(
            api,
            stage="audited",
            rules=[{"election_threshold_pct": 0.50, "runoff_floor_pct": 0.25}],
            elector_count=3,
            candidate_count=4,
            votes=WATERFALL_VOTES,
            cycle_overrides={"max_inductees": 1},
        )

    def test_only_as_many_slots_as_there_are_seats_are_elected(self, api, world):
        """The number of seats available is the cycle's `max_inductees` minus the number of
        candidacies of this cycle already in `ELECTED` status from earlier rounds. The elected set is
        the leading run of the ranked list, taking as many as there are seats or as many as
        qualified, whichever is fewer.

        Design: Corner/calculations/seat_waterfall_stops_at_max_inductees
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["threshold_votes_final"] == 2
        assert ballot["elected_slot_count"] == 1
        assert ballot["tally_status"] == "AUDIT_CERTIFIED"
        assert ballot["threshold_votes_provisional"] == 2
        assert ballot["max_votes_per_elector"] == 2

    def test_a_qualifying_slot_that_missed_the_seat_is_not_elected(self, api, world):
        """Slot statuses follow from the resolved outcome. Every slot in the elected set becomes
        `ELECTED`. Every slot in the carry set becomes `CARRIED_TO_RUNOFF`, but only when the
        `outcome` is `RUNOFF_REQUIRED`. Every other `LISTED` slot becomes `NOT_ELECTED`.

        Design: Corner/calculations/seat_waterfall_stops_at_max_inductees
        """
        winner = read_slot(api, slot_of(world, 0)["id"])
        runner_up = read_slot(api, slot_of(world, 1)["id"])
        unvoted = read_slot(api, slot_of(world, 2)["id"])
        assert (winner["votes_received"], winner["status"]) == (3, "ELECTED")
        assert winner["vote_pct"] == pytest.approx(1.0, abs=0.005)
        assert (runner_up["votes_received"], runner_up["status"]) == (2, "NOT_ELECTED")
        assert runner_up["vote_pct"] == pytest.approx(0.67, abs=0.005)
        assert (unvoted["votes_received"], unvoted["status"]) == (0, "NOT_ELECTED")
        assert unvoted["vote_pct"] == pytest.approx(0.0, abs=0.005)

    def test_an_elected_slot_suppresses_the_runoff(self, api, world):
        """If at least one slot was elected, the `outcome` is `ELECTION_COMPLETE`.

        Design: Corner/calculations/seat_waterfall_stops_at_max_inductees
        """
        assert read_ballot(api, world["ballot"]["id"])["outcome"] == "ELECTION_COMPLETE"
        assert read_cycle(api, world["cycle"]["id"])["current_round"] == 1
        for index in (0, 1):
            candidacy = read_candidacy(api, world["candidacies"][index]["id"])
            assert candidacy["status"] == "ON_BALLOT"
        first = read_candidacy(api, world["candidacies"][0]["id"])
        second = read_candidacy(api, world["candidacies"][1]["id"])
        assert first["latest_round_votes"] == 3
        assert first["latest_round_pct"] == pytest.approx(1.0, abs=0.005)
        assert second["latest_round_votes"] == 2
        assert second["latest_round_pct"] == pytest.approx(0.67, abs=0.005)


def run_certified_cycle(api, world, *, cycle_year, candidate_id):
    """Drive one further cycle from setup to CERTIFIED with electors 0 and 1 voting."""
    cycle = setup_cycle(api, cycle_year=cycle_year)
    validate_success(api.open_nominations(cycle["id"], ADMIN_HEADERS), 200)
    candidacy = validate_success(
        api.create_candidacy(
            create_candidacy_payload(cycle["id"], candidate_id, world["electors"][0]["id"]),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(api.close_nominations(cycle["id"], ADMIN_HEADERS), 200)
    validate_success(
        api.create_screening_decision(
            candidacy["id"], create_screening_decision_payload("ADVANCE"), screening_headers(world)
        ),
        200,
    )
    cycle = read_cycle(api, cycle["id"])
    ballot = validate_success(
        api.create_ballot(create_ballot_payload(cycle["id"], cycle["version"]), ADMIN_HEADERS), 201
    )
    slots, _ = validate_paginated(
        api.list_ballot_slots(ADMIN_HEADERS, {"ballot_id": ballot["id"], "limit": 100})
    )
    ballot = validate_success(api.certify_ballot(ballot["id"], ADMIN_HEADERS), 200)
    version = ballot["version"]
    for headers in (elector_headers(world, 0), screening_headers(world)):
        submission = validate_success(
            api.create_vote_submission(
                create_vote_submission_payload(ballot["id"], [slots[0]["id"]], version), headers
            ),
            201,
        )
        version = submission["ballot_version_after"]
    validate_success(api.close_ballot(ballot["id"], ADMIN_HEADERS), 200)
    validate_success(api.tally_ballot(ballot["id"], ADMIN_HEADERS), 200)
    validate_success(
        api.create_audit_decision(
            ballot["id"], create_audit_decision_payload("CERTIFY"), AUDITOR_HEADERS
        ),
        200,
    )
    return validate_success(api.certify_election(cycle["id"], ADMIN_HEADERS), 200)


class TestParticipationDecayAcrossTwoCycles:
    """One missed cycle is a warning; the second one ends the tenure."""

    @pytest.fixture
    def world(self, api):
        """A certified 2026 cycle in which the third elector never voted."""
        return build_election_world(
            api,
            stage="certified",
            rules=[{"election_threshold_pct": 0.50}],
            elector_count=3,
            candidate_count=2,
            votes=[(0, [0]), (1, [0])],
        )

    def test_the_first_missed_cycle_only_increments_the_counter(self, api, world):
        """A non-participating elector has `consecutive_missed_cycles` incremented by 1, and if the
        incremented counter is greater than or equal to 2 the elector's `status` flips to the
        terminal `LAPSED` — the comparison is inclusive and is evaluated after the increment, so two
        consecutive missed certified cycles is the trigger, not three.

        Design: Corner/calculations/participation_counter_increments_then_lapses_on_second_missed_cycle
        """
        absentee = read_elector(api, world["electors"][2]["id"])
        assert absentee["consecutive_missed_cycles"] == 1
        assert absentee["status"] == "CREDENTIALED"
        assert absentee["last_participated_cycle_year"] is None
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 3

    def test_the_second_missed_cycle_lapses_the_elector_and_frees_the_seat(self, api, world):
        """A lapse decrements that elector's bloc `seats_filled` by 1, freeing the seat for a new
        credential, and the freed seat is immediately available to the credentialing check of §3.2.

        Design: Corner/calculations/participation_counter_increments_then_lapses_on_second_missed_cycle
        """
        replacement = setup_candidate(
            api,
            full_name="Player Three",
            retirement_year=2016,
            career_seasons=13,
            career_metric_value=2600,
        )
        second = run_certified_cycle(
            api, world, cycle_year=2027, candidate_id=replacement["id"]
        )
        assert second["status"] == "CERTIFIED"
        assert second["induction_count"] == 1
        absentee = read_elector(api, world["electors"][2]["id"])
        assert absentee["consecutive_missed_cycles"] == 2
        assert absentee["status"] == "LAPSED"
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 2

    def test_participation_resets_the_counter_and_stamps_the_year(self, api, world):
        """A participating elector has `consecutive_missed_cycles` reset to 0 and
        `last_participated_cycle_year` set to this cycle's `cycle_year`.

        Design: Corner/calculations/participation_counter_increments_then_lapses_on_second_missed_cycle
        """
        replacement = setup_candidate(
            api,
            full_name="Player Three",
            retirement_year=2016,
            career_seasons=13,
            career_metric_value=2600,
        )
        run_certified_cycle(api, world, cycle_year=2027, candidate_id=replacement["id"])
        for index in (0, 1):
            voter = read_elector(api, world["electors"][index]["id"])
            assert voter["consecutive_missed_cycles"] == 0
            assert voter["last_participated_cycle_year"] == 2027
            assert voter["status"] == "CREDENTIALED"


class TestAusterityTierBoundaryAtHalfTheBudget:
    """A cycle exactly half committed prices the next grant one tier down."""

    @pytest.fixture
    def world(self, api):
        """A ceremony-planned cycle with two inductees and a 299,998-cent travel budget."""
        world = build_election_world(
            api,
            stage="ceremony",
            rules=[{"election_threshold_pct": 0.75, "runoff_floor_pct": 0.25}],
            elector_count=2,
            candidate_count=4,
            votes=[(0, [0, 1]), (1, [0, 1])],
            ceremony_overrides={"travel_budget_cents": 299998},
        )
        world["induction_a"] = induction_of(world, 0)
        world["induction_b"] = induction_of(world, 1)
        return world

    def _first_grant(self, world):
        grant = request_travel_grant(
            world, world["induction_a"]["id"], nights=3, requested_airfare_cents=95000
        )
        approve_travel_grant(world, grant["id"])
        return grant

    def test_the_second_grant_prices_at_the_reduced_tier(self, api, world):
        """Both tier boundaries are inclusive at their lower edge — a cycle exactly half-committed is
        `REDUCED`, and a cycle exactly four-fifths committed is `MINIMAL`. The tier selects a
        spending factor: one for `FULL`, eight tenths for `REDUCED`, six tenths for `MINIMAL`.

        Design: Corner/calculations/austerity_tier_boundary_at_exactly_half_the_budget
        """
        first = self._first_grant(world)
        assert first["award_cents"] == 149999
        assert first["austerity_tier_applied"] == "FULL"
        second = request_travel_grant(
            world, world["induction_b"]["id"], nights=3, requested_airfare_cents=95000
        )
        assert second["austerity_tier_applied"] == "REDUCED"
        assert second["award_cents"] == 43999 + 95000

    def test_only_approved_grants_move_the_ratio(self, api, world):
        """Only grants already in `APPROVED` status contribute to `travel_committed_cents`; grants
        sitting in `REQUESTED`, `DENIED` or `CANCELLED` contribute nothing, so the tier reflects
        committed money rather than pending intent.

        Design: Corner/calculations/austerity_tier_boundary_at_exactly_half_the_budget
        """
        self._first_grant(world)
        second = request_travel_grant(
            world, world["induction_b"]["id"], nights=3, requested_airfare_cents=95000
        )
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 149999
        approved = validate_success(api.approve_travel_grant(second["id"], ADMIN_HEADERS), 200)
        assert approved["status"] == "APPROVED"
        assert approved["traveler_count"] == 1
        assert approved["variant"] == "LIVING_INDUCTEE"

    def test_the_second_approval_pushes_the_cycle_to_the_minimal_tier(self, api, world):
        """Approval then increases the cycle's `travel_committed_cents` by `award_cents`, which
        recomputes the cycle's `austerity_tier` from the new ratio and increments the cycle's
        `version` by 1.

        Design: Corner/calculations/austerity_tier_boundary_at_exactly_half_the_budget
        """
        self._first_grant(world)
        second = request_travel_grant(
            world, world["induction_b"]["id"], nights=3, requested_airfare_cents=95000
        )
        validate_success(api.approve_travel_grant(second["id"], ADMIN_HEADERS), 200)
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 288998
        assert cycle["austerity_tier"] == "MINIMAL"
        assert cycle["induction_count"] == 2


class TestTravelDenialWaivesTheDimension:
    """A denied grant funds nothing and yet clears the readiness gate."""

    REASON = "Inductee is travelling at their own expense"

    @pytest.fixture
    def world(self, api):
        """A ceremony-planned, artifact-exempt induction holding one requested grant."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        setup_artifact_intake(api, world["induction"]["id"], artifact_count=OMIT, is_exempt=True)
        world["grant"] = request_travel_grant(
            world, world["induction"]["id"], nights=3, requested_airfare_cents=120000
        )
        return world

    def test_denial_waives_the_travel_dimension_without_committing_money(self, api, world):
        """Denial takes a `cancellation_reason`, moves the grant `REQUESTED` → `DENIED`, and
        deliberately leaves the cycle's `travel_committed_cents` and `austerity_tier` untouched,
        because nothing was ever committed.

        Design: Corner/calculations/travel_denial_waives_the_dimension_and_flips_readiness
        """
        denied = validate_success(
            api.deny_travel_grant(
                world["grant"]["id"], ADMIN_HEADERS, {"cancellation_reason": self.REASON}
            ),
            200,
        )
        assert denied["status"] == "DENIED"
        assert denied["cancellation_reason"] == self.REASON
        assert denied["award_cents"] == 149999
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 0
        assert cycle["austerity_tier"] == "FULL"

    def test_the_waived_dimension_flips_readiness_without_any_exhibit(self, api, world):
        """Its interesting effect is on the induction: `travel_status` moves `REQUESTED` → `WAIVED`,
        meaning the inductee travels unfunded and stops blocking ceremony readiness. `WAIVED` is as
        good as `APPROVED` for readiness purposes.

        Design: Corner/calculations/travel_denial_waives_the_dimension_and_flips_readiness
        """
        validate_success(
            api.deny_travel_grant(
                world["grant"]["id"], ADMIN_HEADERS, {"cancellation_reason": self.REASON}
            ),
            200,
        )
        induction = read_induction(api, world["induction"]["id"])
        assert induction["travel_status"] == "WAIVED"
        assert induction["artifact_status"] == "EXEMPT"
        assert induction["exhibit_status"] == "NOT_PLANNED"
        assert induction["ceremony_ready"] is True
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 1
        assert read_grant(api, world["grant"]["id"])["status"] == "DENIED"
