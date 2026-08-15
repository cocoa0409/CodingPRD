"""Star-rating breakpoints and the response-rate cap, the publication gate,
the closed-interval fielding-window rule, and duplicate cycle_index
(PRD §2.6, §3.3, §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_cycle_payload,
    get_cycle,
    get_success_data,
    import_responses,
    make_cycle,
    make_program,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestStarThresholdInclusive:
    def _scored_cycle(self, api, name, topbox_count, low_count,
                      denominator_cases=None):
        """Cycle in SCORING with `topbox_count` all-4 + `low_count` all-3 MAIL
        responses. `denominator_cases` (default topbox+low) sets how many cases
        were fielded in total."""
        total_cases = denominator_cases or (topbox_count + low_count)
        ctx = setup_cycle_in_state(
            setup_program(name=name), "FIELDING", discharge_count=total_cases,
            target_sample_size=max(100, total_cases))
        import_responses(ctx["case_ids"][0:topbox_count], ctx["vendor"]["id"],
                         mode_used="MAIL", score=4)
        if low_count:
            import_responses(
                ctx["case_ids"][topbox_count:topbox_count + low_count],
                ctx["vendor"]["id"], mode_used="MAIL", score=3)
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))
        return get_cycle(ctx["cycle"]["id"]), ctx

    def test_star_threshold_80_inclusive(self, api):
        """PRD §3.6: "Otherwise the rating reads the adjusted `overall_rating`
        percentage from the snapshot: at least 90.0 earns 5 stars, at least
        80.0 earns 4, at least 70.0 earns 3, at least 60.0 earns 2, and
        anything below earns 1 — every boundary inclusive, so exactly 80.00
        earns 4."

        Design: Difficulty/boundary_precision_check/star_threshold_80_inclusive
        """
        cycle, ctx = self._scored_cycle(api, "P-BP1", topbox_count=20,
                                        low_count=5)
        assert cycle["scored_adjusted_composite_pcts"]["overall_rating"] == (
            pytest.approx(80.0, abs=0.001))

        rating = validate_success(api.get_star_rating(cycle["id"], ADMIN), 200)
        assert rating["stars"] == 4
        assert rating["rating_status"] == "RATED"
        assert rating["capped"] is False

    def test_star_boundary_79_99_versus_80_00(self, api):
        """PRD §3.6: "at least 90.0 earns 5 stars, at least 80.0 earns 4, at
        least 70.0 earns 3, at least 60.0 earns 2, and anything below earns 1 —
        every boundary inclusive, so exactly 80.00 earns 4."
        PRD §2.9: "Threshold comparisons against stored two-decimal percentages
        are inclusive: a value exactly equal to the threshold satisfies it."

        Design: Difficulty/boundary_precision_check/star_threshold_80_inclusive
        """
        # 20x4 + 5x3 -> exactly 80.00 -> 4 stars.
        cycle_at, _ctx = self._scored_cycle(api, "P-BP1C", topbox_count=20,
                                            low_count=5)
        rating_at = validate_success(
            api.get_star_rating(cycle_at["id"], ADMIN), 200)
        assert rating_at["adjusted_overall_topbox_pct"] == pytest.approx(
            80.0, abs=0.001)
        assert rating_at["stars"] == 4
        assert rating_at["capped"] is False

        # 19x4 + 6x3 -> 76.00 (< 80.00, >= 70.00) -> 3 stars.
        cycle_below, _ctx2 = self._scored_cycle(api, "P-BP1D",
                                                topbox_count=19, low_count=6)
        rating_below = validate_success(
            api.get_star_rating(cycle_below["id"], ADMIN), 200)
        assert rating_below["adjusted_overall_topbox_pct"] == pytest.approx(
            76.0, abs=0.001)
        assert rating_below["stars"] == 3


class TestResponseRateCapInteraction:
    def test_star_rating_response_rate_cap_interaction(self, api):
        """PRD §3.6: "A response-rate cap then applies: when
        `scored_response_rate` is below 10.0, the rating is capped at 3 stars
        (`stars` becomes the lesser of the earned rating and 3) and `capped` is
        true; at exactly 10.0 or above there is no cap."
        PRD §3.6: "The rating payload carries `cycle_id`, `rating_status`,
        `stars`, `capped`, `adjusted_overall_topbox_pct`, `response_rate`, and
        `completed_responses`."

        Design: Difficulty/combinatorial_formula/star_rating_response_rate_cap_interaction
        """
        # 300 fielded cases, only 25 completed: rate 8.33 < 10.0 while the
        # piecewise breakpoints alone would earn 4 stars at 88.00.
        cycle, ctx = TestStarThresholdInclusive._scored_cycle(
            self, api, "P-CF1", topbox_count=22, low_count=3,
            denominator_cases=300)
        rating = validate_success(api.get_star_rating(cycle["id"], ADMIN), 200)
        assert rating["adjusted_overall_topbox_pct"] == pytest.approx(
            88.0, abs=0.001)
        assert rating["response_rate"] == pytest.approx(8.33, abs=0.001)
        assert rating["completed_responses"] == 25
        assert rating["stars"] == 3
        assert rating["capped"] is True
        assert rating["rating_status"] == "RATED"

    def test_rate_cap_overrides_piecewise_breakpoint(self, api):
        """PRD §3.6: "A response-rate cap then applies: when
        `scored_response_rate` is below 10.0, the rating is capped at 3 stars
        (`stars` becomes the lesser of the earned rating and 3) and `capped` is
        true; at exactly 10.0 or above there is no cap."
        PRD §3.6: "at least 90.0 earns 5 stars"

        Design: Difficulty/combinatorial_formula/star_rating_response_rate_cap_interaction
        """
        # Perfect 100.00 adjusted percentage (would be 5 stars piecewise) but
        # response rate 25/300 = 8.33 < 10.0 -> capped at 3.
        cycle, _ctx = TestStarThresholdInclusive._scored_cycle(
            self, api, "P-CF1B", topbox_count=25, low_count=0,
            denominator_cases=300)
        rating = validate_success(api.get_star_rating(cycle["id"], ADMIN), 200)
        assert rating["adjusted_overall_topbox_pct"] == pytest.approx(
            100.0, abs=0.001)
        assert rating["response_rate"] == pytest.approx(8.33, abs=0.001)
        assert rating["stars"] == 3
        assert rating["capped"] is True


class TestPublicationGate:
    def test_publication_min_completed_count_boundary(self, api):
        """PRD §3.6: "The frozen snapshot must show
        `scored_completed_responses` of at least 25 and a
        `scored_response_rate` of at least 10.0, both thresholds inclusive; a
        cycle below either is rejected with `ERR_BELOW_PUBLICATION_THRESHOLD`."
        PRD §3.6: "the live preview of the publication gate, true exactly when
        `completed_responses` is at least 25 and `response_rate` is at least
        10.0"

        Design: Difficulty/boundary_precision_check/publication_min_completed_count_boundary
        """
        cycle, ctx = TestStarThresholdInclusive._scored_cycle(
            self, api, "P-BP2", topbox_count=24, low_count=0,
            denominator_cases=24)
        assert cycle["scored_completed_responses"] == 24
        assert cycle["scored_response_rate"] == pytest.approx(100.0, abs=0.001)
        assert cycle["publication_eligible"] is False

        res = api.publish_cycle(cycle["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_BELOW_PUBLICATION_THRESHOLD)
        assert res.status_code == 422
        assert get_cycle(cycle["id"])["status"] == "SCORING"

    def test_publish_at_25_completed_succeeds(self, api):
        """PRD §3.6: "The frozen snapshot must show
        `scored_completed_responses` of at least 25 and a
        `scored_response_rate` of at least 10.0, both thresholds inclusive; a
        cycle below either is rejected with `ERR_BELOW_PUBLICATION_THRESHOLD`."
        PRD §3.6: "On publish, `published_star_rating` is pinned from the star
        rating of the stored snapshot and `published_at` is stamped from the
        logical clock."

        Design: Difficulty/boundary_precision_check/publication_min_completed_count_boundary
        """
        # 25 completed of 25 fielded: the count boundary is met exactly.
        cycle, _ctx = TestStarThresholdInclusive._scored_cycle(
            self, api, "P-BP2B", topbox_count=25, low_count=0,
            denominator_cases=25)
        assert cycle["scored_completed_responses"] == 25
        assert cycle["publication_eligible"] is True

        published = validate_success(api.publish_cycle(cycle["id"], ADMIN), 200)
        assert published["status"] == "PUBLISHED"
        assert published["published_star_rating"] == 5


class TestCycleWindowOverlap:
    def test_cycle_fielding_closed_interval_touch_conflicts(self, api):
        """PRD §3.3: "The fielding window is a closed interval, and it may not
        intersect the fielding window of any other non-`VOIDED` cycle of the
        same program — intervals that merely touch, sharing exactly one
        boundary date, count as conflicting and are rejected with
        `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cycle_fielding_closed_interval_touch_conflicts
        """
        program = make_program(name="P-TO1")
        make_cycle(program["id"], label="QA", cycle_index=1,
                   discharge_window_start="2026-06-01",
                   discharge_window_end="2026-06-30",
                   fielding_start_date="2026-08-03",
                   fielding_end_date="2026-08-31")

        touching = api.create_cycle(
            create_cycle_payload(
                program["id"], label="QB", cycle_index=2,
                discharge_window_start="2026-07-01",
                discharge_window_end="2026-07-31",
                fielding_start_date="2026-08-31",
                fielding_end_date="2026-09-15"),
            ADMIN)
        validate_error(touching, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)

        disjoint = validate_success(
            api.create_cycle(
                create_cycle_payload(
                    program["id"], label="QC", cycle_index=3,
                    discharge_window_start="2026-07-01",
                    discharge_window_end="2026-07-31",
                    fielding_start_date="2026-09-01",
                    fielding_end_date="2026-09-30"),
                ADMIN),
            201)
        assert disjoint["status"] == "DRAFT"

    def test_touching_boundary_conflicts_but_disjoint_passes(self, api):
        """PRD §3.3: "The fielding window is a closed interval, and it may not
        intersect the fielding window of any other non-`VOIDED` cycle of the
        same program — intervals that merely touch, sharing exactly one
        boundary date, count as conflicting and are rejected with
        `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cycle_fielding_closed_interval_touch_conflicts
        """
        program = make_program(name="P-TO1B")
        make_cycle(program["id"], label="QA", cycle_index=1,
                   discharge_window_start="2026-06-01",
                   discharge_window_end="2026-06-30",
                   fielding_start_date="2026-08-03",
                   fielding_end_date="2026-08-31")
        # Same boundary touch on the other side: [2026-07-20, 2026-08-03].
        validate_error(
            api.create_cycle(
                create_cycle_payload(
                    program["id"], label="QB", cycle_index=2,
                    discharge_window_start="2026-05-01",
                    discharge_window_end="2026-05-31",
                    fielding_start_date="2026-07-20",
                    fielding_end_date="2026-08-03"),
                ADMIN),
            ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)
        # One day of separation (ending 2026-08-02) is disjoint.
        ok = validate_success(
            api.create_cycle(
                create_cycle_payload(
                    program["id"], label="QC", cycle_index=2,
                    discharge_window_start="2026-05-01",
                    discharge_window_end="2026-05-31",
                    fielding_start_date="2026-07-20",
                    fielding_end_date="2026-08-02"),
                ADMIN),
            201)
        assert ok["status"] == "DRAFT"


class TestDuplicateCycleIndex:
    def test_duplicate_cycle_index_rejected(self, api):
        """PRD §3.3: "a `cycle_index` (the program's quarter index, unique per
        program — duplicates are rejected with `ERR_DUPLICATE_CYCLE_INDEX` —
        and the basis for initiative window arithmetic)"

        Design: Corner/validations/duplicate_cycle_index_rejected
        """
        program = make_program(name="P-V21")
        make_cycle(program["id"], label="Q1", cycle_index=1)
        res = api.create_cycle(
            create_cycle_payload(
                program["id"], label="Q1-dup", cycle_index=1,
                discharge_window_start="2026-07-01",
                discharge_window_end="2026-07-31",
                fielding_start_date="2026-09-01",
                fielding_end_date="2026-09-30"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CYCLE_INDEX)

    def test_duplicate_cycle_index_even_without_window_overlap(self, api):
        """PRD §3.3: "a `cycle_index` (the program's quarter index, unique per
        program — duplicates are rejected with `ERR_DUPLICATE_CYCLE_INDEX` —
        and the basis for initiative window arithmetic)"

        Design: Corner/validations/duplicate_cycle_index_rejected
        """
        program = make_program(name="P-V21B")
        make_cycle(program["id"], label="Q1", cycle_index=1)
        # Windows deliberately disjoint — only the index collides.
        res = api.create_cycle(
            create_cycle_payload(
                program["id"], label="Q1-dup", cycle_index=1,
                discharge_window_start="2026-07-01",
                discharge_window_end="2026-07-31",
                fielding_start_date="2026-09-01",
                fielding_end_date="2026-09-30"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CYCLE_INDEX)
        assert res.status_code == 409
        data = get_success_data(api.list_cycles(
            ADMIN, params={"program_id": program["id"], "limit": 100}))
        assert len(data) == 1
