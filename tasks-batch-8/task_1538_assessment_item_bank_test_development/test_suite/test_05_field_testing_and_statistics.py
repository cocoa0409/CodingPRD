"""Field-test windows, response ingestion, and the statistics pipeline."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_item_response,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_response_payload, create_window_payload
from test_helpers.fixtures import (
    PD_H,
    PSYCH_H,
    WINDOW_END,
    WINDOW_START,
    close_window,
    create_draft_item,
    create_program,
    create_standard,
    create_window,
    drive_item_to_field_test_eligible,
    field_test_and_close,
    ingest_response,
    list_statistics,
    open_window,
    read_item,
)


def _eligible_item(program_id, standard_id, code):
    item = create_draft_item(program_id, standard_id, item_code=code)
    return drive_item_to_field_test_eligible(program_id, item)


def _ones(ones, n=50):
    """Nested score vector: the first `ones` students score 1."""
    return [1 if i < ones else 0 for i in range(n)]


def _final_row(program_id, item_id, window_id):
    rows = list_statistics(program_id, item_id=item_id, window_id=window_id,
                           stats_kind="FINAL")
    assert len(rows) == 1, f"expected exactly one FINAL row, got {len(rows)}"
    return rows[0]


class TestWindowStateRules:
    def test_window_open_from_open_returns_invalid_state(self, api):
        """PRD: "Opening a window requires it to be `SCHEDULED`
        (`ERR_WINDOW_NOT_SCHEDULED` otherwise)"

        Design: Corner/state_machines/window_open_from_open_returns_invalid_state
        """
        program = create_program()
        # Clock is still at its initial instant, inside these bounds.
        window = get_success_data(api.create_field_test_window(
            create_window_payload(program["id"], start_utc="2026-08-01T00:00:00Z",
                                  end_utc="2026-08-31T23:59:59Z"),
            PD_H,
        ))
        get_success_data(api.open_field_test_window(window["id"], PD_H))
        resp = api.open_field_test_window(window["id"], PD_H)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_SCHEDULED)

    def test_validation_window_time_invalid_when_start_after_end(self, api):
        """PRD: "The end must be strictly later than the start, or creation
        fails with `ERR_WINDOW_TIME_INVALID` (HTTP 422)."

        Design: Corner/validations/validation_window_time_invalid_when_start_after_end
        """
        program = create_program()
        resp = api.create_field_test_window(
            create_window_payload(program["id"], window_label="BAD",
                                  start_utc="2026-08-31T00:00:00Z",
                                  end_utc="2026-08-01T00:00:00Z"),
            PD_H,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_TIME_INVALID)


class TestItemResponseRecord:
    def test_item_response_immutable_no_version_field(self, api):
        """PRD: "The sole exception is the ItemResponse resource. An ingested
        response is an immutable measurement record: it carries only `id` and
        `created_at`, and both `updated_at` and `version` are absent from it."

        Design: Corner/entities/item_response_immutable_no_version_field
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-IMM")
        window = create_window(program["id"])
        open_window(program["id"], window["id"])
        response = get_success_data(api.ingest_item_response(
            window["id"], create_response_payload(item["id"], "s0", 1),
            PSYCH_H,
        ))
        fetched = validate_success(api.get_item_response(response["id"], PSYCH_H))
        assert_item_response(fetched)
        assert fetched["excluded"] is False


class TestProvisionalVsFinalFiltering:
    def _setup_filtered_window(self, api):
        """One item with 50 non-excluded responses: 45 fully valid (30 scoring
        1, 15 scoring 0), 3 short-duration (10s, scoring 0), and 2 timestamped
        one second past end_utc (scoring 0)."""
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "IT-A")
        window = create_window(program["id"], target_sample_size=50)
        open_window(program["id"], window["id"])
        for i in range(30):
            ingest_response(window["id"], item["id"], f"s{i}", 1)
        for i in range(30, 45):
            ingest_response(window["id"], item["id"], f"s{i}", 0)
        for i in range(45, 48):
            ingest_response(window["id"], item["id"], f"s{i}", 0,
                            attempt_duration_seconds=10)
        for i in range(48, 50):
            ingest_response(window["id"], item["id"], f"s{i}", 0,
                            response_timestamp="2026-08-11T00:00:00Z")
        close_window(program["id"], window["id"])
        return program, item, window

    def test_provisional_and_final_rows_carry_different_p_values(self, api):
        """PRD: "The provisional computation always runs. Over the set of the
        item's non-excluded responses in the window — with no timestamp filter
        and no duration filter — `n_responses` counts the set, and the
        provisional difficulty is the sum of the responses' `raw_score` values
        divided by the product of `n_responses` and the item's
        `max_score_points`, rounded to 4 decimal places half-up."
        PRD: "It recomputes both measures over a stricter set: non-excluded
        responses whose `response_timestamp` falls within the closed interval
        from `start_utc` through `end_utc` and whose `attempt_duration_seconds`
        is at least 30 seconds."

        Design: Difficulty/dual_variant_calc/item_p_value_provisional_vs_final_filtering
        """
        program, item, window = self._setup_filtered_window(api)
        rows = list_statistics(program["id"], item_id=item["id"],
                               window_id=window["id"])
        by_kind = {r["stats_kind"]: r for r in rows}
        assert set(by_kind) == {"PROVISIONAL", "FINAL"}, (
            "one PROVISIONAL and one FINAL row for the (item, window) pair"
        )
        # Provisional: 30 ones over all 50 non-excluded responses.
        assert by_kind["PROVISIONAL"]["p_value"] == pytest.approx(0.6, abs=1e-9)
        assert by_kind["PROVISIONAL"]["n_responses"] == 50
        # Final: 30 ones over the 45 responses surviving both filters.
        assert by_kind["FINAL"]["p_value"] == pytest.approx(0.6667, abs=1e-9)

    def test_item_mirrors_both_statistic_variants(self, api):
        """PRD: "These results are written to an ItemStatistic row whose
        `stats_kind` is `PROVISIONAL`, and mirrored onto the item as
        `p_value_provisional` and `point_biserial_provisional`."
        PRD: "The final difficulty and discrimination are written to a second
        ItemStatistic row whose `stats_kind` is `FINAL`, mirrored onto the item
        as `p_value_final` and `point_biserial_final`"
        PRD: "Because the final filter can exclude responses the provisional
        set included, the two difficulty values for the same window may
        legitimately differ."

        Design: Difficulty/dual_variant_calc/item_p_value_provisional_vs_final_filtering
        """
        program, item, _window = self._setup_filtered_window(api)
        after = read_item(program["id"], item["id"])
        assert after["p_value_provisional"] == pytest.approx(0.6, abs=1e-9)
        assert after["p_value_final"] == pytest.approx(0.6667, abs=1e-9)
        assert after["p_value_provisional"] != after["p_value_final"], (
            "the two variants produce different observable results"
        )


class TestPassFlagBranching:
    def test_fail_severe_when_discrimination_below_010(self, api):
        """PRD: "When the final discrimination falls strictly below 0.10, the
        flag is `FAIL_SEVERE`."
        PRD: "if the set holds fewer than two responses, or every normalized
        item score is identical, or every student mean is identical, the
        correlation is undefined and the value is recorded as 0.0000"
        (The filler's constant scores pin discrimination to 0.0000 while
        difficulty stays at 0.5, in range — the severe branch dominates.)

        Design: Difficulty/combinatorial_formula/item_pass_flag_multi_threshold_branching
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-X")
        filler = _eligible_item(program["id"], standard["id"], "I-F1")
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: _ones(25),
            filler["id"]: _ones(50),   # every student mean identical
        })
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["p_value"] == pytest.approx(0.5, abs=1e-9)
        assert row["point_biserial"] == pytest.approx(0.0, abs=1e-9)
        assert row["pass_flag"] == "FAIL_SEVERE"

    def test_fail_borderline_when_difficulty_below_030(self, api):
        """PRD: "Otherwise, when the final discrimination falls strictly below
        0.20, or the final difficulty falls strictly below 0.30, or the final
        difficulty rises strictly above 0.85, the flag is `FAIL_BORDERLINE`."
        (Difficulty 0.20 < 0.30 with discrimination 1.0 — above both
        discrimination thresholds — so the borderline branch fires on
        difficulty alone.)

        Design: Difficulty/combinatorial_formula/item_pass_flag_multi_threshold_branching
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-Y")
        filler = _eligible_item(program["id"], standard["id"], "I-F2")
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: _ones(10),
            filler["id"]: _ones(10),   # identical vectors -> correlation 1.0
        })
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["p_value"] == pytest.approx(0.2, abs=1e-9)
        assert row["pass_flag"] == "FAIL_BORDERLINE"

    def test_pass_when_discrimination_exactly_020(self, api):
        """PRD: "The comparisons are strict at every boundary: a final
        difficulty of exactly 0.30 satisfies the lower bound, and a final
        discrimination of exactly 0.20 satisfies its threshold."
        (Contingency 15/10/10/15 over 50 students yields a point-biserial of
        exactly 0.20 with difficulty 0.50, so both borderline branches miss
        and the flag is PASS.)

        Design: Difficulty/combinatorial_formula/item_pass_flag_multi_threshold_branching
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-Z")
        filler = _eligible_item(program["id"], standard["id"], "I-F3")
        item_scores = _ones(25)                       # p = 0.5
        filler_scores = [1] * 15 + [0] * 10 + [1] * 10 + [0] * 15
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: item_scores,
            filler["id"]: filler_scores,
        })
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["point_biserial"] == pytest.approx(0.2, abs=1e-9)
        assert row["p_value"] == pytest.approx(0.5, abs=1e-9)
        assert row["pass_flag"] == "PASS"


class TestBoundaryPrecision:
    def test_p_value_exactly_at_p_low_boundary_passes(self, api):
        """PRD: "The comparisons are strict at every boundary: a final
        difficulty of exactly 0.30 satisfies the lower bound, and a final
        discrimination of exactly 0.20 satisfies its threshold."

        Design: Difficulty/boundary_precision_check/p_value_exactly_at_p_low_boundary_passes
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-B1")
        filler = _eligible_item(program["id"], standard["id"], "I-F4")
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: _ones(15),          # p = 15/50 = 0.30 exactly
            filler["id"]: _ones(15),        # identical vectors -> pb 1.0
        })
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["p_value"] == pytest.approx(0.3, abs=1e-9)
        assert row["pass_flag"] == "PASS", (
            "exactly 0.30 satisfies the lower bound (strict < semantics)"
        )

    def test_p_value_just_below_p_low_is_borderline(self, api):
        """PRD: "Otherwise, when the final discrimination falls strictly below
        0.20, or the final difficulty falls strictly below 0.30, or the final
        difficulty rises strictly above 0.85, the flag is `FAIL_BORDERLINE`."
        (Difficulty 0.28 < 0.30 with discrimination 1.0 — one step below the
        boundary flips the flag to FAIL_BORDERLINE.)

        Design: Difficulty/boundary_precision_check/p_value_exactly_at_p_low_boundary_passes
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-B2")
        filler = _eligible_item(program["id"], standard["id"], "I-F5")
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: _ones(14),          # p = 0.28 < 0.30
            filler["id"]: _ones(14),
        })
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["p_value"] == pytest.approx(0.28, abs=1e-9)
        assert row["pass_flag"] == "FAIL_BORDERLINE"


class TestClosedIntervalMembership:
    def test_responses_at_both_window_endpoints_are_included(self, api):
        """PRD: "It recomputes both measures over a stricter set: non-excluded
        responses whose `response_timestamp` falls within the closed interval
        from `start_utc` through `end_utc` and whose `attempt_duration_seconds`
        is at least 30 seconds."
        (Half the FINAL-eligible responses sit exactly at start_utc scoring 1
        and half exactly at end_utc scoring 0; only closed-interval membership
        on both ends produces p_value 0.5.)

        Design: Difficulty/resource_temporal_overlap/response_timestamp_closed_interval_membership
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-CI")
        window = create_window(program["id"], target_sample_size=50)
        open_window(program["id"], window["id"])
        for i in range(25):
            ingest_response(window["id"], item["id"], f"sa{i}", 1,
                            response_timestamp=WINDOW_START)
        for i in range(25):
            ingest_response(window["id"], item["id"], f"sb{i}", 0,
                            response_timestamp=WINDOW_END)
        close_window(program["id"], window["id"])
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["p_value"] == pytest.approx(0.5, abs=1e-9), (
            "closed interval: a response at exactly start_utc and one at "
            "exactly end_utc are both included"
        )

    def test_response_one_second_past_end_is_excluded_from_final(self, api):
        """PRD: "It recomputes both measures over a stricter set: non-excluded
        responses whose `response_timestamp` falls within the closed interval
        from `start_utc` through `end_utc`"
        PRD: "Over the set of the item's non-excluded responses in the window —
        with no timestamp filter and no duration filter — `n_responses` counts
        the set"
        (Ten extra responses one second past end_utc, all scoring 1, lift the
        unfiltered provisional difficulty to 0.5833 while the FINAL difficulty
        stays at 0.5.)

        Design: Difficulty/resource_temporal_overlap/response_timestamp_closed_interval_membership
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-CO")
        window = create_window(program["id"], target_sample_size=50)
        open_window(program["id"], window["id"])
        for i in range(25):
            ingest_response(window["id"], item["id"], f"sa{i}", 1,
                            response_timestamp=WINDOW_START)
        for i in range(25):
            ingest_response(window["id"], item["id"], f"sb{i}", 0,
                            response_timestamp=WINDOW_END)
        for i in range(10):
            ingest_response(window["id"], item["id"], f"sc{i}", 1,
                            response_timestamp="2026-08-11T00:00:00Z")
        close_window(program["id"], window["id"])
        rows = list_statistics(program["id"], item_id=item["id"],
                               window_id=window["id"])
        by_kind = {r["stats_kind"]: r for r in rows}
        assert by_kind["PROVISIONAL"]["p_value"] == pytest.approx(0.5833, abs=1e-9)
        assert by_kind["FINAL"]["p_value"] == pytest.approx(0.5, abs=1e-9), (
            "the response one second past end_utc is outside the closed interval"
        )


class TestWindowCloseCascade:
    def _setup_two_item_window(self, api):
        program = create_program()
        standard = create_standard(program["id"])
        item_p = _eligible_item(program["id"], standard["id"], "I-P")
        item_q = _eligible_item(program["id"], standard["id"], "I-Q")
        filler = _eligible_item(program["id"], standard["id"], "I-F6")
        _closed, window = field_test_and_close(program["id"], {
            item_p["id"]: _ones(30),        # 50 responses -> meets target
            filler["id"]: _ones(30),
            item_q["id"]: _ones(6, n=10),   # 10 responses -> below target
        })
        return program, window, item_p, item_q

    def test_window_close_drives_items_to_stats_review(self, api):
        """PRD: "Every item with at least one response in the window moves
        `FIELD_TESTING → STATS_REVIEW`, and for every item-and-window pair
        with responses the system computes statistics."
        PRD: "The provisional computation always runs."
        PRD: "The final computation runs only when `n_responses` meets or
        exceeds the window's `target_sample_size`."

        Design: Difficulty/transitive_cascade/window_close_cascade_to_item_stats
        """
        program, window, item_p, item_q = self._setup_two_item_window(api)
        p_after = read_item(program["id"], item_p["id"])
        q_after = read_item(program["id"], item_q["id"])
        assert p_after["status"] == "STATS_REVIEW"
        assert q_after["status"] == "STATS_REVIEW"
        p_kinds = {r["stats_kind"] for r in list_statistics(
            program["id"], item_id=item_p["id"], window_id=window["id"])}
        q_kinds = {r["stats_kind"] for r in list_statistics(
            program["id"], item_id=item_q["id"], window_id=window["id"])}
        assert p_kinds == {"PROVISIONAL", "FINAL"}, (
            "the item meeting target_sample_size gets both rows"
        )
        assert q_kinds == {"PROVISIONAL"}, (
            "the item below target_sample_size gets only the PROVISIONAL row"
        )

    def test_window_close_mirrors_final_stats_only_when_computed(self, api):
        """PRD: "The final difficulty and discrimination are written to a
        second ItemStatistic row whose `stats_kind` is `FINAL`, mirrored onto
        the item as `p_value_final` and `point_biserial_final`, and the row's
        `finalized_at` is stamped from the program clock."
        (The item below target never receives a FINAL row, so its
        p_value_final stays unset.)

        Design: Difficulty/transitive_cascade/window_close_cascade_to_item_stats
        """
        program, window, item_p, item_q = self._setup_two_item_window(api)
        p_after = read_item(program["id"], item_p["id"])
        q_after = read_item(program["id"], item_q["id"])
        assert p_after["p_value_final"] == pytest.approx(0.6, abs=1e-9)
        assert p_after["p_value_provisional"] == pytest.approx(0.6, abs=1e-9)
        assert q_after.get("p_value_final") is None, (
            "no FINAL row -> the final mirror stays unset"
        )
        final_row = _final_row(program["id"], item_p["id"], window["id"])
        assert final_row.get("finalized_at") is not None


class TestStatisticComputationDetails:
    def test_pass_flag_fail_severe_threshold_check(self, api):
        """PRD: "When the final discrimination falls strictly below 0.10, the
        flag is `FAIL_SEVERE`."
        (Discrimination pinned to 0.0000 via identical student means;
        difficulty 0.5 is in range yet the flag is still FAIL_SEVERE.)

        Design: Corner/calculations/pass_flag_fail_severe_threshold_check
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-PB")
        filler = _eligible_item(program["id"], standard["id"], "I-F7")
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: _ones(25),
            filler["id"]: _ones(50),
        })
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["pass_flag"] == "FAIL_SEVERE"

    def test_p_value_rounding_4_decimals_half_up(self, api):
        """PRD: "All computed item statistics — `p_value` and `point_biserial`
        on an ItemStatistic row, and their mirrored counterparts
        `p_value_provisional`, `p_value_final`, `point_biserial_provisional`,
        and `point_biserial_final` on the Item — are rounded to exactly 4
        decimal places using round-half-up."
        (17/51 = 0.33333... rounds to 0.3333; 34/51 = 0.66666... rounds up to
        0.6667.)

        Design: Corner/calculations/p_value_rounding_4_decimals_half_up
        """
        program = create_program()
        standard = create_standard(program["id"])
        item_a = _eligible_item(program["id"], standard["id"], "I-R1")
        item_b = _eligible_item(program["id"], standard["id"], "I-R2")
        _closed, window = field_test_and_close(
            program["id"],
            {item_a["id"]: _ones(17, n=51), item_b["id"]: _ones(34, n=51)},
            target_sample_size=51,
        )
        row_a = _final_row(program["id"], item_a["id"], window["id"])
        row_b = _final_row(program["id"], item_b["id"], window["id"])
        assert row_a["p_value"] == pytest.approx(0.3333, abs=1e-9)
        assert row_b["p_value"] == pytest.approx(0.6667, abs=1e-9)

    def test_point_biserial_degenerate_all_same_returns_zero(self, api):
        """PRD: "if the set holds fewer than two responses, or every normalized
        item score is identical, or every student mean is identical, the
        correlation is undefined and the value is recorded as 0.0000"

        Design: Corner/calculations/point_biserial_degenerate_all_same_returns_zero
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-DEG")
        filler = _eligible_item(program["id"], standard["id"], "I-F8")
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: _ones(50),      # every student scores 1
            filler["id"]: _ones(50),
        })
        row = _final_row(program["id"], item["id"], window["id"])
        assert row["point_biserial"] == pytest.approx(0.0, abs=1e-9)
        assert row["p_value"] == pytest.approx(1.0, abs=1e-9)

    def test_statistic_filtered_list_by_item_and_kind(self, api):
        """PRD: "Statistic rows may be listed filtered by `item_id`,
        `window_id`, or `stats_kind`, and reading them requires an active
        `STATS_READ` grant under §2.11."

        Design: Corner/endpoints/statistic_filtered_list_by_item_and_kind
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = _eligible_item(program["id"], standard["id"], "I-ST")
        filler = _eligible_item(program["id"], standard["id"], "I-F9")
        _closed, window = field_test_and_close(program["id"], {
            item["id"]: _ones(30),
            filler["id"]: _ones(30),
        })
        rows = list_statistics(program["id"], item_id=item["id"],
                               stats_kind="FINAL")
        assert len(rows) == 1
        assert rows[0]["item_id"] == item["id"]
        assert rows[0]["window_id"] == window["id"]
        assert rows[0]["stats_kind"] == "FINAL"
