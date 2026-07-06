"""Order line pricing and pinned order-total evaluation.

Covers the combinatorial pricing formula (size multiplier x modifier surcharge
x quantity), the pinned service-fee/total evaluation order, and tier discounts.
"""
import test_helpers as th
from test_helpers import validate_success


MGR = th.TEST_USERS["manager_headers"]


class TestLinePriceTieredSize:
    def test_large_size_multiplier_with_modifier_and_quantity(self, api, manager_headers):
        """PRD 3.5: "To price a line, the item's base price is first scaled by the
        size multiplier for its `size` — 1.0 for `SMALL`, 1.25 for `MEDIUM`, and
        1.5 for `LARGE` — with the product rounded half-up to whole cents to form
        the sized base."
        PRD 3.5: "The per-unit surcharges of the line's referenced modifiers are
        summed and added to that sized base, and the result is multiplied by the
        line's `quantity` to give `line_price_cents`."

        Design: Difficulty/combinatorial_formula/order_line_price_tiered_size_selection
        """
        shot = th.new_modifier(api, name="Extra Shot", modifier_group="SHOT",
                               surcharge_cents=90, extra_bean_grams=9, headers=manager_headers)
        latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                                 required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                                 origin_required=False, headers=manager_headers)
        resp = api.create_order(
            {"lines": [{"menu_item_id": latte["id"], "quantity": 2,
                        "modifier_ids": [shot["id"]]}]},
            manager_headers)
        order = validate_success(resp, 201)
        # (round_half_up(450 * 1.5)=675 + 90) * 2 = 1530
        assert order["subtotal_cents"] == 1530, f"got {order['subtotal_cents']}"

    def test_line_price_persisted_on_fetch(self, api, manager_headers):
        """PRD 3.5: "The order's `subtotal_cents` is the sum of `line_price_cents`
        across all lines."
        PRD 3.5: "with the product rounded half-up to whole cents to form the
        sized base."

        Design: Difficulty/combinatorial_formula/order_line_price_tiered_size_selection
        """
        shot = th.new_modifier(api, name="Extra Shot", modifier_group="SHOT",
                               surcharge_cents=90, extra_bean_grams=9, headers=manager_headers)
        latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                                 required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                                 origin_required=False, headers=manager_headers)
        created = th.new_order(api, headers=manager_headers,
                               lines=[{"menu_item_id": latte["id"], "quantity": 2,
                                       "modifier_ids": [shot["id"]]}])
        fetched = validate_success(api.get_order(created["id"], manager_headers))
        assert fetched["subtotal_cents"] == 1530, f"got {fetched['subtotal_cents']}"


class TestPinnedOrderTotals:
    def _gold_and_item(self, api, headers):
        member = th.member_with_lifetime(api, lifetime_points=1200, balance=0, headers=headers)
        item = th.new_menu_item(api, name="Batch LG", category="BEVERAGE", base_price_cents=400,
                                required_equipment_type="BATCH_BREW", size="MEDIUM",
                                bean_grams=0, origin_required=False, headers=headers)
        return member, item

    def test_service_fee_waived_from_subtotal_not_total(self, api, manager_headers):
        """PRD 3.5: "First, the `service_fee_cents` is decided purely from the
        subtotal: it is 0 when `subtotal_cents` is at least the fee-waive threshold
        of 2000 cents, and otherwise it is the small-order fee of 50 cents."

        Design: Difficulty/combinatorial_formula/order_totals_pinned_evaluation_order
        """
        member, item = self._gold_and_item(api, manager_headers)
        order = th.new_order(api, headers=manager_headers, member_id=member["id"],
                             lines=[{"menu_item_id": item["id"], "quantity": 4,
                                     "modifier_ids": []}])
        # 500 * 4 = 2000 -> fee waived even though total (1800) is below the threshold
        assert order["subtotal_cents"] == 2000, f"got {order['subtotal_cents']}"
        assert order["service_fee_cents"] == 0, f"got {order['service_fee_cents']}"

    def test_total_after_gold_discount_and_waived_fee(self, api, manager_headers):
        """PRD 3.5: "`tier_discount_cents` is `subtotal_cents` multiplied by the
        member's tier discount rate — 0 percent for `BRONZE`, 5 percent for
        `SILVER`, and 10 percent for `GOLD` — rounded half-up to whole cents"
        PRD 3.5: "Finally, `total_cents` is the subtotal minus the total discount
        plus the service fee, floored at zero so it is never negative."

        Design: Difficulty/combinatorial_formula/order_totals_pinned_evaluation_order
        """
        member, item = self._gold_and_item(api, manager_headers)
        order = th.new_order(api, headers=manager_headers, member_id=member["id"],
                             lines=[{"menu_item_id": item["id"], "quantity": 4,
                                     "modifier_ids": []}])
        # 2000 - round_half_up(2000*0.10)=200 + 0 = 1800
        assert order["total_cents"] == 1800, f"got {order['total_cents']}"


def test_silver_tier_discount_on_totals(api, manager_headers):
    """PRD 3.5: "`tier_discount_cents` is `subtotal_cents` multiplied by the
    member's tier discount rate — 0 percent for `BRONZE`, 5 percent for `SILVER`,
    and 10 percent for `GOLD` — rounded half-up to whole cents"
    PRD 3.5: "The order's `discount_cents` is the sum of the tier discount and the
    redemption discount — both taken off the original subtotal, not applied
    sequentially."

    Design: Corner/calculations/order_totals_silver_tier_discount
    """
    member = th.member_with_lifetime(api, lifetime_points=500, balance=0, headers=manager_headers)
    shot = th.new_modifier(api, name="Extra Shot", modifier_group="SHOT",
                           surcharge_cents=90, extra_bean_grams=9, headers=manager_headers)
    latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                             required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                             origin_required=False, headers=manager_headers)
    order = th.new_order(api, headers=manager_headers, member_id=member["id"],
                         lines=[{"menu_item_id": latte["id"], "quantity": 2,
                                 "modifier_ids": [shot["id"]]}])
    # subtotal 1530; tier_discount round_half_up(1530*0.05)=77; fee 50; total 1530-77+50=1503
    assert order["subtotal_cents"] == 1530, f"got {order['subtotal_cents']}"
    assert order["discount_cents"] == 77, f"got {order['discount_cents']}"
    assert order["total_cents"] == 1503, f"got {order['total_cents']}"
