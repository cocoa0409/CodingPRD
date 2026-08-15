"""Quote pricing: tiered rates, pinned rounding order, mobilization fee,
cost floor, validation ordering, and quote-creation OCC."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_quote,
    create_assessment,
    create_customer,
    create_material,
    create_property,
    create_quote,
    create_submitted_assessment,
    get_property,
    get_quote,
    send_quote,
    setup_quote_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]


class TestQuotePricingMultiFactor:
    """1200 sqft tier-2 STANDARD 1-coat job with crack + patch + seal scope."""

    def test_per_line_amounts(self, api):
        """PRD §3.3: "an area above 1000 up to and including exactly 5000
        square feet prices at 24 cents per square foot" and "Crack filling
        prices at 150 cents per linear foot into `crack_line_cents`; pothole
        patching at 800 cents per square foot into `patch_line_cents`;
        striping at 90 cents per linear foot into `striping_line_cents`; each
        line rounded half-up individually and zeroed when its scope flag is
        off."

        Design: Difficulty/combinatorial_formula/quote_pricing_multi_factor_tiered
        """
        ctx = setup_quote_scenario()
        quote = ctx["quote"]
        assert_quote(quote)
        assert quote["seal_line_cents"] == 28800, (
            f"1200 sqft at tier-2 24c x grade 1.00 x 1 coat = 28800, got {quote['seal_line_cents']}"
        )
        assert quote["crack_line_cents"] == 6000, (
            f"40 ft at 150c = 6000, got {quote['crack_line_cents']}"
        )
        assert quote["patch_line_cents"] == 8000, (
            f"10 sqft at 800c = 8000, got {quote['patch_line_cents']}"
        )
        assert quote["striping_line_cents"] == 0, "striping excluded -> zeroed line"

    def test_subtotal_mobilization_and_total(self, api):
        """PRD §3.3: "A mobilization fee of 7500 cents applies when the
        subtotal minus the discount is strictly below 200000 cents" and "The
        `total_cents` is the subtotal minus discount plus mobilization fee,
        raised to a 25000-cent minimum charge when the arithmetic falls below
        it."

        Design: Difficulty/combinatorial_formula/quote_pricing_multi_factor_tiered
        """
        ctx = setup_quote_scenario()
        quote = ctx["quote"]
        assert quote["subtotal_cents"] == 42800, (
            f"28800 + 6000 + 8000 + 0 = 42800, got {quote['subtotal_cents']}"
        )
        assert quote["discount_cents"] == 0
        assert quote["mobilization_fee_cents"] == 7500, (
            "42800 < 200000 so the mobilization fee applies"
        )
        assert quote["total_cents"] == 50300, (
            f"max(42800 - 0 + 7500, 25000) = 50300, got {quote['total_cents']}"
        )


class TestSealTierBoundaries:
    @pytest.mark.parametrize(
        "area,expected_seal_line",
        [(1000, 30000), (5000, 120000)],
        ids=["area_1000_prices_tier1", "area_5000_prices_tier2"],
    )
    def test_tier_boundary_inclusive(self, api, area, expected_seal_line):
        """PRD §3.3: "an area of exactly 1000 square feet or less prices at 30
        cents per square foot; an area above 1000 up to and including exactly
        5000 square feet prices at 24 cents per square foot; an area above
        5000 prices at 18 cents per square foot."

        Design: Corner/calculations/seal_tier_boundary_1000_and_5000
        """
        ctx = setup_quote_scenario(
            address=f"{area} Boundary Way",
            measured_area_sqft=area,
            crack_linear_ft=0,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            quote_overrides={"include_crack_fill": False, "include_patch": False},
        )
        quote = ctx["quote"]
        assert quote["seal_line_cents"] == expected_seal_line, (
            f"area {area} must price seal at {expected_seal_line} cents "
            f"(tier boundary is inclusive), got {quote['seal_line_cents']}"
        )


class TestMobilizationFeeWaiverBoundary:
    @pytest.mark.parametrize(
        "crack_ft,expected_subtotal,expected_fee,expected_total",
        [(13, 199950, 7500, 207450), (14, 200100, 0, 200100)],
        ids=["subtotal_below_waiver_pays_fee", "subtotal_at_waiver_pays_nothing"],
    )
    def test_mobilization_fee_strictly_below_threshold(
        self, api, crack_ft, expected_subtotal, expected_fee, expected_total
    ):
        """PRD §3.3: "A mobilization fee of 7500 cents applies when the
        subtotal minus the discount is strictly below 200000 cents — two
        thousand dollars — and is otherwise waived; it lands in
        `mobilization_fee_cents`."

        Design: Corner/calculations/mobilization_fee_waiver_boundary
        """
        ctx = setup_quote_scenario(
            address=f"{crack_ft} Crack Way",
            measured_area_sqft=11000,
            crack_linear_ft=crack_ft,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            quote_overrides={"include_patch": False},
        )
        quote = ctx["quote"]
        # 11000 sqft at tier-3 18c = 198000; crack line = crack_ft * 150
        assert quote["subtotal_cents"] == expected_subtotal, (
            f"expected subtotal {expected_subtotal}, got {quote['subtotal_cents']}"
        )
        assert quote["mobilization_fee_cents"] == expected_fee, (
            f"subtotal {expected_subtotal} vs waiver 200000 -> fee {expected_fee}, "
            f"got {quote['mobilization_fee_cents']}"
        )
        assert quote["total_cents"] == expected_total


class TestCostFloor:
    def test_deep_discount_below_cost_floor_rejected(self, api):
        """PRD §3.3: "Every quote must also clear a cost floor: the estimated
        material cost — the gallons the job would require (per the
        whole-gallon reservation formula of §3.5, computed from the pinned
        area, coat count, and the material's `coverage_sqft_per_gallon`) times
        the material's `price_per_gallon_cents`, counted only when sealing is
        in scope — plus a labor floor of the pinned area times 5 cents per
        square foot, rounded half-up. A quote whose total falls below this
        floor is rejected with `ERR_PRICE_BELOW_COST_FLOOR`."

        Design: Corner/validations/price_floor_breach_on_quote_create
        """
        ctx = setup_quote_scenario(
            measured_area_sqft=2000,
            crack_linear_ft=0,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            material_overrides={
                "product_name": "SealMaster Premium",
                "grade": "PREMIUM",
                "coverage_sqft_per_gallon": 70,
                "reapplication_months": 36,
                "warranty_months": 24,
                "price_per_gallon_cents": 1400,
            },
        )
        prop = ctx["property"]
        # discounted total would be 52860 < floor (32 gal x 1400 + 10000 = 54800)
        resp = api.create_quote(
            {
                "property_id": prop["id"],
                "assessment_id": ctx["assessment"]["id"],
                "material_id": ctx["material"]["id"],
                "include_crack_fill": False,
                "include_patch": False,
                "include_seal": True,
                "include_striping": False,
                "coats": 1,
                "discount_pct": 0.30,
                "expected_property_version": prop["version"],
            },
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_BELOW_COST_FLOOR)
        data, _meta = validate_paginated(api.list_quotes(ESTIMATOR))
        assert [q["id"] for q in data] == [ctx["quote"]["id"]], (
            "the rejected create must not persist a new quote; only the "
            "pre-existing setup DRAFT may remain (supersession happens only "
            "on a successful create, PRD §3.3)"
        )


class TestAssessmentPropertyMismatch:
    def test_quote_with_foreign_assessment_rejected(self, api):
        """PRD §3.3: "An `Estimator` builds a quote against a property by
        pinning a specific `assessment_id` (which must belong to the same
        property, else `ERR_ASSESSMENT_PROPERTY_MISMATCH`)".

        Design: Corner/validations/quote_create_assessment_property_mismatch
        """
        customer = create_customer()
        prop_a = create_property(customer["id"], address="1 Elm St")
        prop_b = create_property(customer["id"], address="2 Elm St")
        assessment = create_submitted_assessment(prop_a["id"])
        material = create_material()
        prop_b_fresh = get_property(prop_b["id"])

        resp = api.create_quote(
            {
                "property_id": prop_b["id"],
                "assessment_id": assessment["id"],
                "material_id": material["id"],
                "include_crack_fill": True,
                "include_patch": True,
                "include_seal": True,
                "include_striping": False,
                "coats": 1,
                "expected_property_version": prop_b_fresh["version"],
            },
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_PROPERTY_MISMATCH)
        data, _meta = validate_paginated(api.list_quotes(ESTIMATOR))
        assert data == [], "no quote may be persisted on a property mismatch"


class TestQuotePatchStateVsFiscal:
    """PATCHing a SENT quote violates the state rule; the state error must be
    reported even when the payload would also breach fiscal rules."""

    def _sent_premium_quote(self, api):
        ctx = setup_quote_scenario(
            measured_area_sqft=2000,
            crack_linear_ft=0,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            material_overrides={
                "product_name": "SealMaster Premium",
                "grade": "PREMIUM",
                "coverage_sqft_per_gallon": 70,
                "reapplication_months": 36,
                "warranty_months": 24,
                "price_per_gallon_cents": 1400,
            },
            quote_overrides={"include_crack_fill": False, "include_patch": False},
        )
        ctx["quote"] = send_quote(ctx["quote"]["id"])
        return ctx

    def test_state_error_wins_over_fiscal(self, api):
        """PRD §3.3: "A revision edit by an estimator is permitted while the
        quote is `DRAFT` or `REVISION_REQUESTED` (otherwise
        `ERR_QUOTE_NOT_EDITABLE`)". PRD §2.11: "then state-machine legality
        (including the lazy expiry flips for quotes, assessments, and
        warranties); then the weather gate" ... "then fiscal rules (discount
        range, price floor, payment exactness)".

        Design: Difficulty/priority_pair_validation_conflict/quote_patch_state_vs_fiscal
        """
        ctx = self._sent_premium_quote(api)
        resp = api.patch_quote(ctx["quote"]["id"], {"discount_pct": 0.30}, ESTIMATOR)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_EDITABLE, 409)

    def test_failed_patch_leaves_quote_untouched(self, api):
        """PRD §3.3: "A revision edit by an estimator is permitted while the
        quote is `DRAFT` or `REVISION_REQUESTED` (otherwise
        `ERR_QUOTE_NOT_EDITABLE`); it recomputes every pricing field from the
        revised inputs and clears `sent_at` and `expires_on` back to null,
        restarting the send cycle."

        Design: Difficulty/priority_pair_validation_conflict/quote_patch_state_vs_fiscal
        """
        ctx = self._sent_premium_quote(api)
        original_total = ctx["quote"]["total_cents"]
        assert original_total == 72300, (
            f"PREMIUM 2000-sqft seal-only fixture: 64800 + 7500 = 72300, got {original_total}"
        )
        resp = api.patch_quote(ctx["quote"]["id"], {"discount_pct": 0.30}, ESTIMATOR)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_EDITABLE, 409)

        after = get_quote(ctx["quote"]["id"])
        assert after["status"] == "SENT"
        assert after["discount_pct"] == 0
        assert after["total_cents"] == 72300, (
            f"rejected PATCH must not reprice the quote, got {after['total_cents']}"
        )


class TestQuoteCreateOcc:
    def test_stale_property_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.6: "If `expected_property_version` does not match the
        property's current `version`, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)." PRD §3.3: "Only one open quote may
        exist per property. Creating a new quote supersedes any prior `DRAFT`,
        `SENT`, or `REVISION_REQUESTED` quote on the same property, points
        `open_quote_id` at the newcomer, and increments the property's
        `version`".

        Design: Corner/cross_cutting_layers/occ_quote_create_stale_property_version
        """
        customer = create_customer()
        prop = create_property(customer["id"])
        assessment = create_submitted_assessment(prop["id"])
        material = create_material()

        stale_version = get_property(prop["id"])["version"]
        quote1 = create_quote(prop["id"], assessment["id"], material["id"],
                              expected_property_version=stale_version)
        assert quote1["status"] == "DRAFT"

        # Replay with the pre-first-create version: property advanced already.
        resp = api.create_quote(
            {
                "property_id": prop["id"],
                "assessment_id": assessment["id"],
                "material_id": material["id"],
                "include_crack_fill": False,
                "include_patch": False,
                "include_seal": True,
                "include_striping": False,
                "coats": 2,
                "expected_property_version": stale_version,
            },
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh_version = get_property(prop["id"])["version"]
        quote2 = create_quote(
            prop["id"], assessment["id"], material["id"],
            expected_property_version=fresh_version,
            include_crack_fill=False, include_patch=False, coats=2,
        )
        assert quote2["status"] == "DRAFT"

        quote1_after = get_quote(quote1["id"])
        assert quote1_after["status"] == "SUPERSEDED", (
            "the newcomer supersedes the property's prior open quote"
        )
        prop_after = get_property(prop["id"])
        assert prop_after["open_quote_id"] == quote2["id"]
