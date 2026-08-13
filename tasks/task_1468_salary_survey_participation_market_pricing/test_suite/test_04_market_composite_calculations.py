"""Composite math: aging, geo differential, industry premium, weighted blend,
and the executive conservative variant (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    add_active_strategy,
    add_benchmark,
    analyst_headers,
    bootstrap_org,
    create_active_vendor,
    create_open_survey,
    create_recomputed_composite,
    get_composite,
    get_success_data,
    mgr_headers,
    propose_match,
    review_and_approve_match,
    setup_accepted_survey,
    setup_published_job,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]

# Canonical seven-month aging scenario: data_effective_date 2026-01-01,
# market_as_of_date 2026-08-01 (PRD §3.6).


class TestDualVariantBlend:
    def _setup_two_variant_composites(self, api):
        """One ACCEPTED survey feeding two jobs: IC3 (base blend) and M1
        (executive conservative blend), identical match inputs."""
        bundle = bootstrap_org()
        job_m1 = get_success_data(
            api.create_job(bundle["org"]["id"], {
                "job_code": "ENG.M1", "title": "Eng Mgr", "job_family": "ENG",
                "career_level": "M1", "flsa_status": "EXEMPT"},
                mgr_headers(bundle)))
        bundle["strategy"] = add_active_strategy(bundle)
        chain = setup_accepted_survey(bundle)
        bundle.update(chain)
        bench_b = add_benchmark(
            bundle, bundle["survey"], benchmark_code="B2",
            benchmark_title="SWE IC3 alt", p25_cents=9600000,
            p50_cents=12000000, p75_cents=15000000, p90_cents=18000000,
            sample_size=20)
        matches = {}
        for job, tag in ((bundle["job"], "ic3"), (job_m1, "m1")):
            m_a = propose_match(bundle, bundle["survey"], job,
                                bundle["benchmark"], match_confidence="HIGH",
                                match_weight_pct=60)
            m_b = propose_match(bundle, bundle["survey"], job, bench_b,
                                match_confidence="LOW", match_weight_pct=40)
            matches[tag] = (review_and_approve_match(bundle, m_a["id"]),
                            review_and_approve_match(bundle, m_b["id"]))
        comp_ic3 = create_recomputed_composite(bundle, bundle["job"],
                                               bundle["strategy"])
        comp_m1 = create_recomputed_composite(bundle, job_m1,
                                              bundle["strategy"])
        return comp_ic3, comp_m1

    def test_base_variant_blend_for_ic_job(self, api):
        """PRD §3.6: "Each contributing match's effective weight is the product
        of three terms: its `match_weight_pct` expressed as a fraction of 100;
        a confidence factor of 1.00 for `HIGH`, 0.75 for `MEDIUM`, or 0.40 for
        `LOW`; and a sample factor equal to the benchmark's `sample_size`
        divided by 30, capped at 1.0 so benchmarks with thirty or more
        incumbents earn full sample credit."
        PRD §3.6: "each blended percentile is the weighted sum of the
        premium-adjusted percentile values across sources, rounded half-up to
        a whole cent exactly once at the final sum".

        Design: Difficulty/dual_variant_calc/blend_base_vs_conservative_on_market_composite
        """
        comp_ic3, _ = self._setup_two_variant_composites(api)
        assert comp_ic3["blended_p50_cents"] == 10481058, (
            f"Base variant (LOW factor 0.40) must blend to 10481058, got "
            f"{comp_ic3['blended_p50_cents']}")

    def test_conservative_variant_blend_for_executive_job(self, api):
        """PRD §3.6: "One variant alters this stage: for executive-level jobs —
        `career_level` of `M1`, `M2`, or `M3` — the blend is conservative,
        halving the `LOW` confidence factor to 0.20 and outright excluding any
        benchmark with fewer than ten incumbents instead of merely discounting
        it through the sample factor."

        Design: Difficulty/dual_variant_calc/blend_base_vs_conservative_on_market_composite
        """
        comp_ic3, comp_m1 = self._setup_two_variant_composites(api)
        assert comp_m1["blended_p50_cents"] == 10340026, (
            f"Conservative variant (LOW factor 0.20) must blend to 10340026, "
            f"got {comp_m1['blended_p50_cents']}")
        assert comp_ic3["blended_p50_cents"] != comp_m1["blended_p50_cents"], (
            "Identical inputs must price differently under the two variants")


class TestWeightedBlendNonlinear:
    def _setup_two_match_composite(self, api):
        bundle = bootstrap_org()
        bundle["strategy"] = add_active_strategy(bundle)
        chain = setup_accepted_survey(bundle)
        bundle.update(chain)
        bench_b = add_benchmark(
            bundle, bundle["survey"], benchmark_code="B2", benchmark_title="B",
            p25_cents=9600000, p50_cents=12000000, p75_cents=15000000,
            p90_cents=18000000, sample_size=20)
        m_a = propose_match(bundle, bundle["survey"], bundle["job"],
                            bundle["benchmark"], match_confidence="HIGH",
                            match_weight_pct=60)
        m_b = propose_match(bundle, bundle["survey"], bundle["job"], bench_b,
                            match_confidence="MEDIUM", match_weight_pct=40)
        review_and_approve_match(bundle, m_a["id"])
        review_and_approve_match(bundle, m_b["id"])
        composite = create_recomputed_composite(bundle, bundle["job"],
                                                bundle["strategy"])
        return bundle, composite

    def test_three_input_nonlinear_blend_value(self, api):
        """PRD §3.6: "Each contributing match's effective weight is the product
        of three terms: its `match_weight_pct` expressed as a fraction of 100;
        a confidence factor of 1.00 for `HIGH`, 0.75 for `MEDIUM`, or 0.40 for
        `LOW`; and a sample factor equal to the benchmark's `sample_size`
        divided by 30, capped at 1.0 so benchmarks with thirty or more
        incumbents earn full sample credit."
        PRD §3.6: "Otherwise the effective weights are normalized to sum to
        one, and each blended percentile is the weighted sum of the
        premium-adjusted percentile values across sources, rounded half-up to
        a whole cent exactly once at the final sum — individual weighted terms
        are never rounded."

        Design: Difficulty/combinatorial_formula/weighted_blend_three_input_nonlinear
        """
        _, composite = self._setup_two_match_composite(api)
        assert composite["blended_p50_cents"] == 10682617, (
            f"Expected 0.75*aged_A + 0.25*aged_B == 10682617, got "
            f"{composite['blended_p50_cents']}")

    def test_source_count_records_contributing_matches(self, api):
        """PRD §3.6: "`source_count` records how many approved matches
        contributed."

        Design: Difficulty/combinatorial_formula/weighted_blend_three_input_nonlinear
        """
        bundle, composite = self._setup_two_match_composite(api)
        assert composite["source_count"] == 2, (
            f"Two APPROVED matches under an ACCEPTED survey must count; got "
            f"{composite['source_count']}")
        # Recompute is deterministic: identical inputs reproduce the value.
        recomputed = validate_success(api.recompute_composite(
            composite["id"], mgr_headers(bundle)))
        assert recomputed["blended_p50_cents"] == 10682617


class TestStageRoundingOrder:
    def test_aging_then_geo_then_industry_order(self, api):
        """PRD §3.6: "Computation — whether on demand through the recompute
        capability or as part of publication readiness — runs four stages in a
        fixed order, per source."
        PRD §3.6: "Second, the geographic differential is applied per source
        according to the pinned strategy's `geo_differential_policy`."
        PRD §3.6: "Third, the industry premium is applied."
        PRD §2.7: "all monetary arithmetic rounds half-up to zero decimal
        places (whole cents) at the points the relevant rule specifies".

        With p50_cents=9999999 the pinned order yields 14064427; applying the
        industry premium before the geographic differential would yield
        14064428.

        Design: Difficulty/combinatorial_formula/aging_geo_industry_rounding_order
        """
        bundle = setup_published_job(
            strategy_overrides={"geo_differential_policy": "METRO_TIER",
                                "industry_cut": "HIGH_TECH"},
            benchmark_overrides={"industry_cut": "HIGH_TECH",
                                 "p50_cents": 9999999},
            survey_overrides={"industry_cut_supported": ["HIGH_TECH"]})
        assert bundle["composite"]["blended_p50_cents"] == 14064427, (
            f"aging -> geo -> industry order must yield 14064427, got "
            f"{bundle['composite']['blended_p50_cents']}")

    def test_metro_tier_geo_factor_recorded_on_composite(self, api):
        """PRD §3.6: "Under `METRO_TIER`, the factor comes from the metro
        table: `US-SF` at 12800, `US-NYC` at 12200, `US-SEA` at 11200,
        `US-AUS` at 10400, and `US-REMOTE` at 9500 basis points" and "the
        applied factor is stored on the composite as `geo_differential_bp`."

        Design: Difficulty/combinatorial_formula/aging_geo_industry_rounding_order
        """
        bundle = setup_published_job(
            strategy_overrides={"geo_differential_policy": "METRO_TIER",
                                "industry_cut": "HIGH_TECH"},
            benchmark_overrides={"industry_cut": "HIGH_TECH",
                                 "p50_cents": 9999999},
            survey_overrides={"industry_cut_supported": ["HIGH_TECH"]},
            composite_geo_code="US-SF")
        assert bundle["composite"]["geo_differential_bp"] == 12800, (
            f"METRO_TIER[US-SF] must be stored as 12800, got "
            f"{bundle['composite']['geo_differential_bp']}")


class TestAgingAndBlendInputSet:
    def test_aging_zero_months_when_effective_equals_as_of(self, api):
        """PRD §3.6: "the engine counts the whole calendar months between the
        two dates, counting a month only when the day-of-month of the
        `market_as_of_date` has reached or passed the day-of-month of the
        `data_effective_date` in that month, and flooring the count at zero so
        data is never aged backward when the as-of date precedes the effective
        date."

        Design: Corner/calculations/aging_zero_months_when_effective_equals_as_of
        """
        bundle = bootstrap_org()
        bundle["strategy"] = add_active_strategy(bundle)
        chain = setup_accepted_survey(
            bundle, survey_overrides={"data_effective_date": "2026-08-01"})
        bundle.update(chain)
        match = propose_match(bundle, bundle["survey"], bundle["job"],
                              bundle["benchmark"])
        review_and_approve_match(bundle, match["id"])
        composite = create_recomputed_composite(bundle, bundle["job"],
                                                bundle["strategy"])
        assert composite["blended_p50_cents"] == 10000000, (
            f"Zero elapsed months means aging factor 1.0; expected 10000000, "
            f"got {composite['blended_p50_cents']}")

    def test_blend_excludes_matches_from_non_accepted_surveys(self, api):
        """PRD §3.6: "Only matches count that are themselves `APPROVED`, sit
        under a survey that has reached `ACCEPTED`, and belong to a vendor
        that remains `ACTIVE`."

        Design: Corner/calculations/blend_excludes_matches_from_non_accepted_surveys
        """
        bundle = bootstrap_org()
        bundle["strategy"] = add_active_strategy(bundle)
        chain = setup_accepted_survey(bundle)  # ACCEPTED survey S1
        bundle.update(chain)
        # Second survey stays OPEN (never accepted) with a richer benchmark.
        survey2 = create_open_survey(bundle, chain["vendor"], survey_code="S2")
        bench2 = add_benchmark(bundle, survey2, benchmark_code="B2",
                               p25_cents=16000000, p50_cents=20000000,
                               p75_cents=25000000, p90_cents=30000000,
                               sample_size=100)
        m1 = propose_match(bundle, chain["survey"], bundle["job"],
                           chain["benchmark"])
        m2 = propose_match(bundle, survey2, bundle["job"], bench2)
        review_and_approve_match(bundle, m1["id"])
        review_and_approve_match(bundle, m2["id"])
        composite = create_recomputed_composite(bundle, bundle["job"],
                                                bundle["strategy"])
        assert composite["source_count"] == 1, (
            f"Only the ACCEPTED survey's match may contribute; got "
            f"{composite['source_count']}")
        assert composite["blended_p50_cents"] == 10173921, (
            f"Blend must equal the accepted source's aged value 10173921, "
            f"got {composite['blended_p50_cents']}")


class TestGeographicDifferentialLookup:
    def _setup_three_geo_composites(self, api):
        bundle = bootstrap_org()
        bundle["strategy"] = add_active_strategy(
            bundle, geo_differential_policy="METRO_TIER")
        chain = setup_accepted_survey(bundle)
        bundle.update(chain)
        match = propose_match(bundle, bundle["survey"], bundle["job"],
                              bundle["benchmark"])
        review_and_approve_match(bundle, match["id"])
        composites = {
            geo: create_recomputed_composite(bundle, bundle["job"],
                                             bundle["strategy"],
                                             job_geo_code=geo)
            for geo in ("US-SF", "US-REMOTE", "US-UNKNOWN")
        }
        return bundle, composites

    def test_metro_tier_known_codes_use_table(self, api):
        """PRD §3.6: "Under `METRO_TIER`, the factor comes from the metro
        table: `US-SF` at 12800, `US-NYC` at 12200, `US-SEA` at 11200,
        `US-AUS` at 10400, and `US-REMOTE` at 9500 basis points".

        Design: Corner/calculations/geographic_differential_metro_tier_lookup
        """
        _, composites = self._setup_three_geo_composites(api)
        sf = composites["US-SF"]
        remote = composites["US-REMOTE"]
        assert sf["geo_differential_bp"] == 12800
        assert sf["blended_p50_cents"] == 13022619, (
            f"US-SF blend must be 13022619, got {sf['blended_p50_cents']}")
        assert remote["geo_differential_bp"] == 9500
        assert remote["blended_p50_cents"] == 9665225, (
            f"US-REMOTE blend must be 9665225, got "
            f"{remote['blended_p50_cents']}")

    def test_metro_tier_unknown_geo_falls_back_to_neutral(self, api):
        """PRD §3.6: "a `job_geo_code` absent from the table falls back to a
        neutral 10000."

        Design: Corner/calculations/geographic_differential_metro_tier_lookup
        """
        _, composites = self._setup_three_geo_composites(api)
        unknown = composites["US-UNKNOWN"]
        assert unknown["geo_differential_bp"] == 10000, (
            f"Unknown geo code must fall back to neutral 10000, got "
            f"{unknown['geo_differential_bp']}")
        assert unknown["blended_p50_cents"] == 10173921, (
            f"Neutral geo leaves the aged value unchanged at 10173921, got "
            f"{unknown['blended_p50_cents']}")
