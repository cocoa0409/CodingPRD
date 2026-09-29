"""The declared model is immediate: the next read after a write is already settled."""

from test_helpers import (
    BENEFICIARY_HEADERS,
    TREASURER_HEADERS,
    assert_instant_equals,
    assert_rollup_chain,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ROLLUP_OUTING = {
    "name": "Immediate Rollup Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
FLAT_CONTRACT = {"guaranteed_player_count": 0, "fnb_minimum_cents": 0}
TEAM4_TIER = {
    "code": "TEAM4",
    "kind": "TEAM",
    "price_cents": 120000,
    "player_slots": 4,
    "gsv_cents": 0,
    "inventory_cap": 4,
}
CLOCK_START = "2026-08-01T00:00:00Z"
PACKAGE_PRICE_CENTS = 120000
PLEDGE_CENTS = 50000


class TestEveryDerivedFigureIsCurrentOnTheNextRead:
    def _an_unpaid_foursome_package(self, api):
        ctx = fx.open_outing(
            api, clock=CLOCK_START, outing=ROLLUP_OUTING, contract=FLAT_CONTRACT,
            tier=TEAM4_TIER,
        )
        created = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Immediate Buyer",
            player_count=4,
        )
        ctx["registration_id"] = created["id"]
        return ctx

    def test_the_payment_response_and_the_next_reads_are_already_settled(self, api):
        """Nothing here is deferred: "Cascades are applied immediately and synchronously: a
        read issued after the response is returned always observes the fully settled state,
        and the server never defers reconciliation to a later request."  The payment response
        itself carries the confirmation, because "Confirmation goes further: it stamps
        `confirmed_at` from the logical clock", and the very next reads carry the counters it
        "re-derives the tier's `sold_count`, and re-derives the outing's
        `confirmed_player_slots`" along with the whole rollup, down to the fee where
        "`admin_fee_pct` is 0 when `net_proceeds_before_fee_cents` is zero or negative;
        otherwise 0.05 when it is below 2000000 cents (twenty thousand dollars)" and
        "`admin_fee_cents` is then `admin_fee_pct` multiplied by `gross_revenue_cents`,
        rounded half up to whole cents".

        Design: Corner/consistency_model/every_derived_figure_is_already_current_in_the_next_read_after_the_write
        """
        ctx = self._an_unpaid_foursome_package(api)

        paid = validate_success(
            api.record_registration_payment(
                ctx["registration_id"], f.payment_payload(PACKAGE_PRICE_CENTS),
                TREASURER_HEADERS,
            )
        )
        assert paid["status"] == "CONFIRMED"
        assert paid["amount_paid_cents"] == PACKAGE_PRICE_CENTS
        assert_instant_equals(paid["confirmed_at"], CLOCK_START)

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["confirmed_player_slots"] == 4
        assert outing["gross_revenue_cents"] == 120000
        assert outing["course_charge_cents"] == 38000
        assert outing["direct_costs_cents"] == 38000
        assert outing["net_proceeds_before_fee_cents"] == 82000
        assert outing["admin_fee_cents"] == 6000
        assert outing["net_proceeds_cents"] == 76000
        assert_rollup_chain(outing)

        assert fx.read_tier(api, ctx["tier_id"])["sold_count"] == 1

        report = validate_success(
            api.get_proceeds_report(ctx["outing_id"], BENEFICIARY_HEADERS)
        )
        assert report["gross_revenue_cents"] == 120000
        assert report["net_proceeds_cents"] == 76000

    def test_a_second_revenue_channel_re_derives_the_rollup_rather_than_incrementing_it(
        self, api
    ):
        """A donation arrives through an unrelated channel, and "On acceptance
        `collected_cents` is set to that amount and added to the outing's
        `gross_revenue_cents`, and the rest of the rollup is recomputed."  The result proves
        the recomputation is total rather than a cached increment, since "Every figure the
        beneficiary ever sees comes out of one rollup, and that rollup is recomputed in full"
        on "every event that could move any of its inputs": the net moves by less than the
        pledge, because the fee base moved with it.

        Design: Corner/consistency_model/every_derived_figure_is_already_current_in_the_next_read_after_the_write
        """
        ctx = self._an_unpaid_foursome_package(api)
        fx.pay_registration(api, ctx["registration_id"], PACKAGE_PRICE_CENTS)

        first = fx.read_outing(api, ctx["outing_id"])
        assert first["net_proceeds_cents"] == 76000

        item = fx.new_item(
            api, ctx["outing_id"], item_type="DONATION", description="Matching gift pledge",
            fmv_cents=0, ask_cents=PLEDGE_CENTS,
        )
        sold = fx.sell_item(api, item["id"], ctx["registration_id"], PLEDGE_CENTS)
        assert sold["status"] == "SOLD"
        collected = fx.pay_item(api, item["id"], PLEDGE_CENTS)
        assert collected["status"] == "PAID"
        assert collected["collected_cents"] == PLEDGE_CENTS

        second = fx.read_outing(api, ctx["outing_id"])
        assert second["gross_revenue_cents"] == 170000
        assert second["course_charge_cents"] == 38000
        assert second["direct_costs_cents"] == 38000
        assert second["net_proceeds_before_fee_cents"] == 132000
        assert second["admin_fee_cents"] == 8500
        assert second["net_proceeds_cents"] == 123500
        assert_rollup_chain(second)

        assert second["net_proceeds_cents"] - first["net_proceeds_cents"] == 47500

        report = validate_success(
            api.get_proceeds_report(ctx["outing_id"], BENEFICIARY_HEADERS)
        )
        assert report["gross_revenue_cents"] == 170000
        assert report["net_proceeds_cents"] == 123500
