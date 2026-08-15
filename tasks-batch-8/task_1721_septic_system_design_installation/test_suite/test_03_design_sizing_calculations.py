"""Design sizing derivations: dual flow variants, rounding order, tank catalog,
soil rates, shallow-layer threshold, and submit-time re-derivation."""
from test_helpers import (
    add_design,
    add_science,
    add_site,
    add_variance_request,
    api_client,
    approve_variance,
    assert_system_design,
    setup_site_with_science,
    submit_design,
    validate_success,
)


class TestDualVariantFlow:
    def test_book_flow_variant_sizing(self, api):
        """PRD section 3.3: "The **design daily flow** is the bedroom count
        multiplied by 150 gallons per bedroom per day; when the site's
        `high_water_table` flag is true, that product is multiplied by 1.5 before
        anything else happens."
        PRD section 3.3: "The **required absorption area** divides the flow by the
        soil application rate implied by the pinned evaluation's `soil_class` —
        1.20 gallons per day per square foot for `SAND`, 0.80 for `LOAM`, 0.50 for
        `CLAY_LOAM`, and 0.30 for `CLAY`."

        Design: Difficulty/dual_variant_calc/book_vs_reduced_flow_on_system_design_sizing
        """
        ctx = setup_site_with_science(soil_class="LOAM", limiting_layer_inches=36)
        da = add_design(ctx, bedroom_count=3, system_type="GRAVITY")
        assert_system_design(da)
        assert float(da["design_daily_flow_gpd"]) == 450.0, "3 bedrooms * 150 gpd"
        assert da["required_absorption_area_sqft"] == 563, (
            "book variant: ceil(450 / 0.80) = ceil(562.5) = 563")
        assert da["tank_capacity_gal"] == 1000
        assert da["reserve_area_sqft"] == 563

    def test_reduced_flow_variant_sizing_with_tank_asymmetry(self, api):
        """PRD section 3.3: "When an `APPROVED` variance request of relief kind
        `AREA_REDUCTION` exists for the design, the absorption-area leg alone
        substitutes a reduced figure of 120 gallons per bedroom per day for the
        standard 150. The design's `design_daily_flow_gpd` and the tank-sizing leg
        both continue to use the book figure of 150, so the two legs deliberately
        diverge within a single design."

        Design: Difficulty/dual_variant_calc/book_vs_reduced_flow_on_system_design_sizing
        """
        ctx = setup_site_with_science(soil_class="LOAM", limiting_layer_inches=36)
        db = add_design(ctx, bedroom_count=3, system_type="GRAVITY")
        variance = add_variance_request(ctx, db["id"], relief_kind="AREA_REDUCTION")
        approve_variance(ctx, variance["id"])
        submitted = submit_design(ctx, db["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["required_absorption_area_sqft"] == 450, (
            "reduced variant: ceil((3*120) / 0.80) = 450")
        assert float(submitted["design_daily_flow_gpd"]) == 450.0, (
            "the flow figure itself stays on the book variant")
        assert submitted["tank_capacity_gal"] == 1000, (
            "tank leg stays on book flow despite the approved AREA_REDUCTION")
        assert submitted["reserve_area_sqft"] == 450


class TestRoundingOrder:
    def test_high_water_single_terminal_ceil_flow_and_area(self, api):
        """PRD section 3.3: "The final `required_absorption_area_sqft` is the
        result rounded up to the next whole square foot, with that ceiling applied
        exactly once at the very end of the chain: no intermediate rounding occurs
        between the surcharge, the division, and the shallow-layer multiplier, and
        rounding the pre-multiplier quotient first produces a different, incorrect
        integer."

        Design: Difficulty/combinatorial_formula/absorption_area_single_terminal_ceil_vs_per_step_ceil
        """
        ctx = setup_site_with_science(
            soil_class="LOAM", limiting_layer_inches=20, high_water_table=True,
            minutes_per_inch=5.0, test_pit_count=3)
        d = add_design(ctx, bedroom_count=1, system_type="MOUND")
        assert float(d["design_daily_flow_gpd"]) == 225.0, "1 * 150 * 1.5"
        assert d["required_absorption_area_sqft"] == 352, (
            "single terminal ceil: ceil(225/0.80*1.25) = ceil(351.5625) = 352; "
            "a per-step ceil would produce 353")

    def test_reserve_area_reads_post_ceil_area(self, api):
        """PRD section 3.3: "`reserve_area_sqft` equals the final, post-ceiling
        `required_absorption_area_sqft` multiplied by the reserve fraction of 1.0,
        rounded half-up to a whole square foot."

        Design: Difficulty/combinatorial_formula/absorption_area_single_terminal_ceil_vs_per_step_ceil
        """
        ctx = setup_site_with_science(
            soil_class="LOAM", limiting_layer_inches=20, high_water_table=True,
            minutes_per_inch=5.0, test_pit_count=3)
        d = add_design(ctx, bedroom_count=1, system_type="MOUND")
        assert d["reserve_area_sqft"] == 352, (
            "reserve reads the post-ceil area (352), never the pre-ceiling quotient")
        assert d["reserve_area_sqft"] == d["required_absorption_area_sqft"]


class TestTankCatalogStepUp:
    def test_tank_exact_multiple_stays_on_catalog_size(self, api):
        """PRD section 3.3: "The raw requirement is then stepped up to the smallest
        catalog size greater than or equal to it, chosen from 750, 1000, 1250,
        1500, 2000, 2500, 3000, 4000, and 5000 gallons; a raw requirement landing
        exactly on a catalog size keeps that size."

        Design: Difficulty/combinatorial_formula/tank_catalog_stepup_with_exact_multiple_boundary
        """
        ctx = setup_site_with_science(soil_class="LOAM", limiting_layer_inches=36)
        d5 = add_design(ctx, bedroom_count=5, system_type="GRAVITY")
        assert d5["tank_capacity_gal"] == 1500, (
            "raw 5*150*2.0 = 1500 exactly; an exact multiple keeps the catalog size")

    def test_tank_raw_between_catalog_sizes_steps_up(self, api):
        """PRD section 3.3: "The raw requirement is then stepped up to the smallest
        catalog size greater than or equal to it, chosen from 750, 1000, 1250,
        1500, 2000, 2500, 3000, 4000, and 5000 gallons; a raw requirement landing
        exactly on a catalog size keeps that size."

        Design: Difficulty/combinatorial_formula/tank_catalog_stepup_with_exact_multiple_boundary
        """
        ctx = setup_site_with_science(soil_class="LOAM", limiting_layer_inches=36)
        d4 = add_design(ctx, bedroom_count=4, system_type="GRAVITY")
        assert d4["tank_capacity_gal"] == 1250, "raw 4*150*2.0 = 1200 steps up to 1250"


class TestSoilRatesAndShallowLayer:
    def test_absorption_area_correct_result_per_soil_class(self, api):
        """PRD section 3.3: "The **required absorption area** divides the flow by
        the soil application rate implied by the pinned evaluation's `soil_class`
        — 1.20 gallons per day per square foot for `SAND`, 0.80 for `LOAM`, 0.50
        for `CLAY_LOAM`, and 0.30 for `CLAY`."

        Design: Corner/calculations/absorption_area_correct_result_per_soil_class
        """
        ctx = setup_site_with_science(soil_class="SAND", limiting_layer_inches=48,
                                      minutes_per_inch=5.0, test_pit_count=2)
        s_sand = ctx.s
        add_site(ctx, parcel_id="P-LOAM", address_line="2 Loam Ln", attr="s_loam")
        add_science(ctx, site=ctx.s_loam, soil_class="LOAM", limiting_layer_inches=48,
                    minutes_per_inch=12.0, test_pit_count=2,
                    eval_attr="e_loam", perc_attr="pt_loam")
        add_site(ctx, parcel_id="P-CLAY", address_line="3 Clay Ln", attr="s_clay")
        add_science(ctx, site=ctx.s_clay, soil_class="CLAY", limiting_layer_inches=48,
                    minutes_per_inch=60.0, test_pit_count=2,
                    eval_attr="e_clay", perc_attr="pt_clay")

        d_sand = add_design(ctx, bedroom_count=4, site=s_sand)  # pins ctx.e1/pt1 (SAND)
        d_loam = add_design(ctx, bedroom_count=4, site=ctx.s_loam,
                            eval_attr="e_loam", perc_attr="pt_loam")
        d_clay = add_design(ctx, bedroom_count=4, site=ctx.s_clay,
                            eval_attr="e_clay", perc_attr="pt_clay")
        assert d_sand["required_absorption_area_sqft"] == 500, "600 / 1.20"
        assert d_loam["required_absorption_area_sqft"] == 750, "600 / 0.80"
        assert d_clay["required_absorption_area_sqft"] == 2000, "600 / 0.30"

    def test_shallow_layer_threshold_24_inclusive_of_multiplier_exclusion(self, api):
        """PRD section 3.3: "If the pinned evaluation's `limiting_layer_inches` is
        less than 24 inches, the quotient is multiplied by 1.25 for the
        shallow-layer penalty."

        Design: Corner/calculations/shallow_layer_threshold_24_inclusive_of_multiplier_exclusion
        """
        ctx = setup_site_with_science(soil_class="LOAM", limiting_layer_inches=24,
                                      test_pit_count=2)
        s24 = ctx.s
        add_site(ctx, parcel_id="P-23", address_line="23 Bench Rd", attr="s23")
        add_science(ctx, site=ctx.s23, soil_class="LOAM", limiting_layer_inches=23,
                    test_pit_count=2, eval_attr="e23", perc_attr="pt23")
        d24 = add_design(ctx, bedroom_count=3, site=s24)
        d23 = add_design(ctx, bedroom_count=3, site=ctx.s23,
                         eval_attr="e23", perc_attr="pt23")
        assert d24["required_absorption_area_sqft"] == 563, (
            "limiting layer exactly 24 does NOT trigger the multiplier (strict <)")
        assert d23["required_absorption_area_sqft"] == 704, (
            "23 inches: ceil(450/0.80*1.25) = ceil(703.125) = 704")


class TestComputedFieldsAndReDerivation:
    def test_design_computed_fields_ignore_client_input_and_match_formula(self, api):
        """PRD section 3.3: "Four sizing figures are computed at creation and
        re-derived every time the design is submitted, because variance context
        may have changed since creation."
        PRD section 3.3: "The **tank capacity** always derives from the book flow
        — bedroom count times 150 gallons per day, regardless of any approved
        area-reduction variance — multiplied by a retention of 2.0 days."

        Design: Corner/entities/design_computed_fields_ignore_client_input_and_match_formula
        """
        ctx = setup_site_with_science(soil_class="CLAY", limiting_layer_inches=48,
                                      minutes_per_inch=60.0, test_pit_count=6)
        d = add_design(ctx, bedroom_count=6, system_type="GRAVITY")
        assert_system_design(d)
        assert float(d["design_daily_flow_gpd"]) == 900.0, "6 * 150, no surcharge"
        assert d["required_absorption_area_sqft"] == 3000, "900 / 0.30, exact"
        assert d["tank_capacity_gal"] == 2000, "raw 1800 steps up to catalog 2000"
        assert d["reserve_area_sqft"] == 3000

    def test_variant_reconciliation_on_submit_rederives_sizing(self, api):
        """PRD section 3.3: "Four sizing figures are computed at creation and
        re-derived every time the design is submitted, because variance context
        may have changed since creation."
        PRD section 3.4: "A successful submit also re-derives the four sizing
        figures of §3.3 against current variance context."

        Design: Corner/calculations/variant_reconciliation_on_submit_rederives_sizing
        """
        ctx = setup_site_with_science(soil_class="LOAM", limiting_layer_inches=36)
        d = add_design(ctx, bedroom_count=3, system_type="GRAVITY")
        assert d["required_absorption_area_sqft"] == 563, "book variant at creation"
        variance = add_variance_request(ctx, d["id"], relief_kind="AREA_REDUCTION")
        approve_variance(ctx, variance["id"])
        submitted = submit_design(ctx, d["id"])
        assert submitted["required_absorption_area_sqft"] == 450, (
            "re-derived under the reduced variant once the variance is APPROVED")
        assert submitted["tank_capacity_gal"] == 1000, "tank leg never switches variant"
