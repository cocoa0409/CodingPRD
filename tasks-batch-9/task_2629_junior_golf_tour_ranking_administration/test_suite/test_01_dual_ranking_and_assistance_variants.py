"""Two figures computed from one pool: live rankings against certified rankings,
and a published assistance estimate against the money a real entry settles.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_ledger,
    assert_two_decimals,
)
from test_helpers.constants import (
    ASSISTANCE_ESTIMATE_BASIS_CENTS,
    SEASON_ASSISTANCE_BUDGET_CENTS,
)
from test_helpers.test_users import TOUR_ADMIN
from test_helpers.types import AID_DECISION_APPROVED, FEE_AID_PARTIAL


class TestProvisionalAgainstCertifiedRanking:
    """One 405.00-point win reads at full value live and at a quarter certified."""

    def test_same_single_event_pool_yields_405_provisional_and_101_25_certified(self, api):
        """A ranking run divides by four even when only one event has been played.

        PRD: "The divergence is stark by design: a junior with exactly one
        405.00-point event reads a `provisional_ranking_points` of 405.00 and a
        `certified_ranking_points` of 101.25."

        Design: Difficulty/dual_variant_calc/ranking_provisional_live_diverges_from_certified_run
        """
        ctx = fx.completed_event(api)
        winner_id, runner_up_id = ctx["member_ids"]

        run = fx.run_ranking(api, ctx["season_id"], as_of_date="2026-09-11")
        assert run["ranking_epoch"] == 1
        assert run["ranked_member_count"] == 2

        winner = fx.read_member(api, winner_id)
        assert_two_decimals(winner["provisional_ranking_points"], 405.00,
                            "winner provisional_ranking_points")
        assert winner["provisional_counted_events"] == 1
        assert_two_decimals(winner["certified_ranking_points"], 101.25,
                            "winner certified_ranking_points")
        assert winner["certified_counted_events"] == 1
        assert winner["certified_rank_position"] == 1
        assert winner["provisional_ranking_points"] != winner["certified_ranking_points"]

        runner_up = fx.read_member(api, runner_up_id)
        assert_two_decimals(runner_up["provisional_ranking_points"], 285.00,
                            "runner-up provisional_ranking_points")
        assert_two_decimals(runner_up["certified_ranking_points"], 71.25,
                            "runner-up certified_ranking_points")
        assert runner_up["certified_rank_position"] == 2

        season = fx.read_season(api, ctx["season_id"])
        assert season["last_ranking_as_of_date"] == "2026-09-11"
        assert season["ranking_epoch"] == 1
        assert season["ranked_member_count"] == 2

    def test_ranking_run_rewrites_only_the_certified_side_of_each_junior(self, api):
        """The live figures survive the checkpoint that overwrites the certified ones.

        PRD: "It does **not** alter `provisional_ranking_points` or
        `provisional_counted_events` — that separation is the whole point of
        running two figures."

        Design: Difficulty/dual_variant_calc/ranking_provisional_live_diverges_from_certified_run
        """
        ctx = fx.completed_event(api)
        winner_id = ctx["member_ids"][0]

        before = fx.read_ranking(api, winner_id)
        assert_two_decimals(before["provisional_ranking_points"], 405.00,
                            "provisional_ranking_points before the run")
        assert before["certified_ranking_points"] is None
        assert before["certified_counted_events"] == 0
        assert before["certified_rank_position"] is None
        assert before["last_ranking_epoch"] is None
        assert before["ranking_epoch"] == 0

        fx.run_ranking(api, ctx["season_id"])

        after = fx.read_ranking(api, winner_id)
        assert_two_decimals(after["provisional_ranking_points"], 405.00,
                            "provisional_ranking_points after the run")
        assert after["provisional_counted_events"] == before["provisional_counted_events"]
        assert_two_decimals(after["certified_ranking_points"], 101.25,
                            "certified_ranking_points after the run")
        assert after["last_ranking_epoch"] == 1
        assert after["ranking_epoch"] == 1


class TestAssistanceEstimateAgainstSettlement:
    """The published estimate and the settled award disagree by design."""

    def test_estimate_uses_the_standard_fee_while_the_entry_uses_its_own_fee(self, api):
        """Covered at 0.90, a 32,000-cent event estimates 22,500 and awards 28,800.

        PRD: "A household covered at 0.90 entering an event whose fee is 32,000
        cents therefore sees an `estimated_award_cents` of 22,500 on its
        application and an `aid_award_cents` of 28,800 on its entry."

        Design: Difficulty/dual_variant_calc/assistance_estimate_diverges_from_event_settlement
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]

        application = fx.approved_aid_application(
            api, member_id, ctx["season_id"],
            household_income_cents=6000000, dependents=3,
        )
        assert_two_decimals(application["covered_pct"], 0.90, "covered_pct")
        assert_cents(application["income_per_dependent_cents"], 2000000,
                     "income_per_dependent_cents")
        assert_cents(application["estimated_award_cents"],
                     round(ASSISTANCE_ESTIMATE_BASIS_CENTS * 0.90),
                     "estimated_award_cents")
        assert_cents(application["estimated_award_cents"], 22500,
                     "estimated_award_cents")

        tournament = fx.create_tournament(
            api, ctx["season_id"], name="Pinehurst Regional", entry_fee_cents=32000
        )
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        entry = fx.submit_entry(
            api, member_id, tournament["id"],
            request_assistance=True, aid_application_id=application["id"],
        )
        assert_cents(entry["aid_award_cents"], 28800, "aid_award_cents")
        assert_cents(entry["gross_fee_cents"], 32000, "gross_fee_cents")
        assert_cents(entry["late_entry_surcharge_cents"], 0,
                     "late_entry_surcharge_cents")
        assert_cents(entry["net_fee_due_cents"], 3200, "net_fee_due_cents")
        assert entry["fee_status"] == FEE_AID_PARTIAL

        settled_application = validate_success(
            api.get_aid_application(application["id"], TOUR_ADMIN), 200
        )
        assert settled_application["estimated_award_cents"] != entry["aid_award_cents"]
        assert_cents(settled_application["consumed_cents"], 28800, "consumed_cents")

    def test_approval_publishes_a_notice_while_only_the_entry_moves_the_ledger(self, api):
        """No money leaves the purse until a concrete entry settles against it.

        PRD: "**No money moves on the season at approval time**:
        `assistance_available_cents`, `assistance_committed_cents` and
        `assistance_disbursed_cents` are all untouched."

        Design: Difficulty/dual_variant_calc/assistance_estimate_diverges_from_event_settlement
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]

        application = fx.submit_aid_application(
            api, member_id, ctx["season_id"],
            household_income_cents=6000000, dependents=3,
        )
        approved = validate_success(
            api.decide_aid_application(
                application["id"], f.aid_decision_payload(AID_DECISION_APPROVED),
                TOUR_ADMIN,
            ),
            200,
        )
        assert_cents(approved["estimated_award_cents"], 22500, "estimated_award_cents")

        after_approval = fx.read_season(api, ctx["season_id"])
        assert_ledger(after_approval, SEASON_ASSISTANCE_BUDGET_CENTS, 0, 0)

        tournament = fx.create_tournament(
            api, ctx["season_id"], name="Pinehurst Regional", entry_fee_cents=32000
        )
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        fx.submit_entry(
            api, member_id, tournament["id"],
            request_assistance=True, aid_application_id=application["id"],
        )

        after_entry = fx.read_season(api, ctx["season_id"])
        assert_ledger(after_entry, SEASON_ASSISTANCE_BUDGET_CENTS - 28800, 28800, 0)
