"""Nested-formula arithmetic: adequacy scoring and design-value rounding order."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    EPA_HEADERS,
    PM_HEADERS,
    assert_annual_statistics,
    assert_ratio_4dp,
    assert_siting_codes,
    base_environment,
    compute_design_value,
    create_operating_monitor,
    create_operating_site,
    create_site,
    get_success_data,
    twelve_validated_quarters,
    validate_success,
)


def _mid_size_metro_network(api):
    """A 600 000-person network with three population sites, one waivered
    source site, no background site and one delinquent instrument."""
    env = base_environment(api)
    network = get_success_data(
        api.create_network(
            {
                "name": "Mid-size Metro Network",
                "agency_code": "AQ02",
                "metropolitan_population": 600000,
            },
            ADMIN_HEADERS,
        )
    )
    env.network_id = network["id"]

    population_sites = []
    for code, lat, lon, population, roadway in (
        ("P-001", 39.70, -104.90, 200000, 25.0),
        ("P-002", 39.71, -104.91, 150000, 30.0),
        ("P-003", 39.72, -104.92, 120000, 40.0),
    ):
        site = create_operating_site(
            api,
            env.network_id,
            site_code=code,
            latitude=lat,
            longitude=lon,
            population_served=population,
            distance_to_roadway_m=roadway,
        )
        population_sites.append(site["id"])
    env.site_id = population_sites[0]

    source_site = create_site(
        api,
        env.network_id,
        site_code="X-001",
        site_type="SOURCE_ORIENTED",
        latitude=39.60,
        longitude=-104.80,
        population_served=5000,
        distance_to_source_m=800.0,
    )
    validate_success(
        api.approve_siting(
            source_site["id"],
            {
                "waiver_granted": True,
                "approval_note": "Nearest accessible parcel; source-distance waiver granted",
            },
            EPA_HEADERS,
        )
    )
    validate_success(api.commence_operations(source_site["id"], {}, PM_HEADERS))
    env.source_site_id = source_site["id"]

    monitor = create_operating_monitor(
        api, env.site_id, env.method_id, installed_at="2025-01-01T00:00:00Z"
    )
    env.monitor_id = monitor["id"]
    return env


def _open_assessment(api, env):
    return get_success_data(
        api.create_assessment({"network_id": env.network_id, "cycle_year": 2026}, PM_HEADERS)
    )


def test_each_site_class_credit_is_capped_at_its_own_requirement(api):
    """Three population sites credit only the two the tier requires.

    PRD 3.9: "Because each credit is individually capped, surplus sites of one
    class can never compensate for a missing site of another."

    Design: Difficulty/combinatorial_formula/network_adequacy_nested_min_credits_and_capped_penalty_factors
    """
    env = _mid_size_metro_network(api)

    source_site = get_success_data(api.get_site(env.source_site_id, PM_HEADERS))
    assert_siting_codes(source_site, ["SOURCE_DISTANCE"])

    network = env.read_network()
    assert network["operating_site_count"] == 4
    assert network["waiver_required_site_count"] == 1
    assert network["delinquent_monitor_count"] == 1

    assessment = _open_assessment(api, env)
    assert assessment["required_population_site_count"] == 2
    assert_ratio_4dp(assessment["coverage_ratio"], 0.75)


def test_both_penalty_factors_degrade_the_capped_coverage_ratio(api):
    """Coverage 0.75 degraded by a 10-point QC penalty and a 5-point siting penalty.

    PRD 3.9: "`adequacy_score` is `coverage_ratio` multiplied by the quality-control
    factor, multiplied by the siting factor, multiplied by 100, and rounded to one
    decimal place."

    Design: Difficulty/combinatorial_formula/network_adequacy_nested_min_credits_and_capped_penalty_factors
    """
    env = _mid_size_metro_network(api)
    assessment = _open_assessment(api, env)

    assert assessment["adequacy_score"] == pytest.approx(64.1, abs=0.01)
    assert assessment["adequacy_tier"] == "INADEQUATE"
    assert assessment["status"] == "DRAFT"


def test_annual_statistics_are_rounded_once_per_year_before_the_mean(api):
    """Per-year raw means of 9.25, 9.05 and 8.95 round to 9.3, 9.1 and 9.0.

    PRD 3.7: "That raw figure is then rounded to the pollutant's `rounding_decimals`
    and appended to `annual_statistics`."

    Design: Difficulty/combinatorial_formula/design_value_step_rounding_order_decides_attainment
    """
    env = twelve_validated_quarters(api)
    design_value = compute_design_value(env, 2025, "WITH_EVENT_DATA")

    assert_annual_statistics(design_value["annual_statistics"], [9.3, 9.1, 9.0])
    assert design_value["complete_year_count"] == 3


def test_the_forbidden_single_rounding_order_would_have_read_9_0(api):
    """The normative two-step order yields 9.1, not the 9.0 of the forbidden order.

    PRD 3.7: "The normative order yields annual statistics of 9.3, 9.1 and 9.0, a mean
    of 9.13333, a truncated design value of 9.1 and a verdict of `NONATTAINMENT`."

    Design: Difficulty/combinatorial_formula/design_value_step_rounding_order_decides_attainment
    """
    env = twelve_validated_quarters(api)
    design_value = compute_design_value(env, 2025, "WITH_EVENT_DATA")

    assert design_value["design_value"] == pytest.approx(9.1, abs=0.001)
    assert design_value["design_value"] != pytest.approx(9.0, abs=0.001)
    assert design_value["attainment_status"] == "NONATTAINMENT"

    site = env.read_site()
    assert site["current_attainment_status"] == "NONATTAINMENT"
