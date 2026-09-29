"""Dual-variant scoring: readiness screening versus certification, and the
permissible transfer floor under each transfer basis."""

from test_helpers import (
    assert_money,
    assert_score,
    build_site,
    certify_assessment,
    create_assessment_payload,
    create_valuation_payload,
    read_site,
    release_site,
    set_logical_clock,
    validate_success,
)


class TestReadinessVariantDivergence:
    """The same stored assessment row scores differently before and after
    certification."""

    @staticmethod
    def _site():
        set_logical_clock("2026-08-01T00:00:00Z")
        return build_site(site_code="TJD-A-001",
                          name="Alder Street Park-and-Ride",
                          address_line="1400 Alder St",
                          parcel_area_sqft=86000,
                          acquisition_funding_source="FEDERAL_GRANT",
                          federal_interest_pct=2.5,
                          transit_facility_present=False)

    def test_draft_assessment_scores_under_the_preliminary_variant(
            self, api, real_estate_officer):
        """PRD §3.1: "While the assessment is a `DRAFT`, `variant_applied` is
        `PRELIMINARY` and `composite_score` is simply the unweighted arithmetic
        mean of the four sub-scores — their sum divided by four, rounded half up
        to two decimal places." And: "sub-scores of 80, 75, 70 and 60 with one
        encumbrance on a parcel whose federal interest is two and a half percent
        yield a preliminary score of 71.25 and a certified score of 70.00 from
        identical stored inputs." The preliminary variant "leaves `tier` null."

        Design: Difficulty/dual_variant_calc/readiness_score_preliminary_versus_certified_variant_divergence
        """
        site = self._site()

        assessment = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=1,
                                      assessment_notes="Intake screen"),
            real_estate_officer), 201)

        assert_score(assessment["composite_score"], 71.25, "composite_score")
        assert assessment["variant_applied"] == "PRELIMINARY", (
            "a draft assessment reports the preliminary variant, got "
            f"{assessment['variant_applied']}")
        assert assessment["tier"] is None, (
            f"tier stays null while the assessment is a draft, got {assessment['tier']}")
        assert assessment["status"] == "DRAFT"

    def test_certification_rescores_the_same_row_under_the_certified_variant(
            self, api, real_estate_officer):
        """PRD §3.1: "When a `RealEstateOfficer` certifies a draft assessment,
        the score is recomputed under the `CERTIFIED` variant, `variant_applied`
        is set to `CERTIFIED`, and the result can be materially lower than the
        preliminary figure the officer has been looking at." The worked case:
        "sub-scores of 80, 75, 70 and 60 with one encumbrance on a parcel whose
        federal interest is two and a half percent yield a preliminary score of
        71.25 and a certified score of 70.00 from identical stored inputs." And:
        "A score of at least 70.00 is `READY`".

        Design: Difficulty/dual_variant_calc/readiness_score_preliminary_versus_certified_variant_divergence
        """
        site = self._site()
        assessment = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=1,
                                      assessment_notes="Intake screen"),
            real_estate_officer), 201)

        certified = validate_success(
            api.certify_assessment(assessment["id"], real_estate_officer))

        assert_score(certified["composite_score"], 70.00, "composite_score")
        assert certified["variant_applied"] == "CERTIFIED"
        assert certified["tier"] == "READY", (
            f"70.00 bands into READY, got {certified['tier']}")
        assert certified["status"] == "CERTIFIED"

    def test_certification_copies_score_and_tier_onto_the_site(
            self, api, real_estate_officer):
        """PRD §3.1: "The site's `readiness_composite_score` and
        `readiness_tier` are refreshed to the certifying assessment's
        `composite_score` and `tier` — those two site fields are always a copy
        of the most recently certified assessment, and are null whenever no
        certified assessment exists." And: "A site sitting in `INVENTORIED`
        moves `INVENTORIED → ASSESSED`".

        Design: Difficulty/dual_variant_calc/readiness_score_preliminary_versus_certified_variant_divergence
        """
        site = self._site()
        assessment = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=1),
            real_estate_officer), 201)

        certify_assessment(assessment["id"])

        stored = read_site(site["id"])
        assert_score(stored["readiness_composite_score"], 70.00,
                    "site.readiness_composite_score")
        assert stored["readiness_tier"] == "READY"
        assert stored["status"] == "ASSESSED", (
            f"an inventoried site becomes ASSESSED on certification, got "
            f"{stored['status']}")

    def test_preliminary_screen_overstates_the_certified_score_by_one_and_a_quarter(
            self, api, real_estate_officer):
        """PRD §3.1: "sub-scores of 80, 75, 70 and 60 with one encumbrance on a
        parcel whose federal interest is two and a half percent yield a
        preliminary score of 71.25 and a certified score of 70.00 from identical
        stored inputs." The certified variant subtracts penalties the
        preliminary variant ignores: "The **encumbrance penalty** is three
        points for each recorded encumbrance" and "The **federal interest
        penalty** is one tenth of a point for each whole percent of
        `federal_interest_pct` on the parcel."

        Design: Difficulty/dual_variant_calc/readiness_score_preliminary_versus_certified_variant_divergence
        """
        site = self._site()
        assessment = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=1),
            real_estate_officer), 201)
        preliminary = assessment["composite_score"]

        certified = validate_success(
            api.certify_assessment(assessment["id"], real_estate_officer))

        assert_score(preliminary - certified["composite_score"], 1.25,
                    "preliminary minus certified score")


class TestPermissibleFloorBasisDivergence:
    """One appraisal, two transfer bases, two floors."""

    @staticmethod
    def _prepare(api, real_estate_officer):
        set_logical_clock("2026-08-01T00:00:00Z")
        site = build_site(site_code="TJD-A-002",
                          name="Birch Yard Surplus Parcel",
                          address_line="22 Birch Yard Rd",
                          parcel_area_sqft=74000,
                          acquisition_funding_source="FEDERAL_GRANT",
                          federal_interest_pct=2.5,
                          transit_facility_present=False)
        assessment = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=1),
            real_estate_officer), 201)
        certify_assessment(assessment["id"])
        release_site(site["id"])
        return site

    def test_fmv_strict_basis_floors_the_transfer_at_the_full_appraised_value(
            self, api, real_estate_officer, valuation_officer):
        """PRD §3.2: "Under `FMV_STRICT` the grantor has not concurred in any
        below-market transfer, so `permissible_floor_cents` is the full
        `appraised_value_cents` and the credit computed in step three is
        recorded but never applied." The worked parcel is "appraised at
        48,500,000 cents with sixty percent transit-supportive floor area,
        twenty-five percent affordable units and a federal interest of two and a
        half percent", whose floor is "the untouched 48,500,000 cents under the
        strict basis."

        Design: Difficulty/dual_variant_calc/valuation_floor_fmv_strict_versus_below_market_divergence
        """
        site = self._prepare(api, real_estate_officer)
        site_v1 = read_site(site["id"])["version"]

        strict = validate_success(api.create_valuation(
            site["id"],
            create_valuation_payload(site_v1, method="INCOME_APPROACH",
                                     appraised_value_cents=48_500_000,
                                     transit_supportive_use_pct=60,
                                     affordable_units_pct=25,
                                     transfer_basis="FMV_STRICT",
                                     effective_date="2026-08-20"),
            valuation_officer), 201)

        assert_money(strict["permissible_floor_cents"], 48_500_000,
                    "permissible_floor_cents")
        assert strict["status"] == "DRAFT"

    def test_below_market_basis_floors_the_transfer_twelve_million_lower(
            self, api, real_estate_officer, valuation_officer):
        """PRD §3.2: "Under `TRANSIT_SUPPORTIVE_BELOW_MARKET` the floor is the
        appraised value less the transit-supportive credit, but never below the
        federal interest floor — whichever of those two figures is larger wins."
        For the worked parcel "the credit is 12,125,000 cents, and the floor is
        36,375,000 cents under the below-market basis but the untouched
        48,500,000 cents under the strict basis."

        Design: Difficulty/dual_variant_calc/valuation_floor_fmv_strict_versus_below_market_divergence
        """
        site = self._prepare(api, real_estate_officer)
        site_v1 = read_site(site["id"])["version"]
        strict = validate_success(api.create_valuation(
            site["id"],
            create_valuation_payload(site_v1, transfer_basis="FMV_STRICT",
                                     effective_date="2026-08-20"),
            valuation_officer), 201)
        site_v2 = read_site(site["id"])["version"]

        below = validate_success(api.create_valuation(
            site["id"],
            create_valuation_payload(site_v2,
                                     transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
                                     effective_date="2026-08-20"),
            valuation_officer), 201)

        assert_money(below["permissible_floor_cents"], 36_375_000,
                    "permissible_floor_cents")
        assert_money(strict["permissible_floor_cents"]
                     - below["permissible_floor_cents"], 12_125_000,
                     "strict floor less below-market floor")
        assert below["status"] == "DRAFT"

    def test_both_bases_record_the_same_credit_and_federal_interest_floor(
            self, api, real_estate_officer, valuation_officer):
        """PRD §3.2: "`transit_supportive_credit_cents` is the appraised value
        multiplied by that final rate, rounded half up to a whole cent, and
        `federal_interest_floor_cents` is the appraised value multiplied by the
        site's `federal_interest_pct` and divided by 100, again rounded half up
        to a whole cent. Both of those fields are recorded on the determination
        under **both** variants; only the fourth step differs between them."

        Design: Difficulty/dual_variant_calc/valuation_floor_fmv_strict_versus_below_market_divergence
        """
        site = self._prepare(api, real_estate_officer)
        strict = validate_success(api.create_valuation(
            site["id"],
            create_valuation_payload(read_site(site["id"])["version"],
                                     transfer_basis="FMV_STRICT",
                                     effective_date="2026-08-20"),
            valuation_officer), 201)

        below = validate_success(api.create_valuation(
            site["id"],
            create_valuation_payload(read_site(site["id"])["version"],
                                     transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
                                     effective_date="2026-08-20"),
            valuation_officer), 201)

        assert_money(strict["transit_supportive_credit_cents"], 12_125_000,
                    "strict transit_supportive_credit_cents")
        assert_money(below["transit_supportive_credit_cents"], 12_125_000,
                    "below-market transit_supportive_credit_cents")
        assert_money(strict["federal_interest_floor_cents"], 1_212_500,
                    "strict federal_interest_floor_cents")
        assert_money(below["federal_interest_floor_cents"], 1_212_500,
                    "below-market federal_interest_floor_cents")

    def test_recording_determinations_pins_the_site_federal_interest_basis(
            self, api, real_estate_officer, valuation_officer):
        """PRD §3.2: "The site's `federal_interest_basis_cents` is set to the
        appraised value multiplied by `federal_interest_pct` and divided by 100,
        rounded half up, and `federal_interest_unencumbered_cents` is recomputed
        as that basis less whatever is already in
        `federal_interest_encumbered_cents`; the site's `version` is bumped by
        1."

        Design: Difficulty/dual_variant_calc/valuation_floor_fmv_strict_versus_below_market_divergence
        """
        site = self._prepare(api, real_estate_officer)
        validate_success(api.create_valuation(
            site["id"],
            create_valuation_payload(read_site(site["id"])["version"],
                                     transfer_basis="FMV_STRICT",
                                     effective_date="2026-08-20"),
            valuation_officer), 201)

        validate_success(api.create_valuation(
            site["id"],
            create_valuation_payload(read_site(site["id"])["version"],
                                     transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
                                     effective_date="2026-08-20"),
            valuation_officer), 201)

        stored = read_site(site["id"])
        assert_money(stored["federal_interest_basis_cents"], 1_212_500,
                    "site.federal_interest_basis_cents")
        assert_money(stored["federal_interest_unencumbered_cents"], 1_212_500,
                    "site.federal_interest_unencumbered_cents")
