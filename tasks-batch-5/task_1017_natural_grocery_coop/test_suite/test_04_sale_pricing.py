"""Line pricing: promotion resolution, working-member discount stacking rules,
weight/tare units, round-per-line-then-sum totals, and patronage eligibility."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fiscal_year, create_approved_vendor, create_product, create_posted_lot,
    create_open_register, create_working_member, create_active_member, open_sale, add_line,
    create_promotion_payload, TEST_USERS,
)

INVENTORY = TEST_USERS["inventory_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
COOP = TEST_USERS["coop_admin_headers"]


def _member_deal_working_member_sale(api, promo_price, member_only, deal_type):
    """Build an OPEN-year working-member member sale of a single product (base 500,
    non-taxable, qty 2) with an active promotion, and return the finalized sale."""
    create_fiscal_year()
    vendor = create_approved_vendor(name="V")
    product = create_product(vendor["id"], sku="TEA", name="Herbal Tea",
                             base_price_cents=500, reorder_point=0, reorder_qty=10,
                             is_taxable=False)
    get_success_data(api.create_promotion(
        create_promotion_payload(product["id"], deal_type=deal_type,
                                 promo_price_cents=promo_price, member_only=member_only,
                                 start_date="2026-06-01T00:00:00Z",
                                 end_date="2026-08-01T00:00:00Z"),
        INVENTORY))
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=200)
    member = create_working_member(full_name="Wren W", email="wren@x.com")
    register = create_open_register()
    sale = open_sale(register["id"], member_id=member["id"])
    add_line(sale["id"], product["id"], lot["id"], quantity=2)
    sale = validate_success(api.finalize_sale(sale["id"], CASHIER), 200)
    return member, sale


class TestMemberDealSuppressesWorkingDiscount:
    """A member-only deal blocks the working-member discount (PRD §3.4, §3.5)."""

    def test_member_deal_price_not_further_discounted(self, api):
        """PRD §3.5: "when the sale has a member who is a working member and the applied
        price did not come from a member-only deal, the unit price is reduced by the
        working-member discount of ten percent". The applied price came from a
        member-only deal, so the unit stays 400 and two units total 800.

        Design: Difficulty/combinatorial_formula/cf_mode_a_member_deal_suppresses_working_discount
        """
        _member, sale = _member_deal_working_member_sale(
            api, promo_price=400, member_only=True, deal_type="MEMBER_DEAL")
        assert sale["subtotal_cents"] == 800
        assert sale["tax_total_cents"] == 0
        assert sale["total_cents"] == 800

    def test_member_is_working_member_yet_discount_suppressed(self, api):
        """PRD §3.5: "The discount stacks on the shelf price and on an `AD` promotion,
        but never on a `MEMBER_DEAL`." The member qualifies as a working member, proving
        the suppression is caused by the member-only deal, not a missing standing.

        Design: Difficulty/combinatorial_formula/cf_mode_a_member_deal_suppresses_working_discount
        """
        member, sale = _member_deal_working_member_sale(
            api, promo_price=400, member_only=True, deal_type="MEMBER_DEAL")
        assert member["is_working_member"] is True
        assert sale["subtotal_cents"] == 800


class TestRoundPerLineThenSum:
    """Two taxable lines each round tax independently before summing (PRD §2.5, §3.5)."""

    def _two_line_taxable_sale(self, api):
        vendor = create_approved_vendor(name="V")
        product = create_product(vendor["id"], sku="SOAP", name="Castile Soap",
                                 base_price_cents=706, reorder_point=0, reorder_qty=10,
                                 is_taxable=True)
        lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=300)
        register = create_open_register()
        sale = open_sale(register["id"])
        add_line(sale["id"], product["id"], lot["id"], quantity=1)
        add_line(sale["id"], product["id"], lot["id"], quantity=1)
        return validate_success(api.finalize_sale(sale["id"], CASHIER), 200)

    def test_tax_total_is_per_line_rounded_then_summed(self, api):
        """PRD §3.5: "This round-per-line-then-sum order is deliberate and must not be
        replaced by summing raw values and rounding once." Each 706 line taxes to 56,
        summing to 112 (not 113 from 1412*0.08).

        Design: Difficulty/combinatorial_formula/cf_mode_b_round_per_line_then_sum_tax
        """
        sale = self._two_line_taxable_sale(api)
        assert sale["tax_total_cents"] == 112

    def test_subtotal_and_total_sum_prerounded_lines(self, api):
        """PRD §3.5: "The `subtotal_cents` is the sum of `line_subtotal_cents` across
        lines, the `tax_total_cents` is the sum of `line_tax_cents`, the `total_cents`
        is the subtotal plus the tax total".

        Design: Difficulty/combinatorial_formula/cf_mode_b_round_per_line_then_sum_tax
        """
        sale = self._two_line_taxable_sale(api)
        assert sale["subtotal_cents"] == 1412
        assert sale["total_cents"] == 1524


def test_weight_line_prices_net_kilograms_after_tare(api):
    """PRD §3.5: "For a `WEIGHT` product, the `net_weight_grams` is the
    `gross_weight_grams` minus the product's `tare_grams`, and `units` is that net-gram
    figure divided by 1000 to yield kilograms."

    Design: Corner/entities/computed_weight_tare_line_pricing
    """
    vendor = create_approved_vendor(name="V")
    product = create_product(vendor["id"], sku="BULKNUT", name="Bulk Almonds",
                             department="BULK", unit_type="WEIGHT", base_price_cents=1000,
                             tare_grams=50, reorder_point=0, reorder_qty=100)
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=100, unit_cost_cents=400)
    register = create_open_register()
    sale = open_sale(register["id"])
    sale = add_line(sale["id"], product["id"], lot["id"], gross_weight_grams=550)
    assert sale["subtotal_cents"] == 500
    assert sale["total_cents"] == 500


def test_ad_promo_stacks_with_working_member_discount(api):
    """PRD §3.5: "The discount stacks on the shelf price and on an `AD` promotion, but
    never on a `MEMBER_DEAL`." AD promo 450 then times nine-tenths yields 405.

    Design: Corner/calculations/ad_promo_stacks_working_member_discount
    """
    create_fiscal_year()
    vendor = create_approved_vendor(name="V")
    product = create_product(vendor["id"], sku="COF", name="Fair Coffee",
                             base_price_cents=500, reorder_point=0, reorder_qty=20,
                             is_taxable=False)
    get_success_data(api.create_promotion(
        create_promotion_payload(product["id"], deal_type="AD", promo_price_cents=450,
                                 member_only=False, start_date="2026-06-01T00:00:00Z",
                                 end_date="2026-08-01T00:00:00Z"),
        INVENTORY))
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=20, unit_cost_cents=200)
    member = create_working_member(full_name="Work M", email="workm@x.com")
    register = create_open_register()
    sale = open_sale(register["id"], member_id=member["id"])
    sale = add_line(sale["id"], product["id"], lot["id"], quantity=1)
    assert sale["subtotal_cents"] == 405


def test_prepared_food_excluded_from_patronage(api):
    """PRD §3.5: "Finally, `is_patronage_eligible` on the line is true exactly when the
    product is not prepared food." PRD §3.5: "the `patronage_eligible_cents` is the sum
    of `line_subtotal_cents` over only those lines that are patronage-eligible."

    Design: Corner/calculations/prepared_food_excluded_from_patronage
    """
    create_fiscal_year()
    vendor = create_approved_vendor(name="Deli Co")
    product = create_product(vendor["id"], sku="SANDW", name="Deli Sandwich",
                             department="CAFE_DELI", base_price_cents=700, reorder_point=0,
                             reorder_qty=20, is_taxable=True, is_prepared_food=True)
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=20, unit_cost_cents=300)
    member = create_active_member(full_name="Deli M", email="delim@x.com")
    register = create_open_register()
    sale = open_sale(register["id"], member_id=member["id"])
    add_line(sale["id"], product["id"], lot["id"], quantity=1)
    sale = validate_success(api.finalize_sale(sale["id"], CASHIER), 200)
    assert sale["subtotal_cents"] == 700
    assert sale["patronage_eligible_cents"] == 0

    member_after = validate_success(api.get_member(member["id"], COOP), 200)
    assert member_after["patronage_cents_ytd"] == 0


def test_line_totals_visible_immediately_in_add_response(api):
    """PRD §3.5: "Whenever the lines change — on every line addition and again at
    finalize — the sale's running totals are refreshed by summing already-rounded line
    values, with no re-rounding at the sale level."

    Design: Corner/consistency_model/immediate_line_totals_visible_same_request
    """
    vendor = create_approved_vendor(name="V")
    product = create_product(vendor["id"], sku="PAS", name="Pasta",
                             base_price_cents=250, reorder_point=0, reorder_qty=10)
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=100)
    register = create_open_register()
    sale = open_sale(register["id"])
    sale = add_line(sale["id"], product["id"], lot["id"], quantity=2)
    assert sale["subtotal_cents"] == 500


def test_each_line_missing_quantity_rejected(api):
    """PRD §3.5: "Supplying the wrong measure for the product's unit type — a weight
    item with no gross weight, or an each item with no quantity — is rejected with
    `ERR_LINE_UNIT_INPUT_INVALID`."

    Design: Corner/validations/line_unit_input_invalid_rejected
    """
    vendor = create_approved_vendor(name="V")
    product = create_product(vendor["id"], sku="EGG", name="Eggs",
                             base_price_cents=400, reorder_point=0, reorder_qty=10)
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=200)
    register = create_open_register()
    sale = open_sale(register["id"])
    res = api.add_sale_line(sale["id"],
                            {"product_id": product["id"], "inventory_lot_id": lot["id"]},
                            CASHIER)
    validate_error(res, "ERR_LINE_UNIT_INPUT_INVALID", expected_status=400)
