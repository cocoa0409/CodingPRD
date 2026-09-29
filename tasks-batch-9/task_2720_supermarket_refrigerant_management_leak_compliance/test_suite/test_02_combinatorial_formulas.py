"""
Three multi-component formulas whose composition order matters: per-citation
rounding before summation, a surcharge bracket keyed on one named component, and
a weighted sum whose components are chosen by conditional branches.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_money,
    assert_penalty_exposure,
    assert_score,
    assert_store_posture,
)
from test_helpers.constants import (
    CITATION_DAILY_RATE_MINOR_USD,
    LATE_FILING_DAILY_RATE_USD,
    MULTIPLIER_NON_COMPLIANT,
    SURCHARGE_RATE_UNDER_1000,
)
from test_helpers.test_users import COMPLIANCE_MANAGER_HEADERS, REGULATOR_HEADERS
from test_helpers.types import (
    COMPAT_COMPATIBLE,
    COMPAT_CONDITIONALLY_COMPATIBLE,
    EVENT_REPAIR_OVERDUE,
    LEAKED_CHARGE_BASED,
    PLAN_SUPERSEDED,
    POSTURE_NON_COMPLIANT,
    REPORT_ANNUAL_LEAK_RATE,
    REPORT_SUBMITTED,
)


# ─── penalty exposure: per-item rounding before summation ─────────────


def _overdue_store(api):
    """
    The reference store with one leak event that has blown its 2026-08-31 repair
    deadline: a compliance sweep on 2026-09-01 marks it REPAIR_OVERDUE, which is
    what drives the store to NON_COMPLIANT and the 1.50 multiplier.
    """
    env = X.leak_event_env(api, with_second_technician=False)
    X.set_clock(api, "2026-09-01T00:00:00Z")
    X.run_sweep(api, store_id=env["store_id"])
    return env


def test_penalty_exposure_rounds_each_citation_before_summing_them(api):
    """
    Two MINOR citations of one day each at the 1.50 multiplier round to 413.33
    apiece and sum to 826.66; summing the raw products first would give 826.65.

    Design: Difficulty/combinatorial_formula/penalty_exposure_per_citation_rounding_mode_b
    """
    env = _overdue_store(api)

    assert X.get_leak_event(api, env["event_id"])["status"] == EVENT_REPAIR_OVERDUE
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        compliance_status=POSTURE_NON_COMPLIANT,
        overdue_leak_event_count=1,
    )

    inspection = validate_success(
        api.create_inspection(
            F.inspection_payload(env["store_id"], F.two_minor_one_day_citations()),
            REGULATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_penalty_exposure(
        inspection,
        penalty_exposure_usd=826.66,
        chronic_multiplier_applied=MULTIPLIER_NON_COMPLIANT,
        capped=False,
    )
    assert inspection["penalty_exposure_usd"] != 826.65, (
        "826.65 is the sum-then-round answer; each citation must be rounded first"
    )


def test_penalty_exposure_equals_twice_the_single_citation_amount(api):
    """
    The per-citation amount is round(275.55 * 1 * 1.50, 2) == 413.33, so the
    two-citation total is exactly twice that and the store's exposure follows.

    Design: Difficulty/combinatorial_formula/penalty_exposure_per_citation_rounding_mode_b
    """
    env = _overdue_store(api)

    inspection = validate_success(
        api.create_inspection(
            F.inspection_payload(env["store_id"], F.two_minor_one_day_citations()),
            REGULATOR_HEADERS,
        ),
        expected_status=201,
    )
    per_citation = round(CITATION_DAILY_RATE_MINOR_USD * 1 * MULTIPLIER_NON_COMPLIANT, 2)
    assert_money(per_citation, 413.33, "per-citation amount")
    assert_money(
        inspection["penalty_exposure_usd"], per_citation * 2, "penalty_exposure_usd"
    )
    assert_store_posture(
        X.get_store(api, env["store_id"]), penalty_exposure_total_usd=826.66
    )


# ─── late filing: the bracket is keyed on the base component ──────────


def _report_six_days_late(api):
    """
    A DRAFT annual filing for 2026-01-01..2026-06-30, whose statutory due date is
    the period end plus 60 days, left unsubmitted until six days after that date.
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    X.create_system(api, store["id"], rt404["id"])
    report = validate_success(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                store["id"],
                report_type=REPORT_ANNUAL_LEAK_RATE,
                period_start="2026-01-01T00:00:00Z",
                period_end="2026-06-30T00:00:00Z",
                leaked_lbs_method=LEAKED_CHARGE_BASED,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    X.set_clock(api, "2026-09-04T00:00:00Z")
    return {"store_id": store["id"], "report": report, "report_id": report["id"]}


def test_late_filing_base_assessment_counts_whole_days_past_the_due_date(api):
    """
    The due date is the period end plus 60 days, and submitting six days after it
    assesses six days at the statutory daily rate.

    Design: Difficulty/combinatorial_formula/late_filing_surcharge_bracket_keyed_on_base_mode_c
    """
    env = _report_six_days_late(api)

    assert_instant(env["report"]["due_on"], "2026-08-29T00:00:00Z", "due_on")

    submitted = X.submit_report(api, env["report_id"])
    assert submitted["status"] == REPORT_SUBMITTED
    assert submitted["days_late"] == 6
    assert_money(
        submitted["base_assessment_usd"],
        LATE_FILING_DAILY_RATE_USD * 6,
        "base_assessment_usd",
    )
    assert_money(submitted["base_assessment_usd"], 990.00, "base_assessment_usd")


def test_late_filing_surcharge_bracket_is_keyed_on_the_base_not_the_total(api):
    """
    990.00 sits below the 1000.00 bracket edge, so the surcharge rate is 0.05 and
    the total is 1039.50; keying the bracket on a total that already carries the
    surcharge would have charged 0.10 and reached 1089.00.

    Design: Difficulty/combinatorial_formula/late_filing_surcharge_bracket_keyed_on_base_mode_c
    """
    env = _report_six_days_late(api)

    submitted = X.submit_report(api, env["report_id"])
    assert_money(
        submitted["administrative_surcharge_usd"],
        990.00 * SURCHARGE_RATE_UNDER_1000,
        "administrative_surcharge_usd",
    )
    assert_money(
        submitted["administrative_surcharge_usd"], 49.50, "administrative_surcharge_usd"
    )
    assert_money(
        submitted["late_filing_assessment_usd"], 1039.50, "late_filing_assessment_usd"
    )
    assert submitted["late_filing_assessment_usd"] != 1089.00, (
        "1089.00 is the total-keyed bracket answer; the bracket reads the base alone"
    )


# ─── retrofit compatibility: branch-selected components ──────────────


def _system_with_three_chemistries(api):
    """
    The reference rack charged with R-404A, with an R-448A target that keeps both
    the pressure class and the chemical family, and an R-245fa target that has a
    lower GWP but flips the pressure branch.
    """
    return X.base_env(
        api, with_r448a=True, with_r245fa=True, with_second_technician=False
    )


def test_same_pressure_and_family_target_scores_compatible(api):
    """
    R-404A to R-448A keeps the HIGH pressure class and the HFC family, so both
    branch components take their maximum and the weighted sum is 84.1.

    Design: Difficulty/combinatorial_formula/retrofit_compatibility_conditional_component_branches_mode_a
    """
    env = _system_with_three_chemistries(api)

    plan448 = X.file_retrofit_plan(
        api, env["system_id"], target_refrigerant_type_id=env["rt448_id"]
    )
    assert_score(plan448["compatibility_score"], 84.1, "compatibility_score")
    assert plan448["compatibility_result"] == COMPAT_COMPATIBLE
    assert_score(plan448["gwp_reduction_pct"], 64.6, "gwp_reduction_pct")


def test_lower_gwp_target_scores_worse_when_the_pressure_branch_flips(api):
    """
    R-245fa has the lower GWP of the two targets, yet dropping to a different
    pressure class costs it more than the GWP component gains: 70.2 and only
    CONDITIONALLY_COMPATIBLE, while the earlier plan is superseded.

    Design: Difficulty/combinatorial_formula/retrofit_compatibility_conditional_component_branches_mode_a
    """
    env = _system_with_three_chemistries(api)
    version_before = X.system_version(api, env["system_id"])

    plan448 = X.file_retrofit_plan(
        api, env["system_id"], target_refrigerant_type_id=env["rt448_id"]
    )
    plan245 = X.file_retrofit_plan(
        api,
        env["system_id"],
        target_refrigerant_type_id=env["rt245_id"],
        estimated_cost_usd=98000.00,
    )

    assert_score(plan245["compatibility_score"], 70.2, "compatibility_score")
    assert plan245["compatibility_result"] == COMPAT_CONDITIONALLY_COMPATIBLE
    assert plan245["mandated"] is False
    assert plan245["compatibility_score"] < plan448["compatibility_score"], (
        "the lower-GWP target must still score worse once the pressure branch flips"
    )
    assert X.get_plan(api, plan448["id"])["status"] == PLAN_SUPERSEDED
    assert X.get_system(api, env["system_id"])["version"] == version_before + 2
