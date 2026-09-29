"""Back-wage exposure: the two valuation methods, the pinned rounding order and supersession."""

from typing import Any, Dict

import pytest

from test_helpers import (
    COMPENSATION_MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    BackWageMethod,
    ConversionMethod,
    ErrorId,
    EstimateStatus,
    RemediationPosture,
    assert_estimate_totals,
    assert_money,
    assert_project_ledgers,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_estimate(api, case_id: str, estimate_id: str) -> Dict[str, Any]:
    """The estimate listing is the only read path, and it keeps superseded rows."""
    rows, _ = validate_paginated(
        api.list_case_back_wage_estimates(case_id, COMPENSATION_MANAGER_HEADERS)
    )
    matches = [row for row in rows if row["id"] == estimate_id]
    assert len(matches) == 1, f"expected estimate {estimate_id} in the listing, got {rows}"
    return matches[0]


def _build_case(api, engagement: Dict[str, Any], conversion_method: str) -> Dict[str, Any]:
    """Corroborate the job at 49 validated hours, then open one case on it."""
    position_id = engagement["position_id"]
    fixtures.add_duty(
        api,
        position_id,
        duty_code="D-EX",
        description="Directs the shift and assigns crew",
        claimed_time_pct=45,
        is_exempt_duty=True,
    )
    fixtures.add_duty(
        api,
        position_id,
        duty_code="D-NX",
        description="Works the line alongside the crew",
        claimed_time_pct=55,
        is_exempt_duty=False,
        discretion_level="ROUTINE",
    )
    interviews = fixtures.corroborate_duties(api, position_id, "int-1")
    case = fixtures.open_case(api, position_id, conversion_method=conversion_method)
    return {**engagement, "interviews": interviews, "case": case, "case_id": case["id"]}


@pytest.fixture
def cost_neutral_case(api, willful_ca_engagement) -> Dict[str, Any]:
    """A three-year-lookback engagement with one corroborated job and one open case."""
    return _build_case(api, willful_ca_engagement, ConversionMethod.COST_NEUTRAL_WITH_OT)


@pytest.fixture
def salary_div_case(api, willful_ca_engagement) -> Dict[str, Any]:
    """The same engagement whose case converts on the straight 2,080-hour divisor."""
    return _build_case(api, willful_ca_engagement, ConversionMethod.SALARY_DIV_2080)


@pytest.fixture
def misclassified_case(api, cost_neutral_case) -> Dict[str, Any]:
    """The job is determined nonexempt, so its exposure counts in the engagement rollup."""
    analysis = fixtures.author_analysis(api, cost_neutral_case["position_id"])
    fixtures.submit_analysis(api, analysis["id"])
    fixtures.determine_analysis(api, analysis["id"])
    return {**cost_neutral_case, "analysis_id": analysis["id"]}


@pytest.fixture
def uninterviewed_case(api, willful_ca_engagement) -> Dict[str, Any]:
    """No interviews at all, so the employer-reported 47 hours drive the overtime figure."""
    case = fixtures.open_case(api, willful_ca_engagement["position_id"])
    return {**willful_ca_engagement, "case": case, "case_id": case["id"]}


def test_full_rate_values_the_overtime_against_a_forty_hour_divisor(api, cost_neutral_case):
    """The salary is held to buy 40 hours, so every overtime hour is billed at time and a half.

    PRD: "Under `FULL_RATE` the salary is held to cover 40 hours only, so the regular rate is the
    weekly salary divided by 40, and `week_ot_cents` is the overtime hours multiplied by that
    regular rate multiplied by one and a half, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/back_wage_full_rate_versus_half_time_diverge_on_identical_case
    """
    estimate = fixtures.estimate_back_wages(api, cost_neutral_case["case_id"])

    assert_estimate_totals(
        estimate,
        lookback_weeks=156,
        weekly_ot_hours=9,
        week_ot_cents=35697,
        gross_exposure_cents=11137464,
        liquidated_damages_cents=11137464,
        total_exposure_cents=22274928,
    )
    assert estimate["status"] == EstimateStatus.ACTIVE, (
        f"the only estimate on the case is ACTIVE, got {estimate['status']}"
    )
    assert estimate["method"] == BackWageMethod.FULL_RATE, (
        f"the recorded method must be FULL_RATE, got {estimate['method']}"
    )

    case = fixtures.read_case(api, cost_neutral_case["case_id"])
    assert_money(case["exposure_cents"], 22274928, "case exposure_cents")


def test_half_time_divides_by_the_validated_hours_and_supersedes_the_full_rate_row(
    api, cost_neutral_case
):
    """Re-valuing the identical case under the fluctuating-workweek theory is far cheaper.

    PRD: "For identical inputs `HALF_TIME` yields a strictly smaller exposure than `FULL_RATE`
    whenever `validated_weekly_hours` exceeds 40, which is exactly why the choice of `method` is a
    decision the audit records rather than a detail."

    Design: Difficulty/dual_variant_calc/back_wage_full_rate_versus_half_time_diverge_on_identical_case
    """
    case_id = cost_neutral_case["case_id"]
    full_rate = fixtures.estimate_back_wages(api, case_id, BackWageMethod.FULL_RATE)
    half_time = fixtures.estimate_back_wages(api, case_id, BackWageMethod.HALF_TIME)

    assert_estimate_totals(
        half_time,
        lookback_weeks=156,
        weekly_ot_hours=9,
        week_ot_cents=9713,
        gross_exposure_cents=3030456,
        liquidated_damages_cents=3030456,
        total_exposure_cents=6060912,
    )
    assert half_time["total_exposure_cents"] < full_rate["total_exposure_cents"], (
        "the half-time valuation must be strictly smaller, got "
        f"{half_time['total_exposure_cents']} against {full_rate['total_exposure_cents']}"
    )
    assert half_time["status"] == EstimateStatus.ACTIVE, (
        f"the newest estimate is the live one, got {half_time['status']}"
    )

    superseded = _read_estimate(api, case_id, full_rate["id"])
    assert superseded["status"] == EstimateStatus.SUPERSEDED, (
        f"the earlier estimate must be SUPERSEDED, got {superseded['status']}"
    )
    assert_money(
        superseded["total_exposure_cents"], 22274928, "superseded total_exposure_cents"
    )

    case = fixtures.read_case(api, case_id)
    assert_money(case["exposure_cents"], 6060912, "case exposure_cents")

    project = fixtures.read_project(api, cost_neutral_case["project_id"])
    assert_project_ledgers(project, exposure_cents=0)


def test_the_weekly_overtime_figure_is_rounded_before_it_is_multiplied(api, salary_div_case):
    """Rounding 35697.0375 to whole cents happens per week, not once at the end.

    PRD: "The rounding order here is pinned and consequential: `week_ot_cents` is rounded to whole
    cents **before** any multiplication."

    Design: Difficulty/combinatorial_formula/back_wage_rounding_order_pinned_round_per_week_before_multiplying
    """
    estimate = fixtures.estimate_back_wages(api, salary_div_case["case_id"])

    assert_money(estimate["week_ot_cents"], 35697, "week_ot_cents")
    assert_money(estimate["gross_exposure_cents"], 11137464, "gross_exposure_cents")
    assert estimate["gross_exposure_cents"] != 11137476, (
        "11137476 is the multiply-first, round-last result and must not be reported"
    )


def test_the_gross_exposure_scales_the_rounded_week_by_weeks_and_incumbents(api, salary_div_case):
    """Two incumbents across 156 weeks multiply the already-rounded weekly figure.

    PRD: "Then `gross_exposure_cents` is `week_ot_cents` multiplied by `lookback_weeks` multiplied
    by the position's `incumbent_count`."

    Design: Difficulty/combinatorial_formula/back_wage_rounding_order_pinned_round_per_week_before_multiplying
    """
    estimate = fixtures.estimate_back_wages(api, salary_div_case["case_id"])

    assert_estimate_totals(
        estimate,
        lookback_weeks=156,
        weekly_ot_hours=9,
        week_ot_cents=35697,
        gross_exposure_cents=11137464,
        liquidated_damages_cents=11137464,
        total_exposure_cents=22274928,
    )
    assert estimate["gross_exposure_cents"] == estimate["week_ot_cents"] * 156 * 2, (
        "the gross figure must be the rounded week scaled by 156 weeks and 2 incumbents, got "
        f"{estimate['gross_exposure_cents']}"
    )


def test_superseding_an_estimate_replaces_rather_than_adds_to_the_engagement_exposure(
    api, misclassified_case
):
    """The rollup follows the live estimate only; the superseded row neither adds nor lingers.

    PRD: "The `total_back_wage_exposure_cents` sums `total_exposure_cents` over back-wage estimates
    whose `status` is `ACTIVE` and whose case's position belongs to this engagement **and** whose
    case's position has a `classification_status` of `MISCLASSIFIED` or `RECLASSIFIED` -- so
    rescinding a determination back to `UNREVIEWED` drops that exposure out of the rollup without
    deleting the estimate."

    Design: Corner/calculations/superseding_a_back_wage_estimate_replaces_rather_than_adds_to_exposure
    """
    case_id = misclassified_case["case_id"]
    full_rate = fixtures.estimate_back_wages(api, case_id, BackWageMethod.FULL_RATE)

    project = fixtures.read_project(api, misclassified_case["project_id"])
    assert_project_ledgers(project, exposure_cents=22274928)

    half_time = fixtures.estimate_back_wages(api, case_id, BackWageMethod.HALF_TIME)
    assert_money(half_time["total_exposure_cents"], 6060912, "half-time total_exposure_cents")

    superseded = _read_estimate(api, case_id, full_rate["id"])
    assert superseded["status"] == EstimateStatus.SUPERSEDED, (
        f"the earlier estimate must be SUPERSEDED, got {superseded['status']}"
    )
    assert_money(
        superseded["total_exposure_cents"],
        22274928,
        "the superseded row must be preserved, not rewritten",
    )

    case = fixtures.read_case(api, case_id)
    assert_money(case["exposure_cents"], 6060912, "case exposure_cents")

    project = fixtures.read_project(api, misclassified_case["project_id"])
    assert_project_ledgers(
        project, exposure_cents=6060912, headcount=2, posture=RemediationPosture.FROZEN
    )
    assert project["total_back_wage_exposure_cents"] != 28335840, (
        "the rollup must not add the superseded row to the live one"
    )

    rows, meta = validate_paginated(
        api.list_case_back_wage_estimates(case_id, COMPENSATION_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 2, (
        f"both estimates must survive as history, got {meta['total_count']} rows"
    )
    active = [row for row in rows if row["status"] == EstimateStatus.ACTIVE]
    assert len(active) == 1, f"exactly one estimate may be ACTIVE, got {len(active)}"
    assert active[0]["id"] == half_time["id"], "the live estimate is the half-time one"


def test_an_estimate_for_an_unknown_case_returns_case_not_found(api, uninterviewed_case):
    """The foreign key is resolved before the version token is ever compared.

    PRD: "Every entity referenced by a foreign-key field in the body exists, else the matching 404
    -- `ERR_AUDIT_PROJECT_NOT_FOUND` for `audit_project_id`, `ERR_JOB_FAMILY_NOT_FOUND` for
    `job_family_id` or `parent_family_id`, `ERR_POSITION_NOT_FOUND` for `position_id`,
    `ERR_RECLASS_CASE_NOT_FOUND` for `reclassification_case_id`."

    Design: Corner/endpoints/back_wage_estimate_for_an_unknown_case_returns_reclass_case_not_found
    """
    genuine_case = uninterviewed_case["case"]

    validate_error(
        api.create_back_wage_estimate(
            factories.back_wage_estimate_payload(NON_EXISTENT_UUID, genuine_case["version"]),
            COMPENSATION_MANAGER_HEADERS,
        ),
        ErrorId.RECLASS_CASE_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(
        api.list_case_back_wage_estimates(genuine_case["id"], COMPENSATION_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the genuine case must hold no estimate, got {meta['total_count']} rows"
    )
    assert rows == [], f"the genuine case must hold no estimate, got {rows}"

    unchanged = fixtures.read_case(api, genuine_case["id"])
    assert_money(unchanged["exposure_cents"], 0, "exposure_cents")
    assert unchanged["version"] == genuine_case["version"], (
        f"the case version must not move, got {unchanged['version']}"
    )


def test_a_stale_case_version_blocks_the_estimate_then_the_fresh_one_succeeds(
    api, uninterviewed_case
):
    """Sending the notice moves the case version, so the token read at creation is refused.

    PRD: "A new estimate legitimately supersedes the prior `ACTIVE` one, so a second sequential
    create would otherwise simply succeed; a mismatch is rejected with `ERR_STALE_CASE_VERSION` and
    HTTP 412, signalling that the case's exposure inputs moved after the client read them."

    Design: Corner/complexity_layers/stale_case_version_blocks_the_back_wage_estimate_then_the_fresh_one_succeeds
    """
    case_id = uninterviewed_case["case_id"]
    stale_version = uninterviewed_case["case"]["version"]

    fixtures.send_notice(api, case_id)

    validate_error(
        api.create_back_wage_estimate(
            factories.back_wage_estimate_payload(case_id, stale_version),
            COMPENSATION_MANAGER_HEADERS,
        ),
        ErrorId.STALE_CASE_VERSION,
        412,
    )
    _, meta = validate_paginated(
        api.list_case_back_wage_estimates(case_id, COMPENSATION_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the refused create must have written nothing, got {meta['total_count']} rows"
    )

    fresh_version = fixtures.read_case(api, case_id)["version"]
    assert fresh_version > stale_version, (
        f"the notice must advance the version past {stale_version}, got {fresh_version}"
    )

    estimate = validate_success(
        api.create_back_wage_estimate(
            factories.back_wage_estimate_payload(case_id, fresh_version),
            COMPENSATION_MANAGER_HEADERS,
        ),
        201,
    )
    assert_estimate_totals(
        estimate,
        lookback_weeks=156,
        weekly_ot_hours=7,
        week_ot_cents=27764,
        gross_exposure_cents=8662368,
        liquidated_damages_cents=8662368,
        total_exposure_cents=17324736,
    )
    assert estimate["status"] == EstimateStatus.ACTIVE, (
        f"the accepted estimate is ACTIVE, got {estimate['status']}"
    )

    case = fixtures.read_case(api, case_id)
    assert_money(case["exposure_cents"], 17324736, "case exposure_cents")

    project = fixtures.read_project(api, uninterviewed_case["project_id"])
    assert_project_ledgers(project, exposure_cents=0)
