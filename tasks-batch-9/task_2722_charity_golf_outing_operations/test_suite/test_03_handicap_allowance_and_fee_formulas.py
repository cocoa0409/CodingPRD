"""Two formulas whose result depends on the order the operations are pinned in."""

import pytest

from test_helpers import (
    TREASURER_HEADERS,
    assert_direct_costs,
    assert_rollup_chain,
    best_ball_team_handicap,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

BEST_BALL_OUTING = {
    "name": "Best Ball Benefit",
    "format": "BEST_BALL",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
BEST_BALL_CONTRACT = {
    "guaranteed_player_count": 4,
    "course_rating": 71.4,
    "slope_rating": 128,
    "par": 72,
}
# These four indices convert to the course handicaps 8, 9, 10 and 16.
BEST_BALL_INDEXES = (7.3, 8.2, 9.1, 14.4)

SPONSOR_ONLY_OUTING = {
    "name": "Title Sponsor Cup",
    "format": "STROKE_PLAY",
    "field_capacity_teams": 1,
    "prize_pool_cents": 100000,
}
SPONSOR_ONLY_CONTRACT = {
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 0,
    "fnb_minimum_cents": 0,
    "fnb_per_player_cents": 4500,
}
TITLE_TIER = {
    "code": "TITLE",
    "price_cents": 2100000,
    "player_slots": 0,
    "gsv_cents": 0,
    "inventory_cap": 5,
}


class TestBestBallAllowanceRoundingOrder:
    def test_best_ball_rounds_each_allowance_before_the_quarter_multiplier(self, api):
        """The PRD pins the order: "Under `BEST_BALL` each sorted course handicap is
        multiplied by 0.90 and rounded half up to a whole stroke, those whole-stroke
        allowances are summed, the sum is multiplied by 0.25, and the result is
        rounded half up to one decimal place."  It adds that "aggregating the raw
        products and rounding once at the end is explicitly not what this system
        does", so the 9.7 produced by summing first must not appear.

        Design: Difficulty/combinatorial_formula/best_ball_allowance_per_player_rounding_order
        """
        ctx = fx.open_outing(api, outing=BEST_BALL_OUTING, contract=BEST_BALL_CONTRACT)
        reg = fx.confirmed_registration(
            api, ctx, players=BEST_BALL_INDEXES, buyer_name="Rounding Rangers",
            names=["R1", "R2", "R3", "R4"],
        )

        course_handicaps = [
            fx.read_player(api, pid)["course_handicap"] for pid in reg["player_ids"]
        ]
        assert course_handicaps == [8, 9, 10, 16]

        team = fx.new_team(
            api, ctx["outing_id"], reg["player_ids"], team_name="Rounding Rangers"
        )
        assert team["team_playing_handicap"] == pytest.approx(9.5, abs=0.01)
        assert team["team_playing_handicap"] != pytest.approx(9.7, abs=0.001)
        assert team["handicap_variant"] == "PROVISIONAL"


class TestAdminFeeRateAndBase:
    def test_fee_rate_comes_from_the_before_fee_net_and_the_base_from_gross(self, api):
        """The PRD pins the evaluation order: "The fee *rate* is selected from that
        before-fee figure while the fee *base* is gross revenue, and the order is the
        contract: evaluating the tier against the after-fee net would be circular and
        is forbidden."  A before-fee net of exactly 2000000 selects "0.035 when it is
        below 5000000 cents (fifty thousand dollars)", and that rate lands on gross
        revenue of 2100000.

        Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_on_before_fee_applied_to_gross
        """
        ctx = fx.open_outing(
            api,
            outing=SPONSOR_ONLY_OUTING,
            contract=SPONSOR_ONLY_CONTRACT,
            tier=TITLE_TIER,
            sponsor_tier=True,
        )
        reg = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Summit Bank", player_count=0
        )

        validate_success(
            api.record_registration_payment(
                reg["id"], f.payment_payload(2100000), TREASURER_HEADERS
            )
        )
        outing = fx.read_outing(api, ctx["outing_id"])

        assert outing["gross_revenue_cents"] == 2100000
        assert outing["course_charge_cents"] == 0
        assert outing["fnb_shortfall_cents"] == 0
        assert outing["direct_costs_cents"] == 100000
        assert outing["net_proceeds_before_fee_cents"] == 2000000
        assert outing["admin_fee_pct"] == pytest.approx(0.035, abs=0.0001)
        assert outing["admin_fee_cents"] == 73500
        assert outing["net_proceeds_cents"] == 1926500
        assert_direct_costs(outing)
        assert_rollup_chain(outing)


# 7.4 lands in the same whole-stroke bucket as 7.3, so the four course handicaps
# are unchanged and the pinned rounding order must still produce 9.5.
BEST_BALL_NEARBY_INDEXES = (7.4, 8.2, 9.1, 14.4)

HIGH_GROSS_OUTING = {
    "name": "Presenting Sponsor Classic",
    "format": "STROKE_PLAY",
    "field_capacity_teams": 1,
    "prize_pool_cents": 200000,
}
PRESENTING_TIER = {
    "code": "PRESENTING",
    "price_cents": 5100000,
    "player_slots": 0,
    "gsv_cents": 0,
    "inventory_cap": 5,
}


class TestBestBallAllowanceOnNeighbouringIndexes:
    def test_indices_in_the_same_stroke_bucket_produce_the_same_playing_handicap(self, api):
        """Rounding happens twice, and the first rounding absorbs the index difference.

        The conversion "multiplies the index in use by the contract's `slope_rating`
        divided by 113, then adds the contract's `course_rating` minus its `par`",
        and "That raw figure is rounded half up to a whole stroke".  Both 7.3 and
        7.4 round to 8, so the allowance step - "each sorted course handicap is
        multiplied by 0.90 and rounded half up to a whole stroke, those whole-stroke
        allowances are summed, the sum is multiplied by 0.25, and the result is
        rounded half up to one decimal place" - still sums 7 + 8 + 9 + 14 to 38 and
        reports 9.5.

        Design: Difficulty/combinatorial_formula/best_ball_allowance_per_player_rounding_order
        """
        ctx = fx.open_outing(api, outing=BEST_BALL_OUTING, contract=BEST_BALL_CONTRACT)
        reg = fx.confirmed_registration(
            api,
            ctx,
            players=BEST_BALL_NEARBY_INDEXES,
            buyer_name="Bucket Brigade",
            names=["B1", "B2", "B3", "B4"],
        )

        course_handicaps = [
            fx.read_player(api, pid)["course_handicap"] for pid in reg["player_ids"]
        ]
        assert course_handicaps == [8, 9, 10, 16]

        team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="Bucket Brigade")
        assert team["team_playing_handicap"] == pytest.approx(
            best_ball_team_handicap(course_handicaps), abs=0.01
        )
        assert team["team_playing_handicap"] == pytest.approx(9.5, abs=0.01)


class TestAdminFeeRateIgnoresTheGrossTier:
    def test_a_gross_in_the_top_tier_still_pays_the_rate_its_before_fee_net_selects(self, api):
        """Gross revenue of 5100000 would select 0.02, but the before-fee net selects 0.035.

        The PRD forbids reading the tier off any figure other than the before-fee
        net: "The fee *rate* is selected from that before-fee figure while the fee
        *base* is gross revenue".  A before-fee net of 4900000 is "0.035 when it is
        below 5000000 cents (fifty thousand dollars)", and 0.035 of the 5100000
        gross is 178500 - not the 102000 that reading the tier from gross would
        produce.

        Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_on_before_fee_applied_to_gross
        """
        ctx = fx.open_outing(
            api,
            outing=HIGH_GROSS_OUTING,
            contract=SPONSOR_ONLY_CONTRACT,
            tier=PRESENTING_TIER,
            sponsor_tier=True,
        )
        reg = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Harbor Trust", player_count=0
        )
        validate_success(
            api.record_registration_payment(
                reg["id"], f.payment_payload(5100000), TREASURER_HEADERS
            )
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["gross_revenue_cents"] == 5100000
        assert outing["direct_costs_cents"] == 200000
        assert outing["net_proceeds_before_fee_cents"] == 4900000
        assert outing["admin_fee_pct"] == pytest.approx(0.035, abs=0.0001)
        assert outing["admin_fee_cents"] == 178500
        assert outing["net_proceeds_cents"] == 4721500
        assert_direct_costs(outing)
        assert_rollup_chain(outing)
