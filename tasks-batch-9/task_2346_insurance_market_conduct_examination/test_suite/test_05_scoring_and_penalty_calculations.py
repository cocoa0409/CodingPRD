"""Statutory arithmetic: surveillance ratios, composite scoring, sampling plans,
completeness penalties, error rates and the two penalty algorithms.

Every scenario is built from scratch through the API: the harness relaunches the
server before each test, so each test starts against an empty database.
"""

from test_helpers import (
    ANALYST,
    COORDINATOR,
    EIC,
    SUPERVISOR,
    ApiErrorId,
    assert_analysis_score,
    assert_collaboration,
    assert_consent_order,
    assert_criticism,
    assert_data_call,
    assert_file_sample,
    assert_insurer,
    assert_scope_area,
    build_reviews,
    bulk_review,
    collaboration_payload,
    create_analysis_cycle,
    disposition_data_call,
    disposition_payload,
    draft_consent_order,
    execute_consent_order,
    issue_criticism,
    issue_data_call,
    open_examination,
    propose_plan,
    read_collaboration,
    read_cycle_scores,
    read_data_call,
    read_examination,
    read_exposure_summary,
    read_file_samples,
    read_insurer,
    read_scope_area,
    record_standard_workpapers,
    refresh_market_data,
    register_insurer,
    respond_to_data_call,
    review_plan,
    score_cycle,
    select_targets,
    set_clock,
    setup_area_in_fieldwork,
    setup_examination_in_negotiation,
    setup_examination_in_order_pending,
    setup_locked_examination,
    validate_error,
    validate_paginated,
    validate_success,
)

# ── Shared scenario builders ───────────────────────────────────────────────


def _scores_by_insurer(cycle_id):
    """The cycle's score rows keyed by ``insurer_id``, plus the rank-ordered list."""
    rows = read_cycle_scores(cycle_id, {"limit": 100})
    return {row["insurer_id"]: row for row in rows}, rows


# ─── Complaint-ratio surveillance ──────────────────────────────────────────


class TestComplaintRatioAndRiskTier:
    def test_risk_tier_steps_only_below_each_inclusive_cut_point(self, api):
        """A fixed 100000-policy denominator walked across all three tier cuts.

        PRD §3.1: "Otherwise `risk_tier` is read off the rounded ratio: `HIGH` when the ratio is 5.00 or more, otherwise `ELEVATED` when it is 2.50 or more, otherwise `MODERATE` when it is 1.00 or more, otherwise `LOW`."
        PRD §3.1: "Each of those three comparisons is inclusive and each is made against the already-rounded ratio, not the unrounded quotient."
        PRD §3.1: "Every refresh re-derives `complaint_ratio_per_1k` and `risk_tier` by exactly the rule above and increments the carrier's `version` by 1."

        Design: Corner/calculations/complaint_ratio_tier_boundaries_walk_all_four_bands
        """
        insurer = register_insurer(
            policy_count_in_force=100_000, confirmed_complaints_12mo=500
        )
        assert_insurer(insurer)
        assert insurer["complaint_ratio_per_1k"] == 5.00
        assert insurer["risk_tier"] == "HIGH"
        assert insurer["version"] == 1

        walk = [
            (499, 4.99, "ELEVATED"),
            (250, 2.50, "ELEVATED"),
            (249, 2.49, "MODERATE"),
            (100, 1.00, "MODERATE"),
            (99, 0.99, "LOW"),
        ]
        for step, (complaints, ratio, tier) in enumerate(walk, start=1):
            refreshed = refresh_market_data(
                insurer["id"], confirmed_complaints_12mo=complaints
            )
            assert refreshed["complaint_ratio_per_1k"] == ratio, (
                f"{complaints} complaints over 100000 policies must round to {ratio}"
            )
            assert refreshed["risk_tier"] == tier
            assert refreshed["version"] == 1 + step

        assert read_insurer(insurer["id"])["version"] == 6

    def test_ratio_rounds_half_up_and_survives_a_zero_denominator(self, api):
        """0.625 must round up to 0.63, and a zero denominator yields UNRATED.

        PRD §3.1: "The complaint ratio is the trailing-twelve-month confirmed complaint count multiplied by one thousand and divided by policies in force, rounded half up to two decimal places, and stored as `complaint_ratio_per_1k`."
        PRD §3.1: "A carrier with no policies in force is not a division error: when `policy_count_in_force` is zero, `complaint_ratio_per_1k` is set to 0.00 and `risk_tier` is set to `UNRATED`, and nothing further is computed."

        Design: Corner/calculations/complaint_ratio_rounds_half_up_at_the_third_decimal
        """
        insurer = register_insurer(
            policy_count_in_force=1600, confirmed_complaints_12mo=1
        )
        # 1 x 1000 / 1600 == 0.625 exactly: half up carries the third decimal.
        assert insurer["complaint_ratio_per_1k"] == 0.63
        assert insurer["risk_tier"] == "LOW"

        exact_125 = refresh_market_data(insurer["id"], confirmed_complaints_12mo=2)
        assert exact_125["complaint_ratio_per_1k"] == 1.25
        assert exact_125["risk_tier"] == "MODERATE"

        exact_500 = refresh_market_data(insurer["id"], confirmed_complaints_12mo=8)
        assert exact_500["complaint_ratio_per_1k"] == 5.00
        assert exact_500["risk_tier"] == "HIGH"

        repeating = refresh_market_data(
            insurer["id"], confirmed_complaints_12mo=1, policy_count_in_force=3
        )
        assert repeating["complaint_ratio_per_1k"] == 333.33
        assert repeating["risk_tier"] == "HIGH"

        unrated = refresh_market_data(insurer["id"], policy_count_in_force=0)
        assert unrated["complaint_ratio_per_1k"] == 0.00
        assert unrated["risk_tier"] == "UNRATED"


# ─── Composite scoring ─────────────────────────────────────────────────────


class TestCompositeScoring:
    def test_withdrawn_carriers_receive_no_score_row_while_suspended_ones_do(
        self, api
    ):
        """Three carriers, two scored: WITHDRAWN drops out of the input set entirely.

        PRD §3.2: "The pass requires at least one carrier whose `license_status` is `LICENSED` or `SUSPENDED`; carriers whose status is `WITHDRAWN` are not scored at all and receive no score row."
        PRD §3.2: "First, a carrier whose `license_status` is anything other than `LICENSED` — that is, a `SUSPENDED` carrier that was scored but cannot be examined — is marked `LICENSE_INELIGIBLE`."
        PRD §3.2: "The evaluation order for `composite_score` is: round each of the three components to two decimals **first**, then add the three rounded components together, then multiply that sum by the volume multiplier, then round the product half up to two decimals, and only then hold the result to a ceiling of 100.00."

        Design: Corner/calculations/withdrawn_carriers_are_excluded_from_the_scoring_input_set
        """
        aurora = register_insurer(
            name="Aurora Mutual Insurance Company",
            naic_code="10001",
            annual_premium_written_cents=5_000_000_000,
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=500,
            financial_stress_score=100,
            consumer_trend_score=100,
        )
        boreal = register_insurer(
            name="Boreal Casualty Company",
            naic_code="10002",
            annual_premium_written_cents=1_200_000_000,
            policy_count_in_force=40_000,
            confirmed_complaints_12mo=120,
            financial_stress_score=60,
            consumer_trend_score=10,
            license_status="SUSPENDED",
        )
        cascade = register_insurer(
            name="Cascade Indemnity Group",
            naic_code="10003",
            annual_premium_written_cents=9_000_000_000,
            policy_count_in_force=200_000,
            confirmed_complaints_12mo=2_000,
            financial_stress_score=100,
            consumer_trend_score=100,
            license_status="WITHDRAWN",
        )
        cycle = create_analysis_cycle(
            cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=3
        )

        scored = score_cycle(cycle["id"])
        assert scored["status"] == "SCORED"
        assert scored["scored_insurer_count"] == 2

        rows, ranked = validate_paginated(
            api.list_cycle_scores(cycle["id"], ANALYST, {"limit": 100})
        )
        assert ranked["total_count"] == 2
        by_insurer = {row["insurer_id"]: row for row in rows}
        assert set(by_insurer) == {aurora["id"], boreal["id"]}

        aurora_score = by_insurer[aurora["id"]]
        assert_analysis_score(aurora_score)
        # 40 + 30.00 + 20.00 == 90.00, multiplied by the 1.10 volume multiplier.
        assert aurora_score["composite_score"] == 99.00
        assert aurora_score["rank_position"] == 1

        boreal_score = by_insurer[boreal["id"]]
        # 28 + 18.00 + 2.00 == 48.00, multiplied by 1.00.
        assert boreal_score["composite_score"] == 48.00
        assert boreal_score["rank_position"] == 2

        _, cascade_meta = validate_paginated(
            api.list_insurer_analysis_scores(
                cascade["id"], ANALYST, {"cycle_id": cycle["id"]}
            )
        )
        assert cascade_meta["total_count"] == 0

        selected = select_targets(cycle["id"])
        assert selected["selected_target_count"] == 1
        by_insurer, _ = _scores_by_insurer(cycle["id"])
        assert by_insurer[aurora["id"]]["selection_reason"] == "SELECTED"
        assert by_insurer[boreal["id"]]["selection_reason"] == "LICENSE_INELIGIBLE"

    def test_volume_multiplier_threshold_is_inclusive_and_scores_are_frozen(self, api):
        """One cent of premium separates 56.00 from 61.60 on an otherwise identical carrier.

        PRD §3.2: "The **volume multiplier** is 1.10 for a carrier whose `annual_premium_written_cents` is 5,000,000,000 cents (fifty million dollars) or more, and 1.00 otherwise; it is stored as `volume_multiplier`."
        PRD §3.2: "The **complaint component** is a tier lookup on the snapshotted ratio: 40 points when the ratio is 5.00 or more, otherwise 28 points when it is 2.50 or more, otherwise 16 points when it is 1.00 or more, otherwise 6 points; the result is stored as `complaint_component`."
        PRD §3.2: "The pass writes one `AnalysisScore` per scored carrier, each recording its `cycle_id` and `insurer_id` and snapshotting the carrier's current `complaint_ratio_per_1k` into `complaint_ratio_at_scoring`, so that later data refreshes cannot retroactively alter a completed scoring run."

        Design: Corner/calculations/volume_multiplier_boundary_is_inclusive_at_five_billion_cents
        """
        aurora = register_insurer(
            annual_premium_written_cents=4_999_999_999,
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=90,
            financial_stress_score=100,
            consumer_trend_score=100,
        )
        first_cycle = create_analysis_cycle(
            cycle_label="2026-H1-MARKET-ANALYSIS", target_slot_capacity=3
        )
        score_cycle(first_cycle["id"])

        below = read_cycle_scores(first_cycle["id"])[0]
        assert_analysis_score(below)
        assert below["volume_multiplier"] == 1.00
        assert below["complaint_component"] == 6.00
        assert below["financial_component"] == 30.00
        assert below["trend_component"] == 20.00
        assert below["composite_score"] == 56.00

        refresh_market_data(aurora["id"], annual_premium_written_cents=5_000_000_000)
        second_cycle = create_analysis_cycle(
            cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=3
        )
        score_cycle(second_cycle["id"])

        at_threshold = read_cycle_scores(second_cycle["id"])[0]
        assert at_threshold["volume_multiplier"] == 1.10
        assert at_threshold["composite_score"] == 61.60

        assert read_cycle_scores(first_cycle["id"])[0]["composite_score"] == 56.00

    def test_rank_ties_fall_through_to_created_at_ascending(self, api):
        """Three carriers collide on both ranking keys, so creation order decides.

        PRD §3.2: "Every score row also receives a 1-based `rank_position`, assigned by the cycle's ranking expression: `composite_score` descending, then `complaint_ratio_at_scoring` descending, then the score row's own `created_at` ascending."
        PRD §3.2: "The `created_at` tie-break is final; a record's `id` must never be consulted as a tie-break anywhere in this service."
        PRD §3.2: "Candidates the department ran out of slots for keep `selected` false and are marked `CAPACITY_EXHAUSTED`."

        Design: Corner/calculations/rank_ties_break_on_created_at_not_on_identifier
        """
        shared = dict(
            annual_premium_written_cents=1_000_000_000,
            policy_count_in_force=40_000,
            confirmed_complaints_12mo=100,
            financial_stress_score=50,
            consumer_trend_score=50,
        )
        xenia = register_insurer(
            name="Xenia Mutual Insurance Company", naic_code="10001", **shared
        )
        yarrow = register_insurer(
            name="Yarrow Casualty Company", naic_code="10002", **shared
        )
        zephyr = register_insurer(
            name="Zephyr Indemnity Company", naic_code="10003", **shared
        )
        cycle = create_analysis_cycle(
            cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=1
        )
        score_cycle(cycle["id"])

        selected = select_targets(cycle["id"])
        assert selected["selected_target_count"] == 1

        ranked = read_cycle_scores(cycle["id"], {"limit": 100})
        for row in ranked:
            assert_analysis_score(row)
            # 28 + 15.00 + 10.00 == 53.00, multiplied by 1.00.
            assert row["composite_score"] == 53.00
            assert row["complaint_ratio_at_scoring"] == 2.50
        assert [row["insurer_id"] for row in ranked] == [
            xenia["id"],
            yarrow["id"],
            zephyr["id"],
        ]
        assert [row["rank_position"] for row in ranked] == [1, 2, 3]
        assert ranked[0]["selection_reason"] == "SELECTED"
        assert ranked[0]["selected"] is True
        assert ranked[1]["selection_reason"] == "CAPACITY_EXHAUSTED"
        assert ranked[1]["selected"] is False
        assert ranked[2]["selection_reason"] == "CAPACITY_EXHAUSTED"
        assert ranked[2]["selected"] is False

        examinations, exam_meta = validate_paginated(
            api.list_examinations(SUPERVISOR, {"limit": 100})
        )
        assert exam_meta["total_count"] == 1
        assert examinations[0]["insurer_id"] == xenia["id"]

        _, xenia_meta = validate_paginated(
            api.list_insurer_analysis_scores(
                xenia["id"], ANALYST, {"selected": True}
            )
        )
        assert xenia_meta["total_count"] == 1

    def test_one_selection_pass_emits_every_selection_reason_exactly_once(self, api):
        """Five carriers shaped so one pass has to reach every declared reason.

        PRD §3.2: "Selection assigns a `selection_reason` to **every** score row of the cycle, never only to the winners, and the eligibility filter is evaluated in a fixed order so that reason is single-valued."
        PRD §3.2: "Second, a row whose `composite_score` is below the threshold is marked `BELOW_THRESHOLD`; a score exactly equal to the threshold survives."
        PRD §3.2: "Third, a carrier that already has an examination whose `status` is neither `PUBLISHED` nor `ABORTED`, and whose half-open fieldwork occupancy window from `fieldwork_start_date` inclusive to `fieldwork_end_date` exclusive overlaps the cycle's own half-open window from `default_fieldwork_start` inclusive to `default_fieldwork_end` exclusive, is marked `WINDOW_CONFLICT_DEFERRED`."
        PRD §3.2: "The candidate pool is then ranked by the same expression used for `rank_position` — `composite_score` descending, then `complaint_ratio_at_scoring` descending, then `created_at` ascending — and the department takes as many of the top-ranked rows as it has slots for: the smaller of `slots_available` and the size of the candidate pool."

        Design: Corner/calculations/target_selection_emits_all_five_selection_reasons_in_one_pass
        """
        aurora = register_insurer(
            name="Aurora Mutual Insurance Company",
            naic_code="10001",
            annual_premium_written_cents=1_200_000_000,
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=500,
            financial_stress_score=100,
            consumer_trend_score=100,
        )
        boreal = register_insurer(
            name="Boreal Casualty Company",
            naic_code="10002",
            annual_premium_written_cents=1_200_000_000,
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=250,
            financial_stress_score=100,
            consumer_trend_score=0,
        )
        cascade = register_insurer(
            name="Cascade Indemnity Group",
            naic_code="10003",
            annual_premium_written_cents=1_200_000_000,
            policy_count_in_force=40_000,
            confirmed_complaints_12mo=120,
            financial_stress_score=60,
            consumer_trend_score=10,
            license_status="SUSPENDED",
        )
        dunmore = register_insurer(
            name="Dunmore Reciprocal Exchange",
            naic_code="10004",
            annual_premium_written_cents=1_200_000_000,
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=90,
            financial_stress_score=50,
            consumer_trend_score=25,
        )
        estuary = register_insurer(
            name="Estuary Fire and Marine",
            naic_code="10005",
            annual_premium_written_cents=1_200_000_000,
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=300,
            financial_stress_score=100,
            consumer_trend_score=35,
        )
        # Boreal's live examination overlaps the cycle's own default window.
        open_examination(
            boreal["id"],
            fieldwork_start_date="2026-10-01",
            fieldwork_end_date="2026-12-31",
        )
        cycle = create_analysis_cycle(
            cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=1
        )
        scored = score_cycle(cycle["id"])
        assert scored["scored_insurer_count"] == 5

        selected = select_targets(cycle["id"])
        assert selected["status"] == "TARGETS_SELECTED"
        assert selected["selected_target_count"] == 1
        assert selected["slots_committed"] == 1
        assert selected["slots_available"] == 0

        by_insurer, ranked = _scores_by_insurer(cycle["id"])
        assert [row["composite_score"] for row in ranked] == [
            90.00,
            65.00,
            58.00,
            48.00,
            26.00,
        ]
        assert [row["rank_position"] for row in ranked] == [1, 2, 3, 4, 5]
        assert [row["insurer_id"] for row in ranked] == [
            aurora["id"],
            estuary["id"],
            boreal["id"],
            cascade["id"],
            dunmore["id"],
        ]
        assert by_insurer[aurora["id"]]["selection_reason"] == "SELECTED"
        assert by_insurer[estuary["id"]]["selection_reason"] == "CAPACITY_EXHAUSTED"
        assert by_insurer[boreal["id"]]["selection_reason"] == "WINDOW_CONFLICT_DEFERRED"
        assert by_insurer[cascade["id"]]["selection_reason"] == "LICENSE_INELIGIBLE"
        assert by_insurer[dunmore["id"]]["selection_reason"] == "BELOW_THRESHOLD"

        spawned, spawned_meta = validate_paginated(
            api.list_examinations(SUPERVISOR, {"cycle_id": cycle["id"], "limit": 100})
        )
        assert spawned_meta["total_count"] == 1
        assert spawned[0]["insurer_id"] == aurora["id"]

        exhausted, exhausted_meta = validate_paginated(
            api.list_cycle_scores(
                cycle["id"], ANALYST, {"selection_reason": "CAPACITY_EXHAUSTED"}
            )
        )
        assert exhausted_meta["total_count"] == 1
        assert exhausted[0]["composite_score"] == 65.00


# ─── Data-call completeness ────────────────────────────────────────────────


class TestEffectiveCompleteness:
    def test_late_penalty_floors_effective_completeness_at_zero(self, api):
        """A 259-day-late production drives the penalty far past the raw figure.

        PRD §3.4: "`completeness_pct` is `records_received` multiplied by one hundred and divided by `records_requested`, rounded half up to two decimals."
        PRD §3.4: "The lateness penalty is then applied to that **already-rounded** figure: half a percentage point is deducted for each day late, the result is rounded half up to two decimals again, and the outcome is floored at 0.00 before being stored as `effective_completeness_pct`."
        PRD §3.4: "`days_late` is the whole-day difference from `response_due_date` to the response date, floored at zero — a response on or before the due date yields 0 — and `is_late` is true exactly when `days_late` is 1 or more."
        PRD §3.4: "Accepting requires that `effective_completeness_pct` be at least 95.00; below that figure the acceptance is rejected with `ERR_RESPONSE_INCOMPLETE`, and a value of exactly 95.00 is accepted."
        PRD §3.4: "Rejecting draws no samples at all and never advances the examination into `FIELDWORK`."

        Design: Corner/calculations/late_penalty_floors_effective_completeness_at_zero
        """
        scenario = setup_locked_examination(areas=(("CLAIMS", 4000, 10),))
        data_call = issue_data_call(
            scenario["scope_area_id"],
            records_requested=4000,
            response_due_date="2026-09-15",
        )

        swept = set_clock("2027-06-01T00:00:00Z", SUPERVISOR)
        assert swept["data_calls_flagged_overdue"] == 1
        assert read_data_call(data_call["id"])["status"] == "OVERDUE"

        responded = respond_to_data_call(
            data_call["id"], scenario["insurer_id"], records_received=3700
        )
        assert_data_call(responded)
        assert responded["status"] == "RESPONDED"
        assert responded["is_late"] is True
        assert responded["days_late"] == 259
        # 3700 of 4000 == 92.50 raw; 259 x 0.5 == 129.50 of penalty clamps to 0.00.
        assert responded["completeness_pct"] == 92.50
        assert responded["effective_completeness_pct"] == 0.00

        validate_error(
            api.disposition_data_call(
                data_call["id"],
                disposition_payload(
                    "ACCEPTED",
                    disposition_reason=(
                        "Examiner attempts acceptance despite the late penalty."
                    ),
                ),
                EIC,
            ),
            ApiErrorId.ERR_RESPONSE_INCOMPLETE.value,
        )

        rejected = disposition_data_call(
            data_call["id"],
            "REJECTED",
            disposition_reason=(
                "Production is materially incomplete after the late penalty."
            ),
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["samples_drawn_count"] == 0

        area = read_scope_area(scenario["scope_area_id"])
        assert area["reviewed_sample_count"] == 0
        _, samples_meta = validate_paginated(
            api.list_file_samples(data_call["id"], EIC)
        )
        assert samples_meta["total_count"] == 0

        examination = read_examination(scenario["exam_id"])
        assert examination["rejected_data_call_count"] == 1
        assert examination["status"] == "DATA_CALL"


# ─── Sampling plans ────────────────────────────────────────────────────────


class TestSampleDrawPlan:
    def test_desk_examination_draws_both_interval_geometries_and_both_prefixes(
        self, api
    ):
        """A DESK examination with a degenerate interval 1 area beside an interval 50 area.

        PRD §3.3: "Statutory minimum sample sizes depend on the examination's `mode`: an `ON_SITE` examination requires a `sample_size` of at least 10, a `DESK` examination at least 5, and a smaller figure is rejected with `ERR_SAMPLE_SIZE_BELOW_MINIMUM` at HTTP 422."
        PRD §3.5: "The draw interval is the population size divided by the sample size, discarding any fractional part, and is stored on the call as `sample_draw_interval`; because `sample_size` never exceeds `population_size`, the interval is always 1 or more."
        PRD §3.5: "The plan then walks the sample positions in order: the first sampled file sits at `population_index` 1, and each subsequent file sits one draw interval further along, so the k-th file after the first sits at 1 plus k times the interval."
        PRD §3.5: "The prefixes are `UW` for `UNDERWRITING`, `RT` for `RATING`, `CLM` for `CLAIMS` and `PRD` for `PRODUCER`, so the four-hundred-and-first file of a claims population is labelled `CLM-000401`."
        PRD §3.5: "Each starts with `review_status` of `UNREVIEWED`, `error_severity` of `NONE`, `underpaid_amount_cents` of 0 and `days_to_pay` of 0."

        Design: Corner/calculations/sample_draw_plan_on_a_desk_examination_uses_the_lower_minimum_and_area_prefixes
        """
        scenario = setup_locked_examination(
            areas=(
                ("PRODUCER", 7, 5),
                ("RATING", 500, 10),
                ("UNDERWRITING", 100, 5),
            ),
            mode="DESK",
        )
        assert scenario["scope_areas"]["PRODUCER"]["sample_size"] == 5
        assert scenario["scope_areas"]["UNDERWRITING"]["sample_size"] == 5

        producer_call = issue_data_call(
            scenario["scope_areas"]["PRODUCER"]["id"],
            records_requested=7,
            response_due_date="2026-09-15",
        )
        respond_to_data_call(
            producer_call["id"], scenario["insurer_id"], records_received=7
        )
        producer_call = disposition_data_call(producer_call["id"], "ACCEPTED")
        assert producer_call["sample_draw_interval"] == 1
        assert producer_call["samples_drawn_count"] == 5
        assert producer_call["completeness_pct"] == 100.00
        assert producer_call["effective_completeness_pct"] == 100.00

        producer_samples = read_file_samples(producer_call["id"])
        assert [s["file_reference"] for s in producer_samples] == [
            "PRD-000001",
            "PRD-000002",
            "PRD-000003",
            "PRD-000004",
            "PRD-000005",
        ]
        assert [s["population_index"] for s in producer_samples] == [1, 2, 3, 4, 5]
        for sample in producer_samples:
            assert_file_sample(sample)
            assert sample["review_status"] == "UNREVIEWED"
            assert sample["error_severity"] == "NONE"
            assert sample["underpaid_amount_cents"] == 0
            assert sample["days_to_pay"] == 0

        assert read_examination(scenario["exam_id"])["status"] == "FIELDWORK"

        rating_call = issue_data_call(
            scenario["scope_areas"]["RATING"]["id"],
            records_requested=500,
            response_due_date="2026-09-15",
        )
        respond_to_data_call(
            rating_call["id"], scenario["insurer_id"], records_received=500
        )
        rating_call = disposition_data_call(rating_call["id"], "ACCEPTED")
        assert rating_call["sample_draw_interval"] == 50
        assert rating_call["samples_drawn_count"] == 10

        rating_samples = read_file_samples(rating_call["id"])
        assert [s["file_reference"] for s in rating_samples] == [
            "RT-000001",
            "RT-000051",
            "RT-000101",
            "RT-000151",
            "RT-000201",
            "RT-000251",
            "RT-000301",
            "RT-000351",
            "RT-000401",
            "RT-000451",
        ]

        underwriting_call = issue_data_call(
            scenario["scope_areas"]["UNDERWRITING"]["id"],
            records_requested=90,
            response_due_date="2026-09-15",
        )
        respond_to_data_call(
            underwriting_call["id"], scenario["insurer_id"], records_received=90
        )
        underwriting_call = disposition_data_call(
            underwriting_call["id"],
            "REJECTED",
            disposition_reason=(
                "Underwriting production omits the rated-territory extract."
            ),
        )
        assert underwriting_call["samples_drawn_count"] == 0
        _, underwriting_meta = validate_paginated(
            api.list_file_samples(underwriting_call["id"], EIC)
        )
        assert underwriting_meta["total_count"] == 0


# ─── Error rates and exposure ──────────────────────────────────────────────


class TestErrorRateDivergence:
    def test_minor_only_area_breaches_tolerance_without_escalating(self, api):
        """Three MINOR errors: 30.00 overall, 0.00 material, and SAMPLE_ACTUAL exposure.

        PRD §3.5: "`error_rate_pct` is `error_count` multiplied by one hundred and divided by `reviewed_sample_count`, rounded half up to two decimals, or 0.00 when nothing has been reviewed; `material_error_rate_pct` is the same computation over `material_error_count`."
        PRD §3.5: "`tolerance_breached` is true when `error_rate_pct` is greater than or equal to the area's own `error_tolerance_pct`; an error rate exactly equal to the tolerance breaches it."
        PRD §3.5: "`escalation_required` is true when `material_error_rate_pct` is greater than or equal to 10.00 percent; again exact equality escalates."
        PRD §3.6: "Both operands carry weight: a `MATERIAL` criticism on a within-tolerance area remains `SAMPLE_ACTUAL`, and a `MINOR` criticism on a breached area also remains `SAMPLE_ACTUAL`."
        PRD §3.6: "Under `SAMPLE_ACTUAL`, `restitution_exposure_cents` equals the observed sample harm exactly — the summed underpayment across the area's error files — and the unexamined remainder of the population is not charged."

        Design: Corner/calculations/error_rate_and_material_rate_diverge_on_a_minor_only_area
        """
        scenario = setup_area_in_fieldwork(
            area="CLAIMS", population_size=4000, sample_size=10
        )
        record_standard_workpapers(scenario["exam_id"], "CLAIMS")

        result = bulk_review(
            scenario["data_call_id"],
            build_reviews(
                scenario["file_references"], (10_000, 9_000, 6_000), "MINOR"
            ),
        )
        assert result["applied_count"] == 10
        assert result["skipped_count"] == 0
        assert result["reviewed_sample_count"] == 10
        assert result["error_rate_pct"] == 30.00
        assert result["material_error_rate_pct"] == 0.00
        assert result["tolerance_breached"] is True
        assert result["escalation_required"] is False
        assert result["scope_area_status"] == "TESTED"

        area = read_scope_area(scenario["scope_area_id"])
        assert_scope_area(area)
        assert area["error_count"] == 3
        assert area["material_error_count"] == 0
        assert area["error_rate_pct"] == 30.00
        assert area["material_error_rate_pct"] == 0.00
        assert area["error_tolerance_pct"] == 3.00
        assert area["tolerance_breached"] is True
        assert area["escalation_required"] is False
        assert area["status"] == "TESTED"
        assert read_examination(scenario["exam_id"])["status"] == "CRITICISM"

        criticism = issue_criticism(
            scenario["exam_id"],
            scenario["scope_area_id"],
            "MINOR",
            3,
            statute_citation="NRS 686A.310(1)(n)",
        )
        assert_criticism(criticism)
        assert criticism["restitution_method"] == "SAMPLE_ACTUAL"
        assert criticism["restitution_exposure_cents"] == 25_000


# ─── Penalty determination ─────────────────────────────────────────────────


class TestPenaltyDetermination:
    def test_tiered_waterfall_reaches_the_third_rate_slice(self, api):
        """30,000,000 cents of restitution puts weight in all three tiered slices.

        PRD §3.6: "Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`."
        PRD §3.8: "The first 5,000,000 cents of restitution form the first tier; the next 20,000,000 cents form the second tier; everything beyond the first 25,000,000 cents forms the third tier."
        PRD §3.8: "Each tier's amount is multiplied by its own rate — one tenth for the first tier, six hundredths for the second, three hundredths for the third — and **each of those three products is rounded half up to a whole cent individually before the three are added together**."
        PRD §3.8: "To that sum is added a flat base of 100,000 cents for each `SUSTAINED` criticism on the examination, that is, 100,000 cents multiplied by `sustained_criticism_count`."
        PRD §3.8: "The **per-violation** algorithm ignores restitution size entirely: the gross penalty is the examination's `penalty_units_total` multiplied by 25,000 cents (250 dollars per statutory violation unit)."
        PRD §3.8: "Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise."
        PRD §3.8: "Step two: an order subtotal is formed as the restitution aggregate plus that gross penalty; this subtotal is an intermediate that is never persisted on the order."

        Design: Corner/calculations/tiered_penalty_reaches_the_third_rate_slice
        """
        scenario = setup_examination_in_negotiation(
            criticism_severity="MATERIAL",
            affected_file_count=3,
            penalty_units=40,
            harm_cents=(30_000, 25_000, 20_000),
        )
        criticism = scenario["criticism"]
        assert criticism["restitution_method"] == "POPULATION_EXTRAPOLATED"
        # (30000 + 25000 + 20000) / 10 == 7500 cents average, x 4000 population.
        assert criticism["restitution_exposure_cents"] == 30_000_000

        examination = scenario["examination"]
        assert examination["aggregate_restitution_cents"] == 30_000_000
        assert examination["penalty_units_total"] == 40
        assert examination["sustained_criticism_count"] == 1

        summary = read_exposure_summary(scenario["exam_id"])
        assert summary["aggregate_restitution_cents"] == 30_000_000
        assert summary["penalty_units_total"] == 40
        assert summary["sustained_criticism_count"] == 1
        assert summary["per_violation_penalty_gross_cents"] == 1_000_000
        assert summary["per_violation_cooperation_credit_pct"] == 0.15
        assert summary["per_violation_penalty_net_cents"] == 850_000
        assert summary["per_violation_order_total_cents"] == 30_850_000
        assert summary["tiered_penalty_gross_cents"] == 1_950_000
        assert summary["tiered_cooperation_credit_pct"] == 0.15
        assert summary["tiered_penalty_net_cents"] == 1_657_500
        assert summary["tiered_order_total_cents"] == 31_657_500

        _, orders_meta = validate_paginated(
            api.list_consent_orders(scenario["exam_id"], SUPERVISOR)
        )
        assert orders_meta["total_count"] == 0

        plan = propose_plan(scenario["exam_id"], scenario["insurer_id"])
        review_plan(plan["id"], "APPROVE")

        order = draft_consent_order(
            scenario["exam_id"],
            order_number="NV-MC-2026-0042",
            penalty_variant="TIERED_AGGREGATE",
        )
        assert_consent_order(order)
        assert order["status"] == "DRAFT"
        assert order["penalty_variant"] == "TIERED_AGGREGATE"
        assert order["restitution_cents"] == 30_000_000
        assert order["penalty_gross_cents"] == 1_950_000
        assert order["cooperation_credit_pct"] == 0.15
        assert order["penalty_net_cents"] == 1_657_500
        assert order["order_total_cents"] == 31_657_500
        assert "order_subtotal_cents" not in order
        assert "order_subtotal" not in order

        stored = validate_success(api.get_consent_order(order["id"], EIC))
        assert stored["status"] == "DRAFT"
        assert stored["penalty_variant"] == "TIERED_AGGREGATE"
        assert stored["order_total_cents"] == 31_657_500

    def test_redrafting_the_other_variant_voids_the_first_order_untouched(self, api):
        """Two variants over one 20,132,000-cent aggregate share a 0.05 credit.

        PRD §3.8: "Drafting voids any existing `DRAFT` order on the examination — that order moves to `VOIDED` and has its `version` incremented by 1 — records `drafted_by_user_id` from `X-User-ID` as the segregation-of-duties key, opens the new order in `DRAFT`, and increments the examination's `version` by 1."
        PRD §3.8: "Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent."
        PRD §3.8: "Step five: `order_total_cents` is the restitution aggregate plus the net penalty."
        PRD §3.8: "The credit tier must be derived from the **gross** subtotal and never from a net figure; for orders whose subtotal straddles 25,000,000 cents, deriving it from net selects the wrong tier."
        PRD §3.8: "Execution stamps `executed_at` from the logical clock, moves the order to `EXECUTED`, increments the order's `version` by 1, and raises the subject carrier's `lifetime_restitution_ordered_cents` by the order's frozen `restitution_cents`."

        Design: Corner/calculations/consent_order_variant_reconciliation_voids_the_superseded_draft
        """
        scenario = setup_examination_in_order_pending()
        # (25000 + 18000 + 7333) / 10 rounds to a 5033-cent average, x 4000 population.
        assert scenario["examination"]["aggregate_restitution_cents"] == 20_132_000
        assert scenario["examination"]["penalty_units_total"] == 20

        per_violation = draft_consent_order(
            scenario["exam_id"],
            order_number="NV-MC-2026-0042",
            penalty_variant="PER_VIOLATION",
        )
        assert_consent_order(per_violation)
        assert per_violation["penalty_gross_cents"] == 500_000
        assert per_violation["cooperation_credit_pct"] == 0.05
        assert per_violation["penalty_net_cents"] == 475_000
        assert per_violation["order_total_cents"] == 20_607_000

        tiered = draft_consent_order(
            scenario["exam_id"],
            order_number="NV-MC-2026-0043",
            penalty_variant="TIERED_AGGREGATE",
        )
        assert_consent_order(tiered)
        # 500000 at one tenth + 907920 at six hundredths + nothing in the tail
        # + 100000 of flat base for the single sustained criticism.
        assert tiered["penalty_gross_cents"] == 1_507_920
        assert tiered["cooperation_credit_pct"] == 0.05
        assert tiered["penalty_net_cents"] == 1_432_524
        assert tiered["order_total_cents"] == 21_564_524
        assert tiered["status"] == "DRAFT"

        voided = validate_success(api.get_consent_order(per_violation["id"], SUPERVISOR))
        assert voided["status"] == "VOIDED"
        assert voided["order_total_cents"] == 20_607_000
        assert voided["penalty_gross_cents"] == 500_000
        assert voided["version"] == per_violation["version"] + 1

        _, orders_meta = validate_paginated(
            api.list_consent_orders(scenario["exam_id"], SUPERVISOR, {"limit": 100})
        )
        assert orders_meta["total_count"] == 2

        executed = execute_consent_order(tiered["id"], scenario["insurer_id"])
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at"]
        assert read_insurer(scenario["insurer_id"])[
            "lifetime_restitution_ordered_cents"
        ] == 20_132_000
        assert read_examination(scenario["exam_id"])["status"] == "ORDER_PENDING"


# ─── Lead-state election ───────────────────────────────────────────────────


class TestLeadStateElection:
    def test_lead_election_filters_on_resources_then_ranks_then_breaks_the_tie(
        self, api
    ):
        """Three panels: a filtered-out giant, an unresourced roster, and a tie.

        PRD §3.9: "Only participants whose `has_examiner_resources` is true are eligible."
        PRD §3.9: "Eligible participants are ranked by `policy_count_in_state` descending, and ties are broken by `state_code` ascending in plain lexicographic order on the two-letter code."
        PRD §3.9: "If no participant has examiner resources, the request is rejected with `ERR_NO_ELIGIBLE_LEAD_STATE` at HTTP 422 and **no** collaboration row is created."
        PRD §3.9: "The collaboration records `participant_count` as the roster's length, opens in `LEAD_ASSIGNED` with `allocated_total_cents` of 0, and elects its own `lead_state_code`."

        Design: Corner/calculations/lead_state_selection_ranks_only_resourced_states_and_refuses_an_unresourced_panel
        """
        carriers = [
            register_insurer(
                name="Aurora Mutual Insurance Company", naic_code="10001"
            ),
            register_insurer(name="Boreal Casualty Company", naic_code="10002"),
            register_insurer(name="Cascade Indemnity Group", naic_code="10003"),
        ]
        exams = [open_examination(carrier["id"]) for carrier in carriers]

        panel_a = validate_success(
            api.open_collaboration(
                exams[0]["id"],
                collaboration_payload(
                    [
                        {
                            "state_code": "NV",
                            "policy_count_in_state": 40_000,
                            "has_examiner_resources": True,
                        },
                        {
                            "state_code": "UT",
                            "policy_count_in_state": 90_000,
                            "has_examiner_resources": False,
                        },
                    ],
                    call_reference="NAIC-CAWG-2026-0201",
                ),
                COORDINATOR,
            ),
            201,
        )
        assert_collaboration(panel_a)
        assert panel_a["lead_state_code"] == "NV"
        assert panel_a["participant_count"] == 2
        assert panel_a["status"] == "LEAD_ASSIGNED"
        assert panel_a["allocated_total_cents"] == 0
        for participant in panel_a["participating_states"]:
            assert participant["allocated_cents"] == 0

        validate_error(
            api.open_collaboration(
                exams[1]["id"],
                collaboration_payload(
                    [
                        {
                            "state_code": "AZ",
                            "policy_count_in_state": 50_000,
                            "has_examiner_resources": False,
                        },
                        {
                            "state_code": "UT",
                            "policy_count_in_state": 30_000,
                            "has_examiner_resources": False,
                        },
                    ],
                    call_reference="NAIC-CAWG-2026-0202",
                ),
                COORDINATOR,
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_LEAD_STATE.value,
        )
        _, panel_b_meta = validate_paginated(
            api.list_collaborations(exams[1]["id"], COORDINATOR)
        )
        assert panel_b_meta["total_count"] == 0

        panel_c = validate_success(
            api.open_collaboration(
                exams[2]["id"],
                collaboration_payload(
                    [
                        {
                            "state_code": "NV",
                            "policy_count_in_state": 30_000,
                            "has_examiner_resources": True,
                        },
                        {
                            "state_code": "AZ",
                            "policy_count_in_state": 30_000,
                            "has_examiner_resources": True,
                        },
                    ],
                    call_reference="NAIC-CAWG-2026-0203",
                ),
                COORDINATOR,
            ),
            201,
        )
        assert panel_c["lead_state_code"] == "AZ"
        assert read_collaboration(panel_c["id"])["lead_state_code"] == "AZ"

        for exam in exams:
            assert read_examination(exam["id"])["status"] == "SCOPING"
