"""Derived-quantity behaviour: siting verdicts, quality-control grading and
posture bands, hour accounting, annual rollups, primary-sampler choice,
design-value assembly and network adequacy scoring.

Every expectation below is re-derived from PRD.md and asserted through HTTP
only. The harness restarts the API server before each test, so each test
builds the whole world it needs.
"""

from datetime import datetime

import pytest

from test_helpers import (
    CANONICAL_CLOCK,
    PM_HEADERS,
    QA2_HEADERS,
    QA_HEADERS,
    TECH_HEADERS,
    WORKED_EXAMPLE_QUARTERS,
    apply_invalidation,
    approve_monitor,
    assert_annual_statistics,
    assert_hour_budget_conserved,
    assert_pct,
    assert_ratio_4dp,
    assert_site_census_partitioned,
    assert_siting_codes,
    assessment_payload,
    canonical_environment,
    commission_monitor,
    create_monitor,
    create_network,
    create_operating_site,
    create_pollutant,
    create_reference_method,
    create_site,
    data_batch_payload,
    demonstration_payload,
    design_value_payload,
    exclusion_payload,
    get_success_data,
    package_payload,
    set_clock,
    span_check_payload,
    twelve_validated_quarters,
    validate_paginated,
    zero_check_payload,
)


# Parse an ISO 8601 UTC instant so timestamps can be compared regardless of
# whether the server writes fractional digits.
def _instant(value):
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    text = value.replace("Z", "")
    if "." in text:
        text = text.split(".")[0]
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")


def test_siting_verdict_lists_every_violated_criterion(api):
    """Each failed siting criterion contributes exactly one code, and the
    criteria that are scoped to a single objective class stay silent elsewhere.

    PRD 3.2: "The probe-height band applies to every site type: a violation code of `PROBE_HEIGHT` is recorded unless `probe_height_m` is at least 2.0 metres and at most 15.0 metres."

    PRD 3.2: "Finally, the two-to-one obstruction clearance applies to every site type: the required clearance in metres is twice the amount by which `obstruction_height_m` exceeds `probe_height_m`, and when that required clearance is greater than zero and `distance_to_obstruction_m` is less than it, `OBSTRUCTION_CLEARANCE` is recorded."

    PRD 2.9: "Two further network counters are derived from deeper in the graph: `delinquent_monitor_count` is the number of instruments at the network's sites whose calendar quality-control posture is `QC_DELINQUENT` and whose lifecycle status is `APPROVED`, `OPERATING` or `OUT_OF_SERVICE`, and `waiver_required_site_count` is the number of the network's sites that need a siting waiver and are currently `SITING_APPROVED`, `OPERATING` or `SUSPENDED`."

    Design: Corner/calculations/siting_criteria_evaluation_flags_every_violated_criterion
    """
    set_clock(api, CANONICAL_CLOCK)
    network = create_network(api)

    # Probe below the band, roadway inside the population setback, and a
    # clearance of 4.0 m against a required 2 * (6.0 - 1.5) == 9.0 m.
    bad = create_site(
        api,
        network["id"],
        site_code="S-BAD",
        site_type="POPULATION_ORIENTED",
        latitude=39.75,
        longitude=-104.99,
        population_served=400000,
        probe_height_m=1.5,
        distance_to_roadway_m=5.0,
        distance_to_obstruction_m=4.0,
        obstruction_height_m=6.0,
        distance_to_source_m=0.0,
    )
    assert_siting_codes(bad, ["OBSTRUCTION_CLEARANCE", "PROBE_HEIGHT", "ROADWAY_SETBACK"])

    # A background site 50.0 m from traffic: only the isolation rule fires, and
    # the required clearance of 2 * (6.0 - 4.0) == 4.0 m is met by 12.0 m.
    background = create_site(
        api,
        network["id"],
        site_code="S-BKG",
        site_type="BACKGROUND",
        latitude=40.10,
        longitude=-105.30,
        population_served=0,
        probe_height_m=4.0,
        distance_to_roadway_m=50.0,
        distance_to_obstruction_m=12.0,
        obstruction_height_m=6.0,
        distance_to_source_m=0.0,
    )
    assert_siting_codes(background, ["BACKGROUND_ISOLATION"])

    # A source-oriented site 800.0 m from its source: the roadway setback does
    # not apply to this objective class at all.
    source = create_site(
        api,
        network["id"],
        site_code="S-SRC",
        site_type="SOURCE_ORIENTED",
        latitude=39.60,
        longitude=-104.80,
        population_served=12000,
        probe_height_m=4.0,
        distance_to_roadway_m=40.0,
        distance_to_obstruction_m=12.0,
        obstruction_height_m=6.0,
        distance_to_source_m=800.0,
    )
    assert_siting_codes(source, ["SOURCE_DISTANCE"])

    census = get_success_data(api.get_network(network["id"], PM_HEADERS))
    assert census["total_site_count"] == 3
    assert census["proposed_site_count"] == 3
    # All three sites are still PROPOSED, a status the waiver census excludes.
    assert census["waiver_required_site_count"] == 0
    assert_site_census_partitioned(census)


def test_siting_criteria_boundaries_are_inclusive(api):
    """The probe-height band ends are inclusive, a setback exactly at the
    minimum passes, the clearance test is strict-less-than, and a probe just
    above the band raises the height code on its own.

    PRD 3.2: "The probe-height band applies to every site type: a violation code of `PROBE_HEIGHT` is recorded unless `probe_height_m` is at least 2.0 metres and at most 15.0 metres."

    PRD 3.2: "Roadway setback applies only to a `POPULATION_ORIENTED` site: `ROADWAY_SETBACK` is recorded when `distance_to_roadway_m` is less than 10.0 metres."

    PRD 3.2: "An obstruction no taller than the probe yields a required clearance of zero or less and therefore never produces a violation."

    Design: Corner/calculations/siting_criteria_boundaries_are_inclusive_and_yield_no_violation
    """
    set_clock(api, CANONICAL_CLOCK)
    network = create_network(api)

    # probe 2.0 is the inclusive floor, roadway 10.0 is the inclusive minimum,
    # and 8.0 m of clearance exactly meets the required 2 * (6.0 - 2.0).
    low = create_site(
        api,
        network["id"],
        site_code="S-LOW",
        site_type="POPULATION_ORIENTED",
        latitude=39.75,
        longitude=-104.99,
        population_served=400000,
        probe_height_m=2.0,
        distance_to_roadway_m=10.0,
        distance_to_obstruction_m=8.0,
        obstruction_height_m=6.0,
        distance_to_source_m=0.0,
    )
    assert_siting_codes(low, [])

    # probe 15.0 is the inclusive ceiling, and the required clearance
    # 2 * (6.0 - 15.0) is negative, so the obstruction test is skipped.
    high = create_site(
        api,
        network["id"],
        site_code="S-HIGH",
        site_type="POPULATION_ORIENTED",
        latitude=39.76,
        longitude=-104.98,
        population_served=400000,
        probe_height_m=15.0,
        distance_to_roadway_m=10.0,
        distance_to_obstruction_m=0.0,
        obstruction_height_m=6.0,
        distance_to_source_m=0.0,
    )
    assert_siting_codes(high, [])

    over = create_site(
        api,
        network["id"],
        site_code="S-OVER",
        site_type="POPULATION_ORIENTED",
        latitude=39.77,
        longitude=-104.97,
        population_served=400000,
        probe_height_m=15.01,
        distance_to_roadway_m=10.0,
        distance_to_obstruction_m=0.0,
        obstruction_height_m=6.0,
        distance_to_source_m=0.0,
    )
    assert_siting_codes(over, ["PROBE_HEIGHT"])

    census = get_success_data(api.get_network(network["id"], PM_HEADERS))
    assert census["total_site_count"] == 3
    # The one waivered site is still PROPOSED, so the waiver census counts none.
    assert census["waiver_required_site_count"] == 0
    assert_site_census_partitioned(census)


def test_qc_reading_is_rounded_to_two_decimals_before_banding(api):
    """A reading is rounded to two decimals first and only then banded, the
    band edges are inclusive, and a failing grade moves no timestamp while
    pulling the instrument out of service.

    PRD 3.3: "For a span check, take the absolute value of `span_drift_pct`, round it to two decimal places, and compare it against the governing method's `max_span_drift_pct`: an absolute drift at or below the tolerance is `PASS`, a drift above the tolerance but at or below one and a half times the tolerance is `WARN`, and anything beyond that is `FAIL`."

    PRD 3.3: "Both comparisons at the limit are inclusive: an absolute reading exactly equal to the tolerance is `PASS`, not `WARN`, and a reading exactly equal to one and a half times the tolerance is `WARN`, not `FAIL`."

    PRD 3.3: "On a `FAIL` outcome no timestamp moves at all."

    Design: Corner/calculations/qc_event_outcome_rounds_the_drift_to_two_decimals_before_comparing
    """
    env = canonical_environment(api)

    # 5.004 rounds to 5.00, which is at the 5.0 tolerance, so it passes.
    first = get_success_data(
        api.create_qc_event(
            env.monitor_id,
            span_check_payload(performed_at="2026-01-03T00:00:00Z", span_drift_pct=5.004),
            TECH_HEADERS,
        )
    )
    assert first["outcome"] == "PASS"

    # 5.005 rounds half up to 5.01, above 5.0 but within 1.5 * 5.0 == 7.5.
    second = get_success_data(
        api.create_qc_event(
            env.monitor_id,
            span_check_payload(performed_at="2026-01-04T00:00:00Z", span_drift_pct=5.005),
            TECH_HEADERS,
        )
    )
    assert second["outcome"] == "WARN"

    # 2.25 is exactly 1.5 * the 1.5 zero tolerance, which is a warning.
    third = get_success_data(
        api.create_qc_event(
            env.monitor_id,
            zero_check_payload(performed_at="2026-01-04T12:00:00Z", zero_drift_value=2.25),
            TECH_HEADERS,
        )
    )
    assert third["outcome"] == "WARN"

    fourth = get_success_data(
        api.create_qc_event(
            env.monitor_id,
            zero_check_payload(performed_at="2026-01-04T18:00:00Z", zero_drift_value=2.26),
            TECH_HEADERS,
        )
    )
    assert fourth["outcome"] == "FAIL"

    monitor = get_success_data(api.get_monitor(env.monitor_id, TECH_HEADERS))
    # The warning advanced both timestamps; the failure advanced neither.
    assert _instant(monitor["last_span_check_at"]) == _instant("2026-01-04T00:00:00Z")
    assert _instant(monitor["last_zero_check_at"]) == _instant("2026-01-04T12:00:00Z")
    assert monitor["monitor_status"] == "OUT_OF_SERVICE"
    assert monitor["consecutive_qc_failure_count"] == 1


def test_qc_posture_bands_move_with_the_clock_alone(api):
    """Against a fourteen-day interval and a one-week grace period, fourteen
    elapsed days is current, twenty-one is merely due and twenty-two is
    delinquent, and the network counter follows.

    PRD 3.3: "An elapsed-days figure no greater than the interval yields `QC_CURRENT`; an elapsed figure greater than the interval but no greater than the interval plus a grace period of one week yields `QC_DUE`; anything beyond that yields `QC_DELINQUENT`."

    PRD 3.3: "The **in-service-elapsed** variant is written to `qc_posture_in_service`: elapsed days are the same whole-day figure less `out_of_service_day_count`, floored at zero, so days the instrument was formally out of service are forgiven."

    Design: Corner/calculations/monitor_qc_posture_bands_shift_with_the_grace_days_constant
    """
    env = canonical_environment(api, span_check_at="2025-12-22T00:00:00Z")

    # Clock 2026-01-05 is exactly fourteen whole days after the baseline.
    monitor = get_success_data(api.get_monitor(env.monitor_id, TECH_HEADERS))
    assert monitor["qc_posture"] == "QC_CURRENT"
    assert monitor["qc_posture_in_service"] == "QC_CURRENT"
    assert monitor["out_of_service_day_count"] == 0
    network = get_success_data(api.get_network(env.network_id, PM_HEADERS))
    assert network["delinquent_monitor_count"] == 0

    # Twenty-one elapsed days sits exactly on the grace boundary.
    set_clock(api, "2026-01-12T00:00:00Z")
    monitor = get_success_data(api.get_monitor(env.monitor_id, TECH_HEADERS))
    assert monitor["qc_posture"] == "QC_DUE"
    assert monitor["qc_posture_in_service"] == "QC_DUE"
    network = get_success_data(api.get_network(env.network_id, PM_HEADERS))
    assert network["delinquent_monitor_count"] == 0

    # One day further and the grace period is exhausted.
    set_clock(api, "2026-01-13T00:00:00Z")
    monitor = get_success_data(api.get_monitor(env.monitor_id, TECH_HEADERS))
    assert monitor["qc_posture"] == "QC_DELINQUENT"
    assert monitor["qc_posture_in_service"] == "QC_DELINQUENT"
    assert monitor["out_of_service_day_count"] == 0
    network = get_success_data(api.get_network(env.network_id, PM_HEADERS))
    assert network["delinquent_monitor_count"] == 1


def test_proposed_event_hours_do_not_leave_the_hour_budget(api):
    """Nominated hours are a claim, not a deduction: while the nomination is
    only proposed the quarter keeps its full denominator and its perfect
    completeness, and the demonstration total stays at zero.

    PRD 3.4: "Third, `event_excluded_hour_count` is the total of `hours_affected` over every event exclusion on this quarter that has become effective; proposed and rejected exclusions contribute nothing."

    PRD 3.6: "Crucially, nothing else moves: the demonstration's `excluded_hour_total` is unchanged because only effective exclusions count toward it, and the target quarter's hour accounting is unchanged for exactly the same reason."

    Design: Corner/calculations/batch_hour_accounting_excludes_proposed_event_exclusions
    """
    env = canonical_environment(api)
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(
                env.monitor_id,
                2024,
                3,
                scheduled_hour_count=2208,
                quarterly_mean_concentration=9.2,
                quarterly_mean_concentration_event_adjusted=7.9,
            ),
            QA_HEADERS,
        )
    )
    demonstration = get_success_data(
        api.create_demonstration(
            demonstration_payload(env.site_id, env.pollutant_id), PM_HEADERS
        )
    )

    # The claimed window 2024-08-12 to 2024-08-19 projects onto hours 1008
    # through 1200 of the quarter that began 2024-07-01.
    exclusion = get_success_data(
        api.create_exclusion(
            demonstration["id"], exclusion_payload(batch["id"], 1008, 1200), PM_HEADERS
        )
    )
    assert exclusion["status"] == "PROPOSED"
    assert exclusion["hours_affected"] == 192
    assert exclusion["effective_at"] is None

    submitted = get_success_data(
        api.submit_demonstration(
            demonstration["id"],
            {"submission_note": "Demonstration submitted for concurrence"},
            PM_HEADERS,
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["excluded_hour_total"] == 0

    reread = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert reread["event_excluded_hour_count"] == 0
    assert reread["adjusted_scheduled_hour_count"] == 2208
    assert reread["valid_hour_count"] == 2208
    assert_pct(reread["completeness_pct"], 100.0)
    assert reread["regulatory_use_eligible"] is True
    assert_hour_budget_conserved(reread)


def test_package_rollup_divides_summed_hours_rather_than_averaging(api):
    """A fully complete quarter and a half-complete quarter of different
    lengths roll up to the hour-weighted figure, not to the mean of the two
    per-quarter percentages, and one ineligible member blocks readiness.

    PRD 3.8: "`rollup_completeness_pct` is computed from summed hours, not by averaging per-quarter percentages: sum `valid_hour_count` across the selected quarters, sum `adjusted_scheduled_hour_count` across the same quarters, divide the first total by the second, multiply by 100 and round to one decimal place — with the value taken as 0.0 when the second total is zero."

    PRD 3.8: "Finally, `certification_ready` is true exactly when `included_batch_count` is at least 1 **and** `eligible_batch_count` equals `included_batch_count`; a single member quarter below its pollutant's completeness threshold makes the whole package unready, as does a package with no members at all."

    PRD 3.8: "First, `certification_deadline` is pinned to the first of May of the year following `year`, at midnight UTC."

    Design: Corner/calculations/certification_rollup_sums_hours_instead_of_averaging_percentages
    """
    env = canonical_environment(api)
    first = get_success_data(
        api.create_data_batch(
            data_batch_payload(
                env.monitor_id,
                2025,
                1,
                scheduled_hour_count=2160,
                quarterly_mean_concentration=9.0,
            ),
            QA_HEADERS,
        )
    )
    second = get_success_data(
        api.create_data_batch(
            data_batch_payload(
                env.monitor_id,
                2025,
                2,
                scheduled_hour_count=2184,
                quarterly_mean_concentration=9.1,
            ),
            QA_HEADERS,
        )
    )
    # Half of the second quarter is written off under a non-excused code, so
    # those hours stay in the denominator.
    apply_invalidation(api, second["id"], 0, 1092, "QC_FAILURE", QA_HEADERS)

    validated = get_success_data(
        api.bulk_validate({"monitor_id": env.monitor_id, "year": 2025}, QA2_HEADERS)
    )
    assert len(validated) == 2

    first = get_success_data(api.get_data_batch(first["id"], QA_HEADERS))
    assert first["valid_hour_count"] == 2160
    assert first["adjusted_scheduled_hour_count"] == 2160
    assert_pct(first["completeness_pct"], 100.0)
    assert first["regulatory_use_eligible"] is True
    assert first["validation_status"] == "VALIDATED"
    assert first["validated_by_user_id"] == "qa-2"

    second = get_success_data(api.get_data_batch(second["id"], QA_HEADERS))
    assert second["invalidated_hour_count"] == 1092
    assert second["valid_hour_count"] == 1092
    assert second["adjusted_scheduled_hour_count"] == 2184
    assert_pct(second["completeness_pct"], 50.0)
    assert second["regulatory_use_eligible"] is False
    assert second["validation_status"] == "VALIDATED"
    assert second["validated_by_user_id"] == "qa-2"

    package = get_success_data(
        api.create_package(package_payload(env.network_id, env.pollutant_id, 2025), PM_HEADERS)
    )
    assert package["included_batch_count"] == 2
    assert package["eligible_batch_count"] == 1
    # 100 * 3252 / 4344 == 74.86..., which rounds to 74.9; averaging the two
    # quarter percentages would have produced 75.0.
    assert package["rollup_completeness_pct"] == pytest.approx(74.9, abs=0.01)
    assert package["certification_ready"] is False
    assert package["status"] == "DRAFT"
    assert _instant(package["certification_deadline"]) == _instant("2026-05-01T00:00:00Z")


def test_primary_sampler_pool_excludes_unnominated_and_never_operated_instruments(api):
    """Of four co-located instruments only the nominated ones that have reached
    service are candidates, and the lowest parameter occurrence code wins.

    PRD 3.7: "The candidate pool is the instruments at the requested site whose reference method measures the requested pollutant, whose `is_primary_for_design_value` flag is true, and whose lifecycle status is `OPERATING`, `OUT_OF_SERVICE` or `DECOMMISSIONED`."

    PRD 3.7: "Otherwise the candidates are ordered by `poc` ascending and, where two share a `poc`, by `created_at` ascending; the first is recorded as `primary_monitor_id`."

    PRD 3.7: "If `complete_year_count` does not equal the pollutant's `design_value_years`, `design_value` is null and `attainment_status` is `INSUFFICIENT_DATA`."

    Design: Corner/calculations/primary_monitor_selection_skips_never_operated_monitors_and_ranks_by_poc
    """
    env = canonical_environment(api, monitor_overrides={"poc": 2, "installed_at": "2022-12-21T00:00:00Z"})
    nominated_but_idle = create_monitor(
        api,
        env.site_id,
        env.method_id,
        poc=1,
        is_primary_for_design_value=True,
        installed_at="2022-12-20T00:00:00Z",
    )
    approve_monitor(api, nominated_but_idle["id"])

    unnominated = create_monitor(
        api,
        env.site_id,
        env.method_id,
        poc=3,
        is_primary_for_design_value=False,
        installed_at="2022-12-22T00:00:00Z",
    )
    approve_monitor(api, unnominated["id"])
    commission_monitor(api, unnominated["id"])

    higher_poc = create_monitor(
        api,
        env.site_id,
        env.method_id,
        poc=4,
        is_primary_for_design_value=True,
        installed_at="2022-12-23T00:00:00Z",
    )
    approve_monitor(api, higher_poc["id"])
    commission_monitor(api, higher_poc["id"])

    design_value = get_success_data(
        api.create_design_value(
            design_value_payload(
                env.site_id, env.pollutant_id, 2025, "WITH_EVENT_DATA", env.site_version()
            ),
            PM_HEADERS,
        ),
        expected_status=201,
    )
    assert design_value["primary_monitor_id"] == env.monitor_id

    # The nominated instrument that never reached service is still outside the
    # pool, and the unnominated one never enters it.
    assert get_success_data(api.get_monitor(nominated_but_idle["id"], PM_HEADERS))["monitor_status"] == "APPROVED"
    idle = get_success_data(api.get_monitor(unnominated["id"], PM_HEADERS))
    assert idle["monitor_status"] == "OPERATING"
    assert idle["is_primary_for_design_value"] is False
    loser = get_success_data(api.get_monitor(higher_poc["id"], PM_HEADERS))
    assert loser["monitor_status"] == "OPERATING"
    assert loser["is_primary_for_design_value"] is True

    assert design_value["complete_year_count"] == 0
    assert design_value["annual_statistics"] == []
    assert design_value["design_value"] is None
    assert design_value["attainment_status"] == "INSUFFICIENT_DATA"
    assert env.read_site()["operating_monitor_count"] == 3


def test_a_year_missing_a_quarter_contributes_no_annual_statistic(api):
    """Eleven qualifying quarters leave one year short of its fourth quarter,
    so that year is skipped entirely rather than averaged over three quarters.

    PRD 3.7: "A year that does not have all four of its qualifying quarters contributes no annual statistic at all and is simply skipped; `complete_year_count` is the number of the three years that did have four qualifying quarters."

    PRD 3.7: "The array is ordered earliest year first: its first element belongs to the `period_end_year` less 2 and its last belongs to the `period_end_year`."

    PRD 3.2: "`current_attainment_status` is the attainment standing of the site's most relevant design value: among the site's design-value rows whose `status` is `PROVISIONAL` or `FINAL`, order by `created_at` descending and then by `period_end_year` descending and take the first row's attainment verdict; when no such row exists the value is `UNDETERMINED`."

    Design: Corner/calculations/design_value_reports_insufficient_data_when_a_year_lacks_four_quarters
    """
    eleven = [
        dict(quarter)
        for quarter in WORKED_EXAMPLE_QUARTERS
        if not (quarter["year"] == 2024 and quarter["quarter"] == 4)
    ]
    assert len(eleven) == 11
    env = twelve_validated_quarters(api, batches=eleven)

    rows, meta = validate_paginated(
        api.list_data_batches(
            QA_HEADERS, {"monitor_id": env.monitor_id, "validation_status": "VALIDATED"}
        )
    )
    assert meta["total_count"] == 11

    design_value = get_success_data(
        api.create_design_value(
            design_value_payload(
                env.site_id, env.pollutant_id, 2025, "WITH_EVENT_DATA", env.site_version()
            ),
            PM_HEADERS,
        ),
        expected_status=201,
    )
    # 2023 averages to 9.25 and rounds half up to 9.3; 2025 averages to 8.95
    # and rounds half up to 9.0; 2024 holds only three quarters.
    assert_annual_statistics(design_value["annual_statistics"], [9.3, 9.0])
    assert design_value["complete_year_count"] == 2
    assert design_value["design_value"] is None
    assert design_value["attainment_status"] == "INSUFFICIENT_DATA"
    assert env.read_site()["current_attainment_status"] == "INSUFFICIENT_DATA"


def test_adequacy_score_of_exactly_ninety_lands_in_the_top_tier(api):
    """Full site coverage degraded by a single delinquent instrument scores
    exactly ninety, and the top band's lower edge is inclusive.

    PRD 3.9: "The three credits are summed and divided by the requirement total — `required_population_site_count` plus one required source site plus one required background site — and `coverage_ratio` is that quotient rounded to four decimal places."

    PRD 3.9: "`adequacy_score` is `coverage_ratio` multiplied by the quality-control factor, multiplied by the siting factor, multiplied by 100, and rounded to one decimal place."

    PRD 3.9: "Both band boundaries are inclusive at their lower edge, so a score of exactly 90.0 is `ADEQUATE` and a score of exactly 75.0 is `CONDITIONAL`."

    Design: Corner/calculations/network_adequacy_score_of_exactly_90_is_adequate
    """
    set_clock(api, CANONICAL_CLOCK)
    pollutant = create_pollutant(api)
    method = create_reference_method(api, pollutant["id"])
    network = create_network(api, name="Small Metro Network", agency_code="AQ02", metropolitan_population=400000)

    population_site = create_operating_site(
        api,
        network["id"],
        site_code="S-POP",
        site_type="POPULATION_ORIENTED",
        population_served=300000,
    )
    create_operating_site(
        api,
        network["id"],
        site_code="S-SRC",
        site_type="SOURCE_ORIENTED",
        latitude=39.60,
        longitude=-104.80,
        population_served=12000,
        distance_to_roadway_m=40.0,
        distance_to_source_m=300.0,
    )
    create_operating_site(
        api,
        network["id"],
        site_code="S-BKG",
        site_type="BACKGROUND",
        latitude=40.10,
        longitude=-105.30,
        population_served=0,
        distance_to_roadway_m=150.0,
    )

    # No span check has ever been logged, so the baseline is the installation
    # date and 369 elapsed days put the instrument past the grace period.
    monitor = create_monitor(
        api,
        population_site["id"],
        method["id"],
        installed_at="2025-01-01T00:00:00Z",
    )
    approve_monitor(api, monitor["id"])
    monitor = get_success_data(api.get_monitor(monitor["id"], PM_HEADERS))
    assert monitor["monitor_status"] == "APPROVED"
    assert monitor["qc_posture"] == "QC_DELINQUENT"

    census = get_success_data(api.get_network(network["id"], PM_HEADERS))
    assert census["delinquent_monitor_count"] == 1
    assert census["waiver_required_site_count"] == 0
    assert census["total_site_count"] == 3
    assert census["operating_site_count"] == 3
    assert_site_census_partitioned(census)

    assessment = get_success_data(
        api.create_assessment(assessment_payload(network["id"], 2026), PM_HEADERS),
        expected_status=201,
    )
    assert assessment["required_population_site_count"] == 1
    assert_ratio_4dp(assessment["coverage_ratio"], 1.0)
    # 100 * 1.0 * (1 - 0.10) * 1.0 == 90.0, exactly on the inclusive edge.
    assert assessment["adequacy_score"] == pytest.approx(90.0, abs=0.01)
    assert assessment["adequacy_tier"] == "ADEQUATE"
    assert assessment["status"] == "DRAFT"
