"""The two on-air forecast variants computed from one program state."""

from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_score,
    ok,
    parse_instant,
)
from test_helpers.constants import iso

TARGET_DATE = iso("2026-12-01")
BASELINE_DATE = iso("2026-11-15")
RISK_ADJUSTED_DATE = iso("2026-11-24")
REMAINING_DAYS = 45
RISK_DAYS = 54
SLIP_DAYS = -7
RISK_SCORE = 36.00


def test_baseline_and_risk_adjusted_forecasts_land_nine_days_apart(
    api: ApiClient,
) -> None:
    """One driver, one remaining-work total, two dates.

    PRD: "The **baseline** variant is simply the current logical clock advanced by
    the total remaining days — nominal durations, no delay factor, no continuance
    penalty — and is stored as `baseline_forecast_date`."

    PRD: "The **risk-adjusted** variant inflates the work: the remaining days are
    multiplied by the jurisdiction's `historical_delay_factor` and rounded *up* to
    a whole number of days, and to that is added the continuance count multiplied
    by the jurisdiction's `hearing_cadence_days`, so each continuance the
    authority granted costs one full hearing cycle."

    PRD: "Otherwise, if the driver has no backhaul order at all, forty-five days."

    Design: Difficulty/dual_variant_calc/on_air_baseline_vs_risk_adjusted_forecast_diverge
    """
    chain = S.build_selected_chain(api)

    plan = ok(
        api.create_on_air_plan(
            {"search_ring_id": chain["ring_id"], "target_on_air_date": TARGET_DATE},
            headers=S.director(),
        ),
        expected_status=201,
    )

    assert_instant(plan["baseline_forecast_date"], BASELINE_DATE, "baseline_forecast_date")
    assert_instant(
        plan["risk_adjusted_forecast_date"], RISK_ADJUSTED_DATE, "risk_adjusted_forecast_date"
    )
    gap = parse_instant(plan["risk_adjusted_forecast_date"]) - parse_instant(
        plan["baseline_forecast_date"]
    )
    assert gap.days == 9, (
        "the delay factor must inflate the nominal horizon, not leave it alone"
    )
    assert_fields(plan, driver_candidate_id=chain["cand_id"], status="PLANNED")


def test_forecast_read_reports_both_totals_without_mutating_the_plan(
    api: ApiClient,
) -> None:
    """The computed read exposes the nominal and inflated day counts side by side.

    PRD: "`schedule_risk_score` starts from a baseline of 50, adds 2.0 points for
    each day of slip (which subtracts when the slip is negative), adds 5 points
    for each continuance, and adds a further 10 points when the driver's
    `feasibility_status` is `STRUCTURAL_HOLD`, since a structure awaiting
    modification is the least predictable state in the pipeline."

    PRD: "It reports `baseline_forecast_date` and `risk_adjusted_forecast_date` as
    recomputed at the current logical clock, `remaining_days` as the nominal
    total, `risk_days` as the inflated total including continuance penalties,
    `schedule_risk_score`, `risk_band`, `slip_days`, and `driver_candidate_id`."

    PRD: "A computed read exposes the forecast to the program authority and the
    construction manager without mutating the plan."

    Design: Difficulty/dual_variant_calc/on_air_baseline_vs_risk_adjusted_forecast_diverge
    """
    chain = S.build_selected_chain(api)
    plan = ok(
        api.create_on_air_plan(
            {"search_ring_id": chain["ring_id"], "target_on_air_date": TARGET_DATE},
            headers=S.director(),
        ),
        expected_status=201,
    )
    assert_score(plan["schedule_risk_score"], RISK_SCORE, "schedule_risk_score")
    assert_fields(plan, risk_band="LOW")
    version_before = plan["version"]

    forecast = ok(api.get_forecast(plan["id"], headers=S.director()))
    assert_fields(
        forecast,
        remaining_days=REMAINING_DAYS,
        risk_days=RISK_DAYS,
        slip_days=SLIP_DAYS,
        risk_band="LOW",
        driver_candidate_id=chain["cand_id"],
    )
    assert_score(forecast["schedule_risk_score"], RISK_SCORE, "schedule_risk_score")

    unchanged = ok(api.get_on_air_plan(plan["id"], headers=S.director()))
    assert unchanged["version"] == version_before, (
        "the forecast read must not mutate the plan"
    )
