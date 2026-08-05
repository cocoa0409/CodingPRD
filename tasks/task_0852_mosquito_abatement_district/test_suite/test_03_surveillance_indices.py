"""The four evidence indices, the vector index, and their pinned arithmetic."""

import test_helpers as fx
from test_helpers import ADMIN, ECOLOGIST, MANAGER, validate_success


def test_abundance_index_ignores_logged_and_voided_collections(api):
    """PRD §3.5: "It considers trap collections whose trap site belongs to the
    area, whose trap site has `is_active` true, whose `status` is either
    `SUBMITTED` or `POOLED`, and whose `collection_date` falls inside the window."
    PRD §3.5: "Collections still `LOGGED`, collections `VOIDED`, and collections
    belonging to an inactive trap site never enter the numerator or the
    denominator."

    Design: Corner/calculations/corner_abundance_index_excludes_logged_and_voided_collections
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    submitted = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=2, female_count=60
    )
    logged = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-29", trap_nights=2, female_count=200
    )
    voided = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-30", trap_nights=2, female_count=400
    )
    fx.void_collection(voided["id"], "Trap flooded")

    report = validate_success(
        api.get_surveillance_report(area["id"], ECOLOGIST, params={"as_of_date": "2026-06-01"})
    )

    fx.assert_index(report["abundance_index"], 30.00, "abundance_index")
    assert fx.read_collection(logged["id"])["status"] == "LOGGED"
    assert fx.read_collection(voided["id"])["status"] == "VOIDED"
    assert fx.read_collection(submitted["id"])["status"] == "SUBMITTED"


def test_abundance_index_ignores_inactive_trap_sites(api):
    """PRD §3.1: "The boolean `is_active` marks whether the trap is in the current
    season's rotation and defaults to true when omitted; collections belonging to
    an inactive trap site are excluded from the abundance index entirely, which is
    how a decommissioned trap stops distorting the season's numbers without anyone
    deleting its history."

    Design: Corner/calculations/corner_abundance_index_excludes_inactive_trap_sites
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    active = fx.create_trap_site(area["id"], site_code="T-001", is_active=True)
    inactive = fx.create_trap_site(
        area["id"], site_code="T-002", trap_type="GRAVID", habitat="WETLAND",
        x_m=50, y_m=50, is_active=False,
    )
    fx.log_and_submit_collection(
        active["id"], tech["id"], collection_date="2026-05-28", trap_nights=2, female_count=60
    )
    ignored = fx.log_and_submit_collection(
        inactive["id"], tech["id"], collection_date="2026-05-28", trap_nights=2,
        female_count=200,
    )

    report = validate_success(
        api.get_surveillance_report(area["id"], ECOLOGIST, params={"as_of_date": "2026-06-01"})
    )

    fx.assert_index(report["abundance_index"], 30.00, "abundance_index")
    assert fx.read_trap_site(inactive["id"])["is_active"] is False
    assert fx.read_collection(ignored["id"])["status"] == "SUBMITTED"


def test_infection_rate_ignores_invalid_and_discarded_pools(api):
    """PRD §3.5: "Both variants exclude pools in `CREATED`, pools in `DISCARDED`,
    and pools in `INVALID`."
    PRD §3.5: "In either variant, sum `pool_size` across the included pools to get
    the total mosquitoes tested, count the included pools whose status is
    `RESULT_POSITIVE`, divide that count by the total mosquitoes tested, multiply
    by 1000, and round half up to two decimal places."

    Design: Corner/calculations/corner_mir_excludes_invalid_and_discarded_pools
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=2, female_count=60
    )
    fx.positive_pool(collection["id"], 50, 25.0)
    invalid = fx.pool_in_testing(collection["id"], 50)
    fx.record_pool_result(invalid["id"], "INVALID")
    discarded = fx.pool_in_testing(collection["id"], 50)
    fx.record_pool_result(discarded["id"], "INVALID")
    fx.discard_pool(discarded["id"])

    report = validate_success(
        api.get_surveillance_report(area["id"], ECOLOGIST, params={"as_of_date": "2026-06-01"})
    )

    fx.assert_index(report["mir_provisional"], 20.00, "mir_provisional")
    fx.assert_index(report["mir_confirmed"], 20.00, "mir_confirmed")
    fx.assert_index(report["abundance_index"], 30.00, "abundance_index")
    refreshed = fx.read_collection(collection["id"])
    assert refreshed["pooled_mosquito_count"] == 100
    assert refreshed["positive_pool_count"] == 1


def test_degree_days_exclude_observations_before_season_start(api):
    """PRD §3.5: "**Degree-day accumulation** for an assessment then sums those
    already-rounded daily values over the observations of the area whose `obs_date`
    falls in the closed interval from the area's `season_start_date` through the
    assessment's `as_of_date`, processing them in ascending `obs_date` order, and
    rounds the sum half up to one decimal place."
    PRD §3.5: "Observations dated before the season start are excluded outright, no
    matter how warm they were."

    Design: Corner/calculations/corner_degree_days_exclude_observations_before_season_start
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area(season_start_date="2026-05-01")

    before_season = validate_success(
        api.create_weather_observation(
            area["id"], {"obs_date": "2026-04-30", "tmax_c": 30.0, "tmin_c": 20.0}, ADMIN
        ),
        201,
    )
    in_season = validate_success(
        api.create_weather_observation(
            area["id"], {"obs_date": "2026-05-02", "tmax_c": 25.1, "tmin_c": 20.0}, ADMIN
        ),
        201,
    )

    fx.assert_weather_observation(before_season)
    fx.assert_index(before_season["degree_day"], 15.0, "degree_day")
    fx.assert_index(in_season["degree_day"], 12.6, "degree_day")

    report = validate_success(
        api.get_surveillance_report(area["id"], ECOLOGIST, params={"as_of_date": "2026-06-01"})
    )
    fx.assert_index(report["degree_days"], 12.6, "degree_days")


def test_surveillance_window_excludes_collection_one_day_too_old(api):
    """PRD §2.4: "Whenever a rule speaks of an *N-day window ending on date D
    inclusive*, it means every calendar date from D minus (N − 1) days through D,
    comparing calendar dates in UTC."
    PRD §2.8: "Every surveillance index is computed over a **14-day window ending
    on the assessment's `as_of_date` inclusive**, and that same 14-day horizon
    governs the abundance, infection-rate, and larval components alike."

    Design: Corner/calculations/corner_surveillance_window_excludes_collection_one_day_too_old
    """
    fx.set_clock("2026-05-20T00:00:00.000Z")
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    outside = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-18", trap_nights=2, female_count=60
    )
    inside = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-19", trap_nights=2, female_count=40
    )
    fx.set_clock(fx.CLOCK_BASE)

    report = validate_success(
        api.get_surveillance_report(area["id"], ECOLOGIST, params={"as_of_date": "2026-06-01"})
    )

    fx.assert_index(report["abundance_index"], 20.00, "abundance_index")
    assert fx.read_collection(outside["id"])["status"] == "SUBMITTED"
    assert fx.read_collection(inside["id"])["status"] == "SUBMITTED"


def test_provisional_variant_counts_in_testing_pool_as_presumed_negative(api):
    """PRD §3.5: "The **provisional** variant includes pools in `IN_TESTING`,
    `RESULT_POSITIVE`, and `RESULT_NEGATIVE`. A pool still on the bench is treated
    as presumed negative: its `pool_size` enters the denominator while it
    contributes nothing to the numerator, which dilutes the rate downward."
    PRD §3.5: "The new record is stamped `status` of `OPEN` with `is_stale` false
    and `stale_reason` null, and all five provisional numbers are computed and
    frozen onto it at that instant: `abundance_index`, `larval_index`,
    `degree_days`, `mir_provisional`, and `vector_index_provisional`."

    Design: Difficulty/dual_variant_calc/vector_index_provisional_vs_confirmed_diverge_on_in_testing_pools
    """
    scenario = fx.setup_surveillance_dual_variant()

    assessment = validate_success(
        api.get_risk_assessment(scenario["assessment"]["id"], ECOLOGIST)
    )

    fx.assert_risk_assessment(assessment)
    fx.assert_index(assessment["abundance_index"], 25.00, "abundance_index")
    fx.assert_index(assessment["larval_index"], 2.00, "larval_index")
    fx.assert_index(assessment["degree_days"], 24.2, "degree_days")
    fx.assert_index(assessment["mir_provisional"], 6.67, "mir_provisional")
    fx.assert_index(
        assessment["vector_index_provisional"], 64.31, "vector_index_provisional"
    )
    assert assessment["status"] == "OPEN"
    assert assessment["mir_confirmed"] is None
    assert assessment["vector_index_confirmed"] is None


def test_confirmed_variant_drops_in_testing_pool_and_raises_the_index(api):
    """PRD §3.5: "The **confirmed** variant includes only pools in
    `RESULT_POSITIVE` and `RESULT_NEGATIVE`. Pools still on the bench are dropped
    from the numerator *and* the denominator, which raises the rate relative to the
    provisional variant for exactly the same untouched data."
    PRD §3.6: "It computes and writes `mir_confirmed` and `vector_index_confirmed`
    from the confirmed variants described above, evaluated against the pool set as
    it stands at confirmation time rather than as it stood at creation time."
    PRD §3.6: "It copies this assessment's `vector_index_confirmed` into the area's
    `latest_confirmed_vector_index` and re-derives the area's `risk_posture` and
    `posture_source`."

    Design: Difficulty/dual_variant_calc/vector_index_provisional_vs_confirmed_diverge_on_in_testing_pools
    """
    scenario = fx.setup_surveillance_dual_variant()

    confirmed = validate_success(
        api.confirm_risk_assessment(scenario["assessment"]["id"], ECOLOGIST)
    )

    assert confirmed["status"] == "CONFIRMED"
    fx.assert_index(confirmed["mir_confirmed"], 10.00, "mir_confirmed")
    fx.assert_index(confirmed["vector_index_confirmed"], 78.88, "vector_index_confirmed")
    fx.assert_index(confirmed["mir_provisional"], 6.67, "mir_provisional")
    fx.assert_index(
        confirmed["vector_index_provisional"], 64.31, "vector_index_provisional"
    )
    assert confirmed["posture_at_confirm"] == "EMERGENCY"

    area = fx.read_area(scenario["area"]["id"])
    fx.assert_index(
        area["latest_confirmed_vector_index"], 78.88, "latest_confirmed_vector_index"
    )
    assert area["risk_posture"] == "EMERGENCY"
    assert area["posture_source"] == "INDEX"


def test_capped_infection_component_feeds_the_weighted_vector_index(api):
    """PRD §3.5: "Each component takes its raw index, divides by that component's
    reference level, multiplies by 100, rounds half up to two decimal places, and
    is then capped at `100.00`:"
    PRD §3.5: "The abundance component normalises the abundance index against a
    reference of 50.0 females per trap-night."
    PRD §3.5: "The infection component normalises the minimum infection rate
    against a reference of 10.0 per thousand."

    Design: Difficulty/combinatorial_formula/vector_index_four_input_nonlinear_min_capped_with_conditional_branch
    """
    scenario = fx.setup_single_positive_pool_assessment(
        female_count=96, trap_nights=4, ct_value=30.0,
        species="CULEX_TARSALIS", trap_type="GRAVID",
    )

    assessment = validate_success(
        api.get_risk_assessment(scenario["assessment"]["id"], ECOLOGIST)
    )

    fx.assert_index(assessment["abundance_index"], 24.00, "abundance_index")
    fx.assert_index(assessment["mir_provisional"], 20.00, "mir_provisional")
    fx.assert_index(assessment["larval_index"], 0.00, "larval_index")
    fx.assert_index(assessment["degree_days"], 0.0, "degree_days")
    assert assessment["status"] == "OPEN"


def test_outbreak_amplification_does_not_fire_below_the_abundance_trigger(api):
    """PRD §3.5: "When the infection component is strictly greater than `0.00`
    *and* the abundance component is at or above 50.0, the weighted sum is
    multiplied by 1.25 — the epidemiological judgement being that virus circulating
    amid a dense adult population is disproportionately dangerous."
    PRD §3.5: "The four capped components are then weighted and added: the
    abundance component at 0.40, the infection component at 0.35, the larval
    component at 0.15, and the weather component at 0.10."

    Design: Difficulty/combinatorial_formula/vector_index_four_input_nonlinear_min_capped_with_conditional_branch
    """
    scenario = fx.setup_single_positive_pool_assessment(
        female_count=96, trap_nights=4, ct_value=30.0,
        species="CULEX_TARSALIS", trap_type="GRAVID",
    )

    assessment = validate_success(
        api.get_risk_assessment(scenario["assessment"]["id"], ECOLOGIST)
    )

    # abundance component 48.00 sits below the 50.0 trigger, so no amplification.
    fx.assert_index(
        assessment["vector_index_provisional"], 54.20, "vector_index_provisional"
    )


def test_each_days_degree_day_is_rounded_before_it_is_stored(api):
    """PRD §3.5: "Take the day's mean temperature — the sum of `tmax_c` and
    `tmin_c` divided by two — and subtract the development base temperature of 10.0
    degrees Celsius. Round that difference half up to one decimal place. If the
    rounded result is negative, `degree_day` is `0.0`; otherwise `degree_day` is
    the rounded result."

    Design: Difficulty/combinatorial_formula/degree_day_rounded_per_day_before_summation
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()

    first = validate_success(
        api.create_weather_observation(
            area["id"],
            {"obs_date": "2026-05-30", "tmax_c": 25.1, "tmin_c": 20.0, "rainfall_mm": 0.0},
            ADMIN,
        ),
        201,
    )
    second = validate_success(
        api.create_weather_observation(
            area["id"],
            {"obs_date": "2026-05-31", "tmax_c": 24.1, "tmin_c": 19.0, "rainfall_mm": 2.5},
            ADMIN,
        ),
        201,
    )

    fx.assert_index(first["degree_day"], 12.6, "degree_day")
    fx.assert_index(second["degree_day"], 11.6, "degree_day")


def test_degree_days_accumulate_from_the_already_rounded_daily_values(api):
    """PRD §2.6: "Two rules in particular are round-then-sum rather than
    sum-then-round: each day's degree-day contribution is rounded to 1 decimal
    before the days are added together, and each route's material cost is rounded
    to whole cents before the routes are added together."
    PRD §3.5: "Two days whose raw values are 12.55 and 11.55 accumulate as 12.6
    plus 11.6, giving 24.2 — not the 24.1 that summing raw values and rounding once
    at the end would produce."

    Design: Difficulty/combinatorial_formula/degree_day_rounded_per_day_before_summation
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    fx.create_observation(area["id"], obs_date="2026-05-30", tmax_c=25.1, tmin_c=20.0)
    fx.create_observation(
        area["id"], obs_date="2026-05-31", tmax_c=24.1, tmin_c=19.0, rainfall_mm=2.5
    )

    report = validate_success(
        api.get_surveillance_report(area["id"], ECOLOGIST, params={"as_of_date": "2026-06-01"})
    )

    fx.assert_index(report["degree_days"], 24.2, "degree_days")
    assert report["degree_days"] != 24.1, "summing raw values then rounding is wrong"
    fx.assert_index(report["abundance_index"], 0.00, "abundance_index")


def test_amplification_fires_when_abundance_component_is_exactly_fifty(api):
    """PRD §3.5: "The abundance trigger is inclusive: a component of exactly
    `50.00` does fire the amplification."
    PRD §3.5: "Finally the result — amplified or not — is rounded half up to two
    decimal places and capped at `100.00`."

    Design: Difficulty/boundary_precision_check/outbreak_multiplier_fires_at_abundance_component_exactly_fifty
    """
    scenario = fx.setup_single_positive_pool_assessment(female_count=100, trap_nights=4)

    assessment = validate_success(
        api.get_risk_assessment(scenario["assessment"]["id"], ECOLOGIST)
    )

    fx.assert_index(assessment["abundance_index"], 25.00, "abundance_index")
    fx.assert_index(assessment["mir_provisional"], 20.00, "mir_provisional")
    fx.assert_index(
        assessment["vector_index_provisional"], 68.75, "vector_index_provisional"
    )


def test_amplified_index_at_the_trigger_confirms_to_elevated_posture(api):
    """PRD §3.6: "Begin with the area's `latest_confirmed_vector_index`, which is
    `0.00` when no assessment of the area has ever been confirmed. If that value is
    at or above 70.0 the index reading is `EMERGENCY`; otherwise, if it is at or
    above 40.0 the index reading is `ELEVATED`; otherwise it is `NORMAL`."
    PRD §3.6: "And it records the resulting posture onto the assessment as
    `posture_at_confirm`, freezing what the confirmation actually decided."

    Design: Difficulty/boundary_precision_check/outbreak_multiplier_fires_at_abundance_component_exactly_fifty
    """
    scenario = fx.setup_single_positive_pool_assessment(female_count=100, trap_nights=4)

    confirmed = validate_success(
        api.confirm_risk_assessment(scenario["assessment"]["id"], ECOLOGIST)
    )

    fx.assert_index(
        confirmed["vector_index_confirmed"], 68.75, "vector_index_confirmed"
    )
    assert confirmed["posture_at_confirm"] == "ELEVATED"
    assert fx.read_area(scenario["area"]["id"])["risk_posture"] == "ELEVATED"


def test_empty_evidence_base_reports_zero_indices(api):
    """PRD §2.6: "**Surveillance indices** (`abundance_index`, `larval_index`,
    `mir_provisional`, `mir_confirmed`, `vector_index_provisional`,
    `vector_index_confirmed`, `latest_confirmed_vector_index`) carry 2 decimal
    places. An empty input set yields exactly `0.00`, never null."
    PRD §3.5: "When the summed trap-nights are zero — because nothing qualified —
    the index is exactly `0.00`."

    Design: Difficulty/boundary_precision_check/empty_surveillance_window_yields_zero_indices_not_division_error
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area(name="Southeast Zone", code="SE2", population=12000)

    report = validate_success(
        api.get_surveillance_report(area["id"], MANAGER, params={"as_of_date": "2026-06-01"}),
        200,
    )

    fx.assert_index(report["abundance_index"], 0.00, "abundance_index")
    fx.assert_index(report["larval_index"], 0.00, "larval_index")
    fx.assert_index(report["degree_days"], 0.0, "degree_days")
    fx.assert_index(report["mir_provisional"], 0.00, "mir_provisional")
    fx.assert_index(report["mir_confirmed"], 0.00, "mir_confirmed")
    fx.assert_index(
        report["vector_index_provisional"], 0.00, "vector_index_provisional"
    )


def test_empty_evidence_base_reports_normal_posture_and_zero_counters(api):
    """PRD §3.6: "It is `NO_ASSESSMENT` when no assessment of the area has ever
    been confirmed and the override did not outrank the index reading."
    PRD §3.10: "Alongside those computed figures it echoes back, unchanged, the
    area's persisted `risk_posture`, `posture_source`, `seasonal_application_count`,
    and the four complaint counters `request_total_count`, `request_open_count`,
    `request_resolved_count`, and `request_closed_count`, plus the `as_of_date`
    that was used."

    Design: Difficulty/boundary_precision_check/empty_surveillance_window_yields_zero_indices_not_division_error
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area(name="Southeast Zone", code="SE2", population=12000)

    response = api.get_surveillance_report(
        area["id"], MANAGER, params={"as_of_date": "2026-06-01"}
    )
    report = validate_success(response, 200)

    assert response.status_code == 200
    assert report["risk_posture"] == "NORMAL"
    assert report["posture_source"] == "NO_ASSESSMENT"
    assert report["as_of_date"] == "2026-06-01"
    assert report["seasonal_application_count"] == 0
    assert report["request_total_count"] == 0
    assert report["request_open_count"] == 0
