"""Loyalty: provisional vs final earning, tier thresholds, member defaults."""
import test_helpers as th
from test_helpers import validate_success


class TestProvisionalVsFinalEarning:
    def _placed_order(self, api, headers):
        member = th.member_with_lifetime(api, lifetime_points=1200, balance=0, headers=headers)
        shop = th.setup_latte_shop(api, headers=headers)
        order = th.two_line_order(api, shop, member_id=member["id"], headers=headers)
        return member, shop, order

    def test_provisional_points_earned_off_subtotal_at_placement(self, api, manager_headers):
        """PRD 3.7: "At placement, the order's `points_earned_provisional` is the
        `subtotal_cents` divided by the earn divisor of 100 cents, rounded down to
        a whole number; this provisional figure is computed off the pre-discount,
        pre-fee subtotal and does not touch any member balance."
        PRD 3.7: "before fulfillment this field is null."

        Design: Difficulty/dual_variant_calc/order_points_provisional_vs_final
        """
        _, _, order = self._placed_order(api, manager_headers)
        # subtotal 1905 -> floor(1905/100) = 19
        assert order["points_earned_provisional"] == 19, f"got {order['points_earned_provisional']}"
        assert order["points_earned_final"] is None, f"got {order['points_earned_final']}"

    def test_final_points_earned_off_total_at_fulfill(self, api, manager_headers):
        """PRD 3.7: "At fulfillment, the order's `points_earned_final` is the
        `total_cents` — the amount actually payable, after discounts and fees —
        divided by the same earn divisor of 100 cents and rounded down to a whole
        number; before fulfillment this field is null."

        Design: Difficulty/dual_variant_calc/order_points_provisional_vs_final
        """
        _, _, order = self._placed_order(api, manager_headers)
        fulfilled = validate_success(api.fulfill_order(order["id"], manager_headers))
        # total 1764 -> floor(1764/100) = 17 (differs from provisional 19)
        assert fulfilled["points_earned_final"] == 17, f"got {fulfilled['points_earned_final']}"


class TestLoyaltyTierBoundary:
    def test_gold_at_exactly_thousand_lifetime_points(self, api, manager_headers):
        """PRD 3.4: "the tier is `GOLD` when `lifetime_points` is at least 1000,
        `SILVER` when it is at least 500 but below 1000, and `BRONZE` otherwise."
        PRD 3.4: "The boundaries are inclusive, so exactly 1000 lifetime points
        yields `GOLD` and exactly 500 yields `SILVER`."

        Design: Difficulty/boundary_precision_check/loyalty_tier_gold_boundary_inclusive
        """
        member = th.member_with_lifetime(api, lifetime_points=1000, balance=0, headers=manager_headers)
        fetched = validate_success(api.get_member(member["id"], manager_headers))
        assert fetched["tier"] == "GOLD", f"got {fetched['tier']}"

    def test_silver_just_below_gold_threshold(self, api, manager_headers):
        """PRD 3.4: "the tier is `GOLD` when `lifetime_points` is at least 1000,
        `SILVER` when it is at least 500 but below 1000, and `BRONZE` otherwise."

        Design: Difficulty/boundary_precision_check/loyalty_tier_gold_boundary_inclusive
        """
        member = th.member_with_lifetime(api, lifetime_points=999, balance=0, headers=manager_headers)
        fetched = validate_success(api.get_member(member["id"], manager_headers))
        assert fetched["tier"] == "SILVER", f"got {fetched['tier']}"


def test_member_defaults_on_create(api, manager_headers):
    """PRD 3.4: "A new member starts with `points_balance` and `lifetime_points`
    at zero and `tier` of `BRONZE`."

    Design: Corner/entities/member_computed_fields_on_create
    """
    member = th.new_member(api, headers=manager_headers, email="new-defaults@example.com",
                           full_name="New")
    fetched = validate_success(api.get_member(member["id"], manager_headers))
    assert fetched["points_balance"] == 0, f"got {fetched['points_balance']}"
    assert fetched["lifetime_points"] == 0, f"got {fetched['lifetime_points']}"
    assert fetched["tier"] == "BRONZE", f"got {fetched['tier']}"
