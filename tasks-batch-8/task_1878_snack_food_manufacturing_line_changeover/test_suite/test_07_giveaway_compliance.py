"""Bag-weight control: reject threshold, dual giveaway variants, pinned
rounding order, reject-ratio compliance bands, the seasoning band, and
weight-check list pagination."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_run,
    create_line,
    create_plain_product,
    get_line_version,
    get_success_data,
    record_weight_check,
    record_weight_checks,
    schedule_run,
    set_clock,
    setup_running_run,
    start_run,
    validate_paginated,
)

PM = TEST_USERS["plant_manager_headers"]


def _checks(run_id, bag_weights):
    record_weight_checks(run_id, [(w, 0, 180.0) for w in bag_weights])


class TestGiveawayVariantDivergence:
    def _setup_three_checks(self, api):
        """Two non-rejects (100.15, 100.25) and one reject (96.99)."""
        ctx = setup_running_run(lbs_planned=2000, cases_planned=100)
        run_id = ctx["run"]["id"]
        ids = []
        for w in (100.15, 100.25, 96.99):
            ids.append(record_weight_check(
                run_id, bag_weight_g=w, lbs_fried_since_last_check=0,
                avg_fry_temp_c=180.0)["id"])
        return ctx, run_id, ids

    def test_provisional_and_final_variants_diverge(self, api):
        """PRD §3.6: "The provisional figure, `giveaway_provisional_pct`, is a
        forward-looking estimate over all recorded checks, rejects included,
        with no per-check rounding: one hundred times the difference between
        the raw mean of all checks' `bag_weight_g` and the declared net weight,
        divided by the declared net weight, rounded half-up to two decimals"
        PRD §3.6: "The final figure, `giveaway_final_pct`, is the
        compliance-grade number: reject checks are excluded, and per-check
        rounding is applied before averaging — for each non-reject check the
        per-bag overfill in grams (`bag_weight_g` minus `declared_net_weight_g`)
        is rounded half-up to one decimal, those rounded values are averaged
        across the non-reject checks, and the result is multiplied by one
        hundred and divided by the declared net weight, rounded half-up to two
        decimals"

        Design: Difficulty/dual_variant_calc/giveaway_provisional_vs_final_divergence
        """
        ctx, run_id, _ids = self._setup_three_checks(api)
        run = get_success_data(api.get_run(run_id, PM))
        # raw mean 99.13 -> (99.13 - 100) / 100 * 100 = -0.87 (reject included)
        assert run["giveaway_provisional_pct"] == pytest.approx(-0.87)
        # per-check rounding first: 0.15 -> 0.2 and 0.25 -> 0.3, mean 0.25
        assert run["giveaway_final_pct"] == pytest.approx(0.25)

    def test_reject_flag_strictly_below_limit(self, api):
        """PRD §3.1: "a bag is a reject if and only if its weight falls
        strictly below the declared weight minus twice the tolerable negative
        error — a bag landing exactly at that limit is not a reject."

        Design: Difficulty/dual_variant_calc/giveaway_provisional_vs_final_divergence
        """
        ctx, run_id, ids = self._setup_three_checks(api)
        checks = [get_success_data(api.get_weight_check(i, PM)) for i in ids]
        # declared 100.0, tne 1.5 -> reject limit 97.0; 96.99 is strictly below
        assert checks[0]["is_reject"] is False
        assert checks[1]["is_reject"] is False
        assert checks[2]["is_reject"] is True


class TestGiveawayPinnedRoundingOrder:
    def _setup_two_clean_checks(self, api):
        ctx = setup_running_run(lbs_planned=2000, cases_planned=100)
        run_id = ctx["run"]["id"]
        _checks(run_id, [100.15, 100.25])
        return run_id

    def test_final_variant_rounds_each_check_before_averaging(self, api):
        """PRD §3.6: "The final figure, `giveaway_final_pct`, is the
        compliance-grade number: reject checks are excluded, and per-check
        rounding is applied before averaging — for each non-reject check the
        per-bag overfill in grams (`bag_weight_g` minus `declared_net_weight_g`)
        is rounded half-up to one decimal, those rounded values are averaged
        across the non-reject checks, and the result is multiplied by one
        hundred and divided by the declared net weight, rounded half-up to two
        decimals"

        Design: Difficulty/combinatorial_formula/giveaway_final_pinned_rounding_order
        """
        run_id = self._setup_two_clean_checks(api)
        run = get_success_data(api.get_run(run_id, PM))
        # pinned order: round(0.15, 1) = 0.2 and round(0.25, 1) = 0.3 first,
        # then mean 0.25 -> 0.25 %; averaging raw first would land on 0.20
        assert run["giveaway_final_pct"] == pytest.approx(0.25)

    def test_provisional_variant_is_raw_mean(self, api):
        """PRD §3.6: "The provisional figure, `giveaway_provisional_pct`, is a
        forward-looking estimate over all recorded checks, rejects included,
        with no per-check rounding: one hundred times the difference between
        the raw mean of all checks' `bag_weight_g` and the declared net weight,
        divided by the declared net weight, rounded half-up to two decimals"

        Design: Difficulty/combinatorial_formula/giveaway_final_pinned_rounding_order
        """
        run_id = self._setup_two_clean_checks(api)
        run = get_success_data(api.get_run(run_id, PM))
        # raw mean of 100.15 and 100.25 is exactly 100.20 -> 0.20 %
        assert run["giveaway_provisional_pct"] == pytest.approx(0.2)


class TestRejectThreshold:
    def test_weight_check_reject_threshold_exact_boundary(self, api):
        """PRD §3.1: "Together they define the reject limit: a bag is a reject
        if and only if its weight falls strictly below the declared weight
        minus twice the tolerable negative error — a bag landing exactly at
        that limit is not a reject."

        Design: Corner/entities/weight_check_reject_threshold_exact_boundary
        """
        ctx = setup_running_run()
        run_id = ctx["run"]["id"]
        # declared 100.0, tne 1.5 -> limit 97.0
        at_limit = record_weight_check(run_id, bag_weight_g=97.0,
                                       lbs_fried_since_last_check=0,
                                       avg_fry_temp_c=180.0)
        below = record_weight_check(run_id, bag_weight_g=96.99,
                                    lbs_fried_since_last_check=0,
                                    avg_fry_temp_c=180.0)
        assert at_limit["is_reject"] is False, "exactly at the limit passes"
        assert below["is_reject"] is True, "strictly below the limit rejects"


class TestRejectRatioCompliance:
    def test_reject_ratio_exactly_at_limit_passes(self, api):
        """PRD §3.5: "the `reject_ratio` — the count of reject checks divided
        by the count of all checks — is strictly greater than 0.025 (a ratio of
        exactly 0.025 passes)"
        PRD §3.5: "When none of the four holds, `quality_status` stays
        `PENDING`, awaiting disposition."

        Design: Corner/calculations/reject_ratio_exactly_at_limit_passes
        """
        ctx = setup_running_run()
        run_id = ctx["run"]["id"]
        # 39 non-rejects (100.2) + 1 reject (96.99) -> ratio exactly 0.025
        _checks(run_id, [100.2] * 39 + [96.99])
        completed = complete_run(run_id)
        assert completed["reject_ratio"] == pytest.approx(0.025)
        # mean 100.11975 >= 100.0, final giveaway 0.2 <= 3.0, seasoning exact:
        # no compliance rule fires
        assert completed["quality_status"] == "PENDING"

    def test_reject_ratio_above_limit_qhold(self, api):
        """PRD §3.5: "The run's `quality_status` moves from `PENDING` to
        `QHOLD` when any of four conditions holds: the `reject_ratio` — the
        count of reject checks divided by the count of all checks — is strictly
        greater than 0.025 (a ratio of exactly 0.025 passes)"

        Design: Corner/calculations/reject_ratio_above_limit_qhold
        """
        ctx = setup_running_run()
        run_id = ctx["run"]["id"]
        # 38 non-rejects + 2 rejects -> ratio 0.05 > 0.025
        _checks(run_id, [96.99, 96.99] + [100.2] * 38)
        completed = complete_run(run_id)
        assert completed["reject_ratio"] == pytest.approx(0.05)
        assert completed["quality_status"] == "QHOLD"


class TestSeasoningBand:
    def test_seasoning_deviation_exactly_half_passes(self, api):
        """PRD §3.1: "Seasoning control uses `seasoning_target_pct`, the target
        seasoning mass as a percent of product mass, with a compliance band of
        half a percentage point on either side, inclusive — a deviation of
        exactly half a point still passes."
        PRD §3.5: "or the absolute deviation of `seasoning_actual_pct` from
        `seasoning_target_pct` exceeds half a percentage point (exactly half a
        point passes)."

        Design: Corner/calculations/seasoning_deviation_exactly_half_passes
        """
        product = create_plain_product()
        line = create_line()
        # run A: deviation exactly 0.5 -> passes
        run_a = schedule_run(line["id"], product["id"],
                             start="2026-08-02T08:00:00Z",
                             end="2026-08-02T10:00:00Z")
        set_clock("2026-08-02T08:00:00Z")
        start_run(run_a["id"])
        record_weight_check(run_a["id"], bag_weight_g=100.0,
                            lbs_fried_since_last_check=100, avg_fry_temp_c=180.0)
        completed_a = complete_run(run_a["id"], seasoning_actual_pct=4.5)
        assert completed_a["quality_status"] == "PENDING"
        # run B (next day, same product — no cleaning buffer): 0.51 trips it
        run_b = schedule_run(line["id"], product["id"],
                             start="2026-08-03T08:00:00Z",
                             end="2026-08-03T10:00:00Z")
        set_clock("2026-08-03T08:00:00Z")
        start_run(run_b["id"])
        record_weight_check(run_b["id"], bag_weight_g=100.0,
                            lbs_fried_since_last_check=100, avg_fry_temp_c=180.0)
        completed_b = complete_run(run_b["id"], seasoning_actual_pct=4.51)
        assert completed_b["quality_status"] == "QHOLD"


class TestWeightCheckPagination:
    def test_pagination_defaults_and_second_page(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_and_second_page
        """
        ctx = setup_running_run()
        run_id = ctx["run"]["id"]
        for _ in range(11):
            record_weight_check(run_id, bag_weight_g=100.1,
                                lbs_fried_since_last_check=0, avg_fry_temp_c=180.0)
        page1, meta1 = validate_paginated(
            api.list_weight_checks(PM, {"run_id": run_id}))
        assert len(page1) == 10
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api.list_weight_checks(PM, {"run_id": run_id, "offset": 10}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 11
