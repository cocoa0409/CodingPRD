"""Validation-precedence conflicts (PRD §2.7): when two checks of different
families are both violated by one request, the lower-numbered check is the one
reported and the other stays silent.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CENTER_FROZEN,
    ERR_INVALID_LOAD_STATE,
    ERR_LABOR_BUDGET_EXCEEDED,
    ERR_LINE_HEADCOUNT_EXCEEDED,
    ERR_WORKER_CENTER_MISMATCH,
    ERR_WORKER_NOT_CLEARED,
)
from test_helpers.assertions import expected_planned_labor_cents, expected_required_headcount
from test_helpers.constants import MAX_LINE_HEADCOUNT
from test_helpers.test_users import LABOR_PLANNER_HEADERS, OPS_MANAGER_HEADERS


def _dispatched_load(world, facility):
    """One trailer taken all the way to `DISPATCHED` at the fixture's building."""
    load = world.create_sealed_load(
        facility["center"]["id"],
        facility["inbound_door"]["id"],
        facility["outbound_door"]["id"],
        facility["lane"]["id"],
        small_count=100,
    )
    return world.dispatch(load["id"])


def _sealed_undispatched_load(world, facility):
    """One trailer that is `LOADED` and `SEALED` but has never left."""
    return world.create_sealed_load(
        facility["center"]["id"],
        facility["inbound_door"]["id"],
        facility["outbound_door"]["id"],
        facility["lane"]["id"],
        small_count=100,
    )


def _submitted_plan(world, center_id, **overrides):
    payload = {
        "forecast_volume": 4000,
        "planned_seasonal_headcount": 0,
    }
    payload.update(overrides)
    return world.create_submitted_plan(center_id, **payload)


def test_redispatching_a_dispatched_load_at_a_frozen_center_reports_invalid_load_state(
    api, world, facility
):
    """PRD §2.7: "Because many operations carry several checks that could each fail, the order of evaluation is fixed."

    Design: Difficulty/priority_pair_validation_conflict/load_state_beats_center_frozen_on_redispatch
    """
    center_id = facility["center"]["id"]
    dispatched = _dispatched_load(world, facility)
    assert dispatched["load_status"] == "DISPATCHED"
    assert dispatched["seal_status"] == "SEALED"
    dispatched_at = dispatched["dispatched_at"]

    injury = world.freeze_center(center_id)
    frozen_center = world.center(center_id)
    assert frozen_center["ops_posture"] == "FROZEN"
    assert frozen_center["open_serious_injury_count"] == 1

    response = api.dispatch_load(dispatched["id"], OPS_MANAGER_HEADERS)
    validate_error(response, ERR_INVALID_LOAD_STATE)

    load_after = world.load(dispatched["id"])
    assert load_after["load_status"] == "DISPATCHED"
    assert load_after["dispatched_at"] == dispatched_at
    assert load_after["seal_status"] == "SEALED"
    assert world.injury(injury["id"])["status"] == "OPEN"


def test_frozen_posture_gate_surfaces_only_for_the_load_whose_state_check_passes(
    api, world, facility
):
    """PRD §2.7: "Implementations must evaluate in exactly this precedence, and the first failing check is the one reported:"

    Design: Difficulty/priority_pair_validation_conflict/load_state_beats_center_frozen_on_redispatch
    """
    center_id = facility["center"]["id"]
    already_gone = _dispatched_load(world, facility)
    still_here = _sealed_undispatched_load(world, facility)
    assert still_here["load_status"] == "LOADED"
    assert still_here["seal_status"] == "SEALED"

    world.freeze_center(center_id)
    assert world.center(center_id)["ops_posture"] == "FROZEN"

    # The load whose own state dimension is already terminal reports its state.
    validate_error(
        api.dispatch_load(already_gone["id"], OPS_MANAGER_HEADERS),
        ERR_INVALID_LOAD_STATE,
    )
    # The load whose state dimensions are both fine reaches the posture gate.
    validate_error(
        api.dispatch_load(still_here["id"], OPS_MANAGER_HEADERS),
        ERR_CENTER_FROZEN,
    )

    assert world.load(still_here["id"])["load_status"] == "LOADED"
    assert world.load(still_here["id"])["dispatched_at"] is None


def test_line_headcount_ceiling_is_reported_ahead_of_the_labor_budget_at_approve(api, world):
    """PRD §3.5: "The checks run in the fixed order of §2.7, which for this operation means: the plan must be `SUBMITTED` (`ERR_INVALID_SHIFT_PLAN_STATE`); the pinned `expected_center_version` must match the center's current `version` (`ERR_STALE_CENTER_VERSION`); the approver's `X-User-ID` must differ from the plan's stored `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); the center must not be `FROZEN` (`ERR_CENTER_FROZEN`); the bodies the plan wants to put on the floor must fit the lines (`ERR_LINE_HEADCOUNT_EXCEEDED`); the flex bench must cover the draw (`ERR_FLEX_POOL_EXHAUSTED`); and the priced shift must fit the budget (`ERR_LABOR_BUDGET_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/line_headcount_safety_beats_labor_budget_at_approve
    """
    built = world.setup_facility(flex_pool_total=20)
    center_id = built["center"]["id"]

    plan = _submitted_plan(
        world,
        center_id,
        planned_core_headcount=30,
        labor_budget_cents=1000,
    )
    assert plan["required_headcount"] == expected_required_headcount(
        4000, 8.00, 70.00, "OPEN", 1
    )
    # One chute, so the whole building takes 22 bodies while the plan wants 30,
    # and the priced shift dwarfs its own 1,000-cent ceiling.
    assert 30 > MAX_LINE_HEADCOUNT * 1
    assert expected_planned_labor_cents(30, 0, 0, 8.00) > 1000

    center_version = world.center_version(center_id)
    response = api.approve_shift_plan(
        plan["id"], f.approve_payload(center_version), OPS_MANAGER_HEADERS
    )
    validate_error(response, ERR_LINE_HEADCOUNT_EXCEEDED)

    plan_after = world.plan(plan["id"])
    assert plan_after["status"] == "SUBMITTED"
    assert plan_after["planned_labor_cents"] == 0
    assert plan_after["flex_draw_count"] == 0
    assert plan_after["approved_by_user_id"] is None

    center_after = world.center(center_id)
    assert center_after["flex_pool_available"] == 20
    assert center_after["flex_pool_reserved"] == 0
    assert center_after["version"] == center_version


def test_labor_budget_failure_surfaces_only_once_the_bodies_fit_the_line(api, world):
    """PRD §3.5: "The line-capacity gate then tests `planned_core_headcount` plus `planned_seasonal_headcount` plus that needed flex against the physical ceiling of 22 associates per line multiplied by the center's line count (chutes whose `status` is `ACTIVE` or `CONGESTED`), refusing the approve with `ERR_LINE_HEADCOUNT_EXCEEDED` when the committed bodies would not fit."

    Design: Difficulty/priority_pair_validation_conflict/line_headcount_safety_beats_labor_budget_at_approve
    """
    built = world.setup_facility(flex_pool_total=20)
    center_id = built["center"]["id"]

    overflowing = _submitted_plan(
        world,
        center_id,
        shift_date="2026-08-01",
        shift_window_start="2026-08-01T00:00:00Z",
        shift_window_end="2026-08-01T08:00:00Z",
        planned_core_headcount=30,
        labor_budget_cents=1000,
    )
    fitting = _submitted_plan(
        world,
        center_id,
        shift_date="2026-08-02",
        shift_window_start="2026-08-02T00:00:00Z",
        shift_window_end="2026-08-02T08:00:00Z",
        planned_core_headcount=MAX_LINE_HEADCOUNT,
        labor_budget_cents=1000,
    )

    # Both plans blow the same 1,000-cent ceiling; only the first also overflows
    # the line, and that is the only difference between the two approvals.
    assert expected_planned_labor_cents(30, 0, 0, 8.00) > 1000
    assert expected_planned_labor_cents(MAX_LINE_HEADCOUNT, 0, 0, 8.00) > 1000

    validate_error(
        api.approve_shift_plan(
            overflowing["id"],
            f.approve_payload(world.center_version(center_id)),
            OPS_MANAGER_HEADERS,
        ),
        ERR_LINE_HEADCOUNT_EXCEEDED,
    )
    validate_error(
        api.approve_shift_plan(
            fitting["id"],
            f.approve_payload(world.center_version(center_id)),
            OPS_MANAGER_HEADERS,
        ),
        ERR_LABOR_BUDGET_EXCEEDED,
    )

    assert world.plan(overflowing["id"])["status"] == "SUBMITTED"
    assert world.plan(fitting["id"])["status"] == "SUBMITTED"
    assert world.plan(fitting["id"])["planned_labor_cents"] == 0


def test_worker_readiness_is_reported_ahead_of_cross_center_integrity_on_assignment(
    api, world
):
    """PRD §3.7: "Readiness must clear: the worker's `status` must be `CLEARED` or `CERTIFIED`, and anything else is refused with `ERR_WORKER_NOT_CLEARED`."

    Design: Difficulty/priority_pair_validation_conflict/worker_readiness_beats_center_mismatch_on_assignment
    """
    home = world.setup_facility()
    home_center_id = home["center"]["id"]
    other_center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)

    plan = world.create_approved_plan(
        home_center_id,
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    assert plan["status"] == "APPROVED"
    assert plan["committed_headcount"] == 4

    foreign_worker = world.create_worker(other_center["id"], hire_class="CORE")
    world.record_event(foreign_worker["id"], "ONBOARDING_STARTED")
    assert world.worker(foreign_worker["id"])["status"] == "ONBOARDING"

    response = api.create_staff_assignment(
        f.staff_assignment_payload(
            plan["id"], foreign_worker["id"], home["chute"]["id"]
        ),
        LABOR_PLANNER_HEADERS,
    )
    validate_error(response, ERR_WORKER_NOT_CLEARED)

    rows, meta = validate_paginated(
        api.list_staff_assignments(LABOR_PLANNER_HEADERS, shift_plan_id=plan["id"])
    )
    assert rows == []
    assert meta["total_count"] == 0

    plan_after = world.plan(plan["id"])
    assert plan_after["status"] == "APPROVED"
    assert plan_after["committed_headcount"] == 4
    assert world.worker(foreign_worker["id"])["status"] == "ONBOARDING"


def test_cross_center_mismatch_surfaces_only_for_the_foreign_worker_who_is_cleared(
    api, world
):
    """PRD §3.7: "Finally, cross-center integrity holds throughout: the worker's `sort_center_id` must equal the plan's `sort_center_id`, and the named line must belong to the same center, with a mismatch refused as `ERR_WORKER_CENTER_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/worker_readiness_beats_center_mismatch_on_assignment
    """
    home = world.setup_facility()
    home_center_id = home["center"]["id"]
    other_center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)

    plan = world.create_approved_plan(
        home_center_id,
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )

    onboarding_worker = world.create_worker(other_center["id"], hire_class="CORE")
    world.record_event(onboarding_worker["id"], "ONBOARDING_STARTED")
    cleared_worker = world.create_cleared_worker(other_center["id"], hire_class="CORE")
    assert world.worker(onboarding_worker["id"])["status"] == "ONBOARDING"
    assert cleared_worker["status"] == "CLEARED"
    assert cleared_worker["sort_center_id"] == other_center["id"]

    # Both workers live at the wrong center; only the unready one hides that fact.
    validate_error(
        api.create_staff_assignment(
            f.staff_assignment_payload(
                plan["id"], onboarding_worker["id"], home["chute"]["id"]
            ),
            LABOR_PLANNER_HEADERS,
        ),
        ERR_WORKER_NOT_CLEARED,
    )
    validate_error(
        api.create_staff_assignment(
            f.staff_assignment_payload(
                plan["id"], cleared_worker["id"], home["chute"]["id"]
            ),
            LABOR_PLANNER_HEADERS,
        ),
        ERR_WORKER_CENTER_MISMATCH,
    )

    rows, meta = validate_paginated(
        api.list_staff_assignments(LABOR_PLANNER_HEADERS, shift_plan_id=plan["id"])
    )
    assert rows == []
    assert meta["total_count"] == 0
