"""
Two selectable-variant calculations that must diverge on identical ledger data:
the per-system leak rate and the store-level period leaked mass.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_mass, assert_projection
from test_helpers.constants import THRESHOLD_PCT_COMMERCIAL_REFRIGERATION
from test_helpers.test_users import COMPLIANCE_MANAGER_HEADERS
from test_helpers.types import (
    LEAKED_BALANCE_BASED,
    LEAKED_CHARGE_BASED,
    METHOD_ANNUALIZING,
    METHOD_ROLLING_AVERAGE,
    REPORT_REJECTED,
)


def _annualizing_system_topped_up(api):
    """
    A 100.0 lb commercial rack on the ANNUALIZING method whose baseline is its
    installation date, exactly 90 days before the clock, holding 90.0 lbs. One
    10.0 lb top-up at the clock brings it back to a full charge, which is the
    single ledger row both variants have to read.
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        system_overrides={
            "full_charge_lbs": 100.0,
            "initial_charge_lbs": 90.0,
            "installed_on": "2026-05-03T00:00:00Z",
            "leak_rate_method": METHOD_ANNUALIZING,
        },
    )
    env["record"] = X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=10.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=120,
    )
    return env


def test_annualizing_variant_time_normalises_the_addition_to_forty_point_six(api):
    """
    Under ANNUALIZING the 10.0 lbs are divided by the 90 days since the baseline
    and scaled to a year, so a 10 percent charge loss reads 40.6 percent and
    crosses the 20.0 percent threshold.

    Design: Difficulty/dual_variant_calc/leak_rate_rolling_average_vs_annualizing_diverge_on_one_system
    """
    env = _annualizing_system_topped_up(api)

    assert_mass(env["record"]["system_charge_after_lbs"], 100.0, "system_charge_after_lbs")
    assert_mass(env["record"]["leak_rate_pct_after"], 40.6, "leak_rate_pct_after")
    assert_mass(
        X.get_system(api, env["system_id"])["leak_rate_pct"], 40.6, "leak_rate_pct"
    )

    projection = validate_success(
        api.get_leak_rate_projection(env["system_id"], COMPLIANCE_MANAGER_HEADERS)
    )
    assert_projection(
        projection,
        method=METHOD_ANNUALIZING,
        leak_rate_pct=40.6,
        refrigerant_added_lbs_in_window=10.0,
        window_start="2026-05-03T00:00:00Z",
        threshold_pct=THRESHOLD_PCT_COMMERCIAL_REFRIGERATION,
        would_trigger_leak_event=True,
    )


def test_rolling_average_variant_reads_ten_percent_on_the_same_ledger(api):
    """
    Asking the same system for the ROLLING_AVERAGE variant reads the trailing 365
    days with no normalisation, so the identical 10.0 lbs read 10.0 percent and
    stay under the threshold: the two variants differ by 30.6 points.

    Design: Difficulty/dual_variant_calc/leak_rate_rolling_average_vs_annualizing_diverge_on_one_system
    """
    env = _annualizing_system_topped_up(api)

    annualizing = validate_success(
        api.get_leak_rate_projection(env["system_id"], COMPLIANCE_MANAGER_HEADERS)
    )
    rolling = validate_success(
        api.get_leak_rate_projection(
            env["system_id"],
            COMPLIANCE_MANAGER_HEADERS,
            params={"method": METHOD_ROLLING_AVERAGE},
        )
    )
    assert_projection(
        rolling,
        method=METHOD_ROLLING_AVERAGE,
        leak_rate_pct=10.0,
        refrigerant_added_lbs_in_window=10.0,
        window_start="2025-08-01T00:00:00Z",
        threshold_pct=THRESHOLD_PCT_COMMERCIAL_REFRIGERATION,
        would_trigger_leak_event=False,
    )
    assert_mass(
        round(annualizing["leak_rate_pct"] - rolling["leak_rate_pct"], 1),
        30.6,
        "variant divergence",
    )
    assert_mass(
        X.get_system(api, env["system_id"])["leak_rate_pct"],
        40.6,
        "the stored rate still follows the system's own method",
    )


def _store_with_one_period_addition(api):
    """
    The reference store with a single 20.0 lb top-up inside the reporting period,
    which takes the rack from 80.0 to a full 100.0 lbs. CHARGE_BASED sees 20.0
    lbs leaked; BALANCE_BASED nets 80.0 + 20.0 - 0.0 - 100.0 == 0.0.
    """
    return X.leak_event_env(api, added_lbs=20.0, with_second_technician=False)


def test_charge_based_variant_counts_every_pound_added_as_leaked(api):
    """
    The CHARGE_BASED filing reports the 20.0 lbs that had to be added, and a
    rejection frees the period so the other variant can be filed over it.

    Design: Difficulty/dual_variant_calc/period_leaked_mass_charge_based_vs_balance_based_diverge_on_one_store
    """
    env = _store_with_one_period_addition(api)

    charge_report = validate_success(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                env["store_id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                leaked_lbs_method=LEAKED_CHARGE_BASED,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert_mass(charge_report["total_leaked_lbs"], 20.0, "total_leaked_lbs")
    assert charge_report["included_system_count"] == 1

    X.submit_report(api, charge_report["id"])
    rejected = X.reject_report(api, charge_report["id"], "METHOD_CHANGE_REQUESTED")
    assert rejected["status"] == REPORT_REJECTED
    assert_mass(rejected["total_leaked_lbs"], 20.0, "total_leaked_lbs after submission")


def test_balance_based_variant_nets_the_ledger_to_zero_on_the_same_period(api):
    """
    Re-filing the identical store and period under BALANCE_BASED nets the opening
    and closing charge against the additions and reports 0.0 lbs, 20.0 lbs below
    the charge-based answer for the very same service ledger.

    Design: Difficulty/dual_variant_calc/period_leaked_mass_charge_based_vs_balance_based_diverge_on_one_store
    """
    env = _store_with_one_period_addition(api)

    charge_report = validate_success(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                env["store_id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                leaked_lbs_method=LEAKED_CHARGE_BASED,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    X.submit_report(api, charge_report["id"])
    X.reject_report(api, charge_report["id"], "METHOD_CHANGE_REQUESTED")

    balance_report = validate_success(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                env["store_id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                leaked_lbs_method=LEAKED_BALANCE_BASED,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert_mass(balance_report["total_leaked_lbs"], 0.0, "total_leaked_lbs")
    assert balance_report["included_system_count"] == 1
    assert_mass(
        round(
            X.get_report(api, charge_report["id"])["total_leaked_lbs"]
            - balance_report["total_leaked_lbs"],
            1,
        ),
        20.0,
        "variant divergence",
    )
