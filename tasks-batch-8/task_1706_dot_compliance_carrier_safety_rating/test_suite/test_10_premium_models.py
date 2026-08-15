"""Insurance premium modeling: the BASELINE/PROJECTED dual variant, single
final rounding, loading caps, the DRAFT->QUOTED->STALE->DRAFT loop, closed
period overlap, and lifecycle guards."""
from test_helpers import (
    ApiErrorId,
    assert_premium_model,
    create_premium_model_payload,
    get_carrier,
    get_premium_model,
    make_carrier,
    make_premium_model,
    make_quoted_model,
    setup_loading_caps_case,
    setup_premium_dual_variant_case,
    setup_premium_recompute_conservation_case,
    setup_premium_rounding_case,
    setup_stale_requote_loop_case,
    validate_error,
    validate_success,
)


class TestPremiumDualVariant:
    def test_premium_baseline_uses_current_rating_and_counts(
        self, api, insurance_headers
    ):
        """PRD §3.9: "A `BASELINE` model uses the carrier's current
        `safety_rating`, the current alerted set, and the current
        preventable-accident count." and "`computed_premium_cents` is the base
        amount multiplied by the rating factor and by one plus the sum of the
        three loading percentages divided by one hundred, rounded half-up to a
        whole cent. This is the only rounding in the computation."

        Design: Difficulty/dual_variant_calc/premium_baseline_vs_projected
        """
        env = setup_premium_dual_variant_case()
        model = validate_success(
            api.create_premium_model(
                create_premium_model_payload(
                    env["carrier"]["id"], base_rate_cents_per_unit=123457,
                    scenario="BASELINE",
                ),
                insurance_headers,
            ),
            201,
        )
        assert_premium_model(model)
        # 3 units x 123457 = 370371; x 1.05 (NONE); loadings 3+5+2 = 10%.
        assert model["computed_premium_cents"] == 427779
        assert model["rating_factor_used"] == 1.05
        assert model["score_loading_pct"] == 3
        assert model["crash_loading_pct"] == 5
        assert model["driver_loading_pct"] == 2

    def test_premium_projected_applies_assume_overrides(self, api, insurance_headers):
        """PRD §3.9: "`assume_rating` (one of `NONE`, `SATISFACTORY`, or
        `CONDITIONAL` — `UNSATISFACTORY` is not modelable), which replaces the
        carrier's current rating factor; `assume_cleared_category_codes`, the
        list of category codes treated as below their intervention threshold;
        and `assume_removed_preventable_accidents`, the number of preventable
        accidents treated as removed from the in-window count." and
        "`driver_loading_pct` is two percentage points per driver of the carrier
        whose `employment_status` is `ACTIVE` and whose `risk_tier` is `HIGH`,
        capped at ten — identical in both scenarios."

        Design: Difficulty/dual_variant_calc/premium_baseline_vs_projected
        """
        env = setup_premium_dual_variant_case()
        baseline = validate_success(
            api.create_premium_model(
                create_premium_model_payload(env["carrier"]["id"], base_rate_cents_per_unit=123457),
                insurance_headers,
            ),
            201,
        )
        projected = validate_success(
            api.create_premium_model(
                create_premium_model_payload(
                    env["carrier"]["id"],
                    policy_period_start="2028-01-01T00:00:00Z",
                    policy_period_end="2028-12-31T00:00:00Z",
                    base_rate_cents_per_unit=123457,
                    scenario="PROJECTED",
                    assume_rating="SATISFACTORY",
                    assume_cleared_category_codes=["HOURS_OF_SERVICE"],
                    assume_removed_preventable_accidents=1,
                ),
                insurance_headers,
            ),
            201,
        )
        # 370371 x 1.00 x 1.02 = 377778.42 -> 377778.
        assert projected["computed_premium_cents"] == 377778
        assert projected["rating_factor_used"] == 1.00
        assert projected["score_loading_pct"] == 0
        assert projected["crash_loading_pct"] == 0
        assert projected["driver_loading_pct"] == 2
        assert baseline["computed_premium_cents"] != projected["computed_premium_cents"]


class TestPremiumRounding:
    def test_premium_single_final_rounding(self, api, insurance_headers):
        """PRD §2.9: "Premium amounts are integer cents with round-half-up
        applied exactly once, at the final step of the premium formula — no
        intermediate rounding occurs anywhere before it."
        PRD §3.9: "`computed_premium_cents` is the base amount multiplied by the
        rating factor and by one plus the sum of the three loading percentages
        divided by one hundred, rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/premium_single_final_rounding
        """
        env = setup_premium_rounding_case()
        model = validate_success(
            api.create_premium_model(
                create_premium_model_payload(
                    env["carrier"]["id"], base_rate_cents_per_unit=99990,
                    scenario="BASELINE",
                ),
                insurance_headers,
            ),
            201,
        )
        # 99990 x 1.05 x 1.10 = 115488.45 -> single final round half-up.
        assert model["computed_premium_cents"] == 115488
        assert model["computed_premium_cents"] != 115489, (
            "115489 would result from rounding components before the final step"
        )

    def test_premium_loading_components_recorded(self, api, insurance_headers):
        """PRD §3.9: "The rating factor is 1.05 for `NONE`, 1.00 for
        `SATISFACTORY`, 1.25 for `CONDITIONAL`, and 1.60 for `UNSATISFACTORY`"
        and "Creation records the computed `computed_premium_cents`, the three
        loadings, and `carrier_version_at_compute` — the carrier's `version` at
        the moment of computation — and the model lands in `DRAFT`."

        Design: Difficulty/combinatorial_formula/premium_single_final_rounding
        """
        env = setup_premium_rounding_case()
        model = validate_success(
            api.create_premium_model(
                create_premium_model_payload(
                    env["carrier"]["id"], base_rate_cents_per_unit=99990,
                    scenario="BASELINE",
                ),
                insurance_headers,
            ),
            201,
        )
        assert model["rating_factor_used"] == 1.05
        assert model["score_loading_pct"] == 3
        assert model["crash_loading_pct"] == 5
        assert model["driver_loading_pct"] == 2
        assert model["status"] == "DRAFT"


class TestPremiumLoadingCaps:
    def test_premium_loading_caps_applied(self, api, insurance_headers):
        """PRD §3.9: "`score_loading_pct` is three percentage points per
        category flagged `alerted_official` in the carrier's latest measurement
        cycle, capped at fifteen" ... "`crash_loading_pct` is five percentage
        points per accident on the carrier's register that is `PREVENTABLE`,
        DOT-reportable, and occurred within the thirty-six calendar months up to
        and including the computation instant, capped at twenty-five" ...
        "`driver_loading_pct` is two percentage points per driver of the carrier
        whose `employment_status` is `ACTIVE` and whose `risk_tier` is `HIGH`,
        capped at ten — identical in both scenarios."

        Design: Corner/calculations/premium_loading_caps_applied
        """
        env = setup_loading_caps_case()
        model = validate_success(
            api.create_premium_model(
                create_premium_model_payload(
                    env["carrier"]["id"], base_rate_cents_per_unit=100000,
                    scenario="BASELINE",
                ),
                insurance_headers,
            ),
            201,
        )
        assert model["score_loading_pct"] == 15, "7 alerted categories x 3, capped"
        assert model["crash_loading_pct"] == 25, "6 preventable accidents x 5, capped"
        assert model["driver_loading_pct"] == 10, "6 HIGH drivers x 2, capped"
        assert model["computed_premium_cents"] == 157500, "100000 x 1.05 x 1.50"


class TestPremiumLifecycle:
    def test_premium_model_stale_requote_loop(self, api, director_headers, insurance_headers):
        """PRD §2.8: "An insurance premium model in `QUOTED` status is swept to
        `STALE` — a derived-field reconciliation marker — whenever any of the
        following occurs for its carrier: the carrier profile is updated, the
        carrier's safety rating changes by audit close or upgrade approval, a
        new-entrant audit fails, a measurement cycle runs for the carrier, or
        one of the carrier's drivers changes `risk_tier`."
        PRD §3.8: "An approval writes the `requested_rating` into the carrier's
        `safety_rating`, clears `rating_cooling_off_until` to null, recomputes
        posture, sweeps the carrier's `QUOTED` premium models to `STALE`,
        increments the carrier's `version`, and stamps the request's
        `decided_at`."

        Design: Difficulty/non_linear_state_machine/premium_model_stale_requote_loop
        """
        env = setup_stale_requote_loop_case()
        model = env["model"]
        assert model["computed_premium_cents"] == 250000, "200000 x 1.25 CONDITIONAL"
        assert model["status"] == "QUOTED"

        validate_success(
            api.decide_upgrade(env["request"]["id"], {"outcome": "APPROVED"}, director_headers),
            200,
        )
        assert get_premium_model(model["id"])["status"] == "STALE"

        carrier = get_carrier(env["carrier"]["id"])
        assert carrier["safety_rating"] == "SATISFACTORY"
        assert carrier["rating_cooling_off_until"] is None

    def test_premium_requote_after_recompute_then_bind(self, api, director_headers, insurance_headers):
        """PRD §3.9: "Recomputation is the recovery path — and the refresh path
        for a still-valid draft: it is permitted from `STALE` or `DRAFT`
        (rejected from `QUOTED` or `BOUND` with `ERR_PREMIUM_MODEL_NOT_STALE`),
        re-validates the policy-period overlap excluding the model itself
        (`ERR_POLICY_PERIOD_OVERLAP`), recomputes the premium and loadings from
        current carrier data and the scenario overrides, refreshes
        `carrier_version_at_compute` to the carrier's current `version`, and
        leaves the model in `DRAFT`. Binding moves `QUOTED` → `BOUND`, requires
        the same freshness check (`ERR_PREMIUM_INPUT_STALE`), and is rejected
        from any status other than `QUOTED` with `ERR_PREMIUM_MODEL_NOT_QUOTED`."
        PRD §3.9: "The rating factor is 1.05 for `NONE`, 1.00 for
        `SATISFACTORY`, 1.25 for `CONDITIONAL`, and 1.60 for `UNSATISFACTORY`".

        Design: Difficulty/non_linear_state_machine/premium_model_stale_requote_loop
        """
        env = setup_stale_requote_loop_case()
        model = env["model"]
        validate_success(
            api.decide_upgrade(env["request"]["id"], {"outcome": "APPROVED"}, director_headers),
            200,
        )
        assert get_premium_model(model["id"])["status"] == "STALE"

        recomputed = validate_success(api.recompute_premium_model(model["id"], insurance_headers), 200)
        assert recomputed["status"] == "DRAFT"
        # Rating is now SATISFACTORY: 200000 x 1.00, no loadings.
        assert recomputed["computed_premium_cents"] == 200000

        quoted = validate_success(api.quote_premium_model(model["id"], insurance_headers), 200)
        assert quoted["status"] == "QUOTED"
        bound = validate_success(api.bind_premium_model(model["id"], insurance_headers), 200)
        assert bound["status"] == "BOUND"

    def test_premium_bind_from_draft_rejected(self, api, insurance_headers):
        """PRD §3.9: "Binding moves `QUOTED` → `BOUND`, requires the same
        freshness check (`ERR_PREMIUM_INPUT_STALE`), and is rejected from any
        status other than `QUOTED` with `ERR_PREMIUM_MODEL_NOT_QUOTED`."

        Design: Corner/state_machines/premium_bind_from_draft_rejected
        """
        carrier = make_carrier(dot_number="DOT-2108")
        model = make_premium_model(carrier["id"], base_rate_cents_per_unit=80000)
        assert model["status"] == "DRAFT"

        resp = api.bind_premium_model(model["id"], insurance_headers)
        validate_error(resp, ApiErrorId.ERR_PREMIUM_MODEL_NOT_QUOTED)
        assert get_premium_model(model["id"])["status"] == "DRAFT"

    def test_premium_quote_twice_and_recompute_quoted_rejected(
        self, api, insurance_headers
    ):
        """PRD §3.9: "Quoting moves `DRAFT` → `QUOTED` and is rejected from any
        other status with `ERR_PREMIUM_MODEL_NOT_DRAFT`." and recomputation "is
        permitted from `STALE` or `DRAFT` (rejected from `QUOTED` or `BOUND`
        with `ERR_PREMIUM_MODEL_NOT_STALE`)".

        Design: Corner/validations/premium_quote_twice_and_recompute_quoted_rejected
        """
        carrier = make_carrier(dot_number="DOT-2330")
        model = make_quoted_model(carrier["id"], base_rate_cents_per_unit=80000)
        assert model["status"] == "QUOTED"

        quote_again = api.quote_premium_model(model["id"], insurance_headers)
        validate_error(quote_again, ApiErrorId.ERR_PREMIUM_MODEL_NOT_DRAFT)

        recompute = api.recompute_premium_model(model["id"], insurance_headers)
        validate_error(recompute, ApiErrorId.ERR_PREMIUM_MODEL_NOT_STALE)


class TestPolicyPeriodOverlap:
    def test_policy_period_touching_closed_end_rejected(self, api, insurance_headers):
        """PRD §3.9: "the `policy_period_start` and `policy_period_end`
        bounding the period as a closed interval on both ends" and "Because the
        interval is closed, policy periods of the same carrier may not intersect
        among models in `DRAFT`, `QUOTED`, or `BOUND` — touching endpoints
        already count as overlap — and a conflicting model is rejected with
        `ERR_POLICY_PERIOD_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/policy_period_closed_interval_touching
        """
        carrier = make_carrier(dot_number="DOT-1016", fleet_size=1)
        make_premium_model(carrier["id"], base_rate_cents_per_unit=50000)

        touching = api.create_premium_model(
            create_premium_model_payload(
                carrier["id"],
                policy_period_start="2027-12-31T00:00:00Z",
                policy_period_end="2028-06-30T00:00:00Z",
                base_rate_cents_per_unit=50000,
            ),
            insurance_headers,
        )
        validate_error(touching, ApiErrorId.ERR_POLICY_PERIOD_OVERLAP)

    def test_policy_period_first_day_after_end_allowed(self, api, insurance_headers):
        """PRD §3.9: "Because the interval is closed, policy periods of the same
        carrier may not intersect among models in `DRAFT`, `QUOTED`, or `BOUND`
        — touching endpoints already count as overlap — and a conflicting model
        is rejected with `ERR_POLICY_PERIOD_OVERLAP`" — a period starting the
        day after the existing closed end does not intersect it.

        Design: Difficulty/resource_temporal_overlap/policy_period_closed_interval_touching
        """
        carrier = make_carrier(dot_number="DOT-1016", fleet_size=1)
        make_premium_model(carrier["id"], base_rate_cents_per_unit=50000)

        adjacent = api.create_premium_model(
            create_premium_model_payload(
                carrier["id"],
                policy_period_start="2028-01-01T00:00:00Z",
                policy_period_end="2028-12-31T00:00:00Z",
                base_rate_cents_per_unit=50000,
            ),
            insurance_headers,
        )
        assert validate_success(adjacent, 201)["status"] == "DRAFT"

    def test_premium_period_inverted_rejected(self, api, insurance_headers):
        """PRD §3.9: "The end must be later than the start, otherwise creation
        fails with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/premium_period_inverted_rejected
        """
        carrier = make_carrier(dot_number="DOT-2319", fleet_size=1)
        resp = api.create_premium_model(
            create_premium_model_payload(
                carrier["id"],
                policy_period_start="2027-06-01T00:00:00Z",
                policy_period_end="2027-06-01T00:00:00Z",
                base_rate_cents_per_unit=50000,
            ),
            insurance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestPremiumRecomputeConservation:
    def test_noop_patch_marks_quoted_model_stale(self, api, admin_headers):
        """PRD §3.1: "A `SafetyAdmin` may later update `legal_name` or
        `fleet_size` under optimistic concurrency (§2.7); each successful update
        increments the carrier's `version` and sweeps its `QUOTED` premium
        models to `STALE` (§2.8)."

        Design: Difficulty/compensating_invariant/premium_recompute_after_noop_stale_conserves_cents
        """
        env = setup_premium_recompute_conservation_case()
        carrier, model = env["carrier"], env["model"]
        assert model["computed_premium_cents"] == 210000, "200000 x 1.05, no loadings"

        patched = validate_success(
            api.patch_carrier(
                carrier["id"],
                {"legal_name": "Hauler Eighteen Renamed", "expected_carrier_version": 1},
                admin_headers,
            ),
            200,
        )
        assert patched["version"] == 2
        assert get_premium_model(model["id"])["status"] == "STALE"

    def test_recompute_restores_identical_premium(self, api, admin_headers, insurance_headers):
        """PRD §3.9: recomputation "recomputes the premium and loadings from
        current carrier data and the scenario overrides, refreshes
        `carrier_version_at_compute` to the carrier's current `version`, and
        leaves the model in `DRAFT`." With unchanged inputs the recomputed value
        is bit-identical to the pre-stale quote.

        Design: Difficulty/compensating_invariant/premium_recompute_after_noop_stale_conserves_cents
        """
        env = setup_premium_recompute_conservation_case()
        carrier, model = env["carrier"], env["model"]
        validate_success(
            api.patch_carrier(
                carrier["id"],
                {"legal_name": "Hauler Eighteen Renamed", "expected_carrier_version": 1},
                admin_headers,
            ),
            200,
        )
        assert get_premium_model(model["id"])["status"] == "STALE"

        recomputed = validate_success(api.recompute_premium_model(model["id"], insurance_headers), 200)
        assert recomputed["status"] == "DRAFT"
        assert recomputed["computed_premium_cents"] == 210000, (
            "no input drift => no value drift"
        )
        assert recomputed["carrier_version_at_compute"] == 2
