"""Closed-form arithmetic whose step order is load-bearing: event points from four
interacting inputs, the two-stage differential rounding, and the four-step fee
settlement.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_one_decimal,
    assert_two_decimals,
)
from test_helpers.test_users import TOUR_ADMIN
from test_helpers.types import (
    ENTRY_FINISHED,
    FEE_AID_PARTIAL,
    FEE_UNPAID,
    TIER_NATIONAL,
    TOURNAMENT_IN_PROGRESS,
)

NATIONAL_START_CLOCK = "2026-09-20T12:00:00Z"
NATIONAL_TEE_TIME = "2026-09-20T13:00:00Z"


class TestEventPointsFourFactorInteraction:
    """A tier base, the field quality, a floored finish decay and an additive bonus."""

    def test_national_win_and_runner_up_are_not_a_scaling_of_one_another(self, api):
        """725.00 and 650.00 come out of the same event; 0.95 x 725.00 is not 650.00.

        PRD: "`event_points` is finally the base multiplied by the tournament's
        `field_quality_factor` multiplied by the finish factor, plus the
        differential bonus, with the whole sum rounded half up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/event_points_four_factor_non_linear_interaction
        """
        ctx = fx.tournament_in_progress(
            api, 2, start_clock=NATIONAL_START_CLOCK,
            name="US Junior National", tier=TIER_NATIONAL, round_count=1,
            start_date="2026-09-20", end_date="2026-09-20",
            withdrawal_deadline_at="2026-09-15T00:00:00Z",
        )
        assert_two_decimals(ctx["tournament"]["field_quality_factor"], 1.00,
                            "field_quality_factor")

        tee_sheet = fx.build_tee_sheet(api, ctx, 1, NATIONAL_TEE_TIME)
        winner_round = fx.play_round(api, ctx, 0, 1, 1, NATIONAL_TEE_TIME, 68,
                                     round_row=tee_sheet[0])
        runner_up_round = fx.play_round(api, ctx, 1, 0, 1, NATIONAL_TEE_TIME, 70,
                                        round_row=tee_sheet[1])
        assert_one_decimal(winner_round["scoring_differential"], -3.0,
                           "winner scoring_differential")
        assert_one_decimal(runner_up_round["scoring_differential"], -1.2,
                           "runner-up scoring_differential")

        tournament = fx.read_tournament(api, ctx["tournament_id"])
        assert tournament["status"] == "COMPLETED"

        winner_entry = fx.read_entry(api, ctx["entry_ids"][0])
        runner_up_entry = fx.read_entry(api, ctx["entry_ids"][1])
        assert winner_entry["finish_position"] == 1
        assert runner_up_entry["finish_position"] == 2
        assert_two_decimals(winner_entry["event_points"], 725.00, "winner event_points")
        assert_two_decimals(runner_up_entry["event_points"], 650.00,
                            "runner-up event_points")
        assert round(float(runner_up_entry["event_points"]), 2) != 688.75
        assert tournament["winner_entry_id"] == winner_entry["id"]

        assert_two_decimals(fx.read_member(api, ctx["member_ids"][0])
                            ["provisional_ranking_points"], 725.00,
                            "winner provisional_ranking_points")
        assert_two_decimals(fx.read_member(api, ctx["member_ids"][1])
                            ["provisional_ranking_points"], 650.00,
                            "runner-up provisional_ranking_points")

    def test_a_poor_differential_subtracts_nothing_from_the_base_product(self, api):
        """The bonus term is floored at zero, so it can never claw points back.

        PRD: "The differential bonus rewards scoring quality against a par
        reference of 2.0 strokes: the entry's `avg_scoring_differential` is
        subtracted from 2.0, the remainder is multiplied by 25 points per stroke,
        that product is rounded half up to 2 decimal places, and the result is
        floored at 0.00 so a poor differential subtracts nothing."

        Design: Difficulty/combinatorial_formula/event_points_four_factor_non_linear_interaction
        """
        ctx = fx.completed_event(api)
        runner_up_entry = fx.read_entry(api, ctx["entry_ids"][1])

        assert_one_decimal(runner_up_entry["avg_scoring_differential"], 3.2,
                           "runner-up avg_scoring_differential")
        assert runner_up_entry["finish_position"] == 2
        assert_two_decimals(runner_up_entry["event_points"], 285.00,
                            "runner-up event_points")
        assert round(float(runner_up_entry["event_points"]), 2) != 255.00


class TestScoringDifferentialRoundingOrder:
    """Per-round rounding first, then the mean of the rounded values."""

    def test_rounds_of_66_and_72_average_to_minus_2_point_2(self, api):
        """The two-stage order pins the answer; averaging raw quotients gives -2.1.

        PRD: "To see why the order matters, consider a course with a
        `course_rating` of 71.4 and a `slope_rating` of 128 and two rounds of 66
        and 72 adjusted strokes: rounding each round first gives differentials of
        -4.8 and 0.5, whose mean is -2.15 and rounds to **-2.2**."

        Design: Difficulty/combinatorial_formula/scoring_differential_rounding_order_is_pinned
        """
        ctx = fx.tournament_in_progress(api, 2)
        first_round = fx.play_round(api, ctx, 0, 1, 1, fx.TEE_TIME_ROUND_ONE, 66)
        assert_one_decimal(first_round["scoring_differential"], -4.8,
                           "round one scoring_differential")
        assert first_round["adjusted_gross"] == 66

        fx.set_clock(api, fx.CLOCK_ROUND_TWO)
        second_round = fx.play_round(api, ctx, 0, 1, 2, fx.TEE_TIME_ROUND_TWO, 72)
        assert_one_decimal(second_round["scoring_differential"], 0.5,
                           "round two scoring_differential")
        assert second_round["adjusted_gross"] == 72

        entry = fx.read_entry(api, ctx["entry_ids"][0])
        assert_one_decimal(entry["avg_scoring_differential"], -2.2,
                           "avg_scoring_differential")
        assert round(float(entry["avg_scoring_differential"]), 1) != -2.1
        assert entry["total_adjusted_strokes"] == 138
        assert entry["certified_round_count"] == 2
        assert entry["entry_status"] == ENTRY_FINISHED
        assert entry["event_points"] is None

        tournament = fx.read_tournament(api, ctx["tournament_id"])
        assert tournament["status"] == TOURNAMENT_IN_PROGRESS
        assert tournament["finished_count"] == 1

    def test_an_exact_half_in_the_second_stage_moves_away_from_zero(self, api):
        """Rounds of 67 and 73 give -3.9 and 1.4, whose mean -1.25 becomes -1.3.

        PRD: "Scoring differentials are rounded per round first and then the
        per-round rounded values are averaged and rounded again — never averaged
        from unrounded values." and "an exact half moves away from zero, so 2.15
        rounds to 2.2 and -2.15 rounds to -2.2".

        Design: Difficulty/combinatorial_formula/scoring_differential_rounding_order_is_pinned
        """
        ctx = fx.tournament_in_progress(api, 2)
        first_round = fx.play_round(api, ctx, 0, 1, 1, fx.TEE_TIME_ROUND_ONE, 67)
        assert_one_decimal(first_round["scoring_differential"], -3.9,
                           "round one scoring_differential")

        fx.set_clock(api, fx.CLOCK_ROUND_TWO)
        second_round = fx.play_round(api, ctx, 0, 1, 2, fx.TEE_TIME_ROUND_TWO, 73)
        assert_one_decimal(second_round["scoring_differential"], 1.4,
                           "round two scoring_differential")

        entry = fx.read_entry(api, ctx["entry_ids"][0])
        assert_one_decimal(entry["avg_scoring_differential"], -1.3,
                           "avg_scoring_differential")
        assert round(float(entry["avg_scoring_differential"]), 1) != -1.2
        assert entry["total_adjusted_strokes"] == 140


LATE_ENTRY_CLOCK = "2026-08-30T00:00:00Z"


def _late_window_tournament(api, season_id):
    """A 32,000-cent event whose entry window is inside its final 72 hours."""
    tournament = fx.create_tournament(
        api, season_id, name="Pinehurst Regional", entry_fee_cents=32000
    )
    validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
    fx.set_clock(api, LATE_ENTRY_CLOCK)
    return tournament


class TestEntryFeeSettlementStepOrder:
    """Surcharge and award are both shares of the gross fee, never of each other."""

    def test_late_assisted_entry_settles_to_3200_surcharge_and_28800_award(self, api):
        """Net due is 6,400: folding the surcharge into the subsidised base gives 3,520.

        PRD: "Note carefully what step three multiplies: the **gross fee**, never
        the gross fee plus surcharge."

        Design: Difficulty/combinatorial_formula/entry_fee_settlement_step_order_is_pinned
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        application = fx.approved_aid_application(
            api, member_id, ctx["season_id"],
            household_income_cents=6000000, dependents=3,
        )
        tournament = _late_window_tournament(api, ctx["season_id"])

        entry = fx.submit_entry(
            api, member_id, tournament["id"],
            request_assistance=True, aid_application_id=application["id"],
        )
        assert_cents(entry["gross_fee_cents"], 32000, "gross_fee_cents")
        assert_cents(entry["late_entry_surcharge_cents"], 3200,
                     "late_entry_surcharge_cents")
        assert_cents(entry["aid_award_cents"], 28800, "aid_award_cents")
        assert_cents(entry["net_fee_due_cents"], 6400, "net_fee_due_cents")
        assert entry["net_fee_due_cents"] != 3520
        assert entry["aid_award_cents"] != 31680
        assert entry["fee_status"] == FEE_AID_PARTIAL

        season = fx.read_season(api, ctx["season_id"])
        assert_cents(season["assistance_committed_cents"], 28800,
                     "assistance_committed_cents")
        assert_cents(season["assistance_available_cents"], 471200,
                     "assistance_available_cents")

    def test_late_unassisted_entry_owes_the_gross_fee_plus_a_tenth_of_it(self, api):
        """With no award in play the surcharge still lands on the gross fee alone.

        PRD: "Step four: `net_fee_due_cents` is `gross_fee_cents` plus
        `late_entry_surcharge_cents` minus `aid_award_cents`, floored at zero so
        it is never negative."

        Design: Difficulty/combinatorial_formula/entry_fee_settlement_step_order_is_pinned
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        tournament = _late_window_tournament(api, ctx["season_id"])

        entry = fx.submit_entry(api, member_id, tournament["id"])
        assert_cents(entry["gross_fee_cents"], 32000, "gross_fee_cents")
        assert_cents(entry["late_entry_surcharge_cents"], 3200,
                     "late_entry_surcharge_cents")
        assert_cents(entry["aid_award_cents"], 0, "aid_award_cents")
        assert_cents(entry["net_fee_due_cents"], 35200, "net_fee_due_cents")
        assert entry["fee_status"] == FEE_UNPAID
