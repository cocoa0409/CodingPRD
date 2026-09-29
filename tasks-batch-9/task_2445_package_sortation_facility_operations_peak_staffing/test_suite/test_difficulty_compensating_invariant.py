"""Three conserved quantities and the forward/compensating action pair that must
leave each of them exactly as it was: physical packages across a mis-sort and its
reroute, flex headcount across a plan's approval and its closure, and lane
backlog and capacity across a jam hold and its resume.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_APPOINTMENT_STATE,
    ERR_STALE_CENTER_VERSION,
)
from test_helpers.assertions import (
    assert_flex_pool_conservation,
    assert_package_conservation,
    expected_batch_cube,
    expected_final_cost_per_package,
    expected_lane_pressure_ratio,
)
from test_helpers.constants import CLOCK_STARTUP_UTC
from test_helpers.fixtures import parse_instant
from test_helpers.test_users import (
    INBOUND_COORDINATOR_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)


# ─── Conserved quantity 1: physical packages ──────────

INDUCTED = 3000
SCANNED_SMALL = 2400
MISSORT_BATCH = 40


def _center_with_packages_sorted_into_one_lane(world, facility):
    """Three thousand packages inducted and 2,400 of them scanned onto a trailer
    bound for the first lane, with a second mapped lane standing by as a reroute
    target."""
    center_id = facility["center"]["id"]
    lane_west = facility["lane"]
    lane_east = world.create_lane(
        center_id, forecast_hourly_volume=1200, service_class="EXPRESS"
    )
    world.map_lane_to_chute(facility["chute"]["id"], lane_east["id"])

    world.induct_packages(center_id, facility["inbound_door"]["id"], INDUCTED)
    load = world.stage_load(
        center_id,
        facility["outbound_door"]["id"],
        lane_west["id"],
        trailer_cube_cuft=1000.00,
    )
    load = world.scan(load["id"], small_count=SCANNED_SMALL)
    return {"lane_west": lane_west, "lane_east": lane_east, "load": load}


def _open_missort_batch(world, center_id, lane_id):
    return world.create_exception(
        center_id,
        exception_type="MISSORT",
        package_count=MISSORT_BATCH,
        from_destination_lane_id=lane_id,
    )


def test_missort_exception_debits_its_source_lane_and_keeps_the_identity(
    world, facility
):
    """PRD §2.8: "After every request that moves packages, the center's `packages_inducted_count` must equal the sum of its `wip_package_count`, its `exception_hold_count`, its `disposed_package_count`, and the total `sorted_package_count` across *all* destination lanes of that center regardless of lane status (a closed lane still holds the packages already sorted into it)."

    Design: Difficulty/compensating_invariant/package_conservation_across_missort_and_reroute
    """
    built = _center_with_packages_sorted_into_one_lane(world, facility)
    center_id = facility["center"]["id"]

    before = world.center(center_id)
    assert before["packages_inducted_count"] == INDUCTED
    assert before["wip_package_count"] == INDUCTED - SCANNED_SMALL
    assert before["exception_hold_count"] == 0
    assert before["disposed_package_count"] == 0
    assert world.lane(built["lane_west"]["id"])["sorted_package_count"] == SCANNED_SMALL
    assert_package_conservation(before, world.all_lanes(center_id))

    exception = _open_missort_batch(world, center_id, built["lane_west"]["id"])
    assert exception["status"] == "OPEN"
    assert exception["package_count"] == MISSORT_BATCH

    after = world.center(center_id)
    assert after["packages_inducted_count"] == INDUCTED
    assert after["wip_package_count"] == INDUCTED - SCANNED_SMALL
    assert after["exception_hold_count"] == MISSORT_BATCH
    assert after["disposed_package_count"] == 0
    assert after["missort_corrected_count"] == 0
    assert (
        world.lane(built["lane_west"]["id"])["sorted_package_count"]
        == SCANNED_SMALL - MISSORT_BATCH
    )
    assert_package_conservation(after, world.all_lanes(center_id))


def test_reroute_resolution_compensates_the_missort_without_moving_the_total(
    world, api, facility
):
    """PRD §2.8: "Note that `missort_corrected_count` is an audit tally of re-laned packages and does not participate in the identity, and that a mis-sort exception followed by a reroute resolution is a forward action and its compensating action: together they leave the identity exactly as it was."

    Design: Difficulty/compensating_invariant/package_conservation_across_missort_and_reroute
    """
    built = _center_with_packages_sorted_into_one_lane(world, facility)
    center_id = facility["center"]["id"]
    exception = _open_missort_batch(world, center_id, built["lane_west"]["id"])

    resolved = validate_success(
        api.resolve_package_exception(
            exception["id"],
            f.resolve_exception_payload(
                "REROUTE", to_destination_lane_id=built["lane_east"]["id"]
            ),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REROUTE"
    assert resolved["resolved_via_chute_id"] == facility["chute"]["id"]
    assert parse_instant(resolved["resolved_at"]) == parse_instant(CLOCK_STARTUP_UTC)

    center = world.center(center_id)
    assert center["packages_inducted_count"] == INDUCTED
    assert center["wip_package_count"] == INDUCTED - SCANNED_SMALL
    assert center["exception_hold_count"] == 0
    assert center["disposed_package_count"] == 0
    assert center["missort_corrected_count"] == MISSORT_BATCH
    assert (
        world.lane(built["lane_west"]["id"])["sorted_package_count"]
        == SCANNED_SMALL - MISSORT_BATCH
    )
    assert world.lane(built["lane_east"]["id"])["sorted_package_count"] == MISSORT_BATCH
    assert_package_conservation(center, world.all_lanes(center_id))

    untouched_trailer = world.load(built["load"]["id"])
    assert untouched_trailer["package_count"] == SCANNED_SMALL
    assert float(untouched_trailer["cube_used_cuft"]) == expected_batch_cube(
        small=SCANNED_SMALL
    )


# ─── Conserved quantity 2: flex headcount ─────────────

FLEX_TOTAL = 20
EXPECTED_DRAW = 3


def _submitted_plan_needing_three_flex_bodies(world):
    """A one-line center with a twenty-body bench and a submitted plan whose
    four-associate requirement leaves three bodies to draw from the bench."""
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=FLEX_TOTAL)
    world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    plan = world.create_submitted_plan(
        center["id"],
        forecast_volume=4000,
        planned_core_headcount=0,
        planned_seasonal_headcount=1,
        labor_budget_cents=100000,
    )
    assert plan["status"] == "SUBMITTED"
    assert plan["required_headcount"] == 4
    return center, plan


def test_plan_approval_reserves_exactly_the_draw_it_sized(world):
    """PRD §2.8: "Furthermore, `flex_pool_reserved` must equal the sum of `flex_draw_count` across the center's shift plans whose `status` is `APPROVED` or `AT_RISK`; plans in `DRAFT`, `SUBMITTED`, `REJECTED` or `CLOSED` hold no reservation at all."

    Design: Difficulty/compensating_invariant/flex_pool_conservation_across_approve_and_close
    """
    center, plan = _submitted_plan_needing_three_flex_bodies(world)

    before = world.center(center["id"])
    assert before["flex_pool_available"] == FLEX_TOTAL
    assert before["flex_pool_reserved"] == 0

    approved = world.approve_plan(plan["id"], center["id"])
    assert approved["status"] == "APPROVED"
    assert approved["flex_draw_count"] == EXPECTED_DRAW

    after = world.center(center["id"])
    assert after["flex_pool_total"] == FLEX_TOTAL
    assert after["flex_pool_available"] == FLEX_TOTAL - EXPECTED_DRAW
    assert after["flex_pool_reserved"] == EXPECTED_DRAW
    assert_flex_pool_conservation(after, world.all_plans(center["id"]))


def test_plan_closure_releases_the_same_headcount_the_approval_drew(world):
    """PRD §2.8: "Approval reserves the plan's draw, a no-show top-up reserves an additional amount, and closure releases exactly the plan's accumulated `flex_draw_count` back to `flex_pool_available`."

    Design: Difficulty/compensating_invariant/flex_pool_conservation_across_approve_and_close
    """
    center, plan = _submitted_plan_needing_three_flex_bodies(world)
    world.approve_plan(plan["id"], center["id"])

    closed = world.close_plan(plan["id"], center["id"])
    assert closed["status"] == "CLOSED"
    assert closed["flex_draw_count"] == EXPECTED_DRAW
    assert closed["actual_labor_cents"] == 0
    assert float(closed["final_cost_per_package_cents"]) == expected_final_cost_per_package(
        0, 0, 0
    )

    after = world.center(center["id"])
    assert after["flex_pool_total"] == FLEX_TOTAL
    assert after["flex_pool_available"] == FLEX_TOTAL
    assert after["flex_pool_reserved"] == 0
    assert_flex_pool_conservation(after, world.all_plans(center["id"]))


def test_close_pinning_the_pre_approval_center_version_is_rejected(world, api):
    """PRD §2.6: "A mismatch against the center's current `version` is rejected with `ERR_STALE_CENTER_VERSION` (HTTP 412)."

    Design: Difficulty/compensating_invariant/flex_pool_conservation_across_approve_and_close
    """
    center, plan = _submitted_plan_needing_three_flex_bodies(world)
    version_before_approve = world.center_version(center["id"])
    world.approve_plan(plan["id"], center["id"])
    assert world.center_version(center["id"]) != version_before_approve

    response = api.close_shift_plan(
        plan["id"],
        f.close_plan_payload(version_before_approve),
        OPS_MANAGER_HEADERS,
    )
    validate_error(response, ERR_STALE_CENTER_VERSION)

    assert world.plan(plan["id"])["status"] == "APPROVED"
    unmoved = world.center(center["id"])
    assert unmoved["flex_pool_available"] == FLEX_TOTAL - EXPECTED_DRAW
    assert unmoved["flex_pool_reserved"] == EXPECTED_DRAW
    assert_flex_pool_conservation(unmoved, world.all_plans(center["id"]))


# ─── Conserved quantity 3: lane backlog and capacity ──

LANE_FORECAST = 3000
CHUTE_PPH = 1200
JAM_REASON = "PRIMARY_BELT_JAM"


def _jam_held_trailer_on_a_high_forecast_lane(world):
    """One chute rated 1,200 packages per hour serving a lane forecast at 3,000 an
    hour, with an unloading trailer jam-held on that chute."""
    built = world.setup_facility(
        throughput_pph=CHUTE_PPH, forecast_hourly_volume=LANE_FORECAST
    )
    center_id = built["center"]["id"]
    lane_before = world.lane(built["lane"]["id"])
    assert lane_before["backlog_package_count"] == 0
    assert lane_before["assigned_capacity_pph"] == CHUTE_PPH
    assert float(lane_before["lane_pressure_ratio"]) == 0.0

    appointment = world.unloading_appointment(
        center_id, built["inbound_door"]["id"], manifest_package_count=3000
    )
    held = world.jam_hold(appointment["id"], built["chute"]["id"], jam_reason=JAM_REASON)
    assert held["status"] == "JAM_HELD"
    built["appointment"] = held
    return built


def test_jam_hold_loads_the_lane_backlog_with_one_hour_of_forecast(world):
    """PRD §3.3: "Caused by the third link, each destination lane that lost an assignment absorbs one hour of unsorted volume: the lane's `backlog_package_count` increases by that lane's own `forecast_hourly_volume`, its `assigned_capacity_pph` is recomputed over the assignments that remain `ACTIVE`, and its `lane_pressure_ratio` is recomputed from the new backlog and capacity."

    Design: Difficulty/compensating_invariant/jam_resume_restores_lane_backlog_and_capacity_exactly
    """
    built = _jam_held_trailer_on_a_high_forecast_lane(world)

    lane = world.lane(built["lane"]["id"])
    assert lane["backlog_package_count"] == LANE_FORECAST
    assert lane["assigned_capacity_pph"] == 0
    assert float(lane["lane_pressure_ratio"]) == expected_lane_pressure_ratio(
        LANE_FORECAST, 0
    )

    suspended = world.assignment(built["assignment"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspended_reason"] == JAM_REASON

    chute = world.chute(built["chute"]["id"])
    assert chute["status"] == "CONGESTED"
    assert chute["jam_hold_count"] == 1

    center = world.center(built["center"]["id"])
    assert center["open_jam_count"] == 1
    assert center["ops_posture"] == "RESTRICTED"
    assert world.appointment(built["appointment"]["id"])["jam_count"] == 1


def test_resume_unload_restores_the_lane_backlog_capacity_and_pressure(world):
    """PRD §3.3: "The named chute flips `CONGESTED → ACTIVE` and its `version` increments; every assignment on that chute whose `status` is `SUSPENDED` transitions `SUSPENDED → ACTIVE` and its `suspended_reason` returns to null; each affected lane's `backlog_package_count` is reduced by that lane's `forecast_hourly_volume` with a floor of 0 so the backlog can never go negative, and its capacity and pressure are recomputed; and finally the center's `open_jam_count` and `ops_posture` are recomputed and its `version` increments."

    Design: Difficulty/compensating_invariant/jam_resume_restores_lane_backlog_and_capacity_exactly
    """
    built = _jam_held_trailer_on_a_high_forecast_lane(world)

    resumed = world.resume_unload(built["appointment"]["id"], built["chute"]["id"])
    assert resumed["status"] == "UNLOADING"

    lane = world.lane(built["lane"]["id"])
    assert lane["backlog_package_count"] == 0
    assert lane["assigned_capacity_pph"] == CHUTE_PPH
    assert float(lane["lane_pressure_ratio"]) == expected_lane_pressure_ratio(
        0, CHUTE_PPH
    )

    revived = world.assignment(built["assignment"]["id"])
    assert revived["status"] == "ACTIVE"
    assert revived["suspended_reason"] is None
    assert world.chute(built["chute"]["id"])["status"] == "ACTIVE"

    center = world.center(built["center"]["id"])
    assert center["open_jam_count"] == 0
    assert center["ops_posture"] == "OPEN"


def test_second_resume_unload_rejected_and_the_retry_counters_never_roll_back(
    world, api
):
    """PRD §3.3: "The appointment returns `JAM_HELD → UNLOADING`, but `jam_count` is deliberately **not** decremented — it is a retry counter, not a gauge, so three holds and three resumes still exhaust the retry limit."

    Design: Difficulty/compensating_invariant/jam_resume_restores_lane_backlog_and_capacity_exactly
    """
    built = _jam_held_trailer_on_a_high_forecast_lane(world)
    world.resume_unload(built["appointment"]["id"], built["chute"]["id"])

    assert world.appointment(built["appointment"]["id"])["jam_count"] == 1
    assert world.chute(built["chute"]["id"])["jam_hold_count"] == 1

    response = api.resume_unload(
        built["appointment"]["id"],
        f.resume_unload_payload(built["chute"]["id"]),
        INBOUND_COORDINATOR_HEADERS,
    )
    validate_error(response, ERR_INVALID_APPOINTMENT_STATE)

    lane = world.lane(built["lane"]["id"])
    assert lane["backlog_package_count"] == 0
    assert lane["assigned_capacity_pph"] == CHUTE_PPH
    assert world.appointment(built["appointment"]["id"])["jam_count"] == 1
    assert world.chute(built["chute"]["id"])["jam_hold_count"] == 1
