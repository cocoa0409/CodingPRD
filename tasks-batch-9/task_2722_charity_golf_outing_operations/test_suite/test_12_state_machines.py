"""The outing's play dimension: its declared edges, preconditions and cascades."""

import pytest

from test_helpers import (
    CLOCK_START_UTC,
    DIRECTOR_HEADERS,
    ApiErrorId,
    assert_direct_costs,
    assert_instant_equals,
    assert_rollup_chain,
    assert_version_unchanged,
    scramble_team_handicap,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

SEED_OUTING = {"name": "Seed State Open", "field_capacity_teams": 4}

# Slope 113 and a course rating equal to par make the raw conversion the identity,
# so each course handicap is exactly the rounded index.
RAW_RATINGS = {"slope_rating": 113, "course_rating": 72.0, "par": 72}
LOCK_OUTING = {"name": "Lock Path Open", "field_capacity_teams": 4}
LOCK_INDEXES = (12.0, 18.4, 8.2, 24.0)
LOCK_COURSE_HANDICAPS = [12, 18, 8, 24]


class TestFreshOutingSeedStates:
    def test_the_create_call_seeds_the_two_dimensions_independently(self, api):
        """Neither seed is read off the other, and both are filterable immediately.

        The PRD states the pair outright: "A freshly created outing sits at `DRAFT`
        on its play dimension and `COLLECTING` on its finance dimension."  Every
        rollup figure "is initialised to 0, as are the operational counters
        `reopen_count`", while "The `proceeds_variant` marker is initialised to
        `PROVISIONAL`".  Both dimensions are readable as filters, because "Outings
        can be listed with either dimension as a filter."

        Design: Corner/state_machines/new_outing_starts_in_draft_on_the_play_dimension_and_collecting_on_finance
        """
        fx.set_clock(api, CLOCK_START_UTC)

        created = validate_success(
            api.create_outing(f.outing_payload(**SEED_OUTING), DIRECTOR_HEADERS), 201
        )
        assert created["play_status"] == "DRAFT"
        assert created["finance_status"] == "COLLECTING"
        assert created["proceeds_variant"] == "PROVISIONAL"
        assert created["reopen_count"] == 0

        drafts, draft_meta = validate_paginated(
            api.list_outings(DIRECTOR_HEADERS, play_status="DRAFT")
        )
        assert draft_meta["total_count"] == 1
        assert [row["id"] for row in drafts] == [created["id"]]

        _, open_meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS, play_status="OPEN"))
        assert open_meta["total_count"] == 0

        _, collecting_meta = validate_paginated(
            api.list_outings(DIRECTOR_HEADERS, finance_status="COLLECTING")
        )
        assert collecting_meta["total_count"] == 1


class TestLockFieldWritesTheLockedHandicap:
    def test_the_lock_caps_each_index_and_rewrites_the_team_figure(self, api):
        """One full foursome, so the lock's three-hop cascade runs end to end.

        "Locking the field moves it `OPEN → FIELD_LOCKED` and requires at least one
        team to exist and every team of the outing to hold exactly four players",
        and at that moment "`effective_handicap_index` is written as the larger of
        the golfer's current `handicap_index` and their `handicap_index_at_confirm`
        reduced by 3.0 strokes".  Nothing moved since confirmation here, so each
        capped value is the index itself.  The team figure follows: "Under
        `SCRAMBLE` the four sorted course handicaps are weighted 0.20, 0.15, 0.10,
        and 0.05 respectively, lowest handicap taking the largest weight", read from
        "the locked treatment reads course handicaps derived from the sandbag-capped
        `effective_handicap_index`".

        Design: Corner/state_machines/lock_field_moves_open_to_field_locked_and_writes_the_locked_team_handicap
        """
        ctx = fx.foursome_outing(
            api,
            handicap_indexes=LOCK_INDEXES,
            outing=LOCK_OUTING,
            contract=RAW_RATINGS,
            team_name="Foursome A",
        )
        version_before = ctx["team"]["version"]

        outing = fx.lock_field(api, ctx["outing_id"])
        assert outing["play_status"] == "FIELD_LOCKED"
        assert outing["finance_status"] == "COLLECTING"

        rows, _ = validate_paginated(
            api.list_players(DIRECTOR_HEADERS, registration_id=ctx["registration_id"])
        )
        by_id = {row["id"]: row for row in rows}
        assert [by_id[pid]["course_handicap"] for pid in ctx["player_ids"]] == (
            LOCK_COURSE_HANDICAPS
        )
        for pid in ctx["player_ids"]:
            player = by_id[pid]
            assert player["effective_handicap_index"] == pytest.approx(
                player["handicap_index"], abs=0.01
            )

        team = fx.read_team(api, ctx["team_id"])
        assert team["handicap_variant"] == "LOCKED"
        assert team["team_playing_handicap"] == pytest.approx(6.4, abs=0.01)
        assert team["team_playing_handicap"] == pytest.approx(
            scramble_team_handicap(LOCK_COURSE_HANDICAPS), abs=0.01
        )
        assert team["version"] > version_before


SHORT_TEAM_OUTING = {"name": "Short Team Open", "field_capacity_teams": 4}
EMPTY_FIELD_OUTING = {"name": "Empty Field Open", "field_capacity_teams": 4}
UNPAIRED_OUTING = {"name": "No Tee Sheet Open", "field_capacity_teams": 4}


class TestLockFieldWithAnIncompleteTeam:
    def test_a_three_player_team_is_a_legal_team_but_an_illegal_field(self, api):
        """The group is admissible on its own terms yet blocks the lock.

        Grouping three golfers is allowed, because "The `player_ids` array must be
        non-empty, must not be longer than four, and must not be longer than the
        `player_count` of the registration that funded the players, otherwise
        `ERR_TEAM_SIZE_INVALID`", since "a team holds between one and four golfers".
        The lock is stricter: it "requires at least one team to exist and every team
        of the outing to hold exactly four players, otherwise `ERR_TEAM_INCOMPLETE`".

        Design: Corner/state_machines/lock_field_with_a_three_player_team_is_rejected
        """
        ctx = fx.open_outing(api, outing=SHORT_TEAM_OUTING)
        reg = fx.confirmed_registration(
            api, ctx, players=(10.0, 14.0, 20.0), player_count=4, buyer_name="Threesome Ltd"
        )
        team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="Threesome")
        assert team["player_count"] == 3
        assert team["handicap_variant"] == "PROVISIONAL"

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("LOCK_FIELD"), DIRECTOR_HEADERS
            ),
            ApiErrorId.TEAM_INCOMPLETE,
            409,
        )

        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "OPEN"
        assert fx.read_team(api, team["id"])["handicap_variant"] == "PROVISIONAL"


class TestLockFieldWithNoTeams:
    def test_an_empty_field_is_not_vacuously_complete(self, api):
        """Zero teams reports the same code as a short team, not a success.

        The precondition is a conjunction whose first half is an existence test:
        the lock "requires at least one team to exist and every team of the outing
        to hold exactly four players, otherwise `ERR_TEAM_INCOMPLETE`".

        Design: Corner/state_machines/lock_field_with_no_teams_at_all_is_rejected
        """
        ctx = fx.open_outing(api, outing=EMPTY_FIELD_OUTING)
        version_before = ctx["outing"]["version"]

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("LOCK_FIELD"), DIRECTOR_HEADERS
            ),
            ApiErrorId.TEAM_INCOMPLETE,
            409,
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["play_status"] == "OPEN"
        assert_version_unchanged(outing, version_before)


class TestStartPlayWithoutATeeAssignment:
    def test_a_legally_locked_field_still_needs_a_starting_hole(self, api):
        """The gate reads each team's own placement history, not the outing's state.

        "Starting play moves it `FIELD_LOCKED → IN_PLAY` and requires that every
        team of the outing has had a tee assignment written at least once and
        carries a non-null `starting_hole`, otherwise `ERR_MISSING_TEE_ASSIGNMENT`."
        A team that has never been placed starts with `tee_assignment_count` at 0,
        because "`tee_assignment_count` starts at 0".

        Design: Corner/state_machines/start_play_without_a_tee_assignment_is_rejected
        """
        ctx = fx.locked_field_outing(api, outing=UNPAIRED_OUTING)
        assert ctx["outing"]["play_status"] == "FIELD_LOCKED"

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("START_PLAY"), DIRECTOR_HEADERS
            ),
            ApiErrorId.MISSING_TEE_ASSIGNMENT,
            409,
        )

        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "FIELD_LOCKED"
        team = fx.read_team(api, ctx["team_id"])
        assert team["tee_assignment_count"] == 0
        assert team["starting_hole"] is None


OPEN_CONTEST_OUTING = {"name": "Open Contest Open", "field_capacity_teams": 4}
PIN_CONTEST = {"contest_type": "CLOSEST_TO_PIN", "hole_number": 7, "prize_value_cents": 20000}

HALF_CARDED_OUTING = {"name": "Half Carded Open", "field_capacity_teams": 4}
ALPHA_INDEXES = (10.0, 12.0, 16.0, 20.0)
BRAVO_INDEXES = (9.0, 13.0, 17.0, 21.0)
SECOND_TEE_TIME = "2026-09-19T12:10:00Z"
ALPHA_CARD = {
    "gross_score": 70,
    "gross_back_9": 34,
    "gross_back_6": 22,
    "gross_back_3": 11,
    "gross_hole_18": 4,
}


class TestFinalizeScoringWithAnOpenContest:
    def test_a_complete_card_is_not_enough_while_a_contest_is_still_running(self, api):
        """The same error code covers unfinished contest administration.

        The gate is a conjunction: "Every team of the outing must carry a non-null
        `gross_score`, `gross_back_9`, `gross_back_6`, `gross_back_3`, and
        `gross_hole_18`, and every contest that has not been voided must have left
        `OPEN`; a failure of either is `ERR_MISSING_SCORES`."  Voiding clears the
        obstruction, since "Voiding is available from `PLANNED`, from `OPEN`, and
        from `CLOSED` with identical effect from all three".

        Design: Corner/state_machines/finalize_scoring_with_a_still_open_contest_is_rejected
        """
        ctx = fx.foursome_outing(api, outing=OPEN_CONTEST_OUTING, team_name="Scored Team")
        contest = fx.new_contest(api, ctx["outing_id"], **PIN_CONTEST)
        assert contest["requires_insurance"] is False

        fx.lock_field(api, ctx["outing_id"])
        assert fx.drive_contest(api, contest["id"], "OPEN")["status"] == "OPEN"
        fx.assign_tee(api, ctx["team_id"])
        fx.start_play(api, ctx["outing_id"])
        fx.post_score(api, ctx["team_id"])

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("FINALIZE_SCORING"), DIRECTOR_HEADERS
            ),
            ApiErrorId.MISSING_SCORES,
            409,
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["play_status"] == "IN_PLAY"
        assert outing["unclaimed_prize_cents"] == 0
        assert fx.read_team(api, ctx["team_id"])["rank_position"] is None

        assert fx.drive_contest(api, contest["id"], "VOID")["status"] == "VOID"
        assert fx.finalize_scoring(api, ctx["outing_id"])["play_status"] == "SCORED"


class TestFinalizeScoringWithAMissingCard:
    def test_one_uncarded_group_blocks_the_whole_field(self, api):
        """Two groups tee off, one posts, and no partial ranking is written.

        The first clause of the gate names all five figures: "Every team of the
        outing must carry a non-null `gross_score`, `gross_back_9`, `gross_back_6`,
        `gross_back_3`, and `gross_hole_18`", and the refusal is what protects the
        ordering, because "Because a team with a null gross score blocks the
        transition entirely, the ranked set is always the full field."  Until then
        every team keeps the creation defaults, where `rank_position` starts null
        and "`prize_award_cents` starts at 0".

        Design: Corner/state_machines/finalize_scoring_with_a_missing_score_card_is_rejected
        """
        ctx = fx.open_outing(api, outing=HALF_CARDED_OUTING)
        first = fx.confirmed_registration(
            api, ctx, players=ALPHA_INDEXES, buyer_name="Team One Buyer"
        )
        alpha = fx.new_team(api, ctx["outing_id"], first["player_ids"], team_name="Alpha")
        second = fx.confirmed_registration(
            api, ctx, players=BRAVO_INDEXES, buyer_name="Team Two Buyer"
        )
        bravo = fx.new_team(api, ctx["outing_id"], second["player_ids"], team_name="Bravo")

        fx.lock_field(api, ctx["outing_id"])
        fx.assign_tee(api, alpha["id"], cart_number=1)
        fx.assign_tee(api, bravo["id"], cart_number=2, tee_time=SECOND_TEE_TIME)
        fx.start_play(api, ctx["outing_id"])
        fx.post_score(api, alpha["id"], **ALPHA_CARD)

        assert fx.read_team(api, bravo["id"])["gross_score"] is None

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("FINALIZE_SCORING"), DIRECTOR_HEADERS
            ),
            ApiErrorId.MISSING_SCORES,
            409,
        )

        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "IN_PLAY"

        rows, meta = validate_paginated(
            api.list_teams(DIRECTOR_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert row["rank_position"] is None
            assert row["prize_award_cents"] == 0


UNSIGNED_OUTING = {"name": "Unsigned Open", "field_capacity_teams": 4}
NO_TIER_OUTING = {"name": "Nothing To Sell Open", "field_capacity_teams": 4}


class TestOpenRegistrationWithADraftContract:
    def test_the_gate_reads_the_contract_status_not_its_existence(self, api):
        """A contract row exists, a tier exists, and the open is still refused.

        "Opening registration moves the outing `DRAFT → OPEN`, and it has two
        preconditions: the outing must have a contract whose status is `SIGNED` or
        `AMENDED`, and an outing with no contract at all fails the same check with
        `ERR_CONTRACT_NOT_SIGNED`".  A fresh contract is not yet there, since "A new
        contract begins at `DRAFT` with `signed_at` null", and the remedy is the
        signature: "Signing moves the contract from `DRAFT` to `SIGNED` and stamps
        `signed_at` from the logical clock."

        Design: Corner/state_machines/open_registration_with_a_draft_contract_is_rejected
        """
        fx.set_clock(api, CLOCK_START_UTC)
        outing = fx.new_outing(api, **UNSIGNED_OUTING)
        contract = fx.new_contract(api, outing["id"])
        tier = fx.new_tier(api, outing["id"])
        assert contract["status"] == "DRAFT"
        assert contract["signed_at"] is None
        assert tier["outing_id"] == outing["id"]

        validate_error(
            api.play_transition(
                outing["id"], f.play_transition_payload("OPEN_REGISTRATION"), DIRECTOR_HEADERS
            ),
            ApiErrorId.CONTRACT_NOT_SIGNED,
            409,
        )
        assert fx.read_outing(api, outing["id"])["play_status"] == "DRAFT"

        signed = fx.sign_contract(api, contract["id"])
        assert signed["status"] == "SIGNED"
        assert fx.drive_play(api, outing["id"], "OPEN_REGISTRATION")["play_status"] == "OPEN"


class TestOpenRegistrationWithNoPackageTier:
    def test_a_signed_contract_with_nothing_to_sell_still_cannot_open(self, api):
        """The second precondition fires only once the first one is satisfied.

        The two preconditions are ordered, and this one is stated last: "and the
        outing must already have at least one package tier, otherwise
        `ERR_NO_PACKAGE_TIER`".  That is the same requirement as "Before
        registration can open, the `TournamentDirector` must publish at least one".

        Design: Corner/state_machines/open_registration_with_no_package_tier_is_rejected
        """
        ctx = fx.signed_contract_outing(api, outing=NO_TIER_OUTING)
        assert ctx["contract"]["status"] == "SIGNED"

        validate_error(
            api.play_transition(
                ctx["outing_id"],
                f.play_transition_payload("OPEN_REGISTRATION"),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.NO_PACKAGE_TIER,
            409,
        )
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "DRAFT"


NO_TERMS_OUTING = {
    "name": "No Terms Open",
    "field_capacity_teams": 4,
    "rain_date": f.DEFAULT_RAIN_DATE,
}
RAINOUT_OUTING = {
    "name": "Rainout Open",
    "field_capacity_teams": 4,
    "rain_date": f.DEFAULT_RAIN_DATE,
}
FULL_CREDIT_CONTRACT = {"rain_date_terms": "FULL_CREDIT"}
CLEARED_PLACEMENT_FIELDS = (
    "wave",
    "starting_hole",
    "tee_time",
    "cart_number",
    "slot_occupancy_start",
    "slot_occupancy_end",
)


class TestPostponeWithoutRainDateTerms:
    def test_an_alternate_date_without_contractual_credit_is_refused(self, api):
        """The conjunction fails on its second half, and nothing at all moves.

        "Two conditions must hold: the outing must carry a non-null `rain_date`, and
        the contract's `rain_date_terms` must be `FULL_CREDIT` or `PARTIAL_CREDIT`;
        if either fails the request is refused with `ERR_NO_RAIN_DATE_TERMS`."  An
        unnegotiated contract fails it by default, because "the `rain_date_terms`
        default to `NONE`".

        Design: Corner/state_machines/postpone_without_rain_date_terms_is_rejected
        """
        ctx = fx.open_outing(api, outing=NO_TERMS_OUTING)
        assert fx.read_contract(api, ctx["contract_id"])["rain_date_terms"] == "NONE"

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("POSTPONE"), DIRECTOR_HEADERS
            ),
            ApiErrorId.NO_RAIN_DATE_TERMS,
            409,
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["play_status"] == "OPEN"
        assert_instant_equals(outing["scheduled_date"], f.DEFAULT_SCHEDULED_DATE)
        assert_instant_equals(outing["rain_date"], f.DEFAULT_RAIN_DATE)
        assert outing["postponed_from_date"] is None

        contract = fx.read_contract(api, ctx["contract_id"])
        assert contract["rain_credit_cents"] == 0
        assert contract["amendment_count"] == 0
        assert contract["status"] == "SIGNED"


class TestPostponeUnderFullCredit:
    def test_one_transition_rotates_the_dates_credits_the_course_and_clears_the_sheet(self, api):
        """Every declared side effect of the postponement, in one accepted request.

        "On acceptance the server captures the outgoing `scheduled_date` into
        `postponed_from_date`, promotes the `rain_date` into `scheduled_date`, and
        clears `rain_date` back to null."  The course pays for it: "`rain_credit_cents`
        is set to the outing's `course_charge_cents` as it stood immediately before
        the postponement when the terms are `FULL_CREDIT`", and "The same request
        increments the contract's `amendment_count` by one and moves the contract's
        status to `AMENDED`".  The credit lands in the rollup, where
        "`direct_costs_cents` is `course_charge_cents` plus `fnb_shortfall_cents`
        plus `insurance_cost_cents` plus `prize_cost_cents`, less the contract's
        `rain_credit_cents`".  The field is unplaced but its history survives:
        "every team of the outing has its `wave`, `starting_hole`, `tee_time`,
        `cart_number`, `slot_occupancy_start`, and `slot_occupancy_end` cleared to
        null", while "but its `tee_assignment_count` is deliberately preserved".

        Design: Corner/state_machines/postpone_shifts_the_date_credits_the_contract_and_clears_the_tee_sheet
        """
        ctx = fx.foursome_outing(
            api, outing=RAINOUT_OUTING, contract=FULL_CREDIT_CONTRACT, team_name="Rain Team"
        )
        fx.assign_tee(api, ctx["team_id"], cart_number=3)
        before = fx.read_outing(api, ctx["outing_id"])
        assert before["course_charge_cents"] == 38000

        outing = fx.drive_play(api, ctx["outing_id"], "POSTPONE")
        assert outing["play_status"] == "POSTPONED"
        assert_instant_equals(outing["postponed_from_date"], f.DEFAULT_SCHEDULED_DATE)
        assert_instant_equals(outing["scheduled_date"], f.DEFAULT_RAIN_DATE)
        assert outing["rain_date"] is None

        contract = fx.read_contract(api, ctx["contract_id"])
        assert contract["status"] == "AMENDED"
        assert contract["amendment_count"] == 1
        assert contract["rain_credit_cents"] == 38000

        assert outing["course_charge_cents"] == 38000
        assert outing["fnb_shortfall_cents"] == 0
        assert outing["direct_costs_cents"] == 0
        assert outing["net_proceeds_before_fee_cents"] == 120000
        assert outing["admin_fee_cents"] == 6000
        assert outing["net_proceeds_cents"] == 114000
        assert_direct_costs(outing, rain_credit_cents=38000)
        assert_rollup_chain(outing)

        team = fx.read_team(api, ctx["team_id"])
        for field in CLEARED_PLACEMENT_FIELDS:
            assert team[field] is None, f"{field} must be cleared by the postponement"
        assert team["tee_assignment_count"] == 1


WRONG_EDGE_OUTING = {"name": "Wrong Edge Open", "field_capacity_teams": 4}
TERMINAL_OUTING = {"name": "Terminal Play Open", "field_capacity_teams": 4}


class TestUndeclaredEdgesOutOfOpen:
    @pytest.mark.parametrize("action", ["START_PLAY", "FINALIZE_SCORING", "RESUME"])
    def test_an_action_that_is_not_an_edge_out_of_open_reports_the_transition_error(
        self, api, action
    ):
        """Each of the three names an origin the outing is not sitting in.

        The ladder places the edge test above every business rule: "the requested
        action is a declared edge out of the target row's current state in the
        relevant lifecycle, including the parallel dimensions carried by outings and
        contests, otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."  None of
        these three leaves `OPEN`: "Starting play moves it `FIELD_LOCKED → IN_PLAY`",
        "Finalizing scoring moves it `IN_PLAY → SCORED`", and "Resuming returns the
        outing `POSTPONED → OPEN` and does nothing else."  So the refusal is the
        undeclared edge rather than the missing tee assignment a start would also
        fail on.

        Design: Corner/state_machines/start_play_from_open_is_not_a_declared_edge
        """
        ctx = fx.open_outing(api, outing=WRONG_EDGE_OUTING)
        version_before = ctx["outing"]["version"]

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload(action), DIRECTOR_HEADERS
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["play_status"] == "OPEN"
        assert_version_unchanged(outing, version_before)


class TestScoredIsTerminalOnThePlayDimensionOnly:
    def test_the_play_dimension_is_closed_while_the_finance_dimension_still_moves(self, api):
        """A per-dimension terminal state is not a dead row.

        "Finalizing scoring moves it `IN_PLAY → SCORED`, which is terminal on the
        play dimension", and cancellation is no way out either, because "Cancelling
        the outing is available from `DRAFT`, from `OPEN`, and from `POSTPONED`".
        The sibling dimension is untouched by that: reconciliation "moves the finance
        dimension `COLLECTING → RECONCILED`. It requires that the play dimension has
        already reached `SCORED`", and "On acceptance it switches `proceeds_variant`
        to `FINAL` and rewrites every finance field under the final treatment."

        Design: Corner/state_machines/terminal_scored_outing_refuses_every_further_play_action
        """
        ctx = fx.scored_outing(api, outing=TERMINAL_OUTING)
        assert ctx["outing"]["play_status"] == "SCORED"
        version_before = fx.outing_version(api, ctx["outing_id"])

        for action in ("OPEN_REGISTRATION", "CANCEL_OUTING"):
            validate_error(
                api.play_transition(
                    ctx["outing_id"], f.play_transition_payload(action), DIRECTOR_HEADERS
                ),
                ApiErrorId.INVALID_STATE_TRANSITION,
                409,
            )

        reconciled = fx.reconcile(api, ctx["outing_id"], version_before)
        assert reconciled["finance_status"] == "RECONCILED"
        assert reconciled["proceeds_variant"] == "FINAL"
        assert reconciled["play_status"] == "SCORED"
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "SCORED"
