"""Derived figures: the index conversion, the team allowance and the rain credit."""

import pytest

from test_helpers import (
    CLOCK_START_UTC,
    DIRECTOR_HEADERS,
    TREASURER_ALT_HEADERS,
    TREASURER_HEADERS,
    ApiErrorId,
    assert_direct_costs,
    assert_instant_equals,
    assert_rollup_chain,
    assert_version_unchanged,
    scramble_team_handicap,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

SOLO_TIER = {
    "code": "SOLO",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
PAIR_TIER = {
    "code": "PAIR",
    "kind": "TEAM",
    "price_cents": 60000,
    "player_slots": 2,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
# Slope 113 with a course rating equal to par makes the raw conversion the
# identity, so a course handicap is exactly the rounded index.
FLAT_RATINGS = {
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 0,
    "slope_rating": 113,
    "course_rating": 72.0,
    "par": 72,
}

HARD_OUTING = {"name": "Hard Course Open", "field_capacity_teams": 4}
HARD_CONTRACT = {
    "course_name": "Ironstone Links",
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 0,
    "slope_rating": 155,
    "course_rating": 76.0,
    "par": 71,
}
EASY_OUTING = {
    "name": "Easy Course Open",
    "beneficiary_name": "Southside Literacy Trust",
    "field_capacity_teams": 4,
}
EASY_CONTRACT = {
    "course_name": "Meadow Short Course",
    "rate_per_player_cents": 5000,
    "guaranteed_player_count": 0,
    "slope_rating": 113,
    "course_rating": 68.0,
    "par": 72,
}
EASY_TIER = dict(SOLO_TIER, price_cents=20000)

HALF_STROKE_OUTING = {"name": "Half Stroke Open", "field_capacity_teams": 4}
HALF_STROKE_CONTRACT = {
    "course_name": "Halfway House GC",
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 0,
    "slope_rating": 113,
    "course_rating": 72.5,
    "par": 72,
}

UNPAID_OUTING = {"name": "Unpaid Filter Open", "field_capacity_teams": 4}
SHORT_TEAM_OUTING = {"name": "Short Team Weights Open", "field_capacity_teams": 4}


class TestCourseHandicapClamps:
    def test_the_floor_and_the_cap_are_both_applied_after_the_rounding(self, api):
        """One brutal course and one short one, taken to opposite ends of the range.

        "The conversion multiplies the index in use by the contract's `slope_rating`
        divided by 113, then adds the contract's `course_rating` minus its `par`. That
        raw figure is rounded half up to a whole stroke, then floored at 0, then
        capped at 36", and "the cap and floor are applied after the rounding, not
        before."  On the hard card a 30.0 index converts to a raw 46.15 that the cap
        pulls back to 36; on the short card a 0.0 index converts to a raw -4 that the
        floor lifts to 0.  Neither field has been locked, so "Before the field is
        locked" the rule is that "the index in use is `handicap_index_at_confirm`, the
        value snapshotted when the package was confirmed, and
        `effective_handicap_index` remains null."

        Design: Corner/calculations/course_handicap_clamps_at_zero_and_at_the_thirty_six_stroke_cap
        """
        hard = fx.open_outing(
            api, outing=HARD_OUTING, contract=HARD_CONTRACT, tier=SOLO_TIER
        )
        high = fx.confirmed_registration(
            api, hard, players=(30.0,), buyer_name="High Index", names=["Thirty Index"]
        )
        capped = fx.read_player(api, high["player_ids"][0])
        assert capped["course_handicap"] == 36
        assert capped["handicap_index_at_confirm"] == pytest.approx(30.0, abs=0.01)
        assert capped["effective_handicap_index"] is None

        easy = fx.open_outing(
            api, outing=EASY_OUTING, contract=EASY_CONTRACT, tier=EASY_TIER
        )
        scratch = fx.confirmed_registration(
            api, easy, players=(0.0,), buyer_name="Scratch Player", names=["Zero Index"]
        )
        floored = fx.read_player(api, scratch["player_ids"][0])
        assert floored["course_handicap"] == 0
        assert floored["handicap_index_at_confirm"] == pytest.approx(0.0, abs=0.01)
        assert floored["effective_handicap_index"] is None


class TestCourseHandicapRoundingMode:
    def test_a_raw_half_stroke_rounds_upward_from_both_parities(self, api):
        """A course rated half a stroke above par makes every raw figure a tie.

        The raw figure comes from a conversion that "multiplies the index in use by
        the contract's `slope_rating` divided by 113, then adds the contract's
        `course_rating` minus its `par`", and "That raw figure is rounded half up to a
        whole stroke".  So 12.0 becomes 12.5 and then 13, and 13.0 becomes 13.5 and
        then 14, which is the behaviour half-even rounding would break in the first
        case.

        Design: Corner/calculations/course_handicap_rounds_a_raw_half_stroke_upward
        """
        ctx = fx.open_outing(
            api,
            outing=HALF_STROKE_OUTING,
            contract=HALF_STROKE_CONTRACT,
            tier=PAIR_TIER,
        )
        reg = fx.confirmed_registration(
            api,
            ctx,
            players=(12.0, 13.0),
            buyer_name="Rounding Pair",
            names=["Twelve Even", "Thirteen Odd"],
        )
        assert reg["registration"]["status"] == "CONFIRMED"

        even, odd = (fx.read_player(api, pid) for pid in reg["player_ids"])
        assert even["course_handicap"] == 13
        assert odd["course_handicap"] == 14


class TestUnpaidRegistrationLeavesTheConversionUnrun:
    def test_the_owning_registration_status_is_what_gates_the_conversion(self, api):
        """Two identical indexes on one outing, separated only by a payment.

        The conversion "runs on registration confirmation, on a waitlist promotion, on
        the field lock, on a contract amendment that changed `slope_rating`,
        `course_rating`, or `par`, and on a handicap-index update", and its input set
        is the owning row: "It runs only for players whose owning registration is
        `CONFIRMED`, `AMENDED`, or `CHECKED_IN`; a player whose registration is
        `PENDING_PAYMENT`, `WAITLISTED`, `CANCELLED`, or `REFUNDED` keeps
        `course_handicap` null."  The unpaid row is invisible to the field count too,
        because "Creation does not touch the outing's `waitlisted_registration_count`,
        because a fresh registration is pending payment, not waitlisted."

        Design: Corner/calculations/players_on_an_unpaid_registration_keep_a_null_course_handicap
        """
        ctx = fx.open_outing(
            api, outing=UNPAID_OUTING, contract=FLAT_RATINGS, tier=SOLO_TIER
        )
        paid = fx.confirmed_registration(
            api, ctx, players=(12.0,), buyer_name="Paid Golfer", names=["Paid Twelve"]
        )
        unpaid = fx.pending_registration(
            api, ctx, players=(12.0,), buyer_name="Unpaid Golfer"
        )

        converted = fx.read_player(api, paid["player_ids"][0])
        assert converted["course_handicap"] == 12
        assert converted["handicap_index_at_confirm"] == pytest.approx(12.0, abs=0.01)

        untouched = fx.read_player(api, unpaid["player_ids"][0])
        assert untouched["handicap_index"] == pytest.approx(12.0, abs=0.01)
        assert untouched["course_handicap"] is None
        assert untouched["handicap_index_at_confirm"] is None

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["confirmed_player_slots"] == 1
        assert outing["waitlisted_registration_count"] == 0


class TestScrambleWeightsOnAShortTeam:
    def test_the_unused_weights_are_dropped_rather_than_redistributed(self, api):
        """A twosome takes the first two weights and nothing stands in for the rest.

        "Under `SCRAMBLE` the four sorted course handicaps are weighted 0.20, 0.15,
        0.10, and 0.05 respectively, lowest handicap taking the largest weight. Each
        product is left unrounded, the four products are summed, and the sum is
        rounded half up to one decimal place."  With only two golfers present, "A team
        holding fewer than four golfers uses only the players present", and "the
        weight vector is applied from its first position upward and the unused weights
        are simply dropped", "never redistributed across the remaining players".  The
        ascending sort decides which golfer takes 0.20, since "Those course handicaps
        are sorted into ascending order".

        Design: Corner/calculations/scramble_weights_are_dropped_not_redistributed_for_a_short_team
        """
        ctx = fx.open_outing(
            api, outing=SHORT_TEAM_OUTING, contract=FLAT_RATINGS, tier=PAIR_TIER
        )
        reg = fx.confirmed_registration(
            api,
            ctx,
            players=(12.0, 8.0),
            buyer_name="Twosome",
            names=["Index Twelve", "Index Eight"],
        )
        assert [fx.read_player(api, pid)["course_handicap"] for pid in reg["player_ids"]] == [
            12,
            8,
        ]

        team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="Twosome Team")
        assert team["player_count"] == 2
        assert team["handicap_variant"] == "PROVISIONAL"
        assert team["team_playing_handicap"] == pytest.approx(3.4, abs=0.01)
        assert team["team_playing_handicap"] == pytest.approx(
            scramble_team_handicap([8, 12]), abs=0.01
        )
        assert team["team_playing_handicap"] != pytest.approx(8.0, abs=0.01)


PARTIAL_CREDIT_OUTING = {
    "name": "Partial Credit Open",
    "field_capacity_teams": 4,
    "rain_date": f.DEFAULT_RAIN_DATE,
}
PARTIAL_CREDIT_CONTRACT = {
    "rate_per_player_cents": 9501,
    "guaranteed_player_count": 0,
    "rain_date_terms": "PARTIAL_CREDIT",
    "rain_date_credit_pct": 0.125,
}

GUARANTEE_OUTING = {"name": "Guarantee Floor Open", "field_capacity_teams": 20}
GUARANTEE_CONTRACT = {
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 40,
    "fnb_minimum_cents": 150000,
    "fnb_per_player_cents": 2500,
}


class TestPartialCreditRainCredit:
    def test_a_half_cent_share_of_the_course_charge_rounds_upward(self, api):
        """An awkward per-player rate puts the credit exactly on a half cent.

        The postponement credit is defined against the charge as it stood a moment
        earlier: "`rain_credit_cents` is set to the outing's `course_charge_cents` as
        it stood immediately before the postponement when the terms are
        `FULL_CREDIT`, or to that same base multiplied by `rain_date_credit_pct` and
        rounded half up to whole cents when the terms are `PARTIAL_CREDIT`".  Four
        billable players at 9501 give a base of 38004, and 0.125 of that is exactly
        4750.5, so the credit is 4751.  The same request "increments the contract's
        `amendment_count` by one and moves the contract's status to `AMENDED`", and the
        credit lands in the cost line, since `direct_costs_cents` is "`course_charge_cents`
        plus `fnb_shortfall_cents` plus `insurance_cost_cents` plus `prize_cost_cents`,
        less the contract's `rain_credit_cents`".

        Design: Corner/calculations/partial_credit_rain_date_rounds_a_half_cent_share_upward
        """
        ctx = fx.open_outing(
            api, outing=PARTIAL_CREDIT_OUTING, contract=PARTIAL_CREDIT_CONTRACT
        )
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Awkward Rate Co", player_count=4
        )
        fx.pay_registration(api, registration["id"], 120000)
        assert fx.read_outing(api, ctx["outing_id"])["course_charge_cents"] == 38004

        outing = fx.drive_play(api, ctx["outing_id"], "POSTPONE")
        assert outing["play_status"] == "POSTPONED"
        assert outing["course_charge_cents"] == 38004

        contract = fx.read_contract(api, ctx["contract_id"])
        assert contract["rain_credit_cents"] == 4751
        assert contract["status"] == "AMENDED"
        assert contract["amendment_count"] == 1

        assert outing["direct_costs_cents"] == 33253
        assert outing["net_proceeds_before_fee_cents"] == 86747
        assert outing["admin_fee_pct"] == pytest.approx(0.05, abs=0.0001)
        assert outing["admin_fee_cents"] == 6000
        assert outing["net_proceeds_cents"] == 80747
        assert_direct_costs(outing, rain_credit_cents=4751)
        assert_rollup_chain(outing)


class TestGuaranteeFloorAndFoodMinimum:
    def test_the_charge_uses_the_guarantee_while_the_food_credit_uses_the_turnout(self, api):
        """Steps 3 and 4 read different headcounts on the same thin field.

        The charge is floored: "`course_charge_cents` is the larger of the billable
        player count and the contract's `guaranteed_player_count`, multiplied by the
        contract's `rate_per_player_cents`. The guarantee is a floor, so a poorly
        attended outing still pays for the players it promised."  The food credit
        deliberately is not: "The actual food-and-beverage spend credited is the
        billable player count multiplied by the contract's `fnb_per_player_cents`, with
        no guarantee floor applied here at all. `fnb_shortfall_cents` is then the
        contract's `fnb_minimum_cents` minus that credited spend, floored at 0".  Four
        confirmed slots therefore pay for forty players and eat for four, and the
        resulting negative net switches the fee off, because `admin_fee_pct` is "0 when
        `net_proceeds_before_fee_cents` is zero or negative".

        Design: Corner/calculations/guaranteed_player_floor_and_food_minimum_shortfall_are_both_applied
        """
        ctx = fx.open_outing(api, outing=GUARANTEE_OUTING, contract=GUARANTEE_CONTRACT)
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Thin Field Co", player_count=4
        )
        fx.pay_registration(api, registration["id"], 120000)

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["gross_revenue_cents"] == 120000
        assert outing["refunded_cents"] == 0
        assert outing["confirmed_player_slots"] == 4
        assert outing["course_charge_cents"] == 380000
        assert outing["fnb_shortfall_cents"] == 140000
        assert outing["direct_costs_cents"] == 520000
        assert outing["net_proceeds_before_fee_cents"] == -400000
        assert outing["admin_fee_pct"] == pytest.approx(0.0, abs=0.0001)
        assert outing["admin_fee_cents"] == 0
        assert outing["net_proceeds_cents"] == -400000
        assert_direct_costs(outing)
        assert_rollup_chain(outing)


BIG_TEAM_TIER = {
    "code": "TEAM4",
    "kind": "TEAM",
    "price_cents": 400000,
    "player_slots": 4,
    "gsv_cents": 24000,
    "inventory_cap": 10,
}
FLAT_FOURSOME = (12.0, 12.0, 12.0, 12.0)
ONE_PROFESSIONAL = ("PROFESSIONAL", "AMATEUR", "AMATEUR", "AMATEUR")
TEE_TIMES = (
    "2026-09-19T12:00:00Z",
    "2026-09-19T12:10:00Z",
    "2026-09-19T12:20:00Z",
    "2026-09-19T12:30:00Z",
)
WATERFALL_OUTING = {
    "name": "Residual Share Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 1000005,
}
CARD_EVEN = {
    "gross_score": 74,
    "gross_back_9": 37,
    "gross_back_6": 25,
    "gross_back_3": 13,
    "gross_hole_18": 4,
}
CARD_SLOW = {
    "gross_score": 78,
    "gross_back_9": 39,
    "gross_back_6": 26,
    "gross_back_3": 14,
    "gross_hole_18": 5,
}
CARD_LOW = {
    "gross_score": 68,
    "gross_back_9": 34,
    "gross_back_6": 23,
    "gross_back_3": 12,
    "gross_hole_18": 3,
}
MATCHING_OUTING = {
    "name": "Matching Cards Open",
    "field_capacity_teams": 2,
    "prize_pool_cents": 0,
}
CARD_WORSE_BACK_NINE = dict(CARD_EVEN, gross_back_9=37)
CARD_BETTER_BACK_NINE = dict(CARD_EVEN, gross_back_9=36)


def _four_player_team(api, ctx, name, statuses=None):
    """One package of four golfers at index 12.0, grouped into a single team."""
    reg = fx.confirmed_registration(
        api,
        ctx,
        players=FLAT_FOURSOME,
        buyer_name=f"{name} Sponsor",
        names=[f"{name} {seat}" for seat in ("One", "Two", "Three", "Four")],
        amateur_statuses=statuses,
    )
    return fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name=name)


class TestPrizeWaterfallResidualAndEligibility:
    def test_the_professional_group_consumes_no_share_and_the_third_share_is_the_residual(
        self, api
    ):
        """An odd pool, an ineligible leader and a dead heat, settled in one request.

        Eligibility is read first: "a team's `prize_eligible` flag reads false when any
        player currently linked to it carries `amateur_status` `PROFESSIONAL`", and
        "The waterfall is over the *eligible* list, not over the raw ranking, so an
        ineligible team does not consume a share".  The first two shares are rounded
        percentages, since "The first eligible team's `prize_award_cents` is 0.50 of
        `prize_pool_cents` rounded half up to whole cents, and the second eligible
        team's is 0.30 of `prize_pool_cents` rounded half up to whole cents", while
        "The third eligible team is paid the residual instead of a rounded percentage",
        namely "the `prize_pool_cents` minus everything already awarded".  The dead
        heat between the two identical cards falls all the way through to key 7, "the
        team's `created_at` ascending, as the final deterministic fallback. A team's
        `id` is never consulted."  Nothing is left over, because
        `unclaimed_prize_cents` is "`prize_pool_cents` minus the sum of
        `prize_award_cents` across all teams".

        Design: Corner/calculations/prize_waterfall_pays_the_residual_to_the_third_share_and_skips_a_professional_team
        """
        ctx = fx.open_outing(
            api, outing=WATERFALL_OUTING, contract=FLAT_RATINGS, tier=BIG_TEAM_TIER
        )
        alpha = _four_player_team(api, ctx, "ALPHA")
        bravo = _four_player_team(api, ctx, "BRAVO")
        charlie = _four_player_team(api, ctx, "CHARLIE")
        delta = _four_player_team(api, ctx, "DELTA", statuses=ONE_PROFESSIONAL)

        for index, team in enumerate((alpha, bravo, charlie, delta)):
            fx.assign_tee(
                api, team["id"], tee_time=TEE_TIMES[index], cart_number=index + 1
            )
        fx.lock_field(api, ctx["outing_id"])
        fx.start_play(api, ctx["outing_id"])

        for team, card in (
            (alpha, CARD_EVEN),
            (bravo, CARD_EVEN),
            (charlie, CARD_SLOW),
            (delta, CARD_LOW),
        ):
            fx.post_score(api, team["id"], **card)

        outing = fx.finalize_scoring(api, ctx["outing_id"])
        assert outing["play_status"] == "SCORED"

        leader = fx.read_team(api, delta["id"])
        assert leader["team_playing_handicap"] == pytest.approx(6.0, abs=0.01)
        assert leader["net_score"] == pytest.approx(62.0, abs=0.01)
        assert leader["rank_position"] == 1
        assert leader["prize_eligible"] is False
        assert leader["prize_award_cents"] == 0

        first_paid = fx.read_team(api, alpha["id"])
        assert first_paid["net_score"] == pytest.approx(68.0, abs=0.01)
        assert first_paid["net_back_9"] == pytest.approx(34.0, abs=0.01)
        assert first_paid["net_back_6"] == pytest.approx(23.0, abs=0.01)
        assert first_paid["net_back_3"] == pytest.approx(12.0, abs=0.01)
        assert first_paid["net_hole_18"] == pytest.approx(3.67, abs=0.01)
        assert first_paid["rank_position"] == 2
        assert first_paid["prize_award_cents"] == 500003

        second_paid = fx.read_team(api, bravo["id"])
        for metric in ("net_score", "net_back_9", "net_back_6", "net_back_3", "net_hole_18"):
            assert second_paid[metric] == pytest.approx(first_paid[metric], abs=0.01), metric
        assert second_paid["team_playing_handicap"] == pytest.approx(
            first_paid["team_playing_handicap"], abs=0.01
        )
        assert second_paid["rank_position"] == 3
        assert second_paid["prize_award_cents"] == 300002

        residual = fx.read_team(api, charlie["id"])
        assert residual["net_score"] == pytest.approx(72.0, abs=0.01)
        assert residual["rank_position"] == 4
        assert residual["prize_award_cents"] == 200000
        assert residual["prize_award_cents"] != 200001

        awarded = (
            first_paid["prize_award_cents"]
            + second_paid["prize_award_cents"]
            + residual["prize_award_cents"]
        )
        assert awarded == 1000005
        assert outing["unclaimed_prize_cents"] == 0


class TestMatchingCardsBeforeTheCreatedAtFallback:
    def test_the_back_nine_decides_the_dead_heat_regardless_of_creation_order(self, api):
        """A tie on net score is broken by key 2, not by which team was entered first.

        The ordering is a sequence, and "it is total, so every team receives a distinct
        `rank_position` numbered from 1": key 1 is "`net_score` ascending" and key 2 is
        "`net_back_9` ascending", with "the team's `created_at` ascending, as the final
        deterministic fallback".  The back-nine figure is a partial handicap deduction,
        since "`net_back_9` is the `gross_back_9` less half the
        `team_playing_handicap`, rounded half up to two decimal places", so the team
        entered second wins on 33.0 against 34.0 and keys 3 to 7 are never consulted.

        Design: Corner/calculations/matching_cards_decide_the_rank_before_the_created_at_fallback
        """
        ctx = fx.open_outing(
            api, outing=MATCHING_OUTING, contract=FLAT_RATINGS, tier=BIG_TEAM_TIER
        )
        xray = _four_player_team(api, ctx, "XRAY")
        yankee = _four_player_team(api, ctx, "YANKEE")

        for index, team in enumerate((xray, yankee)):
            fx.assign_tee(
                api, team["id"], tee_time=TEE_TIMES[index], cart_number=index + 1
            )
        fx.lock_field(api, ctx["outing_id"])
        fx.start_play(api, ctx["outing_id"])
        fx.post_score(api, xray["id"], **CARD_WORSE_BACK_NINE)
        fx.post_score(api, yankee["id"], **CARD_BETTER_BACK_NINE)

        outing = fx.finalize_scoring(api, ctx["outing_id"])
        assert outing["play_status"] == "SCORED"
        assert outing["unclaimed_prize_cents"] == 0

        winner = fx.read_team(api, yankee["id"])
        loser = fx.read_team(api, xray["id"])
        assert winner["net_score"] == pytest.approx(68.0, abs=0.01)
        assert winner["net_back_9"] == pytest.approx(33.0, abs=0.01)
        assert winner["rank_position"] == 1
        assert loser["net_score"] == pytest.approx(68.0, abs=0.01)
        assert loser["net_back_9"] == pytest.approx(34.0, abs=0.01)
        assert loser["rank_position"] == 2

        for team in (winner, loser):
            assert team["net_back_6"] == pytest.approx(23.0, abs=0.01)
            assert team["net_back_3"] == pytest.approx(12.0, abs=0.01)
            assert team["net_hole_18"] == pytest.approx(3.67, abs=0.01)
            assert team["team_playing_handicap"] == pytest.approx(6.0, abs=0.01)


CAP_OUTING = {"name": "Cash Cap Open", "field_capacity_teams": 4}
CAP_STATUSES = ("AMATEUR", "AMATEUR", "AMATEUR", "PROFESSIONAL")
CAP_NAMES = ["Amateur Ann", "Amateur Ben", "Amateur Cal", "Pro Dana"]
CASH_OVER_THE_CAP = {
    "contest_type": "LONGEST_DRIVE",
    "hole_number": 3,
    "prize_value_cents": 75001,
    "prize_form": "CASH",
}
CASH_ON_THE_CAP = {
    "contest_type": "LONGEST_DRIVE",
    "hole_number": 6,
    "prize_value_cents": 75000,
    "prize_form": "CASH",
}
NON_CASH_PRIZE = {
    "contest_type": "LONGEST_DRIVE",
    "hole_number": 9,
    "prize_value_cents": 400000,
    "prize_form": "MERCHANDISE_CREDIT",
}
CASH_FOR_A_PROFESSIONAL = {
    "contest_type": "LONGEST_DRIVE",
    "hole_number": 12,
    "prize_value_cents": 400000,
    "prize_form": "CASH",
}


def _closed_contest_field(api, outing, specs, statuses=None, names=None, policies=None):
    """One four-player team in play, with every named contest opened and closed."""
    ctx = fx.open_outing(api, outing=outing, contract=FLAT_RATINGS, tier=BIG_TEAM_TIER)
    reg = fx.confirmed_registration(
        api,
        ctx,
        players=FLAT_FOURSOME,
        buyer_name="Contest Field Co",
        names=names,
        amateur_statuses=statuses,
    )
    contests = [fx.new_contest(api, ctx["outing_id"], **spec) for spec in specs]
    for index, policy in (policies or {}).items():
        fx.bind_contest_insurance(api, contests[index]["id"], **policy)
    for contest in contests:
        fx.drive_contest(api, contest["id"], "OPEN")

    team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="FIELD")
    fx.assign_tee(api, team["id"])
    fx.lock_field(api, ctx["outing_id"])
    fx.start_play(api, ctx["outing_id"])
    for contest in contests:
        fx.drive_contest(api, contest["id"], "CLOSE")

    ctx["registration"] = reg
    ctx["player_ids"] = reg["player_ids"]
    ctx["contests"] = [fx.read_contest(api, contest["id"]) for contest in contests]
    return ctx


class TestAmateurCashCapGovernsTheAwardForm:
    def test_the_cap_refuses_one_cent_over_admits_the_boundary_and_converts_non_cash(
        self, api
    ):
        """The same declared prize settles four different ways on one field.

        "Amateur status governs the *form* of the award, never the amount. When the
        winner's `amateur_status` is `AMATEUR` and the contest's `prize_form` is
        `CASH`, the advertised value must not exceed 75000 cents", "and a larger cash
        prize is refused outright with `ERR_AMATEUR_CASH_CAP_EXCEEDED`; within the
        ceiling the `award_form` resolves to `CASH`."  A non-cash prize is never
        refused: "When the winner is an `AMATEUR` and the contest's `prize_form` is not
        cash, the `award_form` resolves to `MERCHANDISE_CREDIT`".  And the ceiling is
        an amateur rule only, since "When the winner's `amateur_status` is
        `PROFESSIONAL`, the `award_form` is simply the contest's declared `prize_form`,
        because a professional may take cash without jeopardy."  The amount never
        moves: "In every case `awarded_value_cents` is set to the contest's
        `prize_value_cents`, and the supplied `witness_count` is recorded."  No claim
        is adjudicated on these holes, because "A contest of any other type recovers
        nothing and records no denial reason."

        Design: Corner/calculations/amateur_status_governs_the_award_form_at_the_cash_cap_boundary
        """
        ctx = _closed_contest_field(
            api,
            CAP_OUTING,
            (CASH_OVER_THE_CAP, CASH_ON_THE_CAP, NON_CASH_PRIZE, CASH_FOR_A_PROFESSIONAL),
            statuses=CAP_STATUSES,
            names=CAP_NAMES,
        )
        over, on_cap, non_cash, professional_cash = ctx["contests"]
        amateurs = ctx["player_ids"][:3]
        pro_id = ctx["player_ids"][3]

        validate_error(
            api.award_contest(
                over["id"], f.award_payload(amateurs[0], witness_count=1), DIRECTOR_HEADERS
            ),
            ApiErrorId.AMATEUR_CASH_CAP_EXCEEDED,
            409,
        )
        refused = fx.read_contest(api, over["id"])
        assert refused["status"] == "CLOSED"
        assert refused["award_form"] is None
        assert refused["awarded_value_cents"] == 0
        assert_version_unchanged(refused, over["version"])

        to_professional = validate_success(
            api.award_contest(
                over["id"], f.award_payload(pro_id, witness_count=1), DIRECTOR_HEADERS
            )
        )
        assert to_professional["status"] == "AWARDED"
        assert to_professional["award_form"] == "CASH"
        assert to_professional["awarded_value_cents"] == 75001
        assert to_professional["winner_player_id"] == pro_id

        boundary = validate_success(
            api.award_contest(
                on_cap["id"], f.award_payload(amateurs[1], witness_count=1), DIRECTOR_HEADERS
            )
        )
        assert boundary["award_form"] == "CASH"
        assert boundary["awarded_value_cents"] == 75000

        converted = validate_success(
            api.award_contest(
                non_cash["id"], f.award_payload(amateurs[2], witness_count=1), DIRECTOR_HEADERS
            )
        )
        assert converted["award_form"] == "MERCHANDISE_CREDIT"
        assert converted["awarded_value_cents"] == 400000

        declared = validate_success(
            api.award_contest(
                professional_cash["id"],
                f.award_payload(pro_id, witness_count=1),
                DIRECTOR_HEADERS,
            )
        )
        assert declared["award_form"] == "CASH"
        assert declared["awarded_value_cents"] == 400000

        for settled in (to_professional, boundary, converted, declared):
            row = fx.read_contest(api, settled["id"])
            assert row["insurance_status"] == "NONE"
            assert row["insurance_recovery_cents"] == 0
            assert row["claim_denial_reason"] == "NONE"
            assert row["contest_payout_cents"] == row["awarded_value_cents"]


ACE_FIELD_OUTING = {
    "name": "Ace Adjudication Open",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
ACE_SPECS = tuple(
    {
        "contest_type": "HOLE_IN_ONE",
        "hole_number": hole,
        "prize_value_cents": 400000,
        "yardage": yardage,
    }
    for hole, yardage in ((2, 150), (5, 180), (8, 180), (11, 180), (14, 165))
)
CAPPED_POLICY = {
    "insurance_carrier": "Fairway Mutual",
    "insurance_premium_cents": 10000,
    "insurance_coverage_cap_cents": 100000,
    "insurance_min_yardage": 165,
    "insurance_required_witness_count": 2,
}
FULL_POLICY = dict(CAPPED_POLICY, insurance_coverage_cap_cents=400000)


class TestHoleInOneClaimAdjudicationOrder:
    def test_only_the_first_failing_check_names_the_denial(self, api):
        """Five aces, four verdicts and one paid claim, all from one declared order.

        "When the `contest_type` is `HOLE_IN_ONE` and the insurance dimension reads
        `BOUND`, three tests run in a fixed order and the **first** failing test names
        the denial", running "if the contest's `yardage` is below
        `insurance_min_yardage`, the claim is denied and `claim_denial_reason` becomes
        `YARDAGE_BELOW_MINIMUM`. The comparison is inclusive on the policy's side: a
        hole measured at exactly the minimum yardage is covered."  Then "otherwise, if
        the recorded `witness_count` is below `insurance_required_witness_count`, the
        claim is denied and `claim_denial_reason` becomes `INSUFFICIENT_WITNESSES`."
        Then "otherwise, if `awarded_value_cents` exceeds
        `insurance_coverage_cap_cents`, the claim is denied and `claim_denial_reason`
        becomes `COVERAGE_CAP_EXCEEDED`."  Otherwise "the claim is paid: the insurance
        dimension moves `BOUND → CLAIM_PAID`, `insurance_recovery_cents` is set to the
        smaller of `awarded_value_cents` and `insurance_coverage_cap_cents`, and
        `claim_denial_reason` is left at `NONE`."  An uninsured ace is not a denial:
        "A hole-in-one contest awarded with no policy bound at all is not an error",
        "it simply records `claim_denial_reason` as `NO_POLICY`, leaves the insurance
        dimension where it stands, and recovers nothing."  Every premium stays a cost,
        because `insurance_cost_cents` is "the sum of `insurance_premium_cents` over
        every contest of the outing whose insurance dimension reads `BOUND`,
        `CLAIM_PAID`, `CLAIM_DENIED`, or `EXPIRED`", and the outing absorbs the rest,
        since "`contest_payout_cents` is set to `awarded_value_cents` minus
        `insurance_recovery_cents`".

        Design: Corner/calculations/hole_in_one_claim_denial_reasons_follow_the_declared_check_order
        """
        ctx = _closed_contest_field(
            api,
            ACE_FIELD_OUTING,
            ACE_SPECS,
            policies={0: CAPPED_POLICY, 1: CAPPED_POLICY, 2: CAPPED_POLICY, 4: FULL_POLICY},
        )
        short, thin_witnesses, over_cap, uninsured, paid = ctx["contests"]
        players = ctx["player_ids"]
        assert all(contest["requires_insurance"] is False for contest in ctx["contests"])

        for contest, winner, witnesses in (
            (short, players[0], 1),
            (thin_witnesses, players[1], 1),
            (over_cap, players[2], 2),
            (uninsured, players[3], 2),
            (paid, players[0], 2),
        ):
            validate_success(
                api.award_contest(
                    contest["id"],
                    f.award_payload(winner, witness_count=witnesses),
                    DIRECTOR_HEADERS,
                )
            )

        denials = {
            short["id"]: "YARDAGE_BELOW_MINIMUM",
            thin_witnesses["id"]: "INSUFFICIENT_WITNESSES",
            over_cap["id"]: "COVERAGE_CAP_EXCEEDED",
        }
        for contest_id, reason in denials.items():
            row = fx.read_contest(api, contest_id)
            assert row["insurance_status"] == "CLAIM_DENIED"
            assert row["claim_denial_reason"] == reason

        no_policy = fx.read_contest(api, uninsured["id"])
        assert no_policy["insurance_status"] == "NONE"
        assert no_policy["claim_denial_reason"] == "NO_POLICY"

        for contest_id in list(denials) + [uninsured["id"]]:
            row = fx.read_contest(api, contest_id)
            assert row["insurance_recovery_cents"] == 0
            assert row["award_form"] == "MERCHANDISE_CREDIT"
            assert row["awarded_value_cents"] == 400000
            assert row["contest_payout_cents"] == 400000

        recovered = fx.read_contest(api, paid["id"])
        assert recovered["insurance_status"] == "CLAIM_PAID"
        assert recovered["claim_denial_reason"] == "NONE"
        assert recovered["insurance_recovery_cents"] == 400000
        assert recovered["contest_payout_cents"] == 0

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["insurance_cost_cents"] == 40000
        assert outing["prize_cost_cents"] == 1600000
        assert outing["direct_costs_cents"] == 1678000
        assert outing["net_proceeds_before_fee_cents"] == -1278000
        assert outing["admin_fee_cents"] == 0
        assert outing["net_proceeds_cents"] == -1278000
        assert_direct_costs(outing)
        assert_rollup_chain(outing)


DEDUCTIBLE_OUTING = {"name": "Deductible Open", "field_capacity_teams": 4}
LOW_FMV_LOT = {
    "item_type": "AUCTION",
    "description": "Signed pin flag",
    "fmv_cents": 1000,
    "ask_cents": 50000,
}
DONATION_APPEAL = {
    "item_type": "DONATION",
    "description": "Fund-a-need appeal",
    "fmv_cents": 0,
    "ask_cents": 0,
}
RAFFLE_BOOK = {
    "item_type": "RAFFLE",
    "description": "50-50 raffle book",
    "fmv_cents": 0,
    "ask_cents": 5000,
}


class TestAuctionAndDonationDeductibles:
    def test_the_auction_subtracts_a_token_sized_fmv_while_the_donation_is_whole(self, api):
        """Three channels, three deductible rules, and one refusal that skips a number.

        The auction branch never consults the token ceiling: "For an `AUCTION` lot the
        receipt's `gsv_cents` is the item's `fmv_cents`", because "the token-benefit
        rule deliberately does not apply to auction lots, because the buyer received a
        specific thing of value", "and the `deductible_amount_cents` is the
        `payment_cents` minus that fair market value, floored at 0."  Had the rule
        applied, a ceiling of "the smaller of 1300 cents" "and two percent of the
        receipt's `payment_cents` rounded half up to whole cents" would have erased a
        1000-cent benefit outright.  The appeal is simpler: "For a `DONATION` the
        `gsv_cents` is 0 and the whole `payment_cents` is deductible."  The raffle is
        refused, since "No receipt at all may be issued for a `RAFFLE` item, whatever
        the amount collected, because a raffle ticket buys a chance rather than making a
        gift; that request is refused with `ERR_RAFFLE_NOT_DEDUCTIBLE` (HTTP 422)", so
        it consumes no number from a sequence where "the first receipt of an outing
        reads `GR-0001`, the second `GR-0002`, and so on".  A successful receipt
        cascades its lot, because "Issuing a receipt against a `PAID` fundraising item
        cascades that item `PAID → RECEIPTED`", and the outing total is "the signed sum
        of `deductible_amount_cents` over every receipt of the outing, reversals
        included".  The issuer differs from the recorder throughout, since "the user
        who recorded the item's sale may not issue its receipt."

        Design: Corner/calculations/auction_gsv_ignores_the_token_benefit_rule_while_a_donation_is_fully_deductible
        """
        ctx = fx.open_outing(
            api,
            outing=DEDUCTIBLE_OUTING,
            contract={"rate_per_player_cents": 9500, "guaranteed_player_count": 0},
            tier=SOLO_TIER,
        )
        buyer = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Generous Buyer", player_count=1
        )
        fx.pay_registration(api, buyer["id"], 30000)

        lot = fx.new_item(api, ctx["outing_id"], **LOW_FMV_LOT)
        appeal = fx.new_item(api, ctx["outing_id"], **DONATION_APPEAL)
        raffle = fx.new_item(api, ctx["outing_id"], **RAFFLE_BOOK)
        for item, amount in ((lot, 60000), (appeal, 50000), (raffle, 5000)):
            fx.sell_item(api, item["id"], buyer["id"], amount, headers=TREASURER_HEADERS)
            fx.pay_item(api, item["id"], amount)

        auction_receipt = fx.issue_item_receipt(
            api, ctx["outing_id"], lot["id"], TREASURER_ALT_HEADERS
        )
        assert auction_receipt["payment_cents"] == 60000
        assert auction_receipt["gsv_cents"] == 1000
        assert auction_receipt["deductible_amount_cents"] == 59000
        assert auction_receipt["receipt_number"] == "GR-0001"

        donation_receipt = fx.issue_item_receipt(
            api, ctx["outing_id"], appeal["id"], TREASURER_ALT_HEADERS
        )
        assert donation_receipt["payment_cents"] == 50000
        assert donation_receipt["gsv_cents"] == 0
        assert donation_receipt["deductible_amount_cents"] == 50000
        assert donation_receipt["receipt_number"] == "GR-0002"

        validate_error(
            api.create_receipt(
                f.item_receipt_payload(ctx["outing_id"], raffle["id"]), TREASURER_ALT_HEADERS
            ),
            ApiErrorId.RAFFLE_NOT_DEDUCTIBLE,
            422,
        )
        assert fx.read_item(api, raffle["id"])["status"] == "PAID"

        receipted = fx.read_item(api, lot["id"])
        assert receipted["status"] == "RECEIPTED"
        assert receipted["collected_cents"] == 60000
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 109000


WAITLIST_OUTING = {"name": "Waitlist Filter Open", "field_capacity_teams": 2}
WAITLIST_CONTRACT = {"rate_per_player_cents": 9500, "guaranteed_player_count": 0}
PAIR_A_TIER = {
    "code": "PAIR_A",
    "kind": "TEAM",
    "price_cents": 100000,
    "player_slots": 2,
    "gsv_cents": 12000,
    "inventory_cap": 10,
}
PAIR_B_TIER = dict(PAIR_A_TIER, code="PAIR_B", price_cents=200000)


class TestWaitlistPromotionFiltersBeforeRanking:
    def test_the_oversized_package_is_filtered_out_before_the_price_ranking(self, api):
        """Two freed slots, three candidates, and the dearest package excluded outright.

        "The number of freed slots is the cancelled registration's `player_count`.
        Candidates are the registrations of the same outing that are sitting at
        `WAITLISTED` at the instant step 6 completes and whose own `player_count` is
        less than or equal to the freed slot count. Those candidates are ordered by the
        `price_cents` of the tier they hold, highest first, and ties are broken by the
        registration's `created_at`, earliest first; a registration's `id` is never
        consulted as a tiebreaker. The first candidate in that ordering is the winner
        and moves `WAITLISTED → CONFIRMED`, which stamps its `confirmed_at`", and
        "Exactly one registration is promoted per cancellation, however many slots were
        freed."  The cancellation itself is timely, so "Outside the notice window
        `late_cancel_fee_cents` stays 0 and the refund is the whole of
        `amount_paid_cents`", and "when the refund is greater than zero the row
        auto-advances one further step, `CANCELLED → REFUNDED`, in the same request."
        Only live packages count as revenue, namely "the `amount_paid_cents` of every
        registration whose status is `CONFIRMED`, `AMENDED`, or `CHECKED_IN`".

        Design: Corner/calculations/waitlist_promotion_filters_by_freed_slots_before_ranking_by_tier_price
        """
        ctx = fx.open_outing(
            api, outing=WAITLIST_OUTING, contract=WAITLIST_CONTRACT, tier=BIG_TEAM_TIER
        )
        pair_a = fx.add_tier(api, ctx, **PAIR_A_TIER)
        pair_b = fx.add_tier(api, ctx, **PAIR_B_TIER)

        seats = {}
        for name, tier_id, players, price in (
            ("alpha", ctx["tier_id"], 4, 400000),
            ("bravo", pair_a["id"], 2, 100000),
            ("foxtrot", pair_a["id"], 2, 100000),
            ("charlie", ctx["tier_id"], 4, 400000),
            ("delta", pair_a["id"], 2, 100000),
            ("echo", pair_b["id"], 2, 200000),
        ):
            registration = fx.new_registration(
                api, ctx["outing_id"], tier_id, buyer_name=name.title(), player_count=players
            )
            seats[name] = fx.pay_registration(api, registration["id"], price)

        assert [seats[name]["status"] for name in ("alpha", "bravo", "foxtrot")] == [
            "CONFIRMED",
            "CONFIRMED",
            "CONFIRMED",
        ]
        assert [seats[name]["status"] for name in ("charlie", "delta", "echo")] == [
            "WAITLISTED",
            "WAITLISTED",
            "WAITLISTED",
        ]

        cancelled = validate_success(
            api.registration_lifecycle(
                seats["bravo"]["id"], f.registration_lifecycle_payload("CANCEL"), DIRECTOR_HEADERS
            )
        )
        assert cancelled["status"] == "REFUNDED"
        assert cancelled["late_cancel_fee_cents"] == 0
        assert cancelled["amount_refunded_cents"] == 100000

        promoted = fx.read_registration(api, seats["echo"]["id"])
        assert promoted["status"] == "CONFIRMED"
        assert_instant_equals(promoted["confirmed_at"], CLOCK_START_UTC)
        assert fx.read_registration(api, seats["delta"]["id"])["status"] == "WAITLISTED"
        assert fx.read_registration(api, seats["charlie"]["id"])["status"] == "WAITLISTED"

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["confirmed_player_slots"] == 8
        assert outing["waitlisted_registration_count"] == 2
        assert outing["gross_revenue_cents"] == 700000
        assert outing["refunded_cents"] == 100000
        assert outing["course_charge_cents"] == 76000
        assert outing["net_proceeds_before_fee_cents"] == 524000
        assert outing["admin_fee_pct"] == pytest.approx(0.05, abs=0.0001)
        assert outing["admin_fee_cents"] == 35000
        assert outing["net_proceeds_cents"] == 489000
        assert_direct_costs(outing)
        assert_rollup_chain(outing)
