"""Dual-variant calculations: the two shift-plan cost-per-package figures and the
two attrition scoring bases.

Every test builds its own world from scratch — the harness relaunches the API
server before each individual test, so the database is empty and the logical
clock sits at its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers.assertions import (
    expected_final_cost_per_package,
    expected_planned_labor_cents,
    expected_provisional_cost_per_package,
)

# ─── The eight-hour shift both cost variants are computed for ───
SHIFT_DATE = "2026-08-01"
SHIFT_START = "2026-08-01T00:00:00Z"
SHIFT_END = "2026-08-01T08:00:00Z"
SHIFT_HOURS = 8.00
FORECAST_VOLUME = 4000
PLANNED_CORE = 4
PLANNED_SEASONAL = 0
LABOR_BUDGET_CENTS = 100000

INDUCTED_PACKAGES = 3000
SCANNED_PACKAGES = 2400
MISSORT_PACKAGES = 400

# ─── The attrition world ───
ATTRITION_CLOCK = "2026-08-03T06:00:00Z"
ATTRITION_SHIFT_START = "2026-08-03T06:00:00Z"
ATTRITION_SHIFT_END = "2026-08-03T14:00:00Z"
SEASONAL_HIRE_DATE = "2026-07-15"
EXPECTED_TENURE_DAYS = 19


def _approved_eight_hour_plan(world, facility):
    """One approved eight-hour plan on the mid automation tier: automation 70,
    a single line, forecast 4,000 packages, four core bodies and no flex draw."""
    center = facility["center"]
    plan = world.create_submitted_plan(
        center["id"],
        shift_date=SHIFT_DATE,
        shift_window_start=SHIFT_START,
        shift_window_end=SHIFT_END,
        forecast_volume=FORECAST_VOLUME,
        planned_core_headcount=PLANNED_CORE,
        planned_seasonal_headcount=PLANNED_SEASONAL,
        labor_budget_cents=LABOR_BUDGET_CENTS,
    )
    return world.approve_plan(plan["id"], center["id"])


def _settled_eight_hour_plan(world, facility):
    """The same approved plan driven all the way to `CLOSED`: 2,400 packages
    scanned onto its lane, 400 of them pulled back out as a mis-sort, and two
    certified core associates who each worked the full eight hours."""
    center = facility["center"]
    lane = facility["lane"]
    plan = _approved_eight_hour_plan(world, facility)

    world.induct_packages(
        center["id"], facility["inbound_door"]["id"], INDUCTED_PACKAGES
    )
    load = world.stage_load(
        center["id"], facility["outbound_door"]["id"], lane["id"]
    )
    world.scan(load["id"], small_count=SCANNED_PACKAGES)
    world.create_exception(
        center["id"],
        exception_type="MISSORT",
        package_count=MISSORT_PACKAGES,
        from_destination_lane_id=lane["id"],
    )

    for _ in range(2):
        worker = world.create_certified_worker(center["id"], hire_class="CORE")
        world.complete_assignment_with_hours(
            plan["id"],
            worker["id"],
            facility["chute"]["id"],
            SHIFT_START,
            SHIFT_END,
        )

    return world.close_plan(plan["id"], center["id"])


def _seasonal_worker_with_three_assignments(world, facility):
    """A certified seasonal associate carrying one missed training session and
    three staff assignments on an approved plan, the first two already settled.

    Returns the worker as it stands after two completions and the identifier of
    the third, still-untouched assignment.
    """
    center = facility["center"]
    world.set_clock(ATTRITION_CLOCK)

    plan = world.create_submitted_plan(
        center["id"],
        shift_date="2026-08-03",
        shift_window_start=ATTRITION_SHIFT_START,
        shift_window_end=ATTRITION_SHIFT_END,
        forecast_volume=FORECAST_VOLUME,
        planned_core_headcount=0,
        planned_seasonal_headcount=1,
        labor_budget_cents=LABOR_BUDGET_CENTS,
    )
    plan = world.approve_plan(plan["id"], center["id"])

    worker = world.create_worker(
        center["id"], hire_class="SEASONAL", hire_date=SEASONAL_HIRE_DATE
    )
    world.record_event(worker["id"], "ONBOARDING_STARTED")
    world.record_event(worker["id"], "BACKGROUND_CLEARED")
    world.record_event(worker["id"], "TRAINING_SESSION_COMPLETED")
    world.record_event(worker["id"], "TRAINING_SESSION_COMPLETED")
    world.record_event(worker["id"], "TRAINING_SESSION_MISSED")
    worker = world.record_event(worker["id"], "CERTIFIED")

    assignments = [
        world.create_assignment(
            plan["id"],
            worker["id"],
            facility["chute"]["id"],
            role_on_line="SECONDARY_SORTER",
        )
        for _ in range(3)
    ]
    for settled in assignments[:2]:
        world.check_in(settled["id"], worker["id"])
        world.check_out(settled["id"], worker["id"])

    return world.worker(worker["id"]), assignments[2]["id"]


def test_provisional_cost_per_package_divides_planned_labor_and_overhead_by_the_full_forecast(
    world, facility
):
    """PRD §3.5: "`provisional_cost_per_package_cents` is the sum of `planned_labor_cents` and the fixed overhead of 12,000 cents per shift, divided by the plan's full `forecast_volume`, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/shift_plan_cost_per_package_provisional_vs_final
    """
    plan = _approved_eight_hour_plan(world, facility)

    assert plan["status"] == "APPROVED", (
        f"expected the plan to be APPROVED, got {plan['status']}"
    )
    assert float(plan["shift_hours"]) == pytest.approx(SHIFT_HOURS, abs=1e-6), (
        f"the shift window is eight hours long, got {plan['shift_hours']}"
    )
    assert plan["required_headcount"] == 4, (
        "4,000 packages over 950 packages per associate-hour and 8.00 hours needs "
        "one associate, so the per-line floor of 4 governs, got "
        f"{plan['required_headcount']}"
    )
    assert plan["flex_draw_count"] == 0, (
        "the four core bodies already cover the requirement, so nothing is drawn "
        f"from the bench, got {plan['flex_draw_count']}"
    )

    expected_planned = expected_planned_labor_cents(
        PLANNED_CORE, PLANNED_SEASONAL, 0, SHIFT_HOURS
    )
    assert expected_planned == 68800, (
        f"4 core bodies * 8.00 h * 2,150 cents is 68,800 cents, got {expected_planned}"
    )
    assert plan["planned_labor_cents"] == 68800, (
        f"expected planned_labor_cents 68800, got {plan['planned_labor_cents']}"
    )

    expected_provisional = expected_provisional_cost_per_package(
        68800, FORECAST_VOLUME
    )
    assert expected_provisional == pytest.approx(20.20, abs=1e-6), (
        f"(68,800 + 12,000) / 4,000 is 20.20 cents per package, got {expected_provisional}"
    )
    assert float(plan["provisional_cost_per_package_cents"]) == pytest.approx(
        20.20, abs=1e-6
    ), (
        "the provisional figure divides planned money by every forecast package, "
        f"got {plan['provisional_cost_per_package_cents']}"
    )
    assert plan["final_cost_per_package_cents"] is None, (
        "the final variant is only written when the shift settles, got "
        f"{plan['final_cost_per_package_cents']}"
    )


def test_final_cost_per_package_charges_rework_over_sorted_packages_net_of_missorts(
    world, facility
):
    """PRD §3.9: "The numerator is `actual_labor_cents` plus the fixed overhead of 12,000 cents per shift plus that rework charge."
    PRD §3.9: "The denominator is the plan's `sorted_package_count` minus its `missort_package_count`, floored at 1 so a shift that sorted nothing does not divide by zero."

    Design: Difficulty/dual_variant_calc/shift_plan_cost_per_package_provisional_vs_final
    """
    plan = _settled_eight_hour_plan(world, facility)

    assert plan["status"] == "CLOSED", (
        f"settlement drives the plan to CLOSED, got {plan['status']}"
    )
    assert plan["sorted_package_count"] == SCANNED_PACKAGES, (
        f"the scan credited 2,400 packages to the plan, got {plan['sorted_package_count']}"
    )
    assert plan["missort_package_count"] == MISSORT_PACKAGES, (
        "the MISSORT exception of 400 packages lands on the attributed plan, got "
        f"{plan['missort_package_count']}"
    )
    assert plan["actual_labor_cents"] == 34400, (
        "two completed core lines of 8.00 h * 2,150 cents each and no flex premium "
        f"is 34,400 cents, got {plan['actual_labor_cents']}"
    )

    expected_final = expected_final_cost_per_package(
        34400, SCANNED_PACKAGES, MISSORT_PACKAGES
    )
    assert expected_final == pytest.approx(30.20, abs=1e-6), (
        "(34,400 + 12,000 + 400 * 35) / (2,400 - 400) is 30.20 cents per package, "
        f"got {expected_final}"
    )
    assert float(plan["final_cost_per_package_cents"]) == pytest.approx(
        30.20, abs=1e-6
    ), (
        "the final figure divides actually-worked money plus rework by "
        f"actually-sorted-and-correct packages, got {plan['final_cost_per_package_cents']}"
    )

    provisional = float(plan["provisional_cost_per_package_cents"])
    assert provisional == pytest.approx(20.20, abs=1e-6), (
        f"closure leaves the provisional figure alone, got {provisional}"
    )
    assert float(plan["final_cost_per_package_cents"]) - provisional == pytest.approx(
        10.00, abs=1e-6
    ), "the same shift settles ten cents per package above the figure quoted at approval"


def test_attrition_score_stays_on_the_cohort_curve_below_three_completed_assignments(
    world, facility
):
    """PRD §3.6: "While a worker has completed fewer than 3 assignments there is not enough individual evidence to score them personally: `attrition_risk_basis` is `COHORT_BASELINE` and `attrition_risk_score` is the tenure baseline plus the hire-class adjustment, capped at a ceiling of 0.95 and rounded half up to four decimal places, with the observed adjustment ignored entirely — a brand-new seasonal hire with two missed sessions still scores exactly as its cohort does."

    Design: Difficulty/dual_variant_calc/worker_attrition_cohort_baseline_vs_individual_observed
    """
    worker, _third_assignment_id = _seasonal_worker_with_three_assignments(
        world, facility
    )

    assert worker["completed_assignment_count"] == 2, (
        "two of the three assignments have been clocked out, got "
        f"{worker['completed_assignment_count']}"
    )
    assert worker["tenure_days"] == EXPECTED_TENURE_DAYS, (
        "a hire date of 2026-07-15 read against a clock of 2026-08-03 is 19 whole "
        f"days of tenure, got {worker['tenure_days']}"
    )
    assert worker["training_sessions_missed"] == 1, (
        f"one training session was missed, got {worker['training_sessions_missed']}"
    )
    assert worker["no_show_count"] == 0, (
        f"no no-show was ever recorded, got {worker['no_show_count']}"
    )
    assert worker["status"] == "CERTIFIED", (
        f"the associate is certified, got {worker['status']}"
    )

    assert worker["attrition_risk_basis"] == "COHORT_BASELINE", (
        "fewer than three completions keeps the basis on the cohort curve, got "
        f"{worker['attrition_risk_basis']}"
    )
    assert float(worker["attrition_risk_score"]) == pytest.approx(0.4300, abs=1e-6), (
        "the 15-through-45-day tenure bucket of 0.31 plus the SEASONAL adjustment of "
        "0.12 is 0.4300, with the missed session and the certification credit both "
        f"ignored, got {worker['attrition_risk_score']}"
    )
    assert worker["attrition_flagged"] is False, (
        f"0.4300 is below the flag threshold of 0.55, got {worker['attrition_flagged']}"
    )


def test_third_completed_assignment_flips_the_attrition_basis_to_individual_observed(
    world, facility
):
    """PRD §3.6: "Once the worker has completed at least 3 assignments, `attrition_risk_basis` becomes `INDIVIDUAL_OBSERVED` and `attrition_risk_score` is the tenure baseline plus the hire-class adjustment plus the observed adjustment, clamped to no less than 0.02 and no more than 0.95 and rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/worker_attrition_cohort_baseline_vs_individual_observed
    """
    worker, third_assignment_id = _seasonal_worker_with_three_assignments(
        world, facility
    )
    worker_id = worker["id"]

    world.check_in(third_assignment_id, worker_id)
    world.check_out(third_assignment_id, worker_id)
    rescored = world.worker(worker_id)

    assert rescored["completed_assignment_count"] == 3, (
        f"the third completion has landed, got {rescored['completed_assignment_count']}"
    )
    assert rescored["consecutive_completed_shifts"] == 3, (
        "three completions in a row and no rest day, got "
        f"{rescored['consecutive_completed_shifts']}"
    )
    assert rescored["tenure_days"] == EXPECTED_TENURE_DAYS, (
        f"the clock never moved, so tenure is still 19 days, got {rescored['tenure_days']}"
    )
    assert rescored["training_sessions_missed"] == 1, (
        "the missed session count is unchanged by a check-out, got "
        f"{rescored['training_sessions_missed']}"
    )
    assert rescored["no_show_count"] == 0, (
        f"still no no-show, got {rescored['no_show_count']}"
    )

    assert rescored["attrition_risk_basis"] == "INDIVIDUAL_OBSERVED", (
        "the third completion is enough individual evidence, got "
        f"{rescored['attrition_risk_basis']}"
    )
    assert float(rescored["attrition_risk_score"]) == pytest.approx(0.4400, abs=1e-6), (
        "0.31 tenure plus 0.12 SEASONAL plus the observed adjustment of one missed "
        "session (0.05) less the certified credit (0.04) is 0.4400, got "
        f"{rescored['attrition_risk_score']}"
    )
    assert rescored["attrition_flagged"] is False, (
        f"0.4400 is still below the flag threshold of 0.55, got {rescored['attrition_flagged']}"
    )
