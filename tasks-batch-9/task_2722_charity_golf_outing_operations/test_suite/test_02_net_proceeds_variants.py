"""The provisional and final treatments of an outing's finance rollup."""

import pytest

from test_helpers import (
    COURSE_HEADERS,
    TREASURER_HEADERS,
    assert_direct_costs,
    assert_rollup_chain,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

OUTING = {
    "name": "Two Team Scramble",
    "format": "SCRAMBLE",
    "start_format": "TEE_TIME",
    "field_capacity_teams": 2,
    "prize_pool_cents": 60000,
}
CONTRACT = {
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 6,
    "fnb_minimum_cents": 30000,
    "fnb_per_player_cents": 4500,
}
ALPHA_INDEXES = (12.0, 18.4, 8.2, 24.0)
BRAVO_INDEXES = (13.4, 16.0, 19.6, 21.3)


def _scored_two_team_outing(api):
    """Two paid foursomes, one of which never showed up, carried to SCORED.

    Eight slots are sold but only four golfers check in, which is what makes the
    two billable headcounts differ, and only two of the three prize places can be
    filled, which is what makes the two prize costs differ.
    """
    ctx = fx.open_outing(api, outing=OUTING, contract=CONTRACT)
    alpha = fx.confirmed_registration(
        api, ctx, players=ALPHA_INDEXES, buyer_name="Alpha Partners"
    )
    bravo = fx.confirmed_registration(
        api, ctx, players=BRAVO_INDEXES, buyer_name="Bravo Holdings"
    )
    alpha_team = fx.new_team(api, ctx["outing_id"], alpha["player_ids"], team_name="ALPHA")
    bravo_team = fx.new_team(api, ctx["outing_id"], bravo["player_ids"], team_name="BRAVO")

    fx.lock_field(api, ctx["outing_id"])
    validate_success(
        api.registration_lifecycle(
            alpha["registration_id"],
            f.registration_lifecycle_payload("CHECK_IN"),
            COURSE_HEADERS,
        )
    )

    fx.assign_tee(api, alpha_team["id"], starting_hole=1, tee_time="2026-09-19T12:00:00Z",
                  cart_number=1)
    fx.assign_tee(api, bravo_team["id"], starting_hole=1, tee_time="2026-09-19T12:10:00Z",
                  cart_number=2)
    fx.start_play(api, ctx["outing_id"])

    fx.post_score(api, alpha_team["id"], gross_score=68, gross_back_9=33, gross_back_6=22,
                  gross_back_3=11, gross_hole_18=4)
    fx.post_score(api, bravo_team["id"], gross_score=70, gross_back_9=35, gross_back_6=23,
                  gross_back_3=12, gross_hole_18=4)
    ctx["outing"] = fx.finalize_scoring(api, ctx["outing_id"])

    ctx.update(
        {
            "alpha": alpha,
            "bravo": bravo,
            "alpha_team_id": alpha_team["id"],
            "bravo_team_id": bravo_team["id"],
        }
    )
    return ctx


class TestProvisionalAndFinalNetProceeds:
    def test_provisional_rollup_bills_slots_sold_and_the_whole_prize_pool(self, api):
        """Under the provisional treatment the PRD says "the billable player count
        used by steps 3 and 4 is `confirmed_player_slots`, the slots actually sold"
        and that "`prize_cost_cents` is the full `prize_pool_cents` plus the sum of
        `contest_payout_cents` across the outing's contests, because until the field
        is scored the whole pool is treated as payable".

        Design: Difficulty/dual_variant_calc/net_proceeds_provisional_vs_final
        """
        ctx = _scored_two_team_outing(api)
        outing = fx.read_outing(api, ctx["outing_id"])

        assert outing["proceeds_variant"] == "PROVISIONAL"
        assert outing["confirmed_player_slots"] == 8
        assert outing["checked_in_player_count"] == 4
        assert outing["gross_revenue_cents"] == 240000
        assert outing["course_charge_cents"] == 76000
        assert outing["fnb_shortfall_cents"] == 0
        assert outing["prize_cost_cents"] == 60000
        assert outing["direct_costs_cents"] == 136000
        assert outing["net_proceeds_before_fee_cents"] == 104000
        assert outing["admin_fee_pct"] == pytest.approx(0.05, abs=0.0001)
        assert outing["admin_fee_cents"] == 12000
        assert outing["net_proceeds_cents"] == 92000
        assert_direct_costs(outing)
        assert_rollup_chain(outing)

    def test_reconciliation_rebills_on_turnout_and_only_awarded_prizes(self, api):
        """Reconciling "switches `proceeds_variant` to `FINAL` and rewrites every
        finance field under the final treatment", where "the billable player count
        becomes `checked_in_player_count`, the turnout that actually walked the
        course, still floored by `guaranteed_player_count` in step 3 but with no
        floor applied in the step-4 food-and-beverage credit" and "`prize_cost_cents`
        becomes the sum of `prize_award_cents` actually written across the teams plus
        the sum of `contest_payout_cents`, so an unclaimed placement prize stops
        being a cost".

        Design: Difficulty/dual_variant_calc/net_proceeds_provisional_vs_final
        """
        ctx = _scored_two_team_outing(api)
        version = fx.outing_version(api, ctx["outing_id"], TREASURER_HEADERS)
        outing = validate_success(
            api.finance_transition(
                ctx["outing_id"],
                f.finance_transition_payload("RECONCILE", version),
                TREASURER_HEADERS,
            )
        )

        assert outing["finance_status"] == "RECONCILED"
        assert outing["proceeds_variant"] == "FINAL"
        assert outing["gross_revenue_cents"] == 240000
        assert outing["course_charge_cents"] == 57000
        assert outing["fnb_shortfall_cents"] == 12000
        assert outing["prize_cost_cents"] == 48000
        assert outing["direct_costs_cents"] == 117000
        assert outing["net_proceeds_before_fee_cents"] == 123000
        assert outing["admin_fee_pct"] == pytest.approx(0.05, abs=0.0001)
        assert outing["admin_fee_cents"] == 12000
        assert outing["net_proceeds_cents"] == 111000
        assert outing["unclaimed_prize_cents"] == 12000
        assert_direct_costs(outing)
        assert_rollup_chain(outing)

        assert fx.read_team(api, ctx["alpha_team_id"])["prize_award_cents"] == 30000
        assert fx.read_team(api, ctx["bravo_team_id"])["prize_award_cents"] == 18000
