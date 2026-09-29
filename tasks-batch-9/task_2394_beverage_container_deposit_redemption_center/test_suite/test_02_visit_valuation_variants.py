"""Close-count valuation across channels and against the day's allowance.

The same containers are worth different money depending on how they were
counted, and the three-way minimum decides which of the three ceilings binds.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    assert_account_standing,
    assert_fraud_posture,
    assert_lot_settlement,
    assert_visit_valuation,
)
from test_helpers import fixtures as h


class TestChannelDivergence:
    """Sixty accepted containers pay differently by channel."""

    @staticmethod
    def _two_visits_of_sixty(api, world):
        """One machine-counted and one hand-counted visit, both holding a 60-lot."""
        visit_a = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        h.add_lot(
            api,
            visit_a["id"],
            world.product_id,
            60,
            world.center_headers,
            out_of_state_marked_quantity=0,
            contaminated_quantity=0,
        )
        visit_b = h.open_center_hand_visit(api, world.center_id, world.account_id)
        lot_b = h.add_lot(
            api,
            visit_b["id"],
            world.product_id,
            60,
            world.center_headers,
            out_of_state_marked_quantity=0,
            contaminated_quantity=0,
        )
        return visit_a, visit_b, lot_b

    def test_machine_counted_visit_pays_every_accepted_container(self, api, world):
        """A machine count carries the 240 ceiling and no shrink deduction.

        PRD: "A machine-counted visit at a redemption centre has a base ceiling of 240
        containers." — "A machine-counted visit has a `shrink_adjustment_count` of 0 and
        therefore a `payable_count` equal to its `capped_count`."

        Design: Difficulty/dual_variant_calc/visit_payout_hand_count_vs_machine_count_divergence
        """
        visit_a, visit_b, _ = self._two_visits_of_sixty(api, world)

        counted_a = validate_success(
            api.close_count(visit_a["id"], world.center_headers)
        )
        h.close_count(api, visit_b["id"], world.center_headers)

        assert_visit_valuation(
            counted_a,
            visit_limit_applied=240,
            capped_count=60,
            shrink_adjustment_count=0,
            payable_count=60,
            refused_over_limit_count=0,
            payout_cents=600,
        )

    def test_hand_counted_visit_is_capped_at_fifty_and_charged_shrink(
        self, api, world
    ):
        """A hand count is held to 50 containers and loses one to shrink.

        PRD: "A hand-counted visit at a redemption centre has a base ceiling of 50
        containers." — "`shrink_adjustment_count` is two per cent of `capped_count`
        rounded **up** to the next whole container".

        Design: Difficulty/dual_variant_calc/visit_payout_hand_count_vs_machine_count_divergence
        """
        visit_a, visit_b, lot_b = self._two_visits_of_sixty(api, world)
        h.close_count(api, visit_a["id"], world.center_headers)

        counted_b = validate_success(
            api.close_count(visit_b["id"], world.center_headers)
        )

        assert_visit_valuation(
            counted_b,
            visit_limit_applied=50,
            capped_count=50,
            shrink_adjustment_count=1,
            payable_count=49,
            refused_over_limit_count=10,
            payout_cents=490,
        )

        lots, _ = validate_paginated(
            api.list_visit_lots(visit_b["id"], world.center_headers)
        )
        stored_lot = next(lot for lot in lots if lot["id"] == lot_b["id"])
        assert stored_lot["accepted_quantity"] == 60
        assert_lot_settlement(stored_lot, paid_quantity=49, reconciliation_flag="PAID_PARTIAL")

        account = h.read_account(api, world.account_id, world.account_headers)
        assert account["containers_redeemed_today"] == 109
        assert account["cap_reached_today"] is False
        assert_account_standing(account, "ACTIVE", 0, None)


class TestDailyAllowanceBinds:
    """The third term of the three-way minimum can be the one that binds."""

    @staticmethod
    def _account_with_eighty_paid_and_a_three_hundred_visit(api, world):
        """Close an 80-container visit, then stage a second visit of two 150-lots."""
        first = h.create_counted_center_visit(
            api,
            world.center_id,
            world.machine_id,
            world.product_id,
            [80],
            world.account_id,
        )
        assert first["payable_count"] == 80

        second = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        lots = h.add_lots(
            api, second["id"], world.product_id, [150, 150], world.center_headers
        )
        return second, lots

    def test_remaining_allowance_of_two_hundred_and_twenty_caps_the_payout(
        self, api, world
    ):
        """With 80 already redeemed today, only 220 of the 300 accepted are payable.

        PRD: "`capped_count` is the smallest of three numbers: `raw_accepted_count`,
        `visit_limit_applied` and the remaining daily allowance."

        Design: Difficulty/combinatorial_formula/visit_payable_three_way_min_daily_allowance_binds
        """
        second, _ = self._account_with_eighty_paid_and_a_three_hundred_visit(api, world)

        counted = validate_success(api.close_count(second["id"], world.center_headers))

        assert counted["raw_accepted_count"] == 300
        assert_visit_valuation(
            counted,
            visit_limit_applied=240,
            capped_count=220,
            shrink_adjustment_count=0,
            payable_count=220,
            refused_over_limit_count=80,
            payout_cents=2200,
        )
        assert_fraud_posture(
            counted,
            fraud_hold=True,
            withhold_reason="DAILY_CAP_EXCEEDED",
            payout_status="WITHHELD",
        )

    def test_waterfall_splits_the_allowance_across_the_two_lots(self, api, world):
        """The 220 payable containers land as 150 on the first lot and 70 on the second.

        PRD: "Walking the lots in that order, each lot's `paid_quantity` is the lesser of
        its own `accepted_quantity` and whatever remains undistributed, and the remainder
        shrinks by that amount before the next lot is considered."

        Design: Difficulty/combinatorial_formula/visit_payable_three_way_min_daily_allowance_binds
        """
        second, staged = self._account_with_eighty_paid_and_a_three_hundred_visit(
            api, world
        )
        h.close_count(api, second["id"], world.center_headers)

        lots, meta = validate_paginated(
            api.list_visit_lots(second["id"], world.center_headers)
        )
        assert meta["total_count"] == 2
        by_id = {lot["id"]: lot for lot in lots}
        assert_lot_settlement(by_id[staged[0]["id"]], 150, "PAID_FULL")
        assert_lot_settlement(by_id[staged[1]["id"]], 70, "PAID_PARTIAL")

        account = h.read_account(api, world.account_id, world.account_headers)
        assert account["containers_redeemed_today"] == 300
        assert account["cap_reached_today"] is True
        assert_account_standing(account, "ACTIVE", 1, "DAILY_CAP_EXCEEDED")
