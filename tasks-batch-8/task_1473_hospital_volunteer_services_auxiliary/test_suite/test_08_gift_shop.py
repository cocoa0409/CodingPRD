"""Gift shop point of sale: non-stacking max discount with per-line rounding,
quantity shape validation, catalog restock/soft-disable, cashier placement gate,
and the stock/tender fiscal pair."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    set_clock, approve_application, create_gift_shop_cashier, create_item,
    create_campaign, ring_sale, create_active_volunteer, create_department,
    create_role, create_open_request,
    make_volunteer_headers, make_treasurer_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestDiscountMaxStack:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        cashier = create_gift_shop_cashier()
        _, junior_id = approve_application(
            full_name="Jamie Junior", date_of_birth="2011-06-15",
            email="jamie@x.org", phone="555-0301")
        campaign = create_campaign(name="Promo Week", promo_discount_pct=20,
                                   activate=True)
        ita = create_item(sku="IT-A", name="Item A", unit_price_cents=1000,
                          unit_cost_cents=300, stock_on_hand=10)
        itb = create_item(sku="IT-B", name="Item B", unit_price_cents=555,
                          unit_cost_cents=100, stock_on_hand=10)
        itc = create_item(sku="IT-C", name="Item C", unit_price_cents=1025,
                          unit_cost_cents=100, stock_on_hand=10)
        set_clock("2026-08-02T12:00:00Z")
        return cashier, junior_id, campaign, ita, itb, itc

    def test_max_discount_non_stacking_and_change(self, api):
        """PRD §3.7: "Discounts never stack — the single largest eligible candidate
        wins, and the winner is recorded as `discount_pct_applied`."
        PRD §3.7: "Each line amounts to its quantity times the item's
        `unit_price_cents`, scaled by the winning discount — multiplied by 100 minus
        the discount percent, then divided by 100 — rounded half-up to whole cents;
        `total_cents` is the sum of the rounded line amounts."

        Design: Difficulty/combinatorial_formula/sale_discount_max_stack_per_line_rounding
        """
        cashier, junior_id, campaign, ita, itb, _ = self._setup()
        sale = validate_success(api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "buyer_volunteer_id": junior_id,
             "campaign_id": campaign["id"],
             "lines": [{"item_id": ita["id"], "qty": 2},
                       {"item_id": itb["id"], "qty": 1}],
             "tendered_cents": 2500}, TREASURER), expected_status=201)
        assert sale["discount_pct_applied"] == 20, (
            "max(tier 0, junior 5, promo 20) — the promo alone wins, non-stacking")
        assert sale["total_cents"] == 2044, (
            f"round_half_up(2*1000*0.80)=1600 + round_half_up(1*555*0.80)=444; "
            f"got {sale['total_cents']}")
        assert sale["change_cents"] == 456

    def test_junior_only_discount_half_up_boundary(self, api):
        """PRD §3.7: "The junior discount is 5 percent, applying when the buyer is a
        volunteer and junior today."
        PRD §2.6: "Sale lines are rounded half-up to whole cents per line before the
        per-line amounts are summed." (1025 x 0.95 = 973.75 -> 974.)

        Design: Difficulty/combinatorial_formula/sale_discount_max_stack_per_line_rounding
        """
        cashier, junior_id, _, _, _, itc = self._setup()
        sale = validate_success(api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "buyer_volunteer_id": junior_id,
             "lines": [{"item_id": itc["id"], "qty": 1}],
             "tendered_cents": 1000}, TREASURER), expected_status=201)
        assert sale["discount_pct_applied"] == 5, "no campaign: the junior flag is the only candidate"
        assert sale["total_cents"] == 974, (
            f"round_half_up(1025*0.95) = round_half_up(973.75) = 974, got {sale['total_cents']}")


class TestSaleQuantityValidation:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        cashier = create_gift_shop_cashier()
        item = create_item(sku="PLUSH-BEAR", name="Plush Bear", unit_price_cents=1000,
                           unit_cost_cents=300, stock_on_hand=10)
        set_clock("2026-08-02T12:00:00Z")
        return cashier, item

    def test_zero_quantity_rejected(self, api):
        """PRD §3.7: "Each line pairs an `item_id` with a `qty` of at least 1, and
        the sale must contain at least one line".
        PRD §2.8: "Required fields present, types valid, enum members valid,
        quantities at least 1, amounts non-negative" — reported as
        `ERR_INVALID_REQUEST`.

        Design: Difficulty/boundary_precision_check/sale_zero_quantity_rejected
        """
        cashier, item = self._setup()
        resp = api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "lines": [{"item_id": item["id"], "qty": 0}],
             "tendered_cents": 1000}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        item_now = get_success_data(api.get_item(item["id"], TREASURER))
        assert item_now["stock_on_hand"] == 10, "the rejected sale leaves stock untouched"

    def test_negative_quantity_rejected(self, api):
        """PRD §3.7: "Each line pairs an `item_id` with a `qty` of at least 1".
        PRD §2.8: "quantities at least 1, amounts non-negative" — `ERR_INVALID_REQUEST`.

        Design: Difficulty/boundary_precision_check/sale_zero_quantity_rejected
        """
        cashier, item = self._setup()
        resp = api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "lines": [{"item_id": item["id"], "qty": -1}],
             "tendered_cents": 1000}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        item_now = get_success_data(api.get_item(item["id"], TREASURER))
        assert item_now["stock_on_hand"] == 10


class TestItemRestockAndDisable:
    def test_restock_disable_sale_rejected_still_queryable(self, api):
        """PRD §3.7: "a `restock_qty` in the update adds to `stock_on_hand`".
        PRD §3.7: "An inactive item cannot be sold (`ERR_ITEM_INACTIVE`) but remains
        queryable, and the item list can be filtered by `is_active`, which is how the
        soft-disable stays reversible."
        PRD §2.8: tier-10 item-active failures precede tier-12 cashier-placement
        failures ("the earliest failing tier wins").

        Design: Corner/endpoints/item_restock_and_disable_then_sale_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        item = create_item(sku="SKU-OLD", name="Old Stock", unit_price_cents=500,
                           unit_cost_cents=100, stock_on_hand=10)
        _, vol_id = approve_application(full_name="Cash Caz", email="cz@x.org")

        restocked = validate_success(api.update_item(item["id"], {"restock_qty": 5}, TREASURER))
        assert restocked["stock_on_hand"] == 15, "10 + restock_qty 5"

        disabled = validate_success(api.update_item(item["id"], {"is_active": False}, TREASURER))
        assert disabled["is_active"] is False

        resp = api.create_sale(
            {"cashier_volunteer_id": vol_id,
             "lines": [{"item_id": item["id"], "qty": 1}],
             "tendered_cents": 500}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_ITEM_INACTIVE)

        fetched = get_success_data(api.get_item(item["id"], TREASURER))
        assert fetched["stock_on_hand"] == 15, "the rejected sale decrements nothing"
        assert fetched["is_active"] is False, "soft-disable keeps the row queryable"


class TestCashierPlacementGate:
    def test_cashier_not_gift_shop_placed_rejected(self, api):
        """PRD §3.7: "The cashier must be an `ACTIVE` volunteer holding an `ACCEPTED`
        placement whose role category is `GIFT_SHOP`
        (`ERR_CASHIER_NOT_GIFT_SHOP_PLACED`)."

        Design: Corner/errors/cashier_not_gift_shop_placed_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        ctx = create_active_volunteer(dept, role, request, full_name="Cash Cara",
                                      email="ca@x.org")
        item = create_item(sku="SKU-1", name="Balloon", unit_price_cents=500,
                           unit_cost_cents=100, stock_on_hand=10)

        resp = api.create_sale(
            {"cashier_volunteer_id": ctx["volunteer_id"],
             "lines": [{"item_id": item["id"], "qty": 1}],
             "tendered_cents": 500}, make_volunteer_headers(ctx["volunteer_id"]))
        validate_error(resp, ApiErrorId.ERR_CASHIER_NOT_GIFT_SHOP_PLACED)
        item_now = get_success_data(api.get_item(item["id"], TREASURER))
        assert item_now["stock_on_hand"] == 10


class TestStockAndTender:
    def test_insufficient_stock_and_insufficient_tender(self, api):
        """PRD §3.7: "a line quantity above the item's `stock_on_hand` fails with
        `ERR_INSUFFICIENT_STOCK`."
        PRD §3.7: "`tendered_cents` must cover the total (`ERR_INSUFFICIENT_TENDER`),
        and `change_cents` is the tendered amount minus the total."

        Design: Corner/errors/insufficient_stock_and_tender
        """
        set_clock("2026-08-01T00:00:00Z")
        cashier = create_gift_shop_cashier(full_name="Cashier Kim", email="ck2@x.org")
        item = create_item(sku="SKU-2", name="Mug", unit_price_cents=1000,
                           unit_cost_cents=300, stock_on_hand=2)

        resp = api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "lines": [{"item_id": item["id"], "qty": 5}],
             "tendered_cents": 5000}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)

        resp = api.create_sale(
            {"cashier_volunteer_id": cashier["volunteer_id"],
             "lines": [{"item_id": item["id"], "qty": 2}],
             "tendered_cents": 100}, TREASURER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TENDER)

        item_now = get_success_data(api.get_item(item["id"], TREASURER))
        assert item_now["stock_on_hand"] == 2, "both rejections leave stock untouched"
