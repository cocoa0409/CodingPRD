"""Market adjustments: frozen compa-ratios at submit, band boundary precision,
provisional-vs-final divergence across supersession, retract ownership
(PRD §2.8, §2.9, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_benchmark,
    add_successor_strategy,
    analyst_headers,
    create_draft_adjustment,
    create_open_cycle,
    create_recomputed_composite,
    get_adjustment,
    get_composite,
    get_job,
    get_success_data,
    make_analyst_headers,
    mgr_headers,
    propose_match,
    publish_composite,
    review_and_approve_match,
    setup_published_job,
    submit_adjustment,
    validate_error,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]


class TestCompaRatioBandBoundary:
    def _setup_boundary_adjustments(self, api):
        """Published composite priced at blended_p50 14064429 (METRO_TIER
        US-SF + HIGH_TECH over a 10000000 benchmark, seven-month aging), plus
        two employees straddling the 9500 basis-point band edge."""
        bundle = setup_published_job(
            strategy_overrides={"geo_differential_policy": "METRO_TIER",
                                "industry_cut": "HIGH_TECH"},
            benchmark_overrides={"industry_cut": "HIGH_TECH"},
            survey_overrides={"industry_cut_supported": ["HIGH_TECH"]},
            subject_salary=13361207)
        subject_below = get_success_data(api.create_employee(
            bundle["org"]["id"],
            {"full_name": "Below", "email": "below@x.com",
             "job_id": bundle["job"]["id"], "geo_code": "US-SF",
             "base_salary_annual_cents": 13359801, "hire_date": "2024-06-01"},
            mgr_headers(bundle)))
        cycle = create_open_cycle(bundle, budget_cents=10000000)
        adj_at = create_draft_adjustment(bundle, cycle)
        adj_below = create_draft_adjustment(bundle, cycle,
                                            employee=subject_below)
        return bundle, adj_at, adj_below

    def test_compa_ratio_exactly_9500_is_at_target(self, api):
        """PRD §3.7: "An employee's compa-ratio is their
        `base_salary_annual_cents` multiplied by 10000 and divided by the
        composite's `blended_p50_cents`, rounded half-up to a whole basis
        point" and "at least 9500 and at most 10500 is `AT_TARGET`".

        Salary 13361207 against blended_p50 14064429 yields exactly 9500.

        Design: Difficulty/boundary_precision_check/compa_ratio_exactly_9500_band_boundary
        """
        bundle, adj_at, _ = self._setup_boundary_adjustments(api)
        submitted = submit_adjustment(bundle, adj_at["id"])
        assert submitted["pre_adjustment_compa_ratio_bp"] == 9500, (
            f"Boundary-inclusive: expected 9500 (AT_TARGET), got "
            f"{submitted['pre_adjustment_compa_ratio_bp']}")

    def test_compa_ratio_9499_falls_below_target(self, api):
        """PRD §3.7: "at least 8000 but below 9500 is `BELOW_TARGET`; at least
        9500 and at most 10500 is `AT_TARGET`".

        Salary 13359801 against blended_p50 14064429 yields 9499, one basis
        point below the AT_TARGET edge.

        Design: Difficulty/boundary_precision_check/compa_ratio_exactly_9500_band_boundary
        """
        bundle, _, adj_below = self._setup_boundary_adjustments(api)
        submitted = submit_adjustment(bundle, adj_below["id"])
        assert submitted["pre_adjustment_compa_ratio_bp"] == 9499, (
            f"One cent of salary below the boundary yields 9499 "
            f"(BELOW_TARGET), got "
            f"{submitted['pre_adjustment_compa_ratio_bp']}")


class TestProvisionalVsFinalRecommendation:
    def _setup_frozen_adjustment(self, api):
        """C1 PUBLISHED (NATIONAL / ALL_INDUSTRIES, blended_p50 10173921);
        adjustment submitted for the subject (salary 11251543)."""
        bundle = setup_published_job(subject_salary=11251543)
        cycle = create_open_cycle(bundle, effective_date="2026-09-01")
        adj = create_draft_adjustment(bundle, cycle,
                                      proposed_amount_cents=100000)
        submitted = submit_adjustment(bundle, adj["id"])
        return bundle, adj, submitted

    def test_submit_freezes_compa_ratios_against_current_composite(self, api):
        """PRD §3.7: "On submission the system computes and freezes two
        compa-ratios in basis points."
        PRD §3.7: "`pre_adjustment_compa_ratio_bp` freezes this against the
        current salary, and `post_adjustment_compa_ratio_bp` freezes it with
        `proposed_amount_cents` added to that salary."

        Design: Difficulty/dual_variant_calc/recommended_adjustment_provisional_vs_final_on_market_adjustment
        """
        _, _, submitted = self._setup_frozen_adjustment(api)
        assert submitted["pre_adjustment_compa_ratio_bp"] == 11059, (
            f"11251543 * 10000 / 10173921 rounds half-up to 11059, got "
            f"{submitted['pre_adjustment_compa_ratio_bp']}")
        assert submitted["post_adjustment_compa_ratio_bp"] == 11157, (
            f"(11251543 + 100000) * 10000 / 10173921 rounds half-up to 11157, "
            f"got {submitted['post_adjustment_compa_ratio_bp']}")

    def test_superseding_publish_does_not_recompute_frozen_figures(self, api):
        """PRD §3.7: "The provisional figure is advisory only — it is never
        recomputed at approval, and the approved amount is whatever the
        proposer wrote in `proposed_amount_cents`, which may differ from the
        recommendation."
        PRD §3.8: "when a newer composite has superseded the submit-time one,
        the submit-time and finalize-time figures diverge, and that divergence
        is intentional."

        Design: Difficulty/dual_variant_calc/recommended_adjustment_provisional_vs_final_on_market_adjustment
        """
        bundle, adj, submitted = self._setup_frozen_adjustment(api)
        c1_id = bundle["composite"]["id"]
        # Publish a superseding composite C2 from a richer second benchmark
        # loaded under the same ACCEPTED survey. C2 must pin a different
        # strategy: PRD §3.6 rejects publishing while another PUBLISHED
        # composite for the same job shares the strategy_policy_id
        # (ERR_ALREADY_PUBLISHED), so supersession only ever occurs across
        # strategies.
        bench2 = add_benchmark(bundle, bundle["survey"], benchmark_code="B2",
                               p25_cents=12800000, p50_cents=16000000,
                               p75_cents=20000000, p90_cents=24000000,
                               sample_size=100)
        match2 = propose_match(bundle, bundle["survey"], bundle["job"], bench2)
        review_and_approve_match(bundle, match2["id"])
        strategy2 = add_successor_strategy(bundle)
        c2 = create_recomputed_composite(bundle, bundle["job"], strategy2)
        publish_composite(bundle, bundle["job"]["id"], c2["id"])

        job_after = get_job(bundle, bundle["job"]["id"])
        assert job_after["current_market_composite_id"] == c2["id"]
        assert get_composite(bundle, c1_id)["status"] == "SUPERSEDED"
        assert get_composite(bundle, c2["id"])["status"] == "PUBLISHED"

        adj_after = get_adjustment(bundle, adj["id"])
        assert adj_after["pre_adjustment_compa_ratio_bp"] == 11059, (
            "Submit-time compa-ratio is frozen against the submit-time "
            "composite and must not drift after supersession")
        assert adj_after["post_adjustment_compa_ratio_bp"] == 11157


class TestRetractOwnership:
    def test_retract_only_proposer_allowed(self, api):
        """PRD §2.9: "A related but distinct rule governs retraction: only the
        proposer of an adjustment may retract it, and a retract attempt by
        anyone else is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/retract_only_proposer_allowed
        """
        bundle = setup_published_job()
        analyst2 = get_success_data(api.create_employee(
            bundle["org"]["id"],
            {"full_name": "Analyst Two", "email": "a2@x.com",
             "job_id": bundle["job"]["id"], "geo_code": "US-SF",
             "base_salary_annual_cents": 10000000, "hire_date": "2024-01-01"},
            mgr_headers(bundle)))
        cycle = create_open_cycle(bundle)
        adj = create_draft_adjustment(bundle, cycle)
        submit_adjustment(bundle, adj["id"])
        resp = api.retract_adjustment(
            adj["id"], make_analyst_headers(analyst2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        adj_after = get_adjustment(bundle, adj["id"])
        assert adj_after["status"] == "PENDING_APPROVAL", (
            "A rejected retract must leave the adjustment PENDING_APPROVAL")
