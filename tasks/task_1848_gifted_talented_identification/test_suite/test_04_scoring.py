"""Measure entry, composite scoring, and cut determination."""
import pytest

from test_helpers import (
    CLOCK_TODAY,
    TEST_USERS,
    ApiErrorId,
    advance_cycle,
    api_client,
    assert_gifted_case,
    create_case,
    create_measure_score_payload,
    create_site,
    create_student,
    create_transfer_honor_case,
    enter_measure,
    finalize_case,
    get_case,
    get_student,
    set_clock,
    setup_cycle_in_state,
    setup_scored_case,
    validate_error,
    validate_success,
)

GC = TEST_USERS["gifted_coordinator_headers"]


class TestDualVariantScoring:
    def test_standard_variant_routes_to_band_review(self, api):
        """PRD §3.4: "The scoring variant is `TWICE_EXCEPTIONAL` when the
        student's `has_active_sped_plan` is true at finalize time, else
        `STANDARD`, and is stored on the case as `scored_variant`."
        PRD §3.4: "Routing follows the freshly computed integer composite,
        compared against the variant-appropriate thresholds — `cut_score_2e`
        and `review_band_floor_2e` for `TWICE_EXCEPTIONAL`, `cut_score` and
        `review_band_floor` for `STANDARD`".

        Design: Difficulty/dual_variant_calc/composite_standard_vs_twice_exceptional
        """
        ctx = setup_scored_case(99, 90, 88)  # no SpedPlan -> STANDARD
        case = ctx["case"]
        assert case["scored_variant"] == "STANDARD"
        # 99*(0.4/0.9)=44.00; 90*(0.3/0.9)=30.00; 88*(0.2/0.9)=19.56;
        # sum 93.56 -> 94. 88 <= 94 < 95 -> AWAITING_COMMITTEE.
        assert case["composite_score"] == 94
        assert case["status"] == "AWAITING_COMMITTEE"
        assert get_student(ctx["student"]["id"])["gifted_status"] == "NOT_IDENTIFIED"

    def test_twice_exceptional_variant_substitutes_max_and_uses_2e_cut(self, api):
        """PRD §3.4: "Under the twice-exceptional variant only, the effective
        ability percentile and the effective achievement percentile both become
        the larger of the two raw percentiles — recognition that a disability
        can suppress either instrument — while every other effective
        percentile equals its raw value."

        Design: Difficulty/dual_variant_calc/composite_standard_vs_twice_exceptional
        """
        ctx = setup_scored_case(99, 90, 88, with_sped_plan=True,
                                student_overrides={"demographic_group": "HISPANIC"})
        case = ctx["case"]
        assert case["scored_variant"] == "TWICE_EXCEPTIONAL"
        # effective ability = achievement = max(99, 90) = 99:
        # 99*(0.4/0.9)=44.00; 99*(0.3/0.9)=33.00; 88*(0.2/0.9)=19.56;
        # sum 96.56 -> 97 >= cut_score_2e 90 -> IDENTIFIED.
        assert case["composite_score"] == 97
        assert case["status"] == "IDENTIFIED"
        assert case["decided_on"] == "2026-08-20"
        assert get_student(ctx["student"]["id"])["gifted_status"] == "IDENTIFIED"


class TestPinnedRoundingOrder:
    def test_composite_uses_per_line_rounding_then_sum(self, api):
        """PRD §2.7: "in particular, the composite score rounds each measure's
        contribution first and then rounds the sum of those rounded
        contributions, which can differ from rounding the unrounded sum; the
        per-line order is the only correct one."

        Design: Difficulty/combinatorial_formula/composite_per_measure_rounding_then_sum
        """
        ctx = setup_scored_case(
            90.0, 88.0, 76.0, portfolio=73.3,
            profile_overrides={
                "label": "P4", "ability_weight": 0.35, "achievement_weight": 0.25,
                "rating_weight": 0.25, "portfolio_weight": 0.15,
                "cut_score": 85, "review_band_floor": 80,
                "cut_score_2e": 80, "review_band_floor_2e": 75,
            },
            student_overrides={"demographic_group": "ASIAN"})
        case = ctx["case"]
        # Per-line: 90*0.35=31.50, 88*0.25=22.00, 76*0.25=19.00,
        # 73.3*0.15=10.995 -> 11.00; sum 83.50 -> 84.
        # Sum-then-round of the raw products (83.495) would give 83.
        assert case["composite_score"] == 84, (
            "composite must follow per-line-first rounding (84), not "
            "sum-then-round (83)")
        assert case["status"] == "AWAITING_COMMITTEE"

    def test_portfolio_line_rounds_half_up_to_two_decimals(self, api):
        """PRD §3.4: "Each present measure's `weighted_contribution` is then
        its effective percentile multiplied by its normalized weight, rounded
        half-up to two decimal places, and stored on the `MeasureScore` row."

        Design: Difficulty/combinatorial_formula/composite_per_measure_rounding_then_sum
        """
        ctx = setup_scored_case(
            90.0, 88.0, 76.0, portfolio=73.3,
            profile_overrides={
                "label": "P4", "ability_weight": 0.35, "achievement_weight": 0.25,
                "rating_weight": 0.25, "portfolio_weight": 0.15,
                "cut_score": 85, "review_band_floor": 80,
                "cut_score_2e": 80, "review_band_floor_2e": 75,
            },
            student_overrides={"demographic_group": "ASIAN"})
        resp = api.list_measure_scores(ctx["case"]["id"], GC)
        rows = validate_success(resp, 200)
        by_type = {m["measure_type"]: m for m in rows}
        portfolio = by_type["PORTFOLIO"]
        # 73.3 * 0.15 = 10.995 rounds half-up to 11.00.
        assert float(portfolio["weighted_contribution"]) == pytest.approx(11.00, abs=1e-9)
        assert float(by_type["ABILITY"]["weighted_contribution"]) == pytest.approx(31.50, abs=1e-9)
        assert float(by_type["RATING_SCALE"]["weighted_contribution"]) == pytest.approx(19.00, abs=1e-9)


class TestCutScoreBoundaries:
    def test_composite_at_cut_score_boundary_identified(self, api):
        """PRD §3.4: "Composite at or above the cut — equality identifies —
        routes `SCREENING` → `IDENTIFIED`: `decided_on` becomes today and the
        student's `gifted_status` becomes `IDENTIFIED`."

        Design: Difficulty/boundary_precision_check/composite_at_cut_score_boundary_identified
        """
        ctx = setup_scored_case(95, 95, 95)  # no PORTFOLIO
        case = ctx["case"]
        # 95*(0.4/0.9)=42.22 (42.2222 -> 42.22), 95*(0.3/0.9)=31.67
        # (31.6667 -> 31.67), 95*(0.2/0.9)=21.11 (21.1111 -> 21.11);
        # sum = 95.00 -> 95 == cut_score 95.
        assert case["composite_score"] == 95
        assert case["status"] == "IDENTIFIED"
        assert case["decided_on"] == "2026-08-20"
        assert get_student(ctx["student"]["id"])["gifted_status"] == "IDENTIFIED"

    def test_composite_at_floor_boundary_enters_review(self, api):
        """PRD §3.4: "Composite at or above the review-band floor but below
        the cut — equality enters review — routes `SCREENING` →
        `AWAITING_COMMITTEE`, storing `composite_score` and `scored_variant`."

        Design: Difficulty/boundary_precision_check/composite_at_cut_score_boundary_identified
        """
        # All-equal percentiles p give composite == p (weights renormalize to
        # sum 1): p=88 lands exactly on review_band_floor 88.
        ctx = setup_scored_case(88, 88, 88)
        case = ctx["case"]
        assert case["composite_score"] == 88
        assert case["status"] == "AWAITING_COMMITTEE"
        assert case["scored_variant"] == "STANDARD"


class TestCompositeFormula:
    def test_low_portfolio_drags_composite_below_floor(self, api):
        """PRD §3.4: "`PORTFOLIO` is optional, and its absence shrinks the
        normalization base rather than failing the case."
        PRD §3.4: "Composite below the floor routes `SCREENING` →
        `NOT_IDENTIFIED`, with `decided_on` set to today."

        Design: Corner/calculations/low_portfolio_drags_composite_below_floor
        """
        ctx = setup_scored_case(
            96, 94, 88, portfolio=40,
            profile_overrides={"label": "PF89", "review_band_floor": 89})
        case = ctx["case"]
        # Weights sum to 1.0 with PORTFOLIO present:
        # 96*0.40=38.40 + 94*0.30=28.20 + 88*0.20=17.60 + 40*0.10=4.00 = 88.20
        # -> 88, below the floor of 89.
        assert case["composite_score"] == 88
        assert case["status"] == "NOT_IDENTIFIED"
        assert case["decided_on"] == "2026-08-20"

    def test_finalize_response_reflects_mutation_immediately(self, api):
        """PRD §2.8: "The platform maintains three families of derived values,
        all refreshed synchronously inside the same request that mutates their
        inputs — there is no eventual consistency."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/finalize_response_reflects_mutation_immediately
        """
        ctx = setup_scored_case(99, 90, 88)
        fin = ctx["finalized"]
        assert fin["composite_score"] == 94
        assert fin["status"] == "AWAITING_COMMITTEE"
        assert fin["scored_variant"] == "STANDARD"


class TestMeasureEntryRules:
    def test_measure_entry_after_identification_rejected(self, api):
        """PRD §3.4: "While a case is in `SCREENING` and its cycle is `OPEN`
        or `SCORING` (any other cycle state — `ERR_INVALID_CYCLE_STATE`; a
        case no longer in `SCREENING` — `ERR_INVALID_CASE_STATE`), a
        `GiftedCoordinator` enters `MeasureScore` rows".

        Design: Corner/state_machines/measure_entry_after_identification_rejected
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        case = create_transfer_honor_case(student["id"], cycle["id"])
        assert case["status"] == "IDENTIFIED"
        resp = api.create_measure_score(
            case["id"],
            create_measure_score_payload(
                measure_type="ABILITY", percentile=95,
                administered_on="2026-08-20"),
            GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE.value)

    def test_percentile_out_of_range_rejected(self, api):
        """PRD §2.5: "The request-shape tier (priority 5) covers, across the
        mutation endpoints: percentiles between 1.0 and 99.9 inclusive with
        one decimal place".

        Design: Corner/validations/percentile_out_of_range_rejected
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        case = create_case(student["id"], cycle["id"],
                           pathway="UNIVERSAL_SCREEN")
        resp = api.create_measure_score(
            case["id"],
            create_measure_score_payload(
                measure_type="ABILITY", percentile=100.0,
                administered_on="2026-08-20"),
            GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_incomplete_measures_finalize_rejected(self, api):
        """PRD §3.4: "The required set is `ABILITY`, `ACHIEVEMENT`, and
        `RATING_SCALE`; if any of the three is missing, the finalize fails
        with `ERR_INCOMPLETE_MEASURES`."

        Design: Corner/validations/incomplete_measures_finalize_rejected
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        case = create_case(student["id"], cycle["id"],
                           pathway="UNIVERSAL_SCREEN")
        enter_measure(case["id"], "ABILITY", 95)
        enter_measure(case["id"], "ACHIEVEMENT", 95)
        advance_cycle(cycle["id"], "SCORING")
        resp = api.finalize_scoring(case["id"], GC)
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_MEASURES.value)
        after = get_case(case["id"])
        assert after["status"] == "SCREENING"
        assert after["composite_score"] is None

    def test_duplicate_measure_beats_stale_validity(self, api):
        """PRD §3.4: "Each case holds at most one score per measure type — a
        repeat type is refused with `ERR_DUPLICATE_MEASURE`."
        PRD §2.5: "Checks run in this priority order: ... 10. Uniqueness and
        aggregate rules (`ERR_DUPLICATE_CASE`, `ERR_DUPLICATE_SPED_PLAN`,
        `ERR_DUPLICATE_MEASURE`, `ERR_DUPLICATE_VOTE`,
        `ERR_REVIEW_ALREADY_OPEN`, `ERR_REEVAL_ALREADY_OPEN`,
        `ERR_INCOMPLETE_MEASURES`, `ERR_REEVAL_OUTCOME_MISMATCH`). 11.
        Temporal windows and interval overlaps ..."

        Design: Corner/validations/duplicate_measure_beats_stale_validity
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        case = create_case(student["id"], cycle["id"],
                           pathway="UNIVERSAL_SCREEN")
        enter_measure(case["id"], "ABILITY", 90)
        # Second ABILITY score, also stale (2024-01-01 is older than 730 days
        # before 2026-08-20): the uniqueness rule (priority 10) outranks the
        # temporal rule (priority 11).
        resp = api.create_measure_score(
            case["id"],
            create_measure_score_payload(
                measure_type="ABILITY", percentile=91,
                administered_on="2024-01-01"),
            GC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEASURE.value)

    def test_measure_validity_boundary_day(self, api):
        """PRD §3.2: "and optionally `measure_validity_days`, which defaults
        to 730 — the maximum age, in days, of a usable measure score."
        PRD §3.4: "it must be no older than the cycle profile's
        `measure_validity_days` counted back from today — a stale score is
        rejected with `ERR_MEASURE_OUTSIDE_VALIDITY`".

        Design: Corner/calculations/measure_validity_boundary_day
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        case = create_case(student["id"], cycle["id"],
                           pathway="UNIVERSAL_SCREEN")
        set_clock("2026-09-01T00:00:00Z")
        # 2024-09-01 is exactly 730 days before 2026-09-01: accepted.
        ok = validate_success(
            api.create_measure_score(
                case["id"],
                create_measure_score_payload(
                    measure_type="ABILITY", percentile=90,
                    administered_on="2024-09-01"),
                GC),
            201)
        assert ok["administered_on"] == "2024-09-01"
        # 2024-08-31 is 731 days before today: outside validity.
        resp = api.create_measure_score(
            case["id"],
            create_measure_score_payload(
                measure_type="ACHIEVEMENT", percentile=90,
                administered_on="2024-08-31"),
            GC)
        validate_error(resp, ApiErrorId.ERR_MEASURE_OUTSIDE_VALIDITY.value)


class TestFinalizeCycleGate:
    def test_finalize_rejected_while_cycle_open(self, api):
        """PRD §3.4: "Finalize-scoring is the coordinator action that turns
        evidence into a decision; it requires the cycle in `SCORING` and the
        case in `SCREENING`."
        PRD §3.4: "any other cycle state — `ERR_INVALID_CYCLE_STATE`".

        Design: Difficulty/cross_entity_state_dependency/finalize_scoring_requires_cycle_scoring_state
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-F",
                                 legal_name="Stu F", grade_level=3,
                                 primary_guardian_user_id="guard-f")
        case = create_case(student["id"], cycle["id"],
                           pathway="UNIVERSAL_SCREEN")
        enter_measure(case["id"], "ABILITY", 95)
        enter_measure(case["id"], "ACHIEVEMENT", 95)
        enter_measure(case["id"], "RATING_SCALE", 95)
        resp = api.finalize_scoring(case["id"], GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE.value)
        after = get_case(case["id"])
        assert after["status"] == "SCREENING"
        assert after["composite_score"] is None

    def test_finalize_rejected_once_cycle_left_scoring(self, api):
        """PRD §3.4: "it requires the cycle in `SCORING` and the case in
        `SCREENING`."
        PRD §3.4: "any other cycle state — `ERR_INVALID_CYCLE_STATE`".

        Design: Difficulty/cross_entity_state_dependency/finalize_scoring_requires_cycle_scoring_state
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-F2",
                                 legal_name="Stu F2", grade_level=3,
                                 primary_guardian_user_id="guard-f2")
        case = create_case(student["id"], cycle["id"],
                           pathway="UNIVERSAL_SCREEN")
        enter_measure(case["id"], "ABILITY", 95)
        enter_measure(case["id"], "ACHIEVEMENT", 95)
        enter_measure(case["id"], "RATING_SCALE", 95)
        # Advance through SCORING without finalizing this case: the case
        # remains SCREENING while the cycle moves on to REVIEW, and finalize
        # is now rejected because the cycle is no longer SCORING.
        advance_cycle(cycle["id"], "SCORING")
        advance_cycle(cycle["id"], "REVIEW")
        resp = api.finalize_scoring(case["id"], GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE.value)
