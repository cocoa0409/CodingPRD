"""Four pinned computations: flat-step rent, the lowest fee tier, a 30-day window, a band edge."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_money,
    assert_score,
    created,
    failed,
    ok,
)
from test_helpers.constants import iso

# --- flat-step lease economics ---------------------------------------------
STEP_USD = 50.00
INITIAL_TERM_YEARS = 5
RENEWAL_OPTION_COUNT = 1
RENEWAL_TERM_YEARS = 5
REVENUE_SHARE_PCT = 0.10
PROVISIONAL_TOTAL_USD = 150000.00
FINAL_TOTAL_USD = 346500.00
DELTA_USD = 196500.00
PRICED_YEARS = 10
FIRST_YEAR_RENT_USD = 28800.00
LAST_YEAR_RENT_USD = 34200.00

# --- by-right filing fee and shot clock ------------------------------------
BY_RIGHT_FEE_TOTAL_USD = 1560.00
BY_RIGHT_DEADLINE = iso("2026-09-30")

# --- tribal response window ------------------------------------------------
TCNS_NOTICE_DATE = C.CLOCK_DEFAULT
TRIBAL_DEADLINE = iso("2026-08-31")
ONE_DAY_EARLY = iso("2026-08-30")

# --- on-air risk band ------------------------------------------------------
BASELINE_FORECAST_DATE = iso("2027-02-28")
RISK_ADJUSTED_FORECAST_DATE = iso("2027-04-12")
TARGET_AT_HIGH_EDGE = iso("2027-04-02")
TARGET_ONE_DAY_LATER = iso("2027-04-03")
SCORE_AT_HIGH_EDGE = 70.00
SCORE_ONE_STEP_BELOW = 68.00


def _executed_flat_step_lease(api: ApiClient) -> str:
    """A `FLAT_STEP` lease at 2400.00 with a 50.00 monthly step, executed."""
    chain = S.engaged_candidate(api)
    lease = S.create_lease(
        api,
        chain["cand_id"],
        chain["ll_id"],
        escalation_type="FLAT_STEP",
        escalation_pct=0,
        escalation_step_usd=STEP_USD,
        initial_term_years=INITIAL_TERM_YEARS,
        renewal_option_count=RENEWAL_OPTION_COUNT,
        renewal_term_years=RENEWAL_TERM_YEARS,
        revenue_share_pct=REVENUE_SHARE_PCT,
    )
    S.accept_lease(api, lease["id"])
    return lease["id"]


def test_a_flat_step_lease_totals_both_variants_from_the_same_year_series(
    api: ApiClient,
) -> None:
    """No compounding: ten stepped years, then a ten-percent revenue-share uplift.

    PRD: "Under `FLAT_STEP` there is no compounding at all: the monthly rent for year
    *y* is `base_monthly_rent_usd` plus `escalation_step_usd` multiplied by *y* minus
    one, and the annual figure is that monthly rent multiplied by 12."

    PRD: "Summing unrounded annual figures and rounding once at the end is explicitly
    incorrect."

    PRD: "The **final** variant, written to `committed_rent_final_usd` at execution,
    assumes every renewal option is exercised: its horizon is `initial_term_years` plus
    `renewal_option_count` multiplied by `renewal_term_years`, it sums the rounded years
    1 through that horizon and rounds the sum to two decimal places to obtain a base
    total, then computes a revenue-share uplift as that base total multiplied by
    `revenue_share_pct` rounded half up to two decimal places, and finally stores the
    base total plus the uplift, again rounded half up to two decimal places."

    PRD: "It reports `provisional_total_usd` and `final_total_usd` as just defined,
    `delta_usd` as the final total minus the provisional total rounded half up to two
    decimal places, `priced_years` as the full final-variant horizon in years, and the
    two ends of the per-year series — `first_year_rent_usd`, the rounded annual rent for
    year 1, and `last_year_rent_usd`, the rounded annual rent for the final year of that
    horizon."

    Design: Corner/calculations/corner_lease_flat_step_escalation_totals
    """
    lease_id = _executed_flat_step_lease(api)

    executed = ok(
        api.execute_lease(
            lease_id, {"execution_date": C.CLOCK_DEFAULT}, headers=S.director()
        )
    )
    assert_fields(executed, status="EXECUTED")
    assert_money(
        executed["committed_rent_provisional_usd"],
        PROVISIONAL_TOTAL_USD,
        "committed_rent_provisional_usd",
    )
    assert_money(
        executed["committed_rent_final_usd"], FINAL_TOTAL_USD, "committed_rent_final_usd"
    )

    schedule = ok(api.get_rent_schedule(lease_id, headers=S.director()))
    assert_money(schedule["provisional_total_usd"], PROVISIONAL_TOTAL_USD, "provisional_total_usd")
    assert_money(schedule["final_total_usd"], FINAL_TOTAL_USD, "final_total_usd")
    assert_money(schedule["delta_usd"], DELTA_USD, "delta_usd")
    assert_fields(schedule, priced_years=PRICED_YEARS)
    assert_money(schedule["first_year_rent_usd"], FIRST_YEAR_RENT_USD, "first_year_rent_usd")
    assert_money(schedule["last_year_rent_usd"], LAST_YEAR_RENT_USD, "last_year_rent_usd")


def test_a_by_right_filing_takes_the_lowest_expedite_tier_and_sixty_review_days(
    api: ApiClient,
) -> None:
    """A 1500.00 subtotal with no simulations sits below 4000, so the rate is 0.04.

    PRD: "Step one builds a subtotal: a base fee determined by `application_type` —
    1500.00 for `BY_RIGHT`, 3200.00 for `CONDITIONAL_USE`, 4800.00 for `VARIANCE` — plus
    250.00 for each simulation counted in `visual_simulation_count`, plus a
    historic-district surcharge of 900.00 when the jurisdiction's
    `historic_district_flag` is true and nothing when it is false."

    PRD: "Step two selects an expedite rate **from that step-one subtotal**: a subtotal
    of 6000 or more takes 0.12, a subtotal of at least 4000 but below 6000 takes 0.08,
    and a subtotal below 4000 takes 0.04."

    PRD: "Step four stores `zoning_fee_total_usd` as the subtotal plus the expedite fee,
    rounded half up to two decimal places."

    PRD: "`shot_clock_deadline_date` is the `submitted_date` advanced by the number of
    review days the jurisdiction publishes for this application's path —
    `by_right_review_days` for `BY_RIGHT`, `conditional_use_review_days` for
    `CONDITIONAL_USE`, `variance_review_days` for `VARIANCE` — and further advanced by
    the application's accumulated `tolled_days`."

    Design: Corner/calculations/corner_by_right_fee_lowest_tier_and_sixty_day_shot_clock
    """
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api, requires_visual_simulation=False)
    ring = S.create_open_ring(api)
    landlord = S.create_landlord(api)
    candidate = S.create_candidate(api, ring["id"], landlord["id"], jurisdiction["id"])
    S.engage_landlord(api, candidate["id"])
    lease = S.create_lease(api, candidate["id"], landlord["id"])
    S.accept_lease(api, lease["id"])
    S.execute_lease(api, lease["id"])
    application = S.create_zoning_application(
        api, candidate["id"], application_type="BY_RIGHT"
    )

    submitted = ok(api.submit_zoning_application(application["id"], headers=S.planner()))

    assert_fields(
        submitted, status="SUBMITTED", visual_simulation_count=0, tolled_days=0
    )
    assert_money(
        submitted["zoning_fee_total_usd"], BY_RIGHT_FEE_TOTAL_USD, "zoning_fee_total_usd"
    )
    assert_instant(submitted["submitted_date"], C.CLOCK_DEFAULT, "submitted_date")
    assert_instant(
        submitted["shot_clock_deadline_date"], BY_RIGHT_DEADLINE, "shot_clock_deadline_date"
    )


def _screened_tribal_review(api: ApiClient) -> Dict[str, Any]:
    """A `SCREENING` review whose tribal branch is `PENDING` on a 30-day window."""
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api, tribal_consultation_required=True)
    ring = S.create_open_ring(api)
    landlord = S.create_landlord(api)
    candidate = S.create_candidate(api, ring["id"], landlord["id"], jurisdiction["id"])
    review = S.create_environmental_review(api, candidate["id"])
    screened = S.screen_review(api, review["id"])
    return {"er_id": review["id"], "cand_id": candidate["id"], "screened": screened}


def test_the_tribal_branch_closes_on_the_deadline_but_not_the_day_before(
    api: ApiClient,
) -> None:
    """Thirty days after the TCNS notice, equality is enough; one day early is not.

    PRD: "The tribal branch depends on scope: when `tribal_consultation_required` is
    true, `tribal_branch_status` becomes `PENDING`, `tcns_notice_date` is stamped with
    the logical clock as the moment the TCNS notice went out, and
    `tribal_response_deadline_date` is set to thirty days after `tcns_notice_date`; when
    `tribal_consultation_required` is false, `tribal_branch_status` becomes
    `NOT_APPLICABLE` and both dates stay null."

    PRD: "Equality closes the branch; one second earlier does not, and the attempt is
    refused with `ERR_TRIBAL_RESPONSE_WINDOW_OPEN`."

    PRD: "With a `NO_ADVERSE_EFFECT` finding, closing one branch while the other is
    still `PENDING` moves the review `SCREENING → IN_CONSULTATION`."

    Design: Corner/calculations/corner_tribal_response_window_equality_closes_branch
    """
    scenario = _screened_tribal_review(api)
    screened = scenario["screened"]
    assert_fields(
        screened,
        tribal_consultation_required=True,
        tribal_branch_status="PENDING",
        public_notice_branch_status="PENDING",
    )
    assert_instant(screened["tcns_notice_date"], TCNS_NOTICE_DATE, "tcns_notice_date")
    assert_instant(
        screened["tribal_response_deadline_date"],
        TRIBAL_DEADLINE,
        "tribal_response_deadline_date",
    )

    S.set_clock(api, ONE_DAY_EARLY)
    refused = api.complete_branch(
        scenario["er_id"],
        {"branch": "TRIBAL", "finding": "NO_ADVERSE_EFFECT"},
        headers=S.reviewer(),
    )
    failed(refused, ApiError.TRIBAL_RESPONSE_WINDOW_OPEN, expected_status=409)

    S.set_clock(api, TRIBAL_DEADLINE)
    closed = ok(
        api.complete_branch(
            scenario["er_id"],
            {"branch": "TRIBAL", "finding": "NO_ADVERSE_EFFECT"},
            headers=S.reviewer(),
        )
    )
    assert_fields(
        closed,
        tribal_branch_status="COMPLETE",
        public_notice_branch_status="PENDING",
        status="IN_CONSULTATION",
    )

    candidate = ok(api.get_candidate(scenario["cand_id"], headers=S.reviewer()))
    assert_fields(candidate, environmental_cleared=False)


def test_a_score_of_exactly_seventy_bands_high_and_sixty_eight_bands_medium(
    api: ApiClient,
) -> None:
    """Two hundred eleven nominal days inflate to 254; one day of target moves the band.

    PRD: "The **baseline** variant is simply the current logical clock advanced by the
    total remaining days — nominal durations, no delay factor, no continuance penalty —
    and is stored as `baseline_forecast_date`."

    PRD: "The **risk-adjusted** variant inflates the work: the remaining days are
    multiplied by the jurisdiction's `historical_delay_factor` and rounded *up* to a
    whole number of days, and to that is added the continuance count multiplied by the
    jurisdiction's `hearing_cadence_days`, so each continuance the authority granted
    costs one full hearing cycle."

    PRD: "`schedule_risk_score` starts from a baseline of 50, adds 2.0 points for each
    day of slip (which subtracts when the slip is negative), adds 5 points for each
    continuance, and adds a further 10 points when the driver's `feasibility_status` is
    `STRUCTURAL_HOLD`, since a structure awaiting modification is the least predictable
    state in the pipeline."

    PRD: "`risk_band` bands that score: `HIGH` at 70.00 or above, `MEDIUM` at 40.00 or
    above but below 70.00, and `LOW` below 40.00."

    PRD: "On success `target_on_air_date` is replaced with `new_target_on_air_date`,
    `reset_count` increments by one, the forecast fields are recomputed and the plan
    moves to `RESET`."

    Design: Corner/calculations/corner_risk_band_boundary_seventy_versus_sixty_eight
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])

    plan = created(
        api.create_on_air_plan(
            {
                "search_ring_id": chain["ring_id"],
                "target_on_air_date": TARGET_AT_HIGH_EDGE,
            },
            headers=S.director(),
        )
    )
    assert_instant(
        plan["baseline_forecast_date"], BASELINE_FORECAST_DATE, "baseline_forecast_date"
    )
    assert_instant(
        plan["risk_adjusted_forecast_date"],
        RISK_ADJUSTED_FORECAST_DATE,
        "risk_adjusted_forecast_date",
    )
    assert_score(plan["schedule_risk_score"], SCORE_AT_HIGH_EDGE, "schedule_risk_score")
    assert_fields(
        plan,
        risk_band="HIGH",
        status="PLANNED",
        reset_count=0,
        driver_candidate_id=candidate["id"],
    )

    reset = ok(
        api.reset_plan(
            plan["id"],
            {
                "new_target_on_air_date": TARGET_ONE_DAY_LATER,
                "reason": "vendor re-sequenced the crew calendar",
            },
            headers=S.director(),
        )
    )
    assert_score(
        reset["schedule_risk_score"], SCORE_ONE_STEP_BELOW, "schedule_risk_score"
    )
    assert_fields(reset, risk_band="MEDIUM", status="RESET", reset_count=1)
    assert_instant(
        reset["risk_adjusted_forecast_date"],
        RISK_ADJUSTED_FORECAST_DATE,
        "risk_adjusted_forecast_date",
    )
