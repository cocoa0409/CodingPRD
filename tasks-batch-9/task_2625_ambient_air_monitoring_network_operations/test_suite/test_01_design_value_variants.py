"""Design-value variants and instrument quality-control posture variants."""

import pytest

from test_helpers import (
    TECH_HEADERS,
    add_concurred_demonstration,
    assert_annual_statistics,
    assert_pct,
    canonical_environment,
    compute_design_value,
    set_clock,
    twelve_validated_quarters,
    validate_success,
)


def _both_variants(api):
    """Twelve validated quarters, a concurred wildfire event, then both variants."""
    env = twelve_validated_quarters(api)
    add_concurred_demonstration(env)
    dv_with = compute_design_value(env, 2025, "WITH_EVENT_DATA")
    dv_excl = compute_design_value(env, 2025, "EXCLUDING_CONCURRED_EVENTS")
    return env, dv_with, dv_excl


def test_with_event_data_variant_reads_nonattainment_at_9_1(api):
    """The unadjusted variant keeps the reported quarterly means.

    PRD 3.7: "Under `WITH_EVENT_DATA`, every quarter contributes its
    `quarterly_mean_concentration` regardless of whether the quarter carries an
    effective event exclusion — exceptional-event hours still influence the
    reported mean."

    Design: Difficulty/dual_variant_calc/design_value_variant_divergence_flips_site_attainment
    """
    env, dv_with, _ = _both_variants(api)

    assert_annual_statistics(dv_with["annual_statistics"], [9.3, 9.1, 9.0])
    assert dv_with["design_value"] == pytest.approx(9.1, abs=0.001)
    assert dv_with["attainment_status"] == "NONATTAINMENT"
    assert dv_with["complete_year_count"] == 3
    assert dv_with["primary_monitor_id"] == env.monitor_id


def test_excluding_concurred_events_variant_flips_the_site_to_attainment(api):
    """The event-adjusted variant substitutes the adjusted mean and flips the verdict.

    PRD 3.7: "Under `EXCLUDING_CONCURRED_EVENTS`, a quarter that is referenced by
    at least one exclusion whose `status` is `EFFECTIVE` contributes its
    `quarterly_mean_concentration_event_adjusted` instead, while every other
    quarter still contributes its `quarterly_mean_concentration`."

    Design: Difficulty/dual_variant_calc/design_value_variant_divergence_flips_site_attainment
    """
    env, dv_with, dv_excl = _both_variants(api)

    assert_annual_statistics(dv_excl["annual_statistics"], [9.3, 8.7, 9.0])
    assert dv_excl["design_value"] == pytest.approx(9.0, abs=0.001)
    assert dv_excl["attainment_status"] == "ATTAINMENT"
    assert dv_excl["complete_year_count"] == 3
    assert dv_excl["primary_monitor_id"] == env.monitor_id
    assert dv_with["design_value"] - dv_excl["design_value"] == pytest.approx(0.1, abs=0.001)

    q3 = env.read_batch(2024, 3)
    assert q3["event_excluded_hour_count"] == 192
    assert q3["adjusted_scheduled_hour_count"] == 2016
    assert_pct(q3["completeness_pct"], 100.0)


def _delinquent_but_forgiven_monitor(api):
    """One instrument 35 calendar days past its span check, 20 of them out of service."""
    env = canonical_environment(
        api, clock="2025-12-01T00:00:00Z", span_check_at=None
    )
    validate_success(
        api.create_qc_event(
            env.monitor_id,
            {
                "event_type": "SPAN_CHECK",
                "performed_at": "2025-12-01T00:00:00Z",
                "span_drift_pct": 1.0,
            },
            TECH_HEADERS,
        ),
        201,
    )
    set_clock(api, "2025-12-05T00:00:00Z")
    validate_success(
        api.set_service_status(
            env.monitor_id,
            {"new_status": "OUT_OF_SERVICE", "reason": "Analyser sent for factory repair"},
            TECH_HEADERS,
        )
    )
    set_clock(api, "2025-12-25T00:00:00Z")
    validate_success(
        api.set_service_status(
            env.monitor_id,
            {"new_status": "OPERATING", "reason": "Analyser reinstalled"},
            TECH_HEADERS,
        )
    )
    set_clock(api, "2026-01-05T00:00:00Z")
    return env


def test_out_of_service_accrual_is_closed_out_on_return_to_service(api):
    """Twenty whole days accrue while the instrument sits out of service.

    PRD 3.3: "Returning to service closes out the accrual: `out_of_service_day_count`
    grows by the number of whole days elapsed from `out_of_service_since` to the
    logical clock, computed by dividing the elapsed seconds by 86400 and discarding
    any fraction, and `out_of_service_since` is cleared to null."

    Design: Difficulty/dual_variant_calc/monitor_qc_posture_variant_divergence_on_instrument_delinquency
    """
    env = _delinquent_but_forgiven_monitor(api)

    monitor = env.read_monitor()
    assert monitor["out_of_service_day_count"] == 20
    assert monitor["out_of_service_since"] is None
    assert monitor["monitor_status"] == "OPERATING"


def test_calendar_and_in_service_postures_diverge_by_the_forgiven_days(api):
    """The two posture variants differ by exactly the accrued out-of-service days.

    PRD 3.3: "The two therefore diverge by exactly the accrued out-of-service days,
    and an instrument can be `QC_DELINQUENT` on `qc_posture` while only `QC_DUE` on
    `qc_posture_in_service` at the very same clock instant."

    Design: Difficulty/dual_variant_calc/monitor_qc_posture_variant_divergence_on_instrument_delinquency
    """
    env = _delinquent_but_forgiven_monitor(api)

    monitor = env.read_monitor()
    assert monitor["qc_posture"] == "QC_DELINQUENT"
    assert monitor["qc_posture_in_service"] == "QC_DUE"

    network = env.read_network()
    assert network["delinquent_monitor_count"] == 1
