"""A conserved ledger: the member's stock capital, taken out of balance by funding an
advance and returned to exactly its opening value by the compensating repurchase."""
from test_helpers import *  # noqa: F401,F403

LIVE_SUBSCRIPTION_STATUSES = ("ISSUED", "REDEMPTION_REQUESTED")


def _live_subscription_total(api, member_bank_id):
    """Sum ``amount_cents`` over the subscriptions that still count as held."""
    rows, _meta = validate_paginated(
        api.list_stock_subscriptions(CREDIT_ONE, {"member_bank_id": member_bank_id})
    )
    return sum(
        row["amount_cents"]
        for row in rows
        if row["status"] in LIVE_SUBSCRIPTION_STATUSES
    )


class TestStockCapitalConservation:
    """9,600,000 out, 9,650,000 through the advance, 9,600,000 back again."""

    def _ledger_through_fund_and_repay(self, api):
        """Fund a 1,000,000 advance that mints its own stock, then repay at maturity."""
        env = member_with_eligible_sf(api)
        members = [env.refresh()]
        sums = [_live_subscription_total(api, env.member_id)]
        product = create_product(api)
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=950_000,
            fund_stock_from_advance=True,
        )
        rows, _meta = validate_paginated(
            api.list_stock_subscriptions(CREDIT_ONE, {"advance_id": advance["id"]})
        )
        activity = rows[0]
        members.append(env.refresh())
        sums.append(_live_subscription_total(api, env.member_id))
        pin_clock(api, "2026-08-31T00:00:00Z")
        repaid = repay_advance(api, advance["id"])
        members.append(env.refresh())
        sums.append(_live_subscription_total(api, env.member_id))
        return env, activity, repaid, members, sums

    def test_the_opening_ledger_carries_membership_stock_and_nothing_else(self, api):
        """PRD §3.1: "`required_membership_stock_cents` is twelve basis points of
        `total_assets_cents`: multiply `total_assets_cents` by 12, divide by 10,000, and
        round half up to whole cents."

        Design: Difficulty/compensating_invariant/stock_capital_conservation_across_fund_repay_repurchase
        """
        _env, _activity, _repaid, members, _sums = self._ledger_through_fund_and_repay(api)

        assert_stock_position(
            members[0],
            required_membership_stock_cents=9_600_000,
            required_activity_stock_cents=0,
            required_total_stock_cents=9_600_000,
            stock_held_cents=9_600_000,
            stock_deficiency_cents=0,
            excess_stock_cents=0,
        )

    def test_funding_lifts_holdings_and_requirement_by_the_same_fifty_thousand(self, api):
        """PRD §3.6: "When `fund_stock_from_advance` is true, an `ACTIVITY` subscription
        of `amount_cents` equal to `activity_stock_cents` is created with its
        `advance_id` pointing at this advance and is immediately `ISSUED` in the same
        request — its `SUBSCRIBED` state is never observable on this path."

        Design: Difficulty/compensating_invariant/stock_capital_conservation_across_fund_repay_repurchase
        """
        _env, activity, _repaid, members, _sums = self._ledger_through_fund_and_repay(api)

        assert_fields(activity, subscription_type="ACTIVITY", amount_cents=50_000)
        assert_par_multiple(activity["amount_cents"])
        assert_stock_position(
            members[1],
            required_activity_stock_cents=50_000,
            required_total_stock_cents=9_650_000,
            stock_held_cents=9_650_000,
            stock_deficiency_cents=0,
            excess_stock_cents=0,
        )

    def test_repayment_drops_the_requirement_while_holdings_stay_put(self, api):
        """PRD §3.6: "Repayment sets `outstanding_principal_cents` to 0, moves
        `collateral_status` to `RELEASED` from either `SECURED` or `SHORTFALL`, and moves
        the linked `ACTIVITY` subscription — the one whose `advance_id` is this advance
        and whose `status` is `ISSUED` — to `REDEMPTION_REQUESTED`."

        Design: Difficulty/compensating_invariant/stock_capital_conservation_across_fund_repay_repurchase
        """
        _env, activity, repaid, members, _sums = self._ledger_through_fund_and_repay(api)

        assert_advance_dimensions(repaid, "REPAID", "RELEASED")
        assert repaid["outstanding_principal_cents"] == 0
        assert (
            get_success_data(api.get_stock_subscription(activity["id"], CREDIT_ONE))[
                "status"
            ]
            == "REDEMPTION_REQUESTED"
        )
        assert_stock_position(
            members[2],
            required_activity_stock_cents=0,
            required_total_stock_cents=9_600_000,
            stock_held_cents=9_650_000,
            stock_deficiency_cents=0,
            excess_stock_cents=50_000,
        )

    def test_the_repurchase_returns_the_ledger_to_its_opening_value(self, api):
        """PRD §3.1: "A `CreditOfficer` later repurchases a `REDEMPTION_REQUESTED`
        subscription, moving it to `REPURCHASED`, stamping `repurchased_at`, and
        recomputing `stock_held_cents`, `stock_deficiency_cents` and
        `excess_stock_cents`."

        Design: Difficulty/compensating_invariant/stock_capital_conservation_across_fund_repay_repurchase
        """
        env, activity, _repaid, members, _sums = self._ledger_through_fund_and_repay(api)

        repurchased = validate_success(
            api.repurchase_stock_subscription(activity["id"], CREDIT_ONE)
        )

        assert repurchased["status"] == "REPURCHASED"
        assert repurchased["repurchased_at"] == "2026-08-31T00:00:00.000Z"
        assert_stock_position(
            env.refresh(),
            required_total_stock_cents=9_600_000,
            stock_held_cents=members[0]["stock_held_cents"],
            stock_deficiency_cents=0,
            excess_stock_cents=0,
        )

    def test_holdings_equal_the_live_subscription_sum_at_every_checkpoint(self, api):
        """PRD §3.1: "`stock_held_cents` is the sum of `amount_cents` over the member's
        subscriptions whose `status` is `ISSUED` or `REDEMPTION_REQUESTED` — a
        subscription awaiting redemption still counts as held."

        Design: Difficulty/compensating_invariant/stock_capital_conservation_across_fund_repay_repurchase
        """
        env, activity, _repaid, members, sums = self._ledger_through_fund_and_repay(api)
        held = [member["stock_held_cents"] for member in members]

        api.repurchase_stock_subscription(activity["id"], CREDIT_ONE)

        held.append(env.refresh()["stock_held_cents"])
        sums.append(_live_subscription_total(api, env.member_id))
        assert held == [9_600_000, 9_650_000, 9_650_000, 9_600_000]
        assert sums == held

    def test_the_floor_permits_the_activity_redemption_and_refuses_the_membership_one(self, api):
        """PRD §3.1: "Both steps enforce the same floor: if `stock_held_cents` minus this
        subscription's `amount_cents` would fall below `required_total_stock_cents`, the
        request is rejected with `ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT`."

        Design: Difficulty/compensating_invariant/stock_capital_conservation_across_fund_repay_repurchase
        """
        env, activity, _repaid, _members, _sums = self._ledger_through_fund_and_repay(api)
        membership = env.subscriptions["membership"]

        refused = api.request_stock_redemption(membership["id"], env.treasury)
        permitted = api.repurchase_stock_subscription(activity["id"], CREDIT_ONE)

        validate_error(refused, "ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT", 409)
        validate_success(permitted)
        assert (
            get_success_data(api.get_stock_subscription(membership["id"], CREDIT_ONE))[
                "status"
            ]
            == "ISSUED"
        )
        assert env.refresh()["stock_held_cents"] == 9_600_000
