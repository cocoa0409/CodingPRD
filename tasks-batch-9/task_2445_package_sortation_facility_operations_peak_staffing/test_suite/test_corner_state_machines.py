"""State-machine corner cases for the Package Sortation Peak Staffing API.

Initial states, refused transitions out of the wrong state, terminal-state
lockdown, the declared side effects of a successful transition, and the two
derived cascades that reach from a child row into the owning sort center.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_APPOINTMENT_STATE,
    ERR_INVALID_LOAD_STATE,
    ERR_INVALID_SHIFT_PLAN_STATE,
)
from test_helpers.assertions import (
    assert_fresh_entity,
    assert_trailer_appointment,
)
from test_helpers.fixtures import parse_instant
from test_helpers.test_users import (
    FACILITY_ADMIN_HEADERS,
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)


def test_trailer_appointment_starts_in_scheduled(api, world, facility):
    """PRD §3.3: "A new appointment is born `SCHEDULED` with `jam_count` at 0, `unload_sequence_rank` null, and `arrived_at` and `unloaded_at` both null."

    Design: Corner/state_machines/trailer_appointment_starts_in_scheduled
    """
    center = facility["center"]

    data = validate_success(
        api.create_trailer_appointment(
            f.trailer_appointment_payload(
                center["id"],
                facility["inbound_door"]["id"],
                window_start="2026-08-01T06:00:00Z",
                window_end="2026-08-01T07:00:00Z",
                priority_class="EXPRESS",
                manifest_package_count=900,
            ),
            INBOUND_COORDINATOR_HEADERS,
        ),
        201,
    )

    assert_trailer_appointment(data)
    assert_fresh_entity(data)
    assert data["status"] == "SCHEDULED"
    assert data["jam_count"] == 0
    assert data["unload_sequence_rank"] is None
    assert data["arrived_at"] is None
    assert data["unloaded_at"] is None
    assert world.center(center["id"])["wip_package_count"] == 0


def test_complete_unload_from_scheduled_rejected(api, world, facility):
    """PRD §3.3: "Requesting any transition from the wrong state — arriving twice, unloading a scheduled trailer, resuming an appointment that is not held — is refused with `ERR_INVALID_APPOINTMENT_STATE`, and a target appointment that does not exist yields `ERR_TRAILER_APPOINTMENT_NOT_FOUND`."

    Finishing the unload is declared only out of `UNLOADING`, so a `SCHEDULED`
    appointment inducts nothing.

    Design: Corner/state_machines/complete_unload_from_scheduled_rejected
    """
    center = facility["center"]
    appointment = world.schedule_appointment(
        center["id"], facility["inbound_door"]["id"], manifest_package_count=900
    )

    validate_error(
        api.complete_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS),
        ERR_INVALID_APPOINTMENT_STATE,
    )

    stored = world.appointment(appointment["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored["unloaded_at"] is None
    stored_center = world.center(center["id"])
    assert stored_center["packages_inducted_count"] == 0
    assert stored_center["wip_package_count"] == 0


def test_unloaded_appointment_cannot_be_arrived_again(api, world, facility):
    """PRD §3.3: "Finishing the unload advances the appointment `UNLOADING → UNLOADED`, which is terminal."

    Requesting any transition from the wrong state is refused with
    `ERR_INVALID_APPOINTMENT_STATE`.

    Design: Corner/state_machines/unloaded_appointment_cannot_be_arrived_again
    """
    center = facility["center"]
    chute = facility["chute"]
    appointment = world.induct_packages(
        center["id"], facility["inbound_door"]["id"], 900
    )
    assert appointment["status"] == "UNLOADED"

    validate_error(
        api.arrive_trailer_appointment(appointment["id"], INBOUND_COORDINATOR_HEADERS),
        ERR_INVALID_APPOINTMENT_STATE,
    )
    validate_error(
        api.jam_hold(
            appointment["id"],
            f.jam_hold_payload(chute["id"], jam_reason="LATE_JAM"),
            INBOUND_COORDINATOR_HEADERS,
        ),
        ERR_INVALID_APPOINTMENT_STATE,
    )

    stored = world.appointment(appointment["id"])
    assert stored["status"] == "UNLOADED"
    assert stored["jam_count"] == 0

    stored_chute = world.chute(chute["id"])
    assert stored_chute["status"] == "ACTIVE"
    assert stored_chute["jam_hold_count"] == 0

    stored_center = world.center(center["id"])
    assert stored_center["packages_inducted_count"] == 900
    assert stored_center["wip_package_count"] == 900


def test_second_submit_on_submitted_plan_rejected(api, world, facility):
    """PRD §3.4: "Submitting a plan that is not in `DRAFT` is refused with `ERR_INVALID_SHIFT_PLAN_STATE`, and a plan identifier that does not resolve yields `ERR_SHIFT_PLAN_NOT_FOUND`."

    Design: Corner/state_machines/second_submit_on_submitted_plan_rejected
    """
    center = facility["center"]
    plan = world.create_submitted_plan(
        center["id"],
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    assert plan["status"] == "SUBMITTED"
    assert plan["required_headcount"] == 4
    submitter = plan["submitted_by_user_id"]

    # A second line would raise the per-line floor to 8 if the requirement were
    # recomputed by the refused submit.
    world.create_chute(center["id"], chute_number=2, throughput_pph=1200)

    validate_error(
        api.submit_shift_plan(plan["id"], LABOR_PLANNER_HEADERS),
        ERR_INVALID_SHIFT_PLAN_STATE,
    )

    stored = world.plan(plan["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["required_headcount"] == 4
    assert stored["submitted_by_user_id"] == submitter


def test_seal_from_staging_load_rejected(api, world, facility):
    """PRD §3.8: "In both cases the load's `load_status` must be `LOADING` or `LOADED` — a `STAGING` trailer has nothing to seal — and an attempt outside those states is refused with `ERR_INVALID_LOAD_STATE`."

    Design: Corner/state_machines/seal_from_staging_load_rejected
    """
    load = world.stage_load(
        facility["center"]["id"],
        facility["outbound_door"]["id"],
        facility["lane"]["id"],
    )
    assert load["load_status"] == "STAGING"

    validate_error(
        api.seal_load(
            load["id"], f.seal_payload(seal_code="SEAL-EARLY"), SORT_SUPERVISOR_HEADERS
        ),
        ERR_INVALID_LOAD_STATE,
    )

    stored = world.load(load["id"])
    assert stored["seal_status"] == "UNSEALED"
    assert stored["seal_code"] is None
    assert stored["load_status"] == "STAGING"


def test_complete_unload_inducts_manifest_into_wip(api, world, facility):
    """PRD §3.3: "The transition stamps `unloaded_at` with the logical clock and inducts the manifest: the center's `packages_inducted_count` and `wip_package_count` both increase by the appointment's `manifest_package_count`, the center's `version` increments, and its posture is recomputed."

    Design: Corner/state_machines/complete_unload_inducts_manifest_into_wip
    """
    center = facility["center"]
    appointment = world.unloading_appointment(
        center["id"], facility["inbound_door"]["id"], manifest_package_count=2500
    )
    assert appointment["status"] == "UNLOADING"

    world.set_clock("2026-08-03T06:00:00Z")
    version_before = world.center_version(center["id"])

    data = validate_success(
        api.complete_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS)
    )

    assert data["status"] == "UNLOADED"
    assert parse_instant(data["unloaded_at"]) == parse_instant("2026-08-03T06:00:00Z")

    stored_center = world.center(center["id"])
    assert stored_center["packages_inducted_count"] == 2500
    assert stored_center["wip_package_count"] == 2500
    assert stored_center["version"] == version_before + 1
    assert stored_center["ops_posture"] == "OPEN"
    assert stored_center["open_jam_count"] == 0
    world.assert_ledgers(center["id"])


def test_injury_close_thaws_frozen_center_to_open(api, world):
    """PRD §3.9: "Closure transitions the report `OPEN → CLOSED`, records the lost time, recomputes the center's `open_serious_injury_count`, re-derives `ops_posture` and increments the center's `version` by 1."

    Design: Corner/state_machines/injury_close_thaws_frozen_center_to_open
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    worker = world.create_worker(
        center["id"], full_name="Core Casey", hire_class="CORE", hire_date="2026-08-01"
    )
    version_before_filing = world.center_version(center["id"])
    report = world.file_injury(
        center["id"], worker["id"], severity="SERIOUS", body_part="SHOULDER"
    )

    frozen = world.center(center["id"])
    assert frozen["ops_posture"] == "FROZEN"
    assert frozen["open_serious_injury_count"] == 1
    assert frozen["version"] == version_before_filing + 1

    world.set_clock("2026-08-04T09:00:00Z")
    data = validate_success(
        api.close_injury_report(
            report["id"], f.close_injury_payload(4), OPS_MANAGER_HEADERS
        )
    )

    assert data["status"] == "CLOSED"
    assert data["lost_time_days"] == 4

    thawed = world.center(center["id"])
    assert thawed["ops_posture"] == "OPEN"
    assert thawed["open_serious_injury_count"] == 0
    assert parse_instant(thawed["last_posture_change_at"]) == parse_instant(
        "2026-08-04T09:00:00Z"
    )
    assert thawed["version"] == frozen["version"] + 1


def test_patch_automation_below_threshold_restricts_then_restores(api, world):
    """PRD §3.1: "Automation is the one center attribute an admin may restate later — an automation outage drops it, commissioning a new sorter raises it — and restating it recomputes `ops_posture`, increments the center's `version`, and changes the throughput tier that the next headcount sizing will use."

    PRD §2.5 makes the posture `RESTRICTED` when the center's
    `automation_utilization_pct` is below 45, and `OPEN` when nothing else is
    outstanding.

    Design: Corner/state_machines/patch_automation_below_threshold_restricts_then_restores
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    baseline_version = center["version"]
    assert center["ops_posture"] == "OPEN"

    restricted = validate_success(
        api.patch_sort_center(
            center["id"], f.sort_center_patch_payload(44), FACILITY_ADMIN_HEADERS
        )
    )
    assert restricted["ops_posture"] == "RESTRICTED"
    assert float(restricted["automation_utilization_pct"]) == 44.00
    assert restricted["version"] == baseline_version + 1

    restored = validate_success(
        api.patch_sort_center(
            center["id"], f.sort_center_patch_payload(45), FACILITY_ADMIN_HEADERS
        )
    )
    assert restored["ops_posture"] == "OPEN"
    assert float(restored["automation_utilization_pct"]) == 45.00
    assert restored["version"] == baseline_version + 2

    assert restored["open_jam_count"] == 0
    assert restored["open_serious_injury_count"] == 0
    assert parse_instant(restored["last_posture_change_at"]) == parse_instant(
        "2026-08-03T06:00:00Z"
    )


def test_shift_plan_close_ends_only_assignments_inside_the_window(api, world):
    """PRD §3.9: "And the sort floor is tidied: every chute assignment of that center whose `status` is `ACTIVE` or `SUSPENDED` and whose `window_end` falls at or before the plan's `shift_window_end` transitions to the terminal `ENDED` — `ACTIVE → ENDED` and `SUSPENDED → ENDED` alike — with `effective_window_end` set to that assignment's own `window_end`, and every destination lane whose assignment set changed has its `assigned_capacity_pph` and `lane_pressure_ratio` recomputed."

    Design: Corner/state_machines/shift_plan_close_ends_only_assignments_inside_the_window
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    chute = world.create_chute(
        center["id"],
        chute_number=1,
        throughput_pph=1200,
        max_concurrent_destinations=2,
    )
    lane_in = world.create_lane(center["id"], forecast_hourly_volume=3000)
    lane_out = world.create_lane(center["id"], forecast_hourly_volume=1200)
    assignment_in = world.map_lane_to_chute(
        chute["id"],
        lane_in["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    assignment_out = world.map_lane_to_chute(
        chute["id"],
        lane_out["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T15:00:00Z",
    )

    plan = world.create_submitted_plan(
        center["id"],
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    approved = world.approve_plan(plan["id"], center["id"])
    assert approved["status"] == "APPROVED"
    assert approved["flex_draw_count"] == 0

    data = validate_success(
        api.close_shift_plan(
            plan["id"],
            f.close_plan_payload(world.center_version(center["id"])),
            OPS_MANAGER_HEADERS,
        )
    )
    assert data["status"] == "CLOSED"

    ended = world.assignment(assignment_in["id"])
    assert ended["status"] == "ENDED"
    assert parse_instant(ended["effective_window_end"]) == parse_instant(
        "2026-08-03T14:00:00Z"
    )

    untouched = world.assignment(assignment_out["id"])
    assert untouched["status"] == "ACTIVE"
    assert untouched["effective_window_end"] is None

    stored_lane_in = world.lane(lane_in["id"])
    assert stored_lane_in["assigned_capacity_pph"] == 0
    assert float(stored_lane_in["lane_pressure_ratio"]) == 0.0
    assert world.lane(lane_out["id"])["assigned_capacity_pph"] == 1200

    stored_center = world.center(center["id"])
    assert stored_center["flex_pool_available"] == 20
    assert stored_center["flex_pool_reserved"] == 0


def test_worker_separation_flips_assigned_rows_to_no_show(api, world):
    """PRD §3.6: "Whether the worker separates out of `CLEARED` or out of `CERTIFIED`, the consequence is identical: every staff assignment of that worker whose `status` is still `ASSIGNED` immediately flips to `NO_SHOW`, and the complete no-show cascade described in §3.7 below runs for each affected shift plan — headcount recomputation, possible flip to `AT_RISK`, flex top-up, possible flip back to `APPROVED`."

    Design: Corner/state_machines/worker_separation_flips_assigned_rows_to_no_show
    """
    built = world.setup_facility(flex_pool_total=5)
    center = built["center"]
    chute = built["chute"]

    plan = world.create_submitted_plan(
        center["id"],
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    approved = world.approve_plan(plan["id"], center["id"])
    assert approved["status"] == "APPROVED"
    assert approved["required_headcount"] == 4
    assert approved["flex_draw_count"] == 0

    worker = world.create_cleared_worker(
        center["id"],
        full_name="Quitting Quinn",
        hire_class="CORE",
        hire_date="2026-07-30",
    )
    staff_assignment = world.create_assignment(plan["id"], worker["id"], chute["id"])
    assert staff_assignment["status"] == "ASSIGNED"

    data = validate_success(
        api.create_onboarding_event(
            worker["id"],
            f.onboarding_event_payload("SEPARATED"),
            LABOR_PLANNER_HEADERS,
        )
    )

    assert data["status"] == "SEPARATED"
    assert data["no_show_count"] == 1
    assert float(data["attrition_risk_score"]) == 0.4200
    assert data["attrition_risk_basis"] == "COHORT_BASELINE"

    assert world.staff_assignment(staff_assignment["id"])["status"] == "NO_SHOW"

    stored_plan = world.plan(plan["id"])
    assert stored_plan["flex_draw_count"] == 1
    assert stored_plan["committed_headcount"] == 4
    assert stored_plan["staffing_gap"] == 0
    assert stored_plan["unfilled_gap"] == 0
    assert stored_plan["status"] == "APPROVED"

    stored_center = world.center(center["id"])
    assert stored_center["flex_pool_available"] == 4
    assert stored_center["flex_pool_reserved"] == 1
    assert stored_center["flex_pool_total"] == 5
    world.assert_ledgers(center["id"])
