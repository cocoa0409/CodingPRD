"""Non-linear lifecycles: the outbound load's two independent dimensions, the
shift plan's fork out of `SUBMITTED` plus its revision cycle, and the counted
jam cycle that the retry limit bounds.

Every test builds its own world from scratch — the harness relaunches the API
server before each individual test, so the database is empty and the logical
clock sits at its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_JAM_RETRY_LIMIT_REACHED,
    ERR_LOAD_NOT_SEALED,
)
from test_helpers.assertions import expected_lane_pressure_ratio
from test_helpers.test_users import (
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_2_USER_ID,
    OPS_MANAGER_HEADERS,
    OPS_MANAGER_USER_ID,
    TEST_USERS,
)

# ─── The outbound trailer both seal-dimension tests drive ───
TRAILER_CUBE = 3800.00
INDUCTED_PACKAGES = 3000
LOADED_SMALL_PACKAGES = 100
LOADED_CUBE = 33.50
EXCEPTION_PACKAGES = 25

# ─── The shift plan that forks and then goes round the revision cycle ───
FORK_FLEX_POOL_TOTAL = 20
FORK_SHIFT_DATE = "2026-08-03"
FORK_SHIFT_START = "2026-08-03T06:00:00Z"
FORK_SHIFT_END = "2026-08-03T14:00:00Z"
FIRST_FORECAST_VOLUME = 4000
FIRST_CORE = 4
REVISED_FORECAST_VOLUME = 40000
REVISED_CORE = 2
FORK_BUDGET_CENTS = 200000
REJECTION_REASON = "forecast understated for the peak week"

# ─── The jam cycle ───
JAM_RETRY_LIMIT = 3
LANE_FORECAST_HOURLY_VOLUME = 100
CHUTE_THROUGHPUT_PPH = 1200


def _loaded_and_sealed_load(world, facility):
    """One trailer taken to `LOADED` on the loading dimension and to `SEALED` on
    the seal dimension: 3,000 packages inducted, 100 small ones scanned onto the
    trailer, the load closed, then sealed with SEAL-A."""
    center = facility["center"]
    world.induct_packages(
        center["id"], facility["inbound_door"]["id"], INDUCTED_PACKAGES
    )
    load = world.stage_load(
        center["id"],
        facility["outbound_door"]["id"],
        facility["lane"]["id"],
        trailer_cube_cuft=TRAILER_CUBE,
    )
    world.scan(load["id"], small_count=LOADED_SMALL_PACKAGES)
    world.close_load(load["id"])
    return world.seal(load["id"], seal_code="SEAL-A")


def _single_line_center_with_bench(world):
    """A center on the mid automation tier with one commissioned line and a
    twenty-body bench, so the requirement never trips the line-capacity ceiling
    and the bench can always fund the draw."""
    center = world.create_center(
        automation_utilization_pct=70.00, flex_pool_total=FORK_FLEX_POOL_TOTAL
    )
    world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    return center


def _rejected_plan(world, center_id):
    """A plan submitted by the standing labor planner and rejected by the ops
    manager, which is the sibling branch out of `SUBMITTED`."""
    plan = world.create_submitted_plan(
        center_id,
        shift_date=FORK_SHIFT_DATE,
        shift_window_start=FORK_SHIFT_START,
        shift_window_end=FORK_SHIFT_END,
        forecast_volume=FIRST_FORECAST_VOLUME,
        planned_core_headcount=FIRST_CORE,
        planned_seasonal_headcount=0,
        labor_budget_cents=FORK_BUDGET_CENTS,
    )
    assert plan["required_headcount"] == 4, (
        "the first submission sizes the shift at the per-line floor of 4, got "
        f"{plan['required_headcount']}"
    )
    return world.reject_plan(plan["id"], rejection_reason=REJECTION_REASON)


def _appointment_after_jam_cycles(world, facility, cycles: int):
    """An unloading trailer that has been held and resumed `cycles` times, so
    its `jam_count` stands at `cycles` while its status is back to `UNLOADING`."""
    appointment = world.unloading_appointment(
        facility["center"]["id"],
        facility["inbound_door"]["id"],
        manifest_package_count=INDUCTED_PACKAGES,
    )
    chute_id = facility["chute"]["id"]
    for index in range(cycles):
        world.jam_hold(appointment["id"], chute_id, jam_reason=f"BELT_JAM_{index + 1}")
        world.resume_unload(appointment["id"], chute_id)
    return world.appointment(appointment["id"])


def test_exception_breaks_the_seal_and_dispatch_is_rejected_while_load_status_holds(
    world, api, facility
):
    """PRD §3.8: "The seal is broken by the system, not by a request of its own: when a package exception is created naming this load and the load is currently `SEALED`, the seal transitions `SEALED → BROKEN` and `seal_code` returns to null, while `load_status` is untouched — a `LOADED` trailer stays `LOADED` but can no longer leave until it has been re-sealed."

    Design: Difficulty/non_linear_state_machine/outbound_load_parallel_load_and_seal_dimensions
    """
    center = facility["center"]
    load = _loaded_and_sealed_load(world, facility)
    assert load["load_status"] == "LOADED", (
        f"the closed trailer sits at LOADED, got {load['load_status']}"
    )
    assert load["seal_status"] == "SEALED", (
        f"the trailer was sealed with SEAL-A, got {load['seal_status']}"
    )
    assert load["seal_code"] == "SEAL-A", (
        f"expected seal_code SEAL-A, got {load['seal_code']}"
    )

    world.create_exception(
        center["id"],
        exception_type="DAMAGED",
        package_count=EXCEPTION_PACKAGES,
        outbound_load_id=load["id"],
    )

    broken = world.load(load["id"])
    assert broken["seal_status"] == "BROKEN", (
        "an exception naming a sealed load breaks the seal, got "
        f"{broken['seal_status']}"
    )
    assert broken["seal_code"] is None, (
        f"the broken seal's code returns to null, got {broken['seal_code']}"
    )
    assert broken["load_status"] == "LOADED", (
        "the loading dimension is untouched by the seal breaking, got "
        f"{broken['load_status']}"
    )
    assert broken["package_count"] == LOADED_SMALL_PACKAGES, (
        f"no scan happened, got {broken['package_count']}"
    )
    assert float(broken["cube_used_cuft"]) == pytest.approx(LOADED_CUBE, abs=1e-6), (
        f"no scan happened, so the cube stays at 33.50, got {broken['cube_used_cuft']}"
    )

    response = api.dispatch_load(load["id"], OPS_MANAGER_HEADERS)
    validate_error(response, ERR_LOAD_NOT_SEALED)

    still_held = world.load(load["id"])
    assert still_held["load_status"] == "LOADED", (
        f"the refused dispatch leaves the trailer LOADED, got {still_held['load_status']}"
    )
    assert still_held["seal_status"] == "BROKEN", (
        f"the refused dispatch leaves the seal broken, got {still_held['seal_status']}"
    )
    assert still_held["dispatched_at"] is None, (
        f"nothing was dispatched, got {still_held['dispatched_at']}"
    )

    reread = world.center(center["id"])
    assert reread["exception_hold_count"] == EXCEPTION_PACKAGES, (
        f"the batch of 25 sits in exception hold, got {reread['exception_hold_count']}"
    )
    assert reread["wip_package_count"] == (
        INDUCTED_PACKAGES - LOADED_SMALL_PACKAGES - EXCEPTION_PACKAGES
    ), (
        "the exception named no source lane, so it debits work-in-process, got "
        f"{reread['wip_package_count']}"
    )
    world.assert_ledgers(center["id"])


def test_re_sealing_the_broken_trailer_lets_the_same_loaded_load_dispatch(
    world, facility
):
    """PRD §3.8: "Sealing is the other dimension and moves independently: supplying a `seal_code` takes `seal_status` from `UNSEALED → SEALED`, and the same operation takes it from `BROKEN → SEALED` with the new code replacing the old."

    Design: Difficulty/non_linear_state_machine/outbound_load_parallel_load_and_seal_dimensions
    """
    center = facility["center"]
    load = _loaded_and_sealed_load(world, facility)
    world.create_exception(
        center["id"],
        exception_type="DAMAGED",
        package_count=EXCEPTION_PACKAGES,
        outbound_load_id=load["id"],
    )
    assert world.load(load["id"])["seal_status"] == "BROKEN", (
        "the exception must have broken the seal for the re-seal leg to be the one "
        "under test"
    )

    resealed = world.seal(load["id"], seal_code="SEAL-B")
    assert resealed["seal_status"] == "SEALED", (
        f"BROKEN → SEALED is the closing leg of the seal cycle, got {resealed['seal_status']}"
    )
    assert resealed["seal_code"] == "SEAL-B", (
        f"the new code replaces the old, got {resealed['seal_code']}"
    )
    assert resealed["load_status"] == "LOADED", (
        f"sealing never changes the loading dimension, got {resealed['load_status']}"
    )

    dispatched = world.dispatch(load["id"])
    assert dispatched["load_status"] == "DISPATCHED", (
        "the join point reads both dimensions and now passes, got "
        f"{dispatched['load_status']}"
    )
    assert dispatched["seal_status"] == "SEALED", (
        f"the trailer left sealed, got {dispatched['seal_status']}"
    )
    assert dispatched["seal_code"] == "SEAL-B", (
        f"the dispatched trailer carries SEAL-B, got {dispatched['seal_code']}"
    )
    assert dispatched["dispatched_at"].startswith("2026-08-01T00:00:00"), (
        "dispatched_at is stamped from the logical clock, which never moved, got "
        f"{dispatched['dispatched_at']}"
    )
    assert dispatched["package_count"] == LOADED_SMALL_PACKAGES, (
        f"the trailer left with the 100 packages it held, got {dispatched['package_count']}"
    )
    assert world.lane(facility["lane"]["id"])["sorted_package_count"] == (
        LOADED_SMALL_PACKAGES
    ), "leaving the building does not remove the packages from the lane total"


def test_rejection_branch_reserves_no_flex_and_revision_clears_the_failed_round(world):
    """PRD §3.5: "No flex is reserved, `flex_pool_available` and `flex_pool_reserved` are untouched, no cost field is written, and `approved_by_user_id` stays null."
    PRD §3.5: "Revision also clears the traces of the failed round: `rejection_reason` returns to null, `submitted_by_user_id` returns to null (so the next submitter is the one the segregation check will use), and `required_headcount` resets to 0 until the next submission recomputes it."

    Design: Difficulty/non_linear_state_machine/shift_plan_branching_fork_and_revision_cycle
    """
    center = _single_line_center_with_bench(world)
    rejected = _rejected_plan(world, center["id"])

    assert rejected["status"] == "REJECTED", (
        f"the sibling branch out of SUBMITTED is REJECTED, got {rejected['status']}"
    )
    assert rejected["rejection_reason"] == REJECTION_REASON, (
        f"the reason is recorded, got {rejected['rejection_reason']}"
    )
    assert rejected["flex_draw_count"] == 0, (
        f"the rejection branch reserves no flex at all, got {rejected['flex_draw_count']}"
    )
    assert rejected["planned_labor_cents"] == 0, (
        f"no cost field is written on rejection, got {rejected['planned_labor_cents']}"
    )
    assert rejected["approved_by_user_id"] is None, (
        f"approved_by_user_id stays null, got {rejected['approved_by_user_id']}"
    )

    after_reject = world.center(center["id"])
    assert after_reject["flex_pool_available"] == FORK_FLEX_POOL_TOTAL, (
        f"the bench is untouched, got {after_reject['flex_pool_available']}"
    )
    assert after_reject["flex_pool_reserved"] == 0, (
        f"nothing is reserved, got {after_reject['flex_pool_reserved']}"
    )

    revised = world.revise_plan(
        rejected["id"],
        forecast_volume=REVISED_FORECAST_VOLUME,
        planned_core_headcount=REVISED_CORE,
    )
    assert revised["status"] == "DRAFT", (
        f"REJECTED → DRAFT closes the revision cycle, got {revised['status']}"
    )
    assert revised["required_headcount"] == 0, (
        "the requirement resets until the next submission recomputes it, got "
        f"{revised['required_headcount']}"
    )
    assert revised["submitted_by_user_id"] is None, (
        "the submitter identity is cleared so the next submitter is the one the "
        f"segregation check uses, got {revised['submitted_by_user_id']}"
    )
    assert revised["rejection_reason"] is None, (
        f"the rejection reason returns to null, got {revised['rejection_reason']}"
    )
    assert revised["forecast_volume"] == REVISED_FORECAST_VOLUME, (
        f"the restated forecast overwrites the stored one, got {revised['forecast_volume']}"
    )
    assert revised["planned_core_headcount"] == REVISED_CORE, (
        f"the restated core bench overwrites the stored one, got "
        f"{revised['planned_core_headcount']}"
    )
    assert revised["labor_budget_cents"] == FORK_BUDGET_CENTS, (
        f"an omitted value keeps whatever it had, got {revised['labor_budget_cents']}"
    )


def test_second_pass_through_the_fork_takes_the_approval_branch_on_the_revised_forecast(
    world, api
):
    """PRD §3.5: "The full revision cycle is therefore `DRAFT → SUBMITTED → REJECTED → DRAFT`, and a plan may go around it as many times as the planner needs."
    PRD §3.5: "The approval's own side effects then land together: `status` becomes `APPROVED`, `approved_by_user_id` records the approver's `X-User-ID`, `flex_draw_count` is set to the draw, the center's `flex_pool_available` decreases by that draw while `flex_pool_reserved` increases by the same amount, the center's `version` increments by 1, and `committed_headcount` and `staffing_gap` are recomputed."

    Design: Difficulty/non_linear_state_machine/shift_plan_branching_fork_and_revision_cycle
    """
    center = _single_line_center_with_bench(world)
    rejected = _rejected_plan(world, center["id"])
    plan_id = rejected["id"]

    # The center version read after the rejection is still the current one when
    # the approve lands, because neither the rejection nor the revision touches
    # the center.
    center_version_after_reject = world.center_version(center["id"])

    world.revise_plan(
        plan_id,
        forecast_volume=REVISED_FORECAST_VOLUME,
        planned_core_headcount=REVISED_CORE,
    )

    resubmitted = validate_success(
        api.submit_shift_plan(plan_id, TEST_USERS["labor_planner_2"])
    )
    assert resubmitted["status"] == "SUBMITTED", (
        f"the revised draft goes round the fork again, got {resubmitted['status']}"
    )
    assert resubmitted["required_headcount"] == 6, (
        "40,000 packages over 950 packages per associate-hour and 8.00 hours ceils to "
        f"6 associates, recomputed from the revised forecast, got "
        f"{resubmitted['required_headcount']}"
    )
    assert resubmitted["submitted_by_user_id"] == LABOR_PLANNER_2_USER_ID, (
        "the second submitter is the identity the segregation check now uses, got "
        f"{resubmitted['submitted_by_user_id']}"
    )

    approved = validate_success(
        api.approve_shift_plan(
            plan_id,
            f.approve_payload(center_version_after_reject),
            OPS_MANAGER_HEADERS,
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the second pass takes the other branch out of SUBMITTED, got {approved['status']}"
    )
    assert approved["approved_by_user_id"] == OPS_MANAGER_USER_ID, (
        f"the approver's identity is recorded, got {approved['approved_by_user_id']}"
    )
    assert approved["flex_draw_count"] == 4, (
        "6 required less 2 core and 0 seasonal draws 4 bodies from the bench, got "
        f"{approved['flex_draw_count']}"
    )
    assert approved["planned_labor_cents"] == 127411, (
        "a base of 34,400 + 79,360 = 113,760 cents at a flex ratio of 4/6 attracts "
        f"the 12 percent tier, got {approved['planned_labor_cents']}"
    )
    assert float(approved["provisional_cost_per_package_cents"]) == pytest.approx(
        3.49, abs=1e-6
    ), (
        "(127,411 + 12,000) / 40,000 is 3.49 cents per package, got "
        f"{approved['provisional_cost_per_package_cents']}"
    )
    assert approved["committed_headcount"] == 6, (
        f"2 core plus a draw of 4 is committed, got {approved['committed_headcount']}"
    )
    assert approved["staffing_gap"] == 0, (
        f"the requirement is fully covered, got {approved['staffing_gap']}"
    )

    after_approve = world.center(center["id"])
    assert after_approve["flex_pool_available"] == FORK_FLEX_POOL_TOTAL - 4, (
        f"the bench gives up 4 bodies, got {after_approve['flex_pool_available']}"
    )
    assert after_approve["flex_pool_reserved"] == 4, (
        f"the draw is reserved against the plan, got {after_approve['flex_pool_reserved']}"
    )
    assert after_approve["version"] == center_version_after_reject + 1, (
        "only the approval touched the center, so its version moved exactly once, "
        f"got {after_approve['version']}"
    )
    world.assert_ledgers(center["id"])


def test_fourth_jam_hold_rejected_after_three_cycles_leave_the_retry_counter_spent(
    world, api, facility
):
    """PRD §3.3: "A fourth jam on the same appointment is refused with `ERR_JAM_RETRY_LIMIT_REACHED` — the line has proven it cannot run and needs engineering, not another retry."

    Design: Difficulty/non_linear_state_machine/trailer_jam_cycle_bounded_by_retry_limit
    """
    center = facility["center"]
    chute_id = facility["chute"]["id"]
    lane_id = facility["lane"]["id"]
    appointment = _appointment_after_jam_cycles(world, facility, JAM_RETRY_LIMIT)

    assert appointment["status"] == "UNLOADING", (
        f"the third resume put the trailer back on the line, got {appointment['status']}"
    )
    assert appointment["jam_count"] == JAM_RETRY_LIMIT, (
        "the three resumes did not decrement the retry counter, got "
        f"{appointment['jam_count']}"
    )
    assert world.chute(chute_id)["status"] == "ACTIVE", "the line was cleared each time"
    assert world.chute(chute_id)["jam_hold_count"] == JAM_RETRY_LIMIT, (
        "the chute's cumulative hold count also never rolls back, got "
        f"{world.chute(chute_id)['jam_hold_count']}"
    )
    before = world.center(center["id"])
    assert before["open_jam_count"] == 0, (
        f"no jam is held right now, got {before['open_jam_count']}"
    )
    assert before["ops_posture"] == "OPEN", (
        "only one appointment was ever held at a time, so the building never froze, "
        f"got {before['ops_posture']}"
    )

    response = api.jam_hold(
        appointment["id"],
        f.jam_hold_payload(chute_id, jam_reason="BELT_JAM_4"),
        INBOUND_COORDINATOR_HEADERS,
    )
    validate_error(response, ERR_JAM_RETRY_LIMIT_REACHED)

    unchanged = world.appointment(appointment["id"])
    assert unchanged["status"] == "UNLOADING", (
        f"the refused hold changes no state, got {unchanged['status']}"
    )
    assert unchanged["jam_count"] == JAM_RETRY_LIMIT, (
        f"the refused hold does not count, got {unchanged['jam_count']}"
    )
    chute = world.chute(chute_id)
    assert chute["status"] == "ACTIVE", (
        f"the line was never congested by the refused hold, got {chute['status']}"
    )
    assert chute["jam_hold_count"] == JAM_RETRY_LIMIT, (
        f"the refused hold does not count on the chute either, got {chute['jam_hold_count']}"
    )
    assert world.assignment(facility["assignment"]["id"])["status"] == "ACTIVE", (
        "the refused hold suspended nothing"
    )
    lane = world.lane(lane_id)
    assert lane["backlog_package_count"] == 0, (
        f"each cycle restored the backlog exactly, got {lane['backlog_package_count']}"
    )
    assert float(lane["lane_pressure_ratio"]) == pytest.approx(
        expected_lane_pressure_ratio(0, CHUTE_THROUGHPUT_PPH), abs=1e-6
    ), f"a quiet lane sits at 0.0000, got {lane['lane_pressure_ratio']}"

    completed = validate_success(
        api.complete_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert completed["status"] == "UNLOADED", (
        "a trailer with a spent retry counter can still finish, got "
        f"{completed['status']}"
    )
    after = world.center(center["id"])
    assert after["wip_package_count"] == INDUCTED_PACKAGES, (
        f"the manifest was inducted, got {after['wip_package_count']}"
    )
    assert after["packages_inducted_count"] == INDUCTED_PACKAGES, (
        f"the manifest was inducted, got {after['packages_inducted_count']}"
    )


def test_third_jam_hold_is_accepted_and_its_resume_leaves_the_jam_count_at_three(
    world, facility
):
    """PRD §3.3: "The appointment returns `JAM_HELD → UNLOADING`, but `jam_count` is deliberately **not** decremented — it is a retry counter, not a gauge, so three holds and three resumes still exhaust the retry limit."

    Design: Difficulty/non_linear_state_machine/trailer_jam_cycle_bounded_by_retry_limit
    """
    center = facility["center"]
    chute_id = facility["chute"]["id"]
    lane_id = facility["lane"]["id"]
    assignment_id = facility["assignment"]["id"]
    appointment = _appointment_after_jam_cycles(world, facility, 2)
    assert appointment["jam_count"] == 2, (
        f"two cycles leave the counter at 2, got {appointment['jam_count']}"
    )

    held = world.jam_hold(appointment["id"], chute_id, jam_reason="BELT_JAM_3")
    assert held["status"] == "JAM_HELD", (
        f"the third hold is still under the limit, got {held['status']}"
    )
    assert held["jam_count"] == JAM_RETRY_LIMIT, (
        f"the third hold takes the counter to 3, got {held['jam_count']}"
    )
    held_chute = world.chute(chute_id)
    assert held_chute["status"] == "CONGESTED", (
        f"the named line flips ACTIVE → CONGESTED, got {held_chute['status']}"
    )
    assert held_chute["jam_hold_count"] == JAM_RETRY_LIMIT, (
        f"the chute has now been held three times, got {held_chute['jam_hold_count']}"
    )
    held_assignment = world.assignment(assignment_id)
    assert held_assignment["status"] == "SUSPENDED", (
        f"the active mapping on that line is suspended, got {held_assignment['status']}"
    )
    assert held_assignment["suspended_reason"] == "BELT_JAM_3", (
        f"the suspension records the jam reason, got {held_assignment['suspended_reason']}"
    )
    held_lane = world.lane(lane_id)
    assert held_lane["backlog_package_count"] == LANE_FORECAST_HOURLY_VOLUME, (
        "the lane absorbs one hour of its own forecast volume, got "
        f"{held_lane['backlog_package_count']}"
    )
    assert held_lane["assigned_capacity_pph"] == 0, (
        "a suspended assignment contributes no capacity, got "
        f"{held_lane['assigned_capacity_pph']}"
    )
    assert float(held_lane["lane_pressure_ratio"]) == pytest.approx(
        expected_lane_pressure_ratio(LANE_FORECAST_HOURLY_VOLUME, 0), abs=1e-6
    ), (
        "100 over a divisor floored at 1 is 100.0000, got "
        f"{held_lane['lane_pressure_ratio']}"
    )
    held_center = world.center(center["id"])
    assert held_center["open_jam_count"] == 1, (
        f"one appointment is held, got {held_center['open_jam_count']}"
    )
    assert held_center["ops_posture"] == "RESTRICTED", (
        "one held jam and a peak lane pressure above 1.50 restricts the building "
        f"without freezing it, got {held_center['ops_posture']}"
    )

    resumed = world.resume_unload(appointment["id"], chute_id)
    assert resumed["status"] == "UNLOADING", (
        f"JAM_HELD → UNLOADING is the compensating transition, got {resumed['status']}"
    )
    assert resumed["jam_count"] == JAM_RETRY_LIMIT, (
        "the retry counter is deliberately not decremented by the resume, got "
        f"{resumed['jam_count']}"
    )
    resumed_chute = world.chute(chute_id)
    assert resumed_chute["status"] == "ACTIVE", (
        f"the line flips CONGESTED → ACTIVE, got {resumed_chute['status']}"
    )
    assert resumed_chute["jam_hold_count"] == JAM_RETRY_LIMIT, (
        "the cumulative hold count is never rolled back either, got "
        f"{resumed_chute['jam_hold_count']}"
    )
    resumed_assignment = world.assignment(assignment_id)
    assert resumed_assignment["status"] == "ACTIVE", (
        f"the mapping returns SUSPENDED → ACTIVE, got {resumed_assignment['status']}"
    )
    assert resumed_assignment["suspended_reason"] is None, (
        f"the suspension reason returns to null, got {resumed_assignment['suspended_reason']}"
    )
    resumed_lane = world.lane(lane_id)
    assert resumed_lane["backlog_package_count"] == 0, (
        f"the backlog is reduced by the same hour of volume, got "
        f"{resumed_lane['backlog_package_count']}"
    )
    assert resumed_lane["assigned_capacity_pph"] == CHUTE_THROUGHPUT_PPH, (
        f"the restored assignment contributes its rated throughput, got "
        f"{resumed_lane['assigned_capacity_pph']}"
    )
    assert float(resumed_lane["lane_pressure_ratio"]) == pytest.approx(
        expected_lane_pressure_ratio(0, CHUTE_THROUGHPUT_PPH), abs=1e-6
    ), f"the lane is quiet again at 0.0000, got {resumed_lane['lane_pressure_ratio']}"
    resumed_center = world.center(center["id"])
    assert resumed_center["open_jam_count"] == 0, (
        f"no jam is held any more, got {resumed_center['open_jam_count']}"
    )
    assert resumed_center["ops_posture"] == "OPEN", (
        f"the building reopens, got {resumed_center['ops_posture']}"
    )
