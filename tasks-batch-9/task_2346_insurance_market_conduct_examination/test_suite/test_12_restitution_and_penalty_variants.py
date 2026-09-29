"""Restitution-method and penalty-variant divergence.

Every scenario in this module is built from scratch through the API: the harness
relaunches the server before each test, so each test starts against an empty
database.
"""

from test_helpers import (
    DEFAULT_HARM_CENTS,
    EIC,
    SUPERVISING_EXAMINER_ID,
    SUPERVISOR,
    assert_analysis_cycle,
    assert_analysis_score,
    assert_consent_order,
    assert_criticism,
    assert_scope_area,
    build_reviews,
    bulk_review,
    consent_order_payload,
    criticism_payload,
    disposition_data_call,
    issue_data_call,
    read_criticism,
    read_cycle,
    read_cycle_scores,
    read_examination,
    read_insurer,
    read_scope_area,
    record_standard_workpapers,
    respond_to_data_call,
    setup_examination_in_criticism,
    setup_examination_in_negotiation,
    setup_examination_in_order_pending,
    setup_locked_examination,
    setup_scored_cycle,
    systematic_file_references,
    validate_success,
)

# The sample harm that drives the 24,000,000-cent extrapolated exposure: three
# MATERIAL files quantifying 30000 + 20000 + 10000 cents over ten reviewed files.
ROUND_HARM_CENTS = (30_000, 20_000, 10_000)


def _examination_with_two_identically_sampled_areas():
    """One examination, two areas carrying byte-identical sample harm.

    CLAIMS keeps the statutory 3.00 percent tolerance; UNDERWRITING overrides its
    tolerance to 40.00 percent.  Both areas draw ten files from a population of
    4000 and both are reviewed with the same three MATERIAL underpayments, so the
    only difference between them is the tolerance.
    """
    scenario = setup_locked_examination(
        areas=(("CLAIMS", 4000, 10), ("UNDERWRITING", 4000, 10)),
        area_overrides={"UNDERWRITING": {"error_tolerance_pct": 40.00}},
    )
    record_standard_workpapers(scenario["exam_id"], "CLAIMS")
    for area in ("CLAIMS", "UNDERWRITING"):
        area_id = scenario["scope_areas"][area]["id"]
        data_call = issue_data_call(
            area_id, records_requested=4000, response_due_date="2026-09-15"
        )
        respond_to_data_call(
            data_call["id"], scenario["insurer_id"], records_received=4000
        )
        disposition_data_call(data_call["id"], "ACCEPTED")
        bulk_review(
            data_call["id"],
            build_reviews(
                systematic_file_references(area, 4000, 10),
                DEFAULT_HARM_CENTS,
                "MATERIAL",
            ),
        )
    scenario["claims_area_id"] = scenario["scope_areas"]["CLAIMS"]["id"]
    scenario["underwriting_area_id"] = scenario["scope_areas"]["UNDERWRITING"]["id"]
    scenario["claims_area"] = read_scope_area(scenario["claims_area_id"])
    scenario["underwriting_area"] = read_scope_area(scenario["underwriting_area_id"])
    return scenario


# ─── Tolerance-driven restitution-method divergence ────────────────────────


class TestToleranceDrivenRestitutionDivergence:
    def test_identical_samples_diverge_only_on_the_area_tolerance_flag(self, api):
        """The two areas hold the same reviewed files, so only the tolerance moves.

        PRD §3.5: "`error_rate_pct` is `error_count` multiplied by one hundred and divided by `reviewed_sample_count`, rounded half up to two decimals, or 0.00 when nothing has been reviewed; `material_error_rate_pct` is the same computation over `material_error_count`."
        PRD §3.5: "`tolerance_breached` is true when `error_rate_pct` is greater than or equal to the area's own `error_tolerance_pct`; an error rate exactly equal to the tolerance breaches it."
        PRD §3.3: "An optional `error_tolerance_pct` between 0.00 and 100.00 inclusive overrides the statutory default; when it is omitted the default is read from the per-area statutory table — 7.00 percent for `UNDERWRITING`, 5.00 percent for `RATING`, 3.00 percent for `CLAIMS` and 10.00 percent for `PRODUCER`."

        Design: Difficulty/dual_variant_calc/restitution_variant_divergence_driven_by_scope_area_tolerance
        """
        scenario = _examination_with_two_identically_sampled_areas()
        claims = scenario["claims_area"]
        underwriting = scenario["underwriting_area"]
        assert_scope_area(claims)
        assert_scope_area(underwriting)

        assert claims["error_tolerance_pct"] == 3.00
        assert underwriting["error_tolerance_pct"] == 40.00
        assert claims["reviewed_sample_count"] == 10
        assert underwriting["reviewed_sample_count"] == 10
        assert claims["error_count"] == 3
        assert underwriting["error_count"] == 3
        assert claims["error_rate_pct"] == 30.00
        assert underwriting["error_rate_pct"] == 30.00
        assert claims["tolerance_breached"] is True
        assert underwriting["tolerance_breached"] is False

    def test_material_criticisms_split_on_tolerance_into_two_restitution_methods(
        self, api
    ):
        """Same severity, same sample harm, two methods and a 400x exposure gap.

        PRD §3.6: "The method is `POPULATION_EXTRAPOLATED` when the `severity` is `EGREGIOUS`, or when the `severity` is `MATERIAL` **and** the area's `tolerance_breached` is true. In every other case the method is `SAMPLE_ACTUAL`."
        PRD §3.6: "Both operands carry weight: a `MATERIAL` criticism on a within-tolerance area remains `SAMPLE_ACTUAL`, and a `MINOR` criticism on a breached area also remains `SAMPLE_ACTUAL`."
        PRD §3.6: "Under `SAMPLE_ACTUAL`, `restitution_exposure_cents` equals the observed sample harm exactly — the summed underpayment across the area's error files — and the unexamined remainder of the population is not charged."

        Design: Difficulty/dual_variant_calc/restitution_variant_divergence_driven_by_scope_area_tolerance
        """
        scenario = _examination_with_two_identically_sampled_areas()

        breached = validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"],
                    scenario["claims_area_id"],
                    "MATERIAL",
                    3,
                ),
                EIC,
            ),
            201,
        )
        within = validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"],
                    scenario["underwriting_area_id"],
                    "MATERIAL",
                    3,
                ),
                EIC,
            ),
            201,
        )
        assert_criticism(breached)
        assert_criticism(within)

        assert breached["restitution_method"] == "POPULATION_EXTRAPOLATED"
        assert breached["restitution_exposure_cents"] == 20132000
        assert within["restitution_method"] == "SAMPLE_ACTUAL"
        assert within["restitution_exposure_cents"] == 50333
        assert (
            breached["restitution_exposure_cents"]
            != within["restitution_exposure_cents"]
        )

    def test_both_frozen_exposures_accumulate_into_pending_restitution(self, api):
        """Issuance moves each frozen exposure onto the examination's provisional total.

        PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."
        PRD §3.6: "The base figure is the sum of `underpaid_amount_cents` across the file samples of the criticism's own scope area whose `review_status` is `ERROR`; samples belonging to other areas of the same examination are excluded entirely."

        Design: Difficulty/dual_variant_calc/restitution_variant_divergence_driven_by_scope_area_tolerance
        """
        scenario = _examination_with_two_identically_sampled_areas()

        validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["claims_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            201,
        )
        validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["underwriting_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            201,
        )

        examination = read_examination(scenario["exam_id"])
        assert examination["open_criticism_count"] == 2
        assert examination["pending_restitution_cents"] == 20182333
        assert examination["aggregate_restitution_cents"] == 0


# ─── Penalty-variant divergence across the cooperation-credit tier ─────────


class TestPenaltyVariantFlipsCooperationCreditTier:
    def test_per_violation_variant_lands_below_the_credit_threshold(self, api):
        """Restitution 24,000,000 plus a 500,000 gross penalty stays under the tier.

        PRD §3.8: "The **per-violation** algorithm ignores restitution size entirely: the gross penalty is the examination's `penalty_units_total` multiplied by 25,000 cents (250 dollars per statutory violation unit)."
        PRD §3.8: "Step two: an order subtotal is formed as the restitution aggregate plus that gross penalty; this subtotal is an intermediate that is never persisted on the order. Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise. Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent. Step five: `order_total_cents` is the restitution aggregate plus the net penalty."

        Design: Difficulty/dual_variant_calc/penalty_variant_divergence_flips_cooperation_credit_tier
        """
        scenario = setup_examination_in_negotiation(
            harm_cents=ROUND_HARM_CENTS, penalty_units=20
        )
        examination = scenario["examination"]
        assert examination["status"] == "NEGOTIATION"
        assert examination["aggregate_restitution_cents"] == 24000000
        assert examination["penalty_units_total"] == 20

        summary = validate_success(api.get_exposure_summary(scenario["exam_id"], SUPERVISOR))
        assert summary["per_violation_penalty_gross_cents"] == 500000
        assert summary["per_violation_cooperation_credit_pct"] == 0.05
        assert summary["per_violation_penalty_net_cents"] == 475000
        assert summary["per_violation_order_total_cents"] == 24475000

    def test_tiered_variant_pushes_the_same_examination_over_the_credit_threshold(
        self, api
    ):
        """The tiered gross penalty carries the subtotal past 25,000,000 cents.

        PRD §3.8: "The **tiered-aggregate** algorithm ignores violation units entirely and instead runs a waterfall over the restitution aggregate."
        PRD §3.8: "Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise. Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent. Step five: `order_total_cents` is the restitution aggregate plus the net penalty."

        Design: Difficulty/dual_variant_calc/penalty_variant_divergence_flips_cooperation_credit_tier
        """
        scenario = setup_examination_in_negotiation(
            harm_cents=ROUND_HARM_CENTS, penalty_units=20
        )
        criticism = read_criticism(scenario["criticism_id"])
        assert criticism["restitution_method"] == "POPULATION_EXTRAPOLATED"
        assert criticism["restitution_exposure_cents"] == 24000000

        summary = validate_success(api.get_exposure_summary(scenario["exam_id"], SUPERVISOR))
        assert summary["tiered_penalty_gross_cents"] == 1740000
        assert summary["tiered_cooperation_credit_pct"] == 0.15
        assert summary["tiered_penalty_net_cents"] == 1479000
        assert summary["tiered_order_total_cents"] == 25479000

    def test_the_two_variants_report_different_credit_rates_side_by_side(self, api):
        """The variant choice changes the credit rate itself, not just its base.

        PRD §3.8: "Because the two variants can differ enormously for the same examination, a supervising examiner or multistate coordinator may ask for both side by side without persisting either."
        PRD §3.8: "That computed read reports `{ examination_id, sustained_criticism_count, aggregate_restitution_cents, penalty_units_total, per_violation_penalty_gross_cents, per_violation_cooperation_credit_pct, per_violation_penalty_net_cents, per_violation_order_total_cents, tiered_penalty_gross_cents, tiered_cooperation_credit_pct, tiered_penalty_net_cents, tiered_order_total_cents }`, applying the same five-step chain independently to each variant."

        Design: Difficulty/dual_variant_calc/penalty_variant_divergence_flips_cooperation_credit_tier
        """
        scenario = setup_examination_in_negotiation(
            harm_cents=ROUND_HARM_CENTS, penalty_units=20
        )

        summary = validate_success(api.get_exposure_summary(scenario["exam_id"], SUPERVISOR))
        assert summary["examination_id"] == scenario["exam_id"]
        assert summary["sustained_criticism_count"] == 1
        assert summary["aggregate_restitution_cents"] == 24000000
        assert summary["penalty_units_total"] == 20
        assert (
            summary["tiered_cooperation_credit_pct"]
            != summary["per_violation_cooperation_credit_pct"]
        )
        assert (
            summary["tiered_order_total_cents"]
            - summary["per_violation_order_total_cents"]
            == 1004000
        )


# ─── Severity-driven restitution-method divergence on one breached area ────


class TestSeveritySelectsRestitutionMethodOnBreachedArea:
    def test_minor_criticism_on_a_breached_area_stays_sample_actual(self, api):
        """A MINOR finding is not extrapolated even where the tolerance is breached.

        PRD §3.6: "Both operands carry weight: a `MATERIAL` criticism on a within-tolerance area remains `SAMPLE_ACTUAL`, and a `MINOR` criticism on a breached area also remains `SAMPLE_ACTUAL`."
        PRD §3.6: "Under `SAMPLE_ACTUAL`, `restitution_exposure_cents` equals the observed sample harm exactly — the summed underpayment across the area's error files — and the unexamined remainder of the population is not charged."

        Design: Difficulty/dual_variant_calc/criticism_severity_selects_sample_actual_on_a_breached_area
        """
        scenario = setup_examination_in_criticism()
        area = read_scope_area(scenario["scope_area_id"])
        assert area["tolerance_breached"] is True

        minor = validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["scope_area_id"], "MINOR", 1
                ),
                EIC,
            ),
            201,
        )
        assert_criticism(minor)
        assert minor["severity"] == "MINOR"
        assert minor["restitution_method"] == "SAMPLE_ACTUAL"
        assert minor["restitution_exposure_cents"] == 50333

    def test_material_criticism_on_the_same_breached_area_extrapolates(self, api):
        """Severity alone flips the selector while tolerance_breached stays true.

        PRD §3.6: "The method is `POPULATION_EXTRAPOLATED` when the `severity` is `EGREGIOUS`, or when the `severity` is `MATERIAL` **and** the area's `tolerance_breached` is true. In every other case the method is `SAMPLE_ACTUAL`."
        PRD §3.6: "For identical sample data, extrapolation yields an exposure orders of magnitude larger than the sample-actual figure."

        Design: Difficulty/dual_variant_calc/criticism_severity_selects_sample_actual_on_a_breached_area
        """
        scenario = setup_examination_in_criticism()
        area = read_scope_area(scenario["scope_area_id"])
        assert area["tolerance_breached"] is True

        minor = validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["scope_area_id"], "MINOR", 1
                ),
                EIC,
            ),
            201,
        )
        material = validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            201,
        )
        assert_criticism(material)
        assert material["restitution_method"] == "POPULATION_EXTRAPOLATED"
        assert material["restitution_exposure_cents"] == 20132000
        assert (
            material["restitution_exposure_cents"]
            > minor["restitution_exposure_cents"]
        )

    def test_both_severities_on_one_area_sum_into_pending_restitution(self, api):
        """The two divergent exposures accrue side by side on the examination.

        PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."

        Design: Difficulty/dual_variant_calc/criticism_severity_selects_sample_actual_on_a_breached_area
        """
        scenario = setup_examination_in_criticism()

        validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["scope_area_id"], "MINOR", 1
                ),
                EIC,
            ),
            201,
        )
        validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            201,
        )

        examination = read_examination(scenario["exam_id"])
        assert examination["open_criticism_count"] == 2
        assert examination["pending_restitution_cents"] == 20182333


# ─── Composite score: tier lookup, component ceiling and volume multiplier ─


class TestCompositeScoreStacksTiersCapsAndMultiplier:
    def _carriers(self):
        """A large-premium high-complaint carrier alongside a smaller one."""
        return [
            {
                "name": "Granite Casualty Insurance Company",
                "naic_code": "10007",
                "annual_premium_written_cents": 6_000_000_000,
                "policy_count_in_force": 50_000,
                "confirmed_complaints_12mo": 300,
                "financial_stress_score": 100,
                "consumer_trend_score": 100,
            },
            {},
        ]

    def test_top_tier_carrier_stacks_component_ceiling_and_volume_multiplier(self, api):
        """Ratio 6.00 tiers to 40, the financial component sits at its 30.00 ceiling.

        PRD §3.1: "The complaint ratio is the trailing-twelve-month confirmed complaint count multiplied by one thousand and divided by policies in force, rounded half up to two decimal places, and stored as `complaint_ratio_per_1k`."
        PRD §3.2: "The **complaint component** is a tier lookup on the snapshotted ratio: 40 points when the ratio is 5.00 or more, otherwise 28 points when it is 2.50 or more, otherwise 16 points when it is 1.00 or more, otherwise 6 points; the result is stored as `complaint_component`. The **financial component** is the carrier's `financial_stress_score` multiplied by three tenths, rounded half up to two decimals, then held to a ceiling of 30.00, and stored as `financial_component`. The **trend component** is the carrier's `consumer_trend_score` multiplied by two tenths, rounded half up to two decimals, then held to a ceiling of 30.00, and stored as `trend_component`. The **volume multiplier** is 1.10 for a carrier whose `annual_premium_written_cents` is 5,000,000,000 cents (fifty million dollars) or more, and 1.00 otherwise; it is stored as `volume_multiplier`."
        PRD §3.2: "The evaluation order for `composite_score` is: round each of the three components to two decimals **first**, then add the three rounded components together, then multiply that sum by the volume multiplier, then round the product half up to two decimals, and only then hold the result to a ceiling of 100.00."

        Design: Difficulty/combinatorial_formula/composite_score_stacks_tier_two_caps_and_volume_multiplier
        """
        scenario = setup_scored_cycle(carriers=self._carriers())
        granite = read_insurer(scenario["insurers"][0]["id"])
        assert granite["complaint_ratio_per_1k"] == 6.00
        assert granite["risk_tier"] == "HIGH"

        scores = read_cycle_scores(scenario["cycle_id"])
        row = next(s for s in scores if s["insurer_id"] == granite["id"])
        assert_analysis_score(row)
        assert row["complaint_ratio_at_scoring"] == 6.00
        assert row["complaint_component"] == 40
        assert row["financial_component"] == 30.00
        assert row["trend_component"] == 20.00
        assert row["volume_multiplier"] == 1.10
        assert row["composite_score"] == 99.00
        assert row["composite_score"] != 90.00

    def test_below_threshold_premium_carrier_takes_the_neutral_multiplier(self, api):
        """A 1,200,000,000-cent carrier scores its raw component sum unscaled.

        PRD §3.2: "The **volume multiplier** is 1.10 for a carrier whose `annual_premium_written_cents` is 5,000,000,000 cents (fifty million dollars) or more, and 1.00 otherwise; it is stored as `volume_multiplier`."
        PRD §3.2: "The evaluation order for `composite_score` is: round each of the three components to two decimals **first**, then add the three rounded components together, then multiply that sum by the volume multiplier, then round the product half up to two decimals, and only then hold the result to a ceiling of 100.00."

        Design: Difficulty/combinatorial_formula/composite_score_stacks_tier_two_caps_and_volume_multiplier
        """
        scenario = setup_scored_cycle(carriers=self._carriers())
        aurora = read_insurer(scenario["insurers"][1]["id"])
        assert aurora["complaint_ratio_per_1k"] == 3.00
        assert aurora["risk_tier"] == "ELEVATED"

        scores = read_cycle_scores(scenario["cycle_id"])
        row = next(s for s in scores if s["insurer_id"] == aurora["id"])
        assert_analysis_score(row)
        assert row["complaint_component"] == 28
        assert row["financial_component"] == 18.00
        assert row["trend_component"] == 10.00
        assert row["volume_multiplier"] == 1.00
        assert row["composite_score"] == 56.00

    def test_scoring_ranks_by_composite_and_leaves_selection_untouched(self, api):
        """The higher composite ranks first and the slot ledger is not consumed.

        PRD §3.2: "Every score row also receives a 1-based `rank_position`, assigned by the cycle's ranking expression: `composite_score` descending, then `complaint_ratio_at_scoring` descending, then the score row's own `created_at` ascending."
        PRD §3.2: "On completion the cycle records `scored_insurer_count`, stamps `scored_at` from the logical clock, moves to `SCORED` and increments its own `version` by 1."
        PRD §3.2: "A new cycle opens in `DRAFT` with `slots_committed` at 0, `slots_available` equal to `target_slot_capacity`, and `scored_insurer_count` and `selected_target_count` both 0."

        Design: Difficulty/combinatorial_formula/composite_score_stacks_tier_two_caps_and_volume_multiplier
        """
        scenario = setup_scored_cycle(carriers=self._carriers())
        granite_id = scenario["insurers"][0]["id"]
        aurora_id = scenario["insurers"][1]["id"]

        scores = read_cycle_scores(scenario["cycle_id"])
        by_insurer = {s["insurer_id"]: s for s in scores}
        assert by_insurer[granite_id]["rank_position"] == 1
        assert by_insurer[aurora_id]["rank_position"] == 2

        cycle = read_cycle(scenario["cycle_id"])
        assert_analysis_cycle(cycle)
        assert cycle["status"] == "SCORED"
        assert cycle["scored_insurer_count"] == 2
        assert cycle["scored_at"] is not None
        assert cycle["selected_target_count"] == 0
        assert cycle["slots_available"] == 2


# ─── Extrapolation rounding order ─────────────────────────────────────────


class TestExtrapolatedRestitutionRoundingOrder:
    def test_per_file_average_is_rounded_before_it_is_scaled_to_the_population(
        self, api
    ):
        """50333 over 10 files rounds to 5033 a file, then scales to 20,132,000.

        PRD §3.6: "Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`."
        PRD §3.6: "The rounding order is pinned: dividing, multiplying, and rounding only at the end is a different number and is explicitly not the rule."

        Design: Difficulty/combinatorial_formula/extrapolated_restitution_pins_average_first_rounding_order
        """
        scenario = setup_examination_in_criticism()
        area = read_scope_area(scenario["scope_area_id"])
        assert area["reviewed_sample_count"] == 10
        assert area["population_size"] == 4000
        assert area["tolerance_breached"] is True

        criticism = validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            201,
        )
        assert_criticism(criticism)
        assert criticism["restitution_method"] == "POPULATION_EXTRAPOLATED"
        assert criticism["restitution_exposure_cents"] == 20132000
        assert criticism["restitution_exposure_cents"] != 20133200
        assert criticism["restitution_exposure_cents"] != 20132400
        assert criticism["restitution_exposure_cents"] != 20120000

    def test_the_frozen_extrapolated_exposure_is_the_examination_pending_total(
        self, api
    ):
        """The single frozen exposure is exactly what pending restitution carries.

        PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."
        PRD §3.6: "The reviewed-sample denominator is that area's `reviewed_sample_count`, which is guaranteed to be at least 1 because the area must be `TESTED`."

        Design: Difficulty/combinatorial_formula/extrapolated_restitution_pins_average_first_rounding_order
        """
        scenario = setup_examination_in_criticism()

        validate_success(
            api.issue_criticism(
                criticism_payload(
                    scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            201,
        )

        examination = read_examination(scenario["exam_id"])
        assert examination["pending_restitution_cents"] == 20132000
        assert examination["aggregate_restitution_cents"] == 0


# ─── Consent order: the five-step credit chain keyed on the gross subtotal ─


class TestConsentOrderCreditTierKeyedOnSubtotal:
    def test_tiered_gross_penalty_rounds_each_tier_slice_and_adds_the_base(self, api):
        """5,000,000 at a tenth plus 19,000,000 at six hundredths plus one 100,000 base.

        PRD §3.8: "`restitution_cents` is a snapshot of the examination's `aggregate_restitution_cents`, which by construction reflects `SUSTAINED` criticisms only — criticisms still in `ISSUED` or `RESPONDED`, and criticisms that were `WITHDRAWN`, contribute nothing to it, nor to `penalty_units_total`, nor to `sustained_criticism_count`."
        PRD §3.8: "The first 5,000,000 cents of restitution form the first tier; the next 20,000,000 cents form the second tier; everything beyond the first 25,000,000 cents forms the third tier. Each tier's amount is multiplied by its own rate — one tenth for the first tier, six hundredths for the second, three hundredths for the third — and **each of those three products is rounded half up to a whole cent individually before the three are added together**. To that sum is added a flat base of 100,000 cents for each `SUSTAINED` criticism on the examination, that is, 100,000 cents multiplied by `sustained_criticism_count`."

        Design: Difficulty/combinatorial_formula/consent_order_credit_tier_is_keyed_on_subtotal_not_restitution
        """
        scenario = setup_examination_in_order_pending(
            harm_cents=ROUND_HARM_CENTS, penalty_units=20
        )
        assert scenario["plan"]["status"] == "APPROVED"
        assert scenario["plan"]["revision_round"] == 1
        assert scenario["examination"]["status"] == "ORDER_PENDING"

        order = validate_success(
            api.draft_consent_order(
                scenario["exam_id"],
                consent_order_payload(
                    scenario["examination"]["version"],
                    "MC-2026-0001",
                    "TIERED_AGGREGATE",
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert_consent_order(order)
        assert order["restitution_cents"] == 24000000
        assert order["penalty_gross_cents"] == 1740000

    def test_cooperation_credit_tier_is_derived_from_the_gross_subtotal(self, api):
        """Restitution alone is 24,000,000; only the subtotal reaches the 15% tier.

        PRD §3.8: "Step two: an order subtotal is formed as the restitution aggregate plus that gross penalty; this subtotal is an intermediate that is never persisted on the order. Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise. Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent."
        PRD §3.8: "The credit tier must be derived from the **gross** subtotal and never from a net figure; for orders whose subtotal straddles 25,000,000 cents, deriving it from net selects the wrong tier."

        Design: Difficulty/combinatorial_formula/consent_order_credit_tier_is_keyed_on_subtotal_not_restitution
        """
        scenario = setup_examination_in_order_pending(
            harm_cents=ROUND_HARM_CENTS, penalty_units=20
        )

        order = validate_success(
            api.draft_consent_order(
                scenario["exam_id"],
                consent_order_payload(
                    scenario["examination"]["version"],
                    "MC-2026-0001",
                    "TIERED_AGGREGATE",
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert order["cooperation_credit_pct"] == 0.15
        assert order["cooperation_credit_pct"] != 0.05
        assert order["penalty_net_cents"] == 1479000
        assert order["penalty_net_cents"] != 1653000

    def test_order_total_is_restitution_plus_the_net_penalty(self, api):
        """Step five closes the chain and the draft records its drafter.

        PRD §3.8: "Step five: `order_total_cents` is the restitution aggregate plus the net penalty."
        PRD §3.8: "Drafting voids any existing `DRAFT` order on the examination — that order moves to `VOIDED` and has its `version` incremented by 1 — records `drafted_by_user_id` from `X-User-ID` as the segregation-of-duties key, opens the new order in `DRAFT`, and increments the examination's `version` by 1."

        Design: Difficulty/combinatorial_formula/consent_order_credit_tier_is_keyed_on_subtotal_not_restitution
        """
        scenario = setup_examination_in_order_pending(
            harm_cents=ROUND_HARM_CENTS, penalty_units=20
        )

        order = validate_success(
            api.draft_consent_order(
                scenario["exam_id"],
                consent_order_payload(
                    scenario["examination"]["version"],
                    "MC-2026-0001",
                    "TIERED_AGGREGATE",
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert order["order_total_cents"] == 25479000
        assert order["order_total_cents"] == (
            order["restitution_cents"] + order["penalty_net_cents"]
        )
        assert order["status"] == "DRAFT"
        assert order["drafted_by_user_id"] == SUPERVISING_EXAMINER_ID
