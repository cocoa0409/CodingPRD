"""Deep in-request cascades: the jam hold that reaches four levels below the
appointment (PRD §3.3) and the no-show that reaches from an assignment into the
center's flex pool and back into the plan's status (PRD §3.7).
"""

from test_helpers.assertions import expected_lane_pressure_ratio, expected_required_headcount

JAM_CLOCK = "2026-08-01T06:00:00Z"
JAM_REASON = "PRIMARY_BELT_JAM"

WEST_FORECAST_HOURLY_VOLUME = 3000
EAST_FORECAST_HOURLY_VOLUME = 1200
CHUTE_THROUGHPUT_PPH = 1200


def _two_lanes_on_one_jammable_chute(world):
    """A center whose single chute serves two destination lanes at once, with one
    trailer already `UNLOADING` on the inbound door.

    Both lanes hold an `ACTIVE` mapping on the same chute, so the fan-out of a
    jam hold onto the assignment set and onto the lanes is observable twice.
    """
    world.set_clock(JAM_CLOCK)
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    chute = world.create_chute(
        center["id"],
        chute_number=1,
        throughput_pph=CHUTE_THROUGHPUT_PPH,
        max_concurrent_destinations=2,
    )
    lane_west = world.create_lane(
        center["id"], region="WEST", service_class="GROUND",
        forecast_hourly_volume=WEST_FORECAST_HOURLY_VOLUME,
    )
    lane_east = world.create_lane(
        center["id"], region="EAST", service_class="EXPRESS",
        forecast_hourly_volume=EAST_FORECAST_HOURLY_VOLUME,
    )
    assignment_west = world.map_lane_to_chute(chute["id"], lane_west["id"])
    assignment_east = world.map_lane_to_chute(chute["id"], lane_east["id"])
    appointment = world.unloading_appointment(
        center["id"], door["id"], manifest_package_count=3000
    )
    return {
        "center": center,
        "chute": chute,
        "lane_west": lane_west,
        "lane_east": lane_east,
        "assignment_west": assignment_west,
        "assignment_east": assignment_east,
        "appointment": appointment,
    }


def _approved_plan_with_one_assigned_worker(world):
    """A thin bench (three bodies), an `APPROVED` plan whose own core headcount
    already covers its requirement, and one `CLEARED` worker sitting on the line
    in `ASSIGNED`."""
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=3)
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    plan = world.create_approved_plan(
        center["id"],
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    worker = world.create_cleared_worker(
        center["id"], hire_class="CORE", hire_date="2026-08-01"
    )
    assignment = world.create_assignment(plan["id"], worker["id"], chute["id"])
    return {
        "center": center,
        "chute": chute,
        "plan": plan,
        "worker": worker,
        "assignment": assignment,
    }


def test_jam_hold_cascades_from_appointment_through_chute_and_lanes_into_center_posture(world):
    """PRD §2.10: "A jam hold reaches four levels deep — appointment, chute, chute assignments, destination lanes, and finally the center's posture — and a no-show reaches from an assignment through its plan's headcount into the center's flex pool and back into the plan's status."

    Design: Difficulty/transitive_cascade/jam_hold_depth4_cascade_to_center_posture
    """
    built = _two_lanes_on_one_jammable_chute(world)
    center_id = built["center"]["id"]
    chute_id = built["chute"]["id"]
    west_id = built["lane_west"]["id"]
    east_id = built["lane_east"]["id"]

    before_center = world.center(center_id)
    assert before_center["ops_posture"] == "OPEN"
    assert before_center["open_jam_count"] == 0
    assert before_center["last_posture_change_at"] is None
    center_version_before = before_center["version"]
    chute_version_before = world.chute(chute_id)["version"]
    for lane_id in (west_id, east_id):
        lane_before = world.lane(lane_id)
        assert lane_before["assigned_capacity_pph"] == CHUTE_THROUGHPUT_PPH
        assert lane_before["backlog_package_count"] == 0
        assert float(lane_before["lane_pressure_ratio"]) == 0.0

    held = world.jam_hold(
        built["appointment"]["id"], chute_id, jam_reason=JAM_REASON
    )

    # Level 1: the appointment itself.
    assert held["status"] == "JAM_HELD"
    assert held["jam_count"] == 1

    # Level 2: the named chute.
    chute_after = world.chute(chute_id)
    assert chute_after["status"] == "CONGESTED"
    assert chute_after["jam_hold_count"] == 1
    assert chute_after["version"] == chute_version_before + 1

    # Level 3: every ACTIVE mapping on that chute.
    for assignment in (built["assignment_west"], built["assignment_east"]):
        row = world.assignment(assignment["id"])
        assert row["status"] == "SUSPENDED"
        assert row["suspended_reason"] == JAM_REASON

    # Level 4: each lane that lost its assignment.
    west_after = world.lane(west_id)
    assert west_after["backlog_package_count"] == WEST_FORECAST_HOURLY_VOLUME
    assert west_after["assigned_capacity_pph"] == 0
    assert float(west_after["lane_pressure_ratio"]) == expected_lane_pressure_ratio(
        WEST_FORECAST_HOURLY_VOLUME, 0
    )
    east_after = world.lane(east_id)
    assert east_after["backlog_package_count"] == EAST_FORECAST_HOURLY_VOLUME
    assert east_after["assigned_capacity_pph"] == 0
    assert float(east_after["lane_pressure_ratio"]) == expected_lane_pressure_ratio(
        EAST_FORECAST_HOURLY_VOLUME, 0
    )

    # Level 5: the center's derived jam counter and posture.
    center_after = world.center(center_id)
    assert center_after["open_jam_count"] == 1
    assert center_after["ops_posture"] == "RESTRICTED"
    assert center_after["version"] == center_version_before + 1
    assert center_after["last_posture_change_at"].startswith("2026-08-01T06:00:00")


def test_resume_unload_compensates_the_jam_cascade_without_rolling_back_the_retry_counter(world):
    """PRD §3.3: "The named chute flips `CONGESTED → ACTIVE` and its `version` increments; every assignment on that chute whose `status` is `SUSPENDED` transitions `SUSPENDED → ACTIVE` and its `suspended_reason` returns to null; each affected lane's `backlog_package_count` is reduced by that lane's `forecast_hourly_volume` with a floor of 0 so the backlog can never go negative, and its capacity and pressure are recomputed; and finally the center's `open_jam_count` and `ops_posture` are recomputed and its `version` increments."

    Design: Difficulty/transitive_cascade/jam_hold_depth4_cascade_to_center_posture
    """
    built = _two_lanes_on_one_jammable_chute(world)
    center_id = built["center"]["id"]
    chute_id = built["chute"]["id"]
    west_id = built["lane_west"]["id"]
    east_id = built["lane_east"]["id"]

    world.jam_hold(built["appointment"]["id"], chute_id, jam_reason=JAM_REASON)
    assert world.center(center_id)["ops_posture"] == "RESTRICTED"
    chute_version_held = world.chute(chute_id)["version"]
    center_version_held = world.center(center_id)["version"]

    resumed = world.resume_unload(built["appointment"]["id"], chute_id)

    assert resumed["status"] == "UNLOADING"
    assert resumed["jam_count"] == 1

    chute_after = world.chute(chute_id)
    assert chute_after["status"] == "ACTIVE"
    assert chute_after["jam_hold_count"] == 1
    assert chute_after["version"] == chute_version_held + 1

    for assignment in (built["assignment_west"], built["assignment_east"]):
        row = world.assignment(assignment["id"])
        assert row["status"] == "ACTIVE"
        assert row["suspended_reason"] is None

    for lane_id in (west_id, east_id):
        lane_after = world.lane(lane_id)
        assert lane_after["backlog_package_count"] == 0
        assert lane_after["assigned_capacity_pph"] == CHUTE_THROUGHPUT_PPH
        assert float(lane_after["lane_pressure_ratio"]) == expected_lane_pressure_ratio(
            0, CHUTE_THROUGHPUT_PPH
        )

    center_after = world.center(center_id)
    assert center_after["open_jam_count"] == 0
    assert center_after["ops_posture"] == "OPEN"
    assert center_after["version"] == center_version_held + 1


def test_no_show_cascade_returns_the_plan_to_approved_after_the_flex_topup(world):
    """PRD §3.7: "Caused by the fifth link, a plan whose `staffing_gap` has returned to 0 after the top-up transitions `AT_RISK → APPROVED`, and `unfilled_gap` is set to 0."

    Design: Difficulty/transitive_cascade/no_show_cascade_flex_topup_returns_plan_to_approved
    """
    built = _approved_plan_with_one_assigned_worker(world)
    plan_id = built["plan"]["id"]

    before_plan = world.plan(plan_id)
    assert before_plan["status"] == "APPROVED"
    assert before_plan["required_headcount"] == expected_required_headcount(
        4000, 8.00, 70.00, "OPEN", 1
    )
    assert before_plan["required_headcount"] == 4
    assert before_plan["flex_draw_count"] == 0
    assert before_plan["committed_headcount"] == 4
    assert before_plan["staffing_gap"] == 0
    assert before_plan["unfilled_gap"] == 0

    marked = world.no_show(built["assignment"]["id"])
    assert marked["status"] == "NO_SHOW"

    after_plan = world.plan(plan_id)
    assert after_plan["status"] == "APPROVED"
    assert after_plan["committed_headcount"] == 4
    assert after_plan["staffing_gap"] == 0
    assert after_plan["unfilled_gap"] == 0


def test_no_show_topup_moves_bench_headcount_into_the_center_reservation(world):
    """PRD §3.7: "Caused by the fourth link, the plan automatically draws a top-up from the bench: the draw is the smaller of the current `staffing_gap` and the center's `flex_pool_available`, that amount moves from `flex_pool_available` into `flex_pool_reserved`, `flex_draw_count` increases by the draw, `committed_headcount` and `staffing_gap` are recomputed, `unfilled_gap` is set to whatever gap remains after the draw, and the center's `version` increments by 1."

    Design: Difficulty/transitive_cascade/no_show_cascade_flex_topup_returns_plan_to_approved
    """
    built = _approved_plan_with_one_assigned_worker(world)
    center_id = built["center"]["id"]
    worker_id = built["worker"]["id"]

    before_center = world.center(center_id)
    assert before_center["flex_pool_total"] == 3
    assert before_center["flex_pool_available"] == 3
    assert before_center["flex_pool_reserved"] == 0
    center_version_before = before_center["version"]

    world.no_show(built["assignment"]["id"])

    plan_after = world.plan(built["plan"]["id"])
    assert plan_after["flex_draw_count"] == 1

    center_after = world.center(center_id)
    assert center_after["flex_pool_total"] == 3
    assert center_after["flex_pool_available"] == 2
    assert center_after["flex_pool_reserved"] == 1
    assert center_after["version"] > center_version_before
    world.assert_ledgers(center_id)

    worker_after = world.worker(worker_id)
    assert worker_after["no_show_count"] == 1
    assert worker_after["attrition_risk_basis"] == "COHORT_BASELINE"
    assert float(worker_after["attrition_risk_score"]) == 0.4200
    assert worker_after["attrition_flagged"] is False
