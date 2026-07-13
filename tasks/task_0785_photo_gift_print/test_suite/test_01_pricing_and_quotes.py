"""Pricing: unit price, volume tiers, promo rounding, shipping, and quote validation."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_quote_payload,
    create_customer, create_template, create_project, create_promotion,
    make_customer_headers,
)


def _draft_project(template_overrides=None):
    """Customer + template + DRAFT project (a quote needs no approval). Returns (proj, headers)."""
    cust = create_customer()
    h = make_customer_headers(cust["id"])
    tmpl = create_template(**(template_overrides or {}))
    proj = create_project(cust, tmpl, headers=h)
    return proj, h


class TestUnitPriceAndSubtotal:
    """Combinatorial pricing: base + finish surcharge, then a quantity-selected volume tier."""

    def test_glossy_unit_price_includes_finish_surcharge(self, api):
        """PRD 3.4: "The unit price is the template's base_unit_price_cents plus a finish
        surcharge determined by the chosen finish: MATTE adds nothing, GLOSSY adds 300 cents,
        LINEN adds 700 cents, LAY_FLAT adds 1200 cents, and METAL adds 2500 cents."

        Design: Difficulty/combinatorial_formula/line_subtotal_tiered_finish_quantity_mode_a
        """
        proj, h = _draft_project({"base_unit_price_cents": 1000, "allowed_finishes": ["MATTE", "GLOSSY"]})
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=10, finish="GLOSSY"), h), 200
        )
        assert data["unit_price_cents"] == 1300, f"1000 base + 300 GLOSSY, got {data['unit_price_cents']}"

    def test_glossy_qty10_subtotal_applies_five_percent_tier(self, api):
        """PRD 3.4: "at least 10 but fewer than 25 earns 5 percent"
        PRD 3.4: "The subtotal_cents is the pre-discount amount minus that volume-discount amount."

        Design: Difficulty/combinatorial_formula/line_subtotal_tiered_finish_quantity_mode_a
        """
        proj, h = _draft_project({"base_unit_price_cents": 1000, "allowed_finishes": ["MATTE", "GLOSSY"]})
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=10, finish="GLOSSY"), h), 200
        )
        # unit 1300 * 10 = 13000; tier 0.05 -> round(650)=650 discount -> subtotal 12350
        assert data["subtotal_cents"] == 12350, f"expected 12350, got {data['subtotal_cents']}"


class TestPromoRounding:
    """Promo discount is rounded per-promo then summed (not sum-then-round)."""

    def test_two_seven_percent_promos_round_each_then_sum(self, api):
        """PRD 3.4: "Each promotion's raw discount is individually rounded half up to whole cents
        before any summing — the individual rounded discounts are then summed, and this
        per-promo-then-sum ordering is mandatory because summing first and rounding once would
        yield a different number of cents."

        Design: Difficulty/combinatorial_formula/promo_discount_round_per_promo_then_sum_mode_b
        """
        proj, h = _draft_project({"product_type": "CARD", "base_unit_price_cents": 333,
                                  "surface_count": 1, "production_days": 1, "min_photos": 1, "max_photos": 4})
        create_promotion("SEVENA", "PERCENT", 7, min_subtotal_cents=0, stackable=True, per_customer_limit=5)
        create_promotion("SEVENB", "PERCENT", 7, min_subtotal_cents=0, stackable=True, per_customer_limit=5)
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=1, finish="MATTE",
                                                               promo_codes=["SEVENA", "SEVENB"]), h), 200
        )
        # round(333*7/100)=round(23.31)=23 each; 23+23=46 (NOT round(46.62)=47)
        assert data["subtotal_cents"] == 333, f"expected subtotal 333, got {data['subtotal_cents']}"
        assert data["discount_cents"] == 46, f"per-promo-then-sum must give 46, got {data['discount_cents']}"

    def test_percent_promo_raw_computed_against_original_subtotal(self, api):
        """PRD 3.4: "a PERCENT promotion's raw discount is the subtotal multiplied by its value
        divided by 100"

        Design: Difficulty/combinatorial_formula/promo_discount_round_per_promo_then_sum_mode_b
        """
        proj, h = _draft_project({"product_type": "CARD", "base_unit_price_cents": 333,
                                  "surface_count": 1, "production_days": 1, "min_photos": 1, "max_photos": 4})
        create_promotion("SEVENA", "PERCENT", 7, min_subtotal_cents=0, stackable=True, per_customer_limit=5)
        create_promotion("SEVENB", "PERCENT", 7, min_subtotal_cents=0, stackable=True, per_customer_limit=5)
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=1, finish="MATTE",
                                                               promo_codes=["SEVENA", "SEVENB"]), h), 200
        )
        # Each promo is 23 cents against the ORIGINAL 333 subtotal (not a running balance): 23+23=46.
        assert data["discount_cents"] == 46, f"expected 46, got {data['discount_cents']}"


class TestVolumeTierBoundary:
    """The 0.12 tier engages at quantity >= 25 exactly; qty 24 stays on the 0.05 tier."""

    def test_qty25_engages_twelve_percent_tier(self, api):
        """PRD 3.4: "at least 25 but fewer than 50 earns 12 percent"

        Design: Difficulty/boundary_precision_check/volume_tier_boundary_qty25_vs_qty24
        """
        proj, h = _draft_project({"base_unit_price_cents": 1000, "max_photos": 100})
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=25, finish="MATTE"), h), 200
        )
        # 1000*25=25000; 0.12 tier -> 3000 discount -> subtotal 22000
        assert data["subtotal_cents"] == 22000, f"qty25 -> 22000, got {data['subtotal_cents']}"

    def test_qty24_stays_on_five_percent_tier(self, api):
        """PRD 3.4: "at least 10 but fewer than 25 earns 5 percent"

        Design: Difficulty/boundary_precision_check/volume_tier_boundary_qty25_vs_qty24
        """
        proj, h = _draft_project({"base_unit_price_cents": 1000, "max_photos": 100})
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=24, finish="MATTE"), h), 200
        )
        # 1000*24=24000; 0.05 tier -> 1200 discount -> subtotal 22800
        assert data["subtotal_cents"] == 22800, f"qty24 -> 22800, got {data['subtotal_cents']}"


class TestShippingAndTransit:
    """FREE_SHIP zeroes shipping; EXPRESS applies its base charge and transit days."""

    def test_free_ship_promo_zeros_shipping(self, api):
        """PRD 3.4: "If any applicable promotion is of kind FREE_SHIP, the shipping_cents is 0;
        otherwise it equals the base charge."

        Design: Corner/calculations/corner_free_ship_promo_zeros_shipping
        """
        proj, h = _draft_project({"base_unit_price_cents": 1000})
        create_promotion("FREESHIP", "FREE_SHIP", 0, min_subtotal_cents=0, stackable=True, per_customer_limit=9)
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=10, finish="MATTE",
                                                               promo_codes=["FREESHIP"]), h), 200
        )
        assert data["shipping_cents"] == 0, f"FREE_SHIP -> 0 shipping, got {data['shipping_cents']}"
        # subtotal 9500, no discount, shipping 0 -> total 9500
        assert data["total_cents"] == 9500, f"expected total 9500, got {data['total_cents']}"

    def test_express_shipping_and_estimated_promised_date(self, api):
        """PRD 3.4: "Shipping starts from a base charge determined by ship_method: 799 cents for
        STANDARD and 1999 cents for EXPRESS."
        PRD 3.4: "Transit adds 5 calendar days for STANDARD and 2 for EXPRESS."

        Design: Corner/calculations/corner_express_shipping_and_transit
        """
        proj, h = _draft_project({"base_unit_price_cents": 1000, "production_days": 3})
        data = validate_success(
            api.quote_project(proj["id"], create_quote_payload(quantity=5, finish="MATTE", ship_method="EXPRESS"), h), 200
        )
        assert data["shipping_cents"] == 1999, f"EXPRESS -> 1999, got {data['shipping_cents']}"
        # clock default 2026-03-01 + prod 3 + surge 0 (quote) + transit 2 = 2026-03-06
        assert data["promised_ship_date"] == "2026-03-06", f"expected 2026-03-06, got {data['promised_ship_date']}"


class TestQuoteValidation:
    """Body well-formedness on the quote endpoint."""

    def test_finish_not_in_allowed_finishes_rejected(self, api):
        """PRD 2.8: "Only then is the request body inspected for well-formedness — required fields
        present, enum values legal, chosen finish within the template's offered set, and quantities
        positive — with any failure reported as ERR_VALIDATION (HTTP 422)."

        Design: Corner/entities/corner_finish_not_in_allowed_finishes_rejected
        """
        proj, h = _draft_project({"product_type": "CANVAS", "base_unit_price_cents": 4000,
                                  "surface_count": 1, "production_days": 5, "allowed_finishes": ["MATTE"],
                                  "min_photos": 1, "max_photos": 1})
        res = api.quote_project(proj["id"], create_quote_payload(quantity=1, finish="METAL"), h)
        validate_error(res, "ERR_VALIDATION", 422)

    def test_two_codes_one_non_stackable_rejected(self, api):
        """PRD 3.5: "If more than one promo code is supplied, every named promotion must be
        stackable; if any one is not, the whole request is rejected with ERR_PROMO_NOT_STACKABLE."

        Design: Corner/validations/corner_promo_not_stackable_rejected
        """
        proj, h = _draft_project({"base_unit_price_cents": 1000})
        create_promotion("STACK", "PERCENT", 5, min_subtotal_cents=0, stackable=True, per_customer_limit=9)
        create_promotion("SOLO", "PERCENT", 5, min_subtotal_cents=0, stackable=False, per_customer_limit=9)
        res = api.quote_project(
            proj["id"], create_quote_payload(quantity=10, finish="MATTE", promo_codes=["STACK", "SOLO"]), h
        )
        validate_error(res, "ERR_PROMO_NOT_STACKABLE", 409)
