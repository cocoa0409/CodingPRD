"""Quote pricing calculations: tiered base, line items, discount-then-tax rounding,
footprint-tier boundary, drain free-threshold, and the two-domain dual-variant contrast
(quote cost vs inspection severity).

Covers Difficulty queue: dual_variant_calc, combinatorial_formula (nested rounding),
boundary_precision_check (footprint tier). Covers Corner queue: drain under-free-threshold.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    assert_quote,
    create_homeowner, create_job, create_finalized_inspection,
    create_quote_payload, create_inspection_payload,
    TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]


class TestQuotePricingDualVariant:
    def test_quote_total_and_subtotal_for_full_scope_spring10(self, api):
        """PRD §3.4: "a footprint from 801 through 1500 square feet bases at 400,000 cents".
        PRD §3.4: "If the vapor barrier is included, it adds 180 cents per square foot of
        `footprint_sqft`" and "If the sump is included, it adds a flat 120,000 cents."
        PRD §3.4: "the first 20 linear feet are free, so the billable footage is the drain
        length minus 20 but never below zero, and the billable footage is charged at 4,500
        cents per foot."
        PRD §3.4: "`SPRING10` is 10 percent ... The discount amount is the subtotal
        multiplied by that percentage, rounded half up to whole cents". "Tax is then
        computed on the discounted subtotal ... at a rate of 7 percent, rounded half up".

        Design: Difficulty/dual_variant_calc/quote_pricing_vs_assessment_severity_distinct_domains
        """
        # footprint 1000 -> base 400000; vapor 180*1000=180000; sump 120000; backup 90000;
        # drain (50-20)*4500=135000 => subtotal 925000; SPRING10 disc 92500;
        # discounted 832500; tax round(832500*0.07)=58275; total 890775.
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=1000, structure_type="CRAWLSPACE")
        res = api.create_quote(job["id"], create_quote_payload(
            includes_vapor_barrier=True, includes_sump=True, includes_drain=True,
            includes_battery_backup=True, drain_linear_ft=50, discount_code="SPRING10"), EST)
        quote = validate_success(res, 201)
        assert_quote(quote)
        assert quote["subtotal_cents"] == 925000
        assert quote["total_cents"] == 890775

    def test_inspection_standing_water_override_forces_moderate(self, api):
        """PRD §3.2: "if standing water was observed and there was at least one structural
        finding and the base mapping landed at `LOW` or `NONE`, the severity is forced up
        to `MODERATE`."

        Design: Difficulty/dual_variant_calc/quote_pricing_vs_assessment_severity_distinct_domains
        """
        # moisture 50 (<60, +0) + 1 structural (1*2=2) => base score 2 => LOW;
        # standing_water true + >=1 structural => override forces MODERATE.
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=1000, structure_type="CRAWLSPACE")
        draft = get_success_data(api.create_inspection(
            job["id"], create_inspection_payload(moisture_pct=50, structural_findings_count=1,
                                                 standing_water=True), INS))
        final = validate_success(api.finalize_inspection(job["id"], draft["id"], INS), 200)
        assert final["severity"] == "MODERATE"


class TestQuotePricingNestedRounding:
    def test_discount_then_tax_rounding_order_senior15(self, api):
        """PRD §3.4: "a footprint above 1500 square feet bases at 600,000 cents."
        PRD §3.4: "If the vapor barrier is included, it adds 180 cents per square foot"
        and "If the dehumidifier is included, it adds a flat 165,000 cents."
        PRD §3.4: "`SENIOR15` is 15 percent ... The discount amount is the subtotal
        multiplied by that percentage, rounded half up to whole cents, and recorded as
        `discount_cents`. ... Tax is then computed on the discounted subtotal — not on the
        pre-discount subtotal — at a rate of 7 percent, rounded half up to whole cents, and
        recorded as `tax_cents`. The total is the discounted subtotal plus the tax."

        Design: Difficulty/combinatorial_formula/quote_pricing_nested_rounding_order_discount_then_tax
        """
        # footprint 2000 -> base 600000; vapor 180*2000=360000; dehu 165000 => subtotal 1125000;
        # SENIOR15 disc round(1125000*0.15)=168750; discounted 956250;
        # tax round(956250*0.07)=66937.5 -> 66938 (half-up); total 1023188.
        ho = create_homeowner(credit_band="NEAR_PRIME")
        job = create_job(ho["id"], footprint_sqft=2000, structure_type="COMBINED")
        res = api.create_quote(job["id"], create_quote_payload(
            includes_vapor_barrier=True, includes_dehumidifier=True,
            discount_code="SENIOR15"), EST)
        quote = validate_success(res, 201)
        assert quote["subtotal_cents"] == 1125000
        assert quote["discount_cents"] == 168750
        assert quote["tax_cents"] == 66938
        assert quote["total_cents"] == 1023188


class TestFootprintTierBoundary:
    def test_footprint_800_selects_tier_1_base(self, api):
        """PRD §3.4: "a footprint of at most 800 square feet bases at 250,000 cents" and
        "If the sump is included, it adds a flat 120,000 cents."

        Design: Difficulty/boundary_precision_check/footprint_tier_boundary_800_vs_801
        """
        # footprint 800 -> base 250000; sump 120000 => subtotal 370000.
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=800, structure_type="CRAWLSPACE")
        res = api.create_quote(job["id"], create_quote_payload(includes_sump=True), EST)
        quote = validate_success(res, 201)
        assert quote["subtotal_cents"] == 370000

    def test_footprint_801_selects_tier_2_base(self, api):
        """PRD §3.4: "a footprint from 801 through 1500 square feet bases at 400,000 cents"
        and "If the sump is included, it adds a flat 120,000 cents."

        Design: Difficulty/boundary_precision_check/footprint_tier_boundary_800_vs_801
        """
        # footprint 801 -> base 400000; sump 120000 => subtotal 520000.
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=801, structure_type="CRAWLSPACE")
        res = api.create_quote(job["id"], create_quote_payload(includes_sump=True), EST)
        quote = validate_success(res, 201)
        assert quote["subtotal_cents"] == 520000


class TestDrainFreeThreshold:
    def test_drain_at_free_threshold_charges_zero(self, api):
        """PRD §3.4: "The drain charge applies only when the drain is included: the first
        20 linear feet are free, so the billable footage is the drain length minus 20 but
        never below zero, and the billable footage is charged at 4,500 cents per foot."
        PRD §3.4: "a footprint of at most 800 square feet bases at 250,000 cents".

        Design: Corner/entities/quote_create_drain_under_free_threshold_charges_zero_drain
        """
        # footprint 600 -> base 250000; drain billable max(0,20-20)=0 => subtotal 250000.
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        res = api.create_quote(job["id"], create_quote_payload(
            includes_drain=True, drain_linear_ft=20), EST)
        quote = validate_success(res, 201)
        assert quote["subtotal_cents"] == 250000
