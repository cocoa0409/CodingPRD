"""The visit's two dimensions, the cap-breach cascade and the reversal.

A visit's counting dimension and its payout dimension advance independently, a
single close-count can reach the account and back out to the centre, and a
reversal undoes a payment by appending to the journal rather than editing it.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    assert_account_standing,
    assert_center_pool,
    assert_fraud_posture,
    assert_ledger_entry,
    assert_lot_settlement,
    assert_visit_valuation,
)
from test_helpers import factories as f
from test_helpers import fixtures as h


class TestParallelDimensions:
    """Counting and paying are two axes of the same visit."""

    @staticmethod
    def _counting_visit_with_forty(api, world):
        visit = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        first = h.add_lot(
            api,
            visit["id"],
            world.product_id,
            40,
            world.center_headers,
            out_of_state_marked_quantity=0,
            contaminated_quantity=0,
        )
        return visit, first

    def test_manual_withhold_lands_while_the_count_is_still_open(self, api, world):
        """A deliberate hold does not disturb the counting dimension.

        PRD: "A visit carries two independent state dimensions, and it is worth being
        explicit about that: `count_status` moves over `OPEN`, `COUNTING`, `JAM_HOLD` and
        `COUNTED`, terminating at `COUNTED`, while `payout_status` moves over `PENDING`,
        `WITHHELD`, `APPROVED`, `PAID` and `REVERSED`, terminating at `REVERSED`."

        Design: Difficulty/non_linear_state_machine/visit_parallel_dimensions_withhold_while_still_counting
        """
        visit, _ = self._counting_visit_with_forty(api, world)

        withheld = validate_success(
            api.post_payout_action(
                visit["id"],
                f.payout_action_payload(
                    "WITHHOLD", "manual audit of the presented containers"
                ),
                world.center_headers,
            )
        )

        assert withheld["count_status"] == "COUNTING"
        assert withheld["payout_status"] == "WITHHELD"
        assert withheld["withhold_reason"] == "MANUAL_REVIEW"

        second = h.add_lot(
            api,
            visit["id"],
            world.product_id,
            30,
            world.center_headers,
            out_of_state_marked_quantity=0,
            contaminated_quantity=0,
        )
        assert second["accepted_quantity"] == 30

        still_held = h.read_visit(api, visit["id"], world.center_headers)
        assert still_held["count_status"] == "COUNTING"
        assert still_held["payout_status"] == "WITHHELD"
        assert still_held["presented_total"] == 70

    def test_release_and_approve_move_only_the_payout_axis(self, api, world):
        """Closing the count, releasing the hold and approving compose to (COUNTED, APPROVED).

        PRD: "Releasing sets `fraud_hold` back to false and `withhold_reason` back to null,
        and recomputes the centre's `withheld_visit_count`."

        Design: Difficulty/non_linear_state_machine/visit_parallel_dimensions_withhold_while_still_counting
        """
        visit, first = self._counting_visit_with_forty(api, world)
        h.payout_action(
            api,
            visit["id"],
            "WITHHOLD",
            world.center_headers,
            "manual audit of the presented containers",
        )
        second = h.add_lot(
            api,
            visit["id"],
            world.product_id,
            30,
            world.center_headers,
            out_of_state_marked_quantity=0,
            contaminated_quantity=0,
        )

        counted = h.close_count(api, visit["id"], world.center_headers)
        assert counted["count_status"] == "COUNTED"
        assert counted["payout_status"] == "WITHHELD"
        assert counted["raw_accepted_count"] == 70
        assert_visit_valuation(
            counted,
            visit_limit_applied=240,
            capped_count=70,
            shrink_adjustment_count=0,
            payable_count=70,
            refused_over_limit_count=0,
            payout_cents=700,
        )
        center = h.read_center(api, world.center_id, world.center_headers)
        assert_center_pool(center, withheld_visit_count=1)

        released = h.payout_action(api, visit["id"], "RELEASE_HOLD", ADMIN_HEADERS)
        assert released["payout_status"] == "PENDING"
        assert released["withhold_reason"] is None
        assert released["fraud_hold"] is False
        center = h.read_center(api, world.center_id, world.center_headers)
        assert_center_pool(center, withheld_visit_count=0)

        approved = h.payout_action(
            api, visit["id"], "APPROVE", world.center_headers
        )
        assert approved["payout_status"] == "APPROVED"
        assert approved["count_status"] == "COUNTED"

        lots, _ = validate_paginated(
            api.list_visit_lots(visit["id"], world.center_headers)
        )
        by_id = {lot["id"]: lot for lot in lots}
        assert by_id[first["id"]]["paid_quantity"] == 40
        assert by_id[second["id"]]["paid_quantity"] == 30


class TestCapBreachCascade:
    """One close-count reaches the account's standing and returns to the centre."""

    @staticmethod
    def _second_visit_of_three_hundred(api, world):
        """Visit 1 is withheld on out-of-state marking; visit 2 stages two 150-lots."""
        first = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        h.add_lot(
            api,
            first["id"],
            world.product_id,
            100,
            world.center_headers,
            out_of_state_marked_quantity=20,
            contaminated_quantity=0,
        )
        counted_first = h.close_count(api, first["id"], world.center_headers)

        second = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        staged = h.add_lots(
            api, second["id"], world.product_id, [150, 150], world.center_headers
        )
        return counted_first, second, staged

    def test_second_strike_flags_the_account_and_renames_the_hold(self, api, world):
        """The cap breach is the account's second strike, so the hold cites the flag.

        PRD: "And if the strikes recorded in this request bring the account's
        `fraud_strikes` to 2, the account moves `ACTIVE → FLAGGED` as described in §3.3 and
        the visit's `withhold_reason` is overwritten with `ACCOUNT_FLAGGED`."

        Design: Difficulty/transitive_cascade/close_count_cap_breach_flags_account_and_withholds_payout
        """
        counted_first, second, _ = self._second_visit_of_three_hundred(api, world)

        assert counted_first["out_of_state_ratio"] == 0.2
        assert counted_first["payable_count"] == 80
        assert counted_first["payout_cents"] == 800
        assert_fraud_posture(
            counted_first,
            fraud_hold=True,
            withhold_reason="OUT_OF_STATE_RATIO",
            payout_status="WITHHELD",
        )

        counted_second = validate_success(
            api.close_count(second["id"], world.center_headers)
        )

        assert counted_second["count_status"] == "COUNTED"
        assert_visit_valuation(
            counted_second,
            visit_limit_applied=240,
            capped_count=220,
            shrink_adjustment_count=0,
            payable_count=220,
            refused_over_limit_count=80,
            payout_cents=2200,
        )
        assert_fraud_posture(
            counted_second,
            fraud_hold=True,
            withhold_reason="ACCOUNT_FLAGGED",
            payout_status="WITHHELD",
        )

        account = h.read_account(api, world.account_id, ADMIN_HEADERS)
        assert_account_standing(account, "FLAGGED", 2, "DAILY_CAP_EXCEEDED")
        assert account["containers_redeemed_today"] == 300
        assert account["cap_reached_today"] is True

    def test_flagging_recomputes_the_centre_hold_count_and_pool(self, api, world):
        """Both visits now sit in WITHHELD, and the accepted pool counts every lot.

        PRD: "A centre's `withheld_visit_count` is the number of its visits whose
        `payout_status` is `WITHHELD`, and its `cash_drawer_balance_cents` is
        `opening_cash_cents`, less the sum of `payout_cents` over its visits whose
        `payout_status` is `PAID`, plus the sum of `payout_cents` over its visits whose
        `payout_status` is `REVERSED`."

        Design: Difficulty/transitive_cascade/close_count_cap_breach_flags_account_and_withholds_payout
        """
        _, second, staged = self._second_visit_of_three_hundred(api, world)
        h.close_count(api, second["id"], world.center_headers)

        center = h.read_center(api, world.center_id, world.center_headers)
        assert_center_pool(
            center, accepted_container_count=380, withheld_visit_count=2
        )
        assert center["cash_drawer_balance_cents"] == 50000

        lots, _ = validate_paginated(
            api.list_visit_lots(second["id"], world.center_headers)
        )
        by_id = {lot["id"]: lot for lot in lots}
        assert_lot_settlement(by_id[staged[0]["id"]], 150, "PAID_FULL")
        assert_lot_settlement(by_id[staged[1]["id"]], 70, "PAID_PARTIAL")


class TestPayoutReversal:
    """Reversal is a counter-entry, never an edit of the paid line."""

    @staticmethod
    def _paid_visit_against_three_thousand_of_liability(api):
        world = h.build_world(
            api,
            center_overrides={"site_name": "Bend Redemption Center"},
            period_overrides={"operating_cost_cents": 1000},
        )
        h.initiate_deposits(
            api, world.distributor_id, world.product_id, 300, world.period_id
        )
        visit = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        lot = h.add_lot(
            api,
            visit["id"],
            world.product_id,
            220,
            world.center_headers,
            out_of_state_marked_quantity=0,
            contaminated_quantity=0,
        )
        h.close_count(api, visit["id"], world.center_headers)
        h.payout_action(api, visit["id"], "APPROVE", world.center_headers)
        h.payout_action(api, visit["id"], "PAY", world.center_headers)
        return world, visit, lot

    def test_reverse_returns_the_drawer_and_the_quarter_liability(self, api):
        """Paying drew 2200 from the drawer; reversing puts all of it back.

        PRD: "The centre's `cash_drawer_balance_cents` increases by `payout_cents`. A
        deposit ledger line is appended whose `entry_type` is `REDEMPTION_REVERSED`, whose
        `amount_cents` is the positive `payout_cents`, whose `container_count` is
        `payable_count`, whose `source_kind` is `REDEMPTION_VISIT` and whose `source_ref_id`
        is this visit's `id`."

        Design: Difficulty/compensating_invariant/payout_reversal_restores_program_deposit_liability
        """
        world, visit, _ = self._paid_visit_against_three_thousand_of_liability(api)

        before_center = h.read_center(api, world.center_id, world.center_headers)
        assert before_center["cash_drawer_balance_cents"] == 47800
        assert h.read_period(api, world.period_id)["outstanding_liability_cents"] == 800

        reversed_visit = validate_success(
            api.post_payout_action(
                visit["id"],
                f.payout_action_payload(
                    "REVERSE", "duplicate payout discovered at the drawer count"
                ),
                ADMIN_HEADERS,
            )
        )

        assert reversed_visit["payout_status"] == "REVERSED"
        assert reversed_visit["payable_count"] == 220
        assert reversed_visit["payout_cents"] == 2200

        center = h.read_center(api, world.center_id, world.center_headers)
        assert center["cash_drawer_balance_cents"] == 50000

        entries, meta = validate_paginated(
            api.list_ledger_entries(world.period_id, ADMIN_HEADERS)
        )
        assert meta["total_count"] == 3
        assert_ledger_entry(
            entries[0],
            entry_type="DEPOSIT_INITIATED",
            amount_cents=3000,
            container_count=300,
            source_kind="DISTRIBUTOR",
            liability_after_cents=3000,
            source_ref_id=world.distributor_id,
        )
        assert_ledger_entry(
            entries[1],
            entry_type="REDEMPTION_PAID",
            amount_cents=-2200,
            container_count=220,
            source_kind="REDEMPTION_VISIT",
            liability_after_cents=800,
            source_ref_id=visit["id"],
        )
        assert_ledger_entry(
            entries[2],
            entry_type="REDEMPTION_REVERSED",
            amount_cents=2200,
            container_count=220,
            source_kind="REDEMPTION_VISIT",
            liability_after_cents=3000,
            source_ref_id=visit["id"],
        )

    def test_reverse_rolls_back_the_lot_and_the_holder_day(self, api):
        """The lot is unpaid again and the holder's day is free for another visit.

        PRD: "Every container lot of the visit is reset to `paid_quantity` 0 with
        `reconciliation_flag` `UNPAID`. And the account's daily bucket is rolled back:
        `payable_count` is subtracted from `containers_redeemed_today` and
        `cap_reached_today` is recomputed from the reduced figure, which can free the holder
        to redeem again the same day."

        Design: Difficulty/compensating_invariant/payout_reversal_restores_program_deposit_liability
        """
        world, visit, lot = self._paid_visit_against_three_thousand_of_liability(api)

        h.payout_action(
            api,
            visit["id"],
            "REVERSE",
            ADMIN_HEADERS,
            "duplicate payout discovered at the drawer count",
        )

        period = h.read_period(api, world.period_id)
        assert period["outstanding_liability_cents"] == 3000
        assert period["redemptions_paid_cents"] == 0
        assert period["containers_redeemed_count"] == 0
        assert period["deposits_initiated_cents"] == 3000

        lots, _ = validate_paginated(
            api.list_visit_lots(visit["id"], world.center_headers)
        )
        stored = next(entry for entry in lots if entry["id"] == lot["id"])
        assert_lot_settlement(stored, paid_quantity=0, reconciliation_flag="UNPAID")

        account = h.read_account(api, world.account_id, ADMIN_HEADERS)
        assert account["containers_redeemed_today"] == 0
        assert account["cap_reached_today"] is False
