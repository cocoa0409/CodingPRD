"""The ACP test: the two testing methods, the two roundings and the correction remedy."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_row,
    assert_cents,
    assert_correction_adjustment_shape,
    assert_nondiscrimination_test_shape,
    assert_ratio_4dp,
)
from test_helpers.test_users import ADMIN_HEADERS, AUDITOR_HEADERS

# Three non-highly-compensated deferrals whose raw ratios are 0.010049, 0.010049
# and 0.010449, so the group average depends on whether each ratio is rounded first.
SPLIT_RATIO_DEFERRALS = (10_049, 10_049, 10_449)


# ---------------------------------------------------------------------------
# The current-year / prior-year method flip
# ---------------------------------------------------------------------------


def test_acp_current_year_method_fails_on_the_current_year_average(client):
    """
    Under the current-year method the limit is built from this year's own NHCE average.

    PRD: "Under the current-year method `nhce_acp` is computed the same way from the
    non-highly-compensated group; under the prior-year method it is simply read from
    the plan year's stored `prior_year_nhce_acp`, so identical current-year data can
    produce a different limit and a different outcome depending on which method the
    test was opened with."

    PRD: "When `hce_acp` is strictly greater than `limit_acp` the test moves `PENDING`
    → `FAILED`, which does not block the reopen but does open the correction path."

    Design: Difficulty/dual_variant_calc/acp_current_year_vs_prior_year_method_flip
    """
    scenario = fx.setup_computed_test(
        client,
        nhce_deferrals=SPLIT_RATIO_DEFERRALS,
        hce_deferrals=(30_000,),
        plan_year_overrides={"prior_year_nhce_acp": 0.0260},
        test_overrides={"test_method": "CURRENT_YEAR"},
    )
    test = scenario["test"]

    assert_nondiscrimination_test_shape(test)
    assert test["nhce_count"] == 3
    assert test["hce_count"] == 1
    assert_ratio_4dp(test["hce_acp"], 0.0300, "hce_acp")
    assert_ratio_4dp(test["nhce_acp"], 0.0101, "nhce_acp")
    assert_ratio_4dp(test["limit_acp"], 0.0202, "limit_acp")
    assert test["status"] == "FAILED"


def test_acp_prior_year_method_passes_on_identical_data(client):
    """
    The prior-year method reads the stored average and flips the same data to a pass.

    PRD: "`prior_year_nhce_acp`, the stored prior-year non-highly-compensated average
    contribution percentage carried to four decimal places and used only by the
    prior-year method, defaulting to 0.0000".

    PRD: "When `hce_acp` is less than or equal to `limit_acp` the test moves `PENDING`
    → `PASSED`, which blocks the plan year's `LOCKED` → `OPEN` reopen with
    `ERR_TEST_ALREADY_FINAL`."

    Design: Difficulty/dual_variant_calc/acp_current_year_vs_prior_year_method_flip
    """
    scenario = fx.setup_computed_test(
        client,
        nhce_deferrals=SPLIT_RATIO_DEFERRALS,
        hce_deferrals=(30_000,),
        plan_year_overrides={"prior_year_nhce_acp": 0.0260},
        test_overrides={"test_method": "PRIOR_YEAR"},
    )
    test = scenario["test"]

    assert test["nhce_count"] == 3
    assert test["hce_count"] == 1
    assert_ratio_4dp(test["hce_acp"], 0.0300, "hce_acp")
    assert_ratio_4dp(test["nhce_acp"], 0.0260, "nhce_acp")
    assert_ratio_4dp(test["limit_acp"], 0.0460, "limit_acp")
    assert test["status"] == "PASSED"


# ---------------------------------------------------------------------------
# Rounding per participant and again on the group average
# ---------------------------------------------------------------------------


def test_acp_average_rounds_after_each_participant_ratio(client):
    """
    Rounding each participant ratio before averaging yields 0.0101, not 0.0102.

    PRD: "The participant's contribution ratio is the numerator divided by the
    denominator, rounded half up to four decimal places — the first of the two
    roundings."

    PRD: "Nondiscrimination ratios are carried to four decimal places with round half
    up, and the rounding is applied twice: once per participant, and again on the group
    average of the already-rounded participant ratios."

    Design: Difficulty/combinatorial_formula/acp_round_per_participant_then_average
    """
    scenario = fx.setup_computed_test(client, nhce_deferrals=SPLIT_RATIO_DEFERRALS)
    test = scenario["test"]

    first, _, third = scenario["nhce"]
    assert_cents(
        first["contribution_record"]["deferral_match_cents"], 10_049, "first deferral match"
    )
    assert_cents(
        third["contribution_record"]["deferral_match_cents"], 10_449, "third deferral match"
    )

    assert test["nhce_count"] == 3
    assert_ratio_4dp(test["nhce_acp"], 0.0101, "nhce_acp")
    assert round(float(test["nhce_acp"]), 4) != 0.0102, (
        "nhce_acp is 0.0102, which is the value produced by averaging the raw ratios "
        "and rounding only once"
    )


def test_acp_limit_and_outcome_follow_the_twice_rounded_average(client):
    """
    The statutory limit is built from the twice-rounded average and decides the outcome.

    PRD: "`limit_acp` is the greater of two candidates, rounded half up to four
    decimal places: `nhce_acp` multiplied by 1.25, and the lesser of `nhce_acp`
    multiplied by 2 and `nhce_acp` plus 0.02."

    PRD: "`hce_acp` is 0.0000 when `hce_count` is zero, and otherwise the sum of the
    already-rounded highly-compensated ratios divided by `hce_count`, rounded half up
    to four decimal places — the second rounding."

    Design: Difficulty/combinatorial_formula/acp_round_per_participant_then_average
    """
    scenario = fx.setup_computed_test(client, nhce_deferrals=SPLIT_RATIO_DEFERRALS)
    test = scenario["test"]

    assert test["hce_count"] == 0
    assert_ratio_4dp(test["hce_acp"], 0.0000, "hce_acp")
    assert_ratio_4dp(test["nhce_acp"], 0.0101, "nhce_acp")
    assert_ratio_4dp(test["limit_acp"], 0.0202, "limit_acp")
    assert test["status"] == "PASSED"
    assert test["computed_at"] is not None


# ---------------------------------------------------------------------------
# The four-decimal rounding boundary
# ---------------------------------------------------------------------------


def test_acp_ratio_exactly_on_the_half_rounds_up(client):
    """
    A raw ratio of exactly 0.010050 rounds up to 0.0101 at the fourth decimal.

    PRD: "The denominator is the participant's total `counted_compensation_cents`. The
    participant's contribution ratio is the numerator divided by the denominator,
    rounded half up to four decimal places — the first of the two roundings."

    Design: Difficulty/boundary_precision_check/acp_ratio_exact_half_rounds_up
    """
    scenario = fx.setup_computed_test(client, nhce_deferrals=(10_050,))
    record = scenario["nhce"][0]["contribution_record"]

    assert_cents(record["deferral_match_cents"], 10_050, "deferral_match_cents")
    assert_cents(record["counted_compensation_cents"], 1_000_000, "counted_compensation_cents")

    test = scenario["test"]
    assert test["nhce_count"] == 1
    assert test["hce_count"] == 0
    assert_ratio_4dp(test["nhce_acp"], 0.0101, "nhce_acp")
    assert_ratio_4dp(test["hce_acp"], 0.0000, "hce_acp")
    assert_ratio_4dp(test["limit_acp"], 0.0202, "limit_acp")
    assert test["status"] == "PASSED"


def test_acp_ratio_just_below_the_half_rounds_down(client):
    """
    One cent below the half the same ratio rounds down to 0.0100 instead.

    PRD: "Nondiscrimination ratios are carried to four decimal places with round half
    up, and the rounding is applied twice: once per participant, and again on the group
    average of the already-rounded participant ratios."

    Design: Difficulty/boundary_precision_check/acp_ratio_exact_half_rounds_up
    """
    scenario = fx.setup_computed_test(client, nhce_deferrals=(10_049,))
    record = scenario["nhce"][0]["contribution_record"]

    assert_cents(record["deferral_match_cents"], 10_049, "deferral_match_cents")
    assert_cents(record["counted_compensation_cents"], 1_000_000, "counted_compensation_cents")

    test = scenario["test"]
    assert test["nhce_count"] == 1
    assert_ratio_4dp(test["nhce_acp"], 0.0100, "nhce_acp")
    assert_ratio_4dp(test["limit_acp"], 0.0200, "limit_acp")
    assert test["status"] == "PASSED"


# ---------------------------------------------------------------------------
# Compute guards and the correction remedy
# ---------------------------------------------------------------------------


def test_acp_compute_without_nhce_population_rejected(client):
    """
    With no non-highly-compensated participant there is no reference population.

    PRD: "A test with no non-highly-compensated participant has no reference
    population and is rejected with `ERR_NO_NHCE_POPULATION`."

    PRD: "The test begins in `PENDING` with all five computed figures at their zero
    defaults and `computed_at` null."

    Design: Corner/calculations/corner_acp_compute_without_nhce_population_rejected
    """
    scenario = fx.setup_acp_population(client, hce_deferrals=(20_000,))
    assert scenario["hce"][0]["employee"]["hce_flag"] is True

    test = fx.open_nondiscrimination_test(client, scenario["plan_year_id"])
    assert test["status"] == "PENDING"

    response = client.compute_nondiscrimination_test(
        test["id"], {"include_qslp_match": True}, AUDITOR_HEADERS
    )
    validate_error(response, ApiErrorId.NO_NHCE_POPULATION.value, 422)

    after = validate_success(client.get_nondiscrimination_test(test["id"], AUDITOR_HEADERS))
    assert after["status"] == "PENDING"
    assert after["computed_at"] is None
    assert_ratio_4dp(after["nhce_acp"], 0.0000, "nhce_acp")


def test_failed_acp_correction_creates_per_hce_forfeiture(client):
    """
    Correcting a failed test writes one negative adjustment per over-limit HCE.

    PRD: "It then writes a correction adjustment for that participant carrying the
    `employee_id`, the `plan_year_id`, the `nondiscrimination_test_id` of this test,
    `reason_code` `ACP_CORRECTIVE_FORFEITURE`, `match_allocation_id` null, and
    `amount_cents` equal to the negative of the excess."

    PRD: "`total_deferral_match_funded_cents` is the sum of `deferral_match_cents`
    across the contribution records of the plan year's payroll periods, plus the sum of
    `amount_cents` over the plan year's correction adjustments whose `reason_code` is
    `ACP_CORRECTIVE_FORFEITURE`."

    Design: Corner/endpoints/corner_failed_acp_correction_creates_per_hce_forfeiture
    """
    scenario = fx.setup_computed_test(
        client, nhce_deferrals=(5_000,), hce_deferrals=(50_000,)
    )
    highly_compensated = scenario["hce"][0]
    non_highly_compensated = scenario["nhce"][0]

    assert highly_compensated["employee"]["hce_flag"] is True
    assert non_highly_compensated["employee"]["hce_flag"] is False
    assert_cents(
        highly_compensated["contribution_record"]["deferral_match_cents"], 40_000, "hce match"
    )
    assert_cents(
        non_highly_compensated["contribution_record"]["deferral_match_cents"], 5_000, "nhce match"
    )

    plan_year_before = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(
        plan_year_before["total_deferral_match_funded_cents"], 45_000, "deferral match before"
    )

    test = scenario["test"]
    assert test["status"] == "FAILED"
    assert test["hce_count"] == 1
    assert test["nhce_count"] == 1
    assert_ratio_4dp(test["hce_acp"], 0.0400, "hce_acp")
    assert_ratio_4dp(test["nhce_acp"], 0.0050, "nhce_acp")
    assert_ratio_4dp(test["limit_acp"], 0.0100, "limit_acp")

    corrected = fx.correct_nondiscrimination_test(client, scenario["test_id"])
    assert corrected["status"] == "CORRECTED"
    assert corrected["correction_method"] == "CORRECTIVE_FORFEITURE"
    assert_cents(corrected["total_correction_cents"], -30_000, "total_correction_cents")

    listing = client.list_correction_adjustments(
        AUDITOR_HEADERS, {"nondiscrimination_test_id": scenario["test_id"]}
    )
    adjustments, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    adjustment = adjustments[0]
    assert_correction_adjustment_shape(adjustment)
    assert_append_only_row(adjustment, "CorrectionAdjustment")
    assert adjustment["reason_code"] == "ACP_CORRECTIVE_FORFEITURE"
    assert adjustment["employee_id"] == highly_compensated["employee"]["id"]
    assert_cents(adjustment["amount_cents"], -30_000, "adjustment amount_cents")
    assert adjustment["match_allocation_id"] is None

    read_back = validate_success(
        client.get_correction_adjustment(adjustment["id"], ADMIN_HEADERS)
    )
    assert read_back["id"] == adjustment["id"]
    assert read_back["match_allocation_id"] is None

    plan_year_after = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(
        plan_year_after["total_deferral_match_funded_cents"], 15_000, "deferral match after"
    )

    nhce_listing = client.list_correction_adjustments(
        AUDITOR_HEADERS, {"employee_id": non_highly_compensated["employee"]["id"]}
    )
    nhce_adjustments, nhce_meta = validate_paginated(nhce_listing)
    assert len(nhce_adjustments) == 0
    assert nhce_meta["total_count"] == 0


def test_compute_on_passed_test_rejected(client):
    """
    A passed test is final and may not be recomputed.

    PRD: "Computing the test is available while its status is `PENDING` or `STALE`;
    any other status is refused with `ERR_TEST_ALREADY_FINAL`, and the plan year must
    be `OPEN` or `LOCKED`."

    Design: Corner/errors/corner_compute_on_passed_test_rejected
    """
    scenario = fx.setup_computed_test(client, nhce_deferrals=(20_000,))
    test = scenario["test"]

    assert test["status"] == "PASSED"
    assert test["nhce_count"] == 1
    assert_ratio_4dp(test["nhce_acp"], 0.0200, "nhce_acp")
    assert_ratio_4dp(test["hce_acp"], 0.0000, "hce_acp")
    assert_ratio_4dp(test["limit_acp"], 0.0400, "limit_acp")

    response = client.compute_nondiscrimination_test(
        scenario["test_id"], {"include_qslp_match": True}, AUDITOR_HEADERS
    )
    validate_error(response, ApiErrorId.TEST_ALREADY_FINAL.value, 409)

    after = validate_success(
        client.get_nondiscrimination_test(scenario["test_id"], AUDITOR_HEADERS)
    )
    assert after["status"] == "PASSED"
    assert_ratio_4dp(after["nhce_acp"], 0.0200, "nhce_acp after")
