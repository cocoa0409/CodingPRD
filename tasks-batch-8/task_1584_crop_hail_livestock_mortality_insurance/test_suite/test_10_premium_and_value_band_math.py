"""Premium arithmetic: the per-acre exposure constant and livestock value-band
tiering (PRD §2.7, §3.4, §3.7)."""
from test_helpers import (
    TEST_USERS,
    add_coverage_unit,
    assert_coverage_unit,
    assign_adjuster,
    bind_policy,
    create_carrier,
    create_grower,
    create_policy_application,
    create_published_rate,
    pay_premium,
    read_claim,
    set_clock,
    submit_initial_head_report,
    submit_livestock_inspection,
    validate_success,
    create_adjuster,
    file_livestock_claim,
)

UW = TEST_USERS["underwriter_headers"]


class TestPerAcreExposureConstant:
    def test_coverage_unit_liability_uses_fixed_per_acre_exposure_constant(self, api):
        """PRD §2.7: "Crop-hail exposure is built from a fixed per-acre constant
        of $400.00 — that is, 40,000 cents of liability per declared acre."
        PRD §3.4: "Each unit's `premium_cents` is then its liability multiplied
        by the matching published row's `rate_per_100_cents_of_liability` and
        divided by 10,000, rounded half up to whole cents — a crop-hail unit
        matches a row on county and crop, while a livestock unit matches when its
        species equals the row's and its per-head value falls at or above the
        band floor and strictly below the band ceiling."
        Seven acres → liability 7 × 40_000 = 280_000; premium
        round_half_up(280_000 × 333 / 10_000) = 9_324.

        Design: Corner/calculations/coverage_unit_liability_uses_fixed_per_acre_exposure_constant
        """
        carrier = create_carrier(carrier_code="CHL-CA1")
        cid = carrier["id"]
        grower = create_grower(cid)
        create_published_rate(cid)
        policy = create_policy_application(cid, grower["id"], "CROP_HAIL")
        res = api.create_coverage_unit(
            cid, policy["id"],
            {"county_code": "06001", "crop_code": "CORN", "declared_acres": 7},
            UW,
        )
        unit = validate_success(res, 201)
        assert_coverage_unit(unit)
        assert unit["liability_cents"] == 280_000
        assert unit["premium_cents"] == 9_324


class TestTieredValueBandInteraction:
    def _setup_two_band_policy(self, api):
        """Two PUBLISHED CATTLE bands — [150_000, 250_000) at rate 400 and
        [250_000, 500_000) at rate 500 — and a policy with CU1 (4 head @
        200_000, band 1) and CU2 (2 head @ 300_000, band 2), bound, paid, ACTIVE,
        with timely initial head reports and one open claim per unit."""
        carrier = create_carrier(carrier_code="CHL-D")
        cid = carrier["id"]
        grower = create_grower(cid)
        adjuster = create_adjuster(cid, species_qualified=["CATTLE"],
                                   capacity_max_open_claims=10)
        create_published_rate(
            cid, "LIVESTOCK_MORTALITY", species="CATTLE",
            value_band_floor_cents=150_000, value_band_ceiling_cents=250_000,
            rate_per_100_cents_of_liability=400,
        )
        create_published_rate(
            cid, "LIVESTOCK_MORTALITY", species="CATTLE",
            value_band_floor_cents=250_000, value_band_ceiling_cents=500_000,
            rate_per_100_cents_of_liability=500,
        )
        policy = create_policy_application(
            cid, grower["id"], "LIVESTOCK_MORTALITY",
            effective_date="2026-08-02T00:00:00Z",
            expiration_date="2027-08-02T00:00:00Z",
        )
        cu1 = add_coverage_unit(
            cid, policy["id"], "LIVESTOCK_MORTALITY", species="CATTLE",
            declared_head_count=4, per_head_value_cents=200_000,
        )
        cu2 = add_coverage_unit(
            cid, policy["id"], "LIVESTOCK_MORTALITY", species="CATTLE",
            declared_head_count=2, per_head_value_cents=300_000,
        )
        bound = bind_policy(cid, policy["id"])
        pay_premium(cid, policy["id"], grower["id"], bound["premium_cents"])
        set_clock(cid, "2026-08-03T00:00:00Z")
        submit_initial_head_report(cid, policy["id"], cu1["id"], grower["id"],
                                   reported_head_count=4)
        submit_initial_head_report(cid, policy["id"], cu2["id"], grower["id"],
                                   reported_head_count=2)
        claim_hi = file_livestock_claim(
            cid, policy["id"], grower["id"], cu2["id"],
            appraisal_value_cents=400_000, deceased_head_count=1,
        )
        assign_adjuster(cid, policy["id"], claim_hi["id"], adjuster["id"])
        claim_lo = file_livestock_claim(
            cid, policy["id"], grower["id"], cu1["id"],
            appraisal_value_cents=300_000, deceased_head_count=1,
        )
        assign_adjuster(cid, policy["id"], claim_lo["id"], adjuster["id"])
        return {
            "carrier_id": cid, "grower": grower, "adjuster": adjuster,
            "policy": bound, "cu1": cu1, "cu2": cu2,
            "claim_hi": claim_hi, "claim_lo": claim_lo,
        }

    def test_livestock_premium_tiered_by_value_band(self, api):
        """PRD §3.4: "Liability is computed immediately: a crop-hail unit's
        `liability_cents` is its declared acres multiplied by the 40,000-cent
        per-acre exposure constant, while a livestock unit's `liability_cents` is
        its head count multiplied by the per-head value."
        PRD §3.4: "Each unit's `premium_cents` is then its liability multiplied
        by the matching published row's `rate_per_100_cents_of_liability` and
        divided by 10,000, rounded half up to whole cents — a crop-hail unit
        matches a row on county and crop, while a livestock unit matches when its
        species equals the row's and its per-head value falls at or above the
        band floor and strictly below the band ceiling."
        CU1: 800_000 × 400 / 10_000 = 32_000; CU2: 600_000 × 500 / 10_000 =
        30_000; policy premium = 62_000.

        Design: Difficulty/combinatorial_formula/tiered_rate_and_value_band_interaction_livestock
        """
        ctx = self._setup_two_band_policy(api)
        assert ctx["cu1"]["liability_cents"] == 800_000
        assert ctx["cu1"]["premium_cents"] == 32_000
        assert ctx["cu2"]["liability_cents"] == 600_000
        assert ctx["cu2"]["premium_cents"] == 30_000
        assert ctx["policy"]["premium_cents"] == 62_000

    def test_provisional_indemnity_capped_by_band_ceiling(self, api):
        """PRD §3.7: "For livestock, the appraisal basis is the lesser of the
        adjuster's `observed_appraisal_cents` and the grower's claimed
        `appraisal_value_cents`; that basis is then capped at the rating row's
        `value_band_ceiling_cents` multiplied by the adjuster's
        `observed_deceased_count`, and the capped figure is scaled down by the
        latest late head report's `coverage_reduction_pct`."
        High-band claim: min(400_000, 350_000) = 350_000 < cap 500_000 →
        350_000. Low-band claim: min(300_000, 280_000) = 280_000 capped to
        250_000 × 1 → 250_000.

        Design: Difficulty/combinatorial_formula/tiered_rate_and_value_band_interaction_livestock
        """
        ctx = self._setup_two_band_policy(api)
        cid, pid = ctx["carrier_id"], ctx["policy"]["id"]
        adj_id = ctx["adjuster"]["id"]

        inspection_hi = submit_livestock_inspection(
            cid, pid, ctx["claim_hi"]["id"], adj_id,
            observed_appraisal_cents=350_000, observed_deceased_count=1,
        )
        assert inspection_hi["provisional_indemnity_cents"] == 350_000
        claim_hi = read_claim(cid, pid, ctx["claim_hi"]["id"])
        assert claim_hi["provisional_indemnity_cents"] == 350_000

        inspection_lo = submit_livestock_inspection(
            cid, pid, ctx["claim_lo"]["id"], adj_id,
            observed_appraisal_cents=280_000, observed_deceased_count=1,
        )
        assert inspection_lo["provisional_indemnity_cents"] == 250_000, (
            "the rating row's value-band ceiling caps the appraisal basis"
        )
        claim_lo = read_claim(cid, pid, ctx["claim_lo"]["id"])
        assert claim_lo["provisional_indemnity_cents"] == 250_000
