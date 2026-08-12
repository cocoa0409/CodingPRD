"""Case posting and duration prediction: benchmarks, surgeon bias, clamping."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    BIAS_CLAMP_HI,
    BIAS_DEFAULT,
    assert_case_posting,
    make_case,
    make_line,
    make_surgeon,
    make_surgeon_headers,
    setup_surgeon_with_completions,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_ADMIN = TEST_USERS["admin_headers"]


class TestCasePostingShape:
    def test_invalid_procedure_class_rejected(self, api):
        """PRD §2.5: "Any minute field outside the range 0 to 1440, any missing
        required field, any type mismatch, and any invalid enum member is a
        request-shape failure rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/post_case_with_invalid_enum_returns_invalid_request
        """
        line = make_line()
        surgeon = make_surgeon(line["id"])
        res = api.create_case(
            {
                "surgeon_id": surgeon["id"],
                "procedure_class": "MEGA",
                "priority": "ELECTIVE",
            },
            make_surgeon_headers(surgeon["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        assert res.status_code == 400
        _, meta = validate_paginated(
            api.list_cases(
                make_surgeon_headers(surgeon["id"]),
                params={"surgeon_id": surgeon["id"]},
            )
        )
        assert meta["total_count"] == 0

    def test_injected_computed_durations_ignored(self, api):
        """PRD §3.3: "The `benchmark_duration_minutes` is a pure procedure-class
        lookup — 45 minutes for `MINOR`, 90 for `STANDARD`, 180 for `COMPLEX` — and
        ignores surgeon history entirely."
        PRD §3.3: "New cases are born `POSTED`, with `block_id`, `or_id`, `date`,
        `scheduled_start_minute`, and `scheduled_end_minute` all null until
        scheduling assigns them."

        Design: Corner/entities/case_posting_computed_duration_injected_input_ignored
        """
        line = make_line()
        surgeon = make_surgeon(line["id"])
        res = api.create_case(
            {
                "surgeon_id": surgeon["id"],
                "procedure_class": "STANDARD",
                "priority": "ELECTIVE",
                "predicted_duration_minutes": 1,
                "benchmark_duration_minutes": 1,
            },
            make_surgeon_headers(surgeon["id"]),
        )
        case = validate_success(res, 201)
        assert_case_posting(case)
        assert case["predicted_duration_minutes"] == 90
        assert case["benchmark_duration_minutes"] == 90
        assert case["status"] == "POSTED"


class TestSurgeonBiasDefaults:
    def test_bias_default_below_five_completed_cases(self, api):
        """PRD §3.3: "While a surgeon's `completed_cases_count` is below five, the
        factor is exactly 1.000."

        Design: Corner/calculations/bias_default_below_five_completed_cases
        """
        env = setup_surgeon_with_completions(
            line_name="GS", block_end=1080, coverage_end=1440,
            procedure_class="STANDARD",
            actual_durations=[180, 180, 180, 180],  # each ratio 2.0
        )
        surgeon = validate_success(api.get_surgeon(env["surgeon"]["id"], TEST_ADMIN), 200)
        assert surgeon["completed_cases_count"] == 4
        assert surgeon["duration_bias_factor"] == BIAS_DEFAULT

        nxt = make_case(env["surgeon"]["id"], procedure_class="STANDARD")
        assert nxt["predicted_duration_minutes"] == 90
        assert nxt["predicted_duration_minutes"] == nxt["benchmark_duration_minutes"]

    def test_bias_clamped_at_upper_bound(self, api):
        """PRD §3.3: "For each kept case, the ratio of actual duration — actual end
        minus actual start — to that case's procedure-class benchmark is computed;
        the unrounded ratios are averaged; the mean is rounded half up to three
        decimal places; and the result is clamped to the range 0.800 through 1.250."

        Design: Corner/calculations/bias_clamped_at_upper_bound_1250
        """
        env = setup_surgeon_with_completions(
            line_name="GS", block_end=1080, coverage_end=1440,
            procedure_class="STANDARD",
            actual_durations=[180, 180, 180, 180, 180],  # each ratio 2.0
        )
        surgeon = validate_success(api.get_surgeon(env["surgeon"]["id"], TEST_ADMIN), 200)
        assert surgeon["duration_bias_factor"] == BIAS_CLAMP_HI

        nxt = make_case(env["surgeon"]["id"], procedure_class="STANDARD")
        # round_half_up(90 * 1.250) = round_half_up(112.5) = 113
        assert nxt["predicted_duration_minutes"] == 113
        assert nxt["benchmark_duration_minutes"] == 90


class TestDualDurationVariants:
    def test_benchmark_vs_surgeon_adjusted_diverge(self, api):
        """PRD §3.3: "The `predicted_duration_minutes` is the surgeon-adjusted
        variant: the benchmark multiplied by the posting surgeon's
        `duration_bias_factor` at posting time, rounded half up to whole minutes."
        PRD §3.3: "Whenever the bias differs from 1.000, the same posting carries
        two different minute values, and both remain pinned no matter how the bias
        later evolves."

        Design: Difficulty/dual_variant_calc/case_duration_benchmark_vs_surgeon_adjusted
        """
        env = setup_surgeon_with_completions(
            line_name="ORTHO", target=75, block_start=420, block_end=1080,
            coverage_start=420, coverage_end=1200,
            procedure_class="STANDARD",
            actual_durations=[108, 108, 108, 108, 108],  # each ratio 1.2
        )
        surgeon = validate_success(api.get_surgeon(env["surgeon"]["id"], TEST_ADMIN), 200)
        assert surgeon["duration_bias_factor"] == 1.2
        assert surgeon["completed_cases_count"] == 5

        case = make_case(env["surgeon"]["id"], procedure_class="STANDARD",
                         patient_ref="P6")
        assert_case_posting(case)
        assert case["benchmark_duration_minutes"] == 90
        assert case["predicted_duration_minutes"] == 108
        assert case["predicted_duration_minutes"] != case["benchmark_duration_minutes"]

    def test_earlier_postings_stay_pinned_as_bias_evolves(self, api):
        """PRD §3.3: "Whenever the bias differs from 1.000, the same posting carries
        two different minute values, and both remain pinned no matter how the bias
        later evolves."

        Design: Difficulty/dual_variant_calc/case_duration_benchmark_vs_surgeon_adjusted
        """
        env = setup_surgeon_with_completions(
            line_name="ORTHO", target=75, block_start=420, block_end=1080,
            coverage_start=420, coverage_end=1200,
            procedure_class="STANDARD",
            actual_durations=[108, 108, 108, 108, 108],
        )
        surgeon = validate_success(api.get_surgeon(env["surgeon"]["id"], TEST_ADMIN), 200)
        assert surgeon["duration_bias_factor"] == 1.2

        # All five history cases were posted while bias was still 1.000 and must
        # keep their originally pinned durations.
        for prior in env["cases"]:
            reread = validate_success(api.get_case(prior["id"], TEST_ADMIN), 200)
            assert reread["benchmark_duration_minutes"] == 90
            assert reread["predicted_duration_minutes"] == 90
            assert reread["status"] == "COMPLETED"
