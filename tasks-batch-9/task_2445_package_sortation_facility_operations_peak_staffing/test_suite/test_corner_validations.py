"""Corner-case validation tests for the Package Sortation Peak Staffing API.

Each test below pushes one refusal rule to the place where it is easy to get
wrong: a boundary that must reject rather than accept, a uniqueness scope that
must be per center rather than global, a claim that must be released once the
holder reaches a terminal state, a precedence order between two checks that a
single request violates at once, and a gate that must stay open while the
building is frozen.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CENTER_FROZEN,
    ERR_DUPLICATE_FACILITY_RESOURCE,
    ERR_DUPLICATE_TRAILER_CODE,
    ERR_ERGONOMIC_ROTATION_REQUIRED,
    ERR_EXCEPTION_COUNT_EXCEEDS_SOURCE,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_TIME_WINDOW,
    ERR_LANE_NOT_ASSIGNED_TO_CHUTE,
)
from test_helpers.assertions import expected_final_cost_per_package
from test_helpers.test_users import (
    FACILITY_ADMIN_HEADERS,
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)


# ─── local setup helpers ──────────────────────────────

def _sorting_building(world, clock):
    """A center with an inbound door, an outbound door, one 1,200 pph chute and
    one lane mapped onto it across the working day at `clock`."""
    world.set_clock(clock)
    center = world.create_center(code="SC1", flex_pool_total=20)
    inbound_door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    outbound_door = world.create_door(center["id"], door_number=2, kind="OUTBOUND")
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    lane = world.create_lane(
        center["id"], lane_code="L-WEST", region="WEST", forecast_hourly_volume=3000
    )
    world.map_lane_to_chute(
        chute["id"],
        lane["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    return {
        "center": center,
        "inbound_door": inbound_door,
        "outbound_door": outbound_door,
        "chute": chute,
        "lane": lane,
    }


def _eight_hour_plan(world, center_id):
    """An eight-hour plan for 2026-08-03 whose required headcount is exactly the
    four-per-line floor, so no flex is drawn."""
    return world.create_submitted_plan(
        center_id,
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )


# ─── tests ────────────────────────────────────────────

def test_non_positive_windows_return_invalid_time_window(world, api):
    """PRD §2.9: "In every case the end must be strictly after the start, and a request violating that is rejected with `ERR_INVALID_TIME_WINDOW`."

    PRD §2.9 also fixes the half-open reading that makes a zero-length window
    meaningless: "Every window in this system — a trailer appointment's
    `window_start` to `window_end`, a chute assignment's window, a shift plan's
    `shift_window_start` to `shift_window_end` — is half-open: the start instant is
    inside the window and the end instant is outside it."

    Design: Corner/validations/non_positive_windows_return_invalid_time_window
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(code="SC1", flex_pool_total=20)
    door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    lane = world.create_lane(
        center["id"], lane_code="L-WEST", forecast_hourly_volume=3000
    )
    pinned_chute_version = world.chute_version(chute["id"])

    # A zero-length appointment window: end equal to start is not strictly after.
    zero_length = api.create_trailer_appointment(
        f.trailer_appointment_payload(
            center["id"],
            door["id"],
            trailer_code="T-ZERO",
            window_start="2026-08-03T07:00:00Z",
            window_end="2026-08-03T07:00:00Z",
            priority_class="STANDARD",
            manifest_package_count=100,
        ),
        INBOUND_COORDINATOR_HEADERS,
    )
    validate_error(zero_length, ERR_INVALID_TIME_WINDOW)

    # An inverted chute-assignment window fails the same check.
    inverted = api.create_chute_assignment(
        f.chute_assignment_payload(
            chute["id"],
            lane["id"],
            pinned_chute_version,
            window_start="2026-08-03T14:00:00Z",
            window_end="2026-08-03T06:00:00Z",
        ),
        SORT_SUPERVISOR_HEADERS,
    )
    validate_error(inverted, ERR_INVALID_TIME_WINDOW)

    # Neither refusal left a row or moved a version behind it.
    _, appointment_meta = validate_paginated(
        api.list_trailer_appointments(
            INBOUND_COORDINATOR_HEADERS, sort_center_id=center["id"]
        )
    )
    assert appointment_meta["total_count"] == 0
    _, assignment_meta = validate_paginated(
        api.list_chute_assignments(SORT_SUPERVISOR_HEADERS, chute_id=chute["id"])
    )
    assert assignment_meta["total_count"] == 0
    assert world.chute(chute["id"])["version"] == pinned_chute_version
    assert world.lane(lane["id"])["assigned_capacity_pph"] == 0


def test_duplicate_resource_codes_are_center_scoped(world, api):
    """PRD §3.1: "Uniqueness violations anywhere on this surface — a duplicate center `code`, a duplicate `door_number`, `chute_number` or `lane_code` within one center — are all reported as `ERR_DUPLICATE_FACILITY_RESOURCE`."

    PRD §3.4 reuses the same error for the one-plan-per-date claim: "One plan per
    shift date per center is the rule, with a deliberate escape hatch: a second
    plan for the same center and the same `shift_date` is refused with
    `ERR_DUPLICATE_FACILITY_RESOURCE` unless every existing plan for that date has
    been rejected, since a rejected plan holds no claim on the date."

    Design: Corner/validations/duplicate_resource_codes_are_center_scoped
    """
    world.set_clock("2026-08-03T05:00:00Z")
    first_center = world.create_center(code="SC1", flex_pool_total=20)
    second_center = world.create_center(code="SC2", flex_pool_total=20)
    world.create_chute(first_center["id"], chute_number=1, throughput_pph=1200)
    plan = world.create_draft_plan(
        first_center["id"],
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )

    # Same chute number inside the same center collides.
    duplicate_chute = api.create_sort_chute(
        first_center["id"],
        f.sort_chute_payload(chute_number=1, throughput_pph=1800),
        FACILITY_ADMIN_HEADERS,
    )
    validate_error(duplicate_chute, ERR_DUPLICATE_FACILITY_RESOURCE)

    # The very same number in a different center is a different scope entirely.
    twin_chute = validate_success(
        api.create_sort_chute(
            second_center["id"],
            f.sort_chute_payload(chute_number=1, throughput_pph=1800),
            FACILITY_ADMIN_HEADERS,
        ),
        201,
    )
    assert twin_chute["chute_number"] == 1
    assert twin_chute["throughput_pph"] == 1800
    assert twin_chute["sort_center_id"] == second_center["id"]

    # A second plan on a date already claimed by a non-rejected plan collides.
    duplicate_plan = api.create_shift_plan(
        first_center["id"],
        f.shift_plan_payload(
            shift_date="2026-08-03",
            shift_window_start="2026-08-03T06:00:00Z",
            shift_window_end="2026-08-03T14:00:00Z",
            forecast_volume=5000,
            planned_core_headcount=5,
            planned_seasonal_headcount=0,
            labor_budget_cents=200000,
        ),
        LABOR_PLANNER_HEADERS,
    )
    validate_error(duplicate_plan, ERR_DUPLICATE_FACILITY_RESOURCE)
    assert world.plan(plan["id"])["status"] == "DRAFT"

    # Center codes, by contrast, are global.
    duplicate_center = api.create_sort_center(
        f.sort_center_payload(code="SC1", name="Second Building Same Code"),
        FACILITY_ADMIN_HEADERS,
    )
    validate_error(duplicate_center, ERR_DUPLICATE_FACILITY_RESOURCE)

    _, chute_meta = validate_paginated(
        api.list_sort_chutes(first_center["id"], FACILITY_ADMIN_HEADERS)
    )
    assert chute_meta["total_count"] == 1


def test_trailer_code_frees_up_once_the_trailer_is_unloaded(world, api):
    """PRD §3.3: "And the `trailer_code` must be free at that center: a code already held by a trailer appointment that has not reached `UNLOADED`, or by an outbound load that has not reached `DISPATCHED`, is refused with `ERR_DUPLICATE_TRAILER_CODE`."

    Design: Corner/validations/trailer_code_frees_up_once_the_trailer_is_unloaded
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(code="SC1", flex_pool_total=20)
    first_door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    second_door = world.create_door(center["id"], door_number=2, kind="INBOUND")

    live = world.schedule_appointment(
        center["id"],
        first_door["id"],
        trailer_code="T-A",
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T07:00:00Z",
        priority_class="STANDARD",
        manifest_package_count=400,
    )
    assert live["status"] == "SCHEDULED"

    reuse_payload = f.trailer_appointment_payload(
        center["id"],
        second_door["id"],
        trailer_code="T-A",
        window_start="2026-08-03T09:00:00Z",
        window_end="2026-08-03T10:00:00Z",
        priority_class="STANDARD",
        manifest_package_count=200,
    )

    # While the first appointment is short of UNLOADED the code is still claimed.
    validate_error(
        api.create_trailer_appointment(reuse_payload, INBOUND_COORDINATOR_HEADERS),
        ERR_DUPLICATE_TRAILER_CODE,
    )

    validate_success(api.arrive_trailer_appointment(live["id"], INBOUND_COORDINATOR_HEADERS))
    validate_success(api.start_unload(live["id"], INBOUND_COORDINATOR_HEADERS))
    unloaded = validate_success(
        api.complete_unload(live["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert unloaded["status"] == "UNLOADED"

    # Reaching UNLOADED releases the claim, and the identical body now succeeds.
    reused = validate_success(
        api.create_trailer_appointment(reuse_payload, INBOUND_COORDINATOR_HEADERS), 201
    )
    assert reused["status"] == "SCHEDULED"
    assert reused["trailer_code"] == "T-A"

    center_row = world.center(center["id"])
    assert center_row["packages_inducted_count"] == 400
    assert center_row["wip_package_count"] == 400

    _, appointment_meta = validate_paginated(
        api.list_trailer_appointments(
            INBOUND_COORDINATOR_HEADERS, sort_center_id=center["id"]
        )
    )
    assert appointment_meta["total_count"] == 2
    world.assert_ledgers(center["id"])


def test_two_exceptions_collectively_exceed_lane_source(world, api):
    """PRD §3.8: "The source pool must be able to fund the batch: a `package_count` exceeding the named lane's `sorted_package_count`, or exceeding the center's `wip_package_count` when no source lane is named, is refused with `ERR_EXCEPTION_COUNT_EXCEEDS_SOURCE`."

    PRD §3.8 fixes the debit that shrinks that pool: "Creating the exception debits
    the pool the packages came from and credits exception hold." and "When
    `from_destination_lane_id` is supplied, that lane's `sorted_package_count`
    decreases by `package_count`; when it is not, the center's `wip_package_count`
    decreases by the same amount."

    Design: Corner/validations/two_exceptions_collectively_exceed_lane_source
    """
    building = _sorting_building(world, "2026-08-03T09:00:00Z")
    center, lane = building["center"], building["lane"]
    world.induct_packages(center["id"], building["inbound_door"]["id"], 500)
    load = world.stage_load(
        center["id"],
        building["outbound_door"]["id"],
        lane["id"],
        trailer_code="T-OUT-1",
        trailer_cube_cuft=1000.00,
        dispatch_cut_time="2026-08-03T13:00:00Z",
    )
    world.scan(load["id"], small_count=300)
    assert world.lane(lane["id"])["sorted_package_count"] == 300

    # 200 of the 300 sorted packages are funded and leave the lane.
    first = world.create_exception(
        center["id"],
        exception_type="DAMAGED",
        package_count=200,
        from_destination_lane_id=lane["id"],
    )
    assert first["status"] == "OPEN"
    assert world.lane(lane["id"])["sorted_package_count"] == 100
    assert world.center(center["id"])["exception_hold_count"] == 200

    # The second batch is under the original 300 but over what is left.
    over_funded = api.create_package_exception(
        f.package_exception_payload(
            center["id"],
            exception_type="DAMAGED",
            package_count=150,
            from_destination_lane_id=lane["id"],
        ),
        SORT_SUPERVISOR_HEADERS,
    )
    validate_error(over_funded, ERR_EXCEPTION_COUNT_EXCEEDS_SOURCE)
    assert world.lane(lane["id"])["sorted_package_count"] == 100
    assert world.center(center["id"])["exception_hold_count"] == 200

    # Exactly the remaining balance is still fundable.
    second = world.create_exception(
        center["id"],
        exception_type="DAMAGED",
        package_count=100,
        from_destination_lane_id=lane["id"],
    )
    assert second["status"] == "OPEN"
    assert world.lane(lane["id"])["sorted_package_count"] == 0
    assert world.center(center["id"])["exception_hold_count"] == 300

    _, exception_meta = validate_paginated(
        api.list_package_exceptions(
            SORT_SUPERVISOR_HEADERS, from_destination_lane_id=lane["id"]
        )
    )
    assert exception_meta["total_count"] == 2
    world.assert_ledgers(center["id"])


def test_open_recordable_injury_forces_ergonomic_rotation(world, api):
    """PRD §3.7: "Ergonomics and safety must clear: the worker's `consecutive_completed_shifts` must be strictly below 5, and the worker must have no injury report in `OPEN` status whose `severity` is `RECORDABLE` or `SERIOUS`; either failure is refused with `ERR_ERGONOMIC_ROTATION_REQUIRED`."

    Design: Corner/validations/open_recordable_injury_forces_ergonomic_rotation
    """
    world.set_clock("2026-08-03T05:00:00Z")
    center = world.create_center(code="SC1", flex_pool_total=20)
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    plan = _eight_hour_plan(world, center["id"])
    approved = world.approve_plan(plan["id"], center["id"])
    assert approved["status"] == "APPROVED"
    assert approved["required_headcount"] == 4

    worker = world.create_certified_worker(
        center["id"], full_name="Sore Sam", hire_class="CORE", hire_date="2026-08-01"
    )
    report = world.file_injury(
        center["id"],
        worker["id"],
        severity="RECORDABLE",
        body_part="SHOULDER",
        occurred_at="2026-08-03T04:00:00Z",
    )
    assert report["status"] == "OPEN"

    # A RECORDABLE injury is not a serious one, so the building stays OPEN, yet
    # the worker behind it may not be put back on a line.
    assert world.center(center["id"])["ops_posture"] == "OPEN"
    assert world.center(center["id"])["open_serious_injury_count"] == 0

    blocked = api.create_staff_assignment(
        f.staff_assignment_payload(plan["id"], worker["id"], chute["id"]),
        LABOR_PLANNER_HEADERS,
    )
    validate_error(blocked, ERR_ERGONOMIC_ROTATION_REQUIRED)

    closed_report = validate_success(
        api.close_injury_report(
            report["id"], f.close_injury_payload(0), OPS_MANAGER_HEADERS
        )
    )
    assert closed_report["status"] == "CLOSED"
    assert closed_report["lost_time_days"] == 0

    # With the report closed the gate clears and the same body is accepted.
    assignment = validate_success(
        api.create_staff_assignment(
            f.staff_assignment_payload(plan["id"], worker["id"], chute["id"]),
            LABOR_PLANNER_HEADERS,
        ),
        201,
    )
    assert assignment["status"] == "ASSIGNED"
    assert float(assignment["worked_hours"]) == 0

    settled_plan = world.plan(plan["id"])
    assert settled_plan["status"] == "APPROVED"
    assert settled_plan["committed_headcount"] == 4
    assert settled_plan["staffing_gap"] == 0


def test_reroute_to_unmapped_lane_rejected_then_accepted(world, api):
    """PRD §3.8: "The order matters: the referential check on the lane's assignment history is evaluated before the live-eligibility check, so a lane that was never mapped reports the referential error and never the empty-pool error."

    PRD §3.8 states the two checks the order applies to: "A reroute carries three
    additional requirements: `to_destination_lane_id` must be present and name a
    lane whose `status` is `ACTIVE`; that lane must have at least one chute
    assignment on record in any status, otherwise `ERR_LANE_NOT_ASSIGNED_TO_CHUTE`;
    and the pool of chutes actually able to take the packages right now must be
    non-empty, otherwise `ERR_NO_ELIGIBLE_CHUTE`."

    Design: Corner/validations/reroute_to_unmapped_lane_rejected_then_accepted
    """
    building = _sorting_building(world, "2026-08-03T09:00:00Z")
    center, source_lane = building["center"], building["lane"]
    fast_chute = world.create_chute(center["id"], chute_number=2, throughput_pph=1800)
    fresh_lane = world.create_lane(
        center["id"], lane_code="L-NEW", region="EAST", forecast_hourly_volume=2000
    )
    assert fresh_lane["assigned_capacity_pph"] == 0

    world.induct_packages(center["id"], building["inbound_door"]["id"], 500)
    load = world.stage_load(
        center["id"],
        building["outbound_door"]["id"],
        source_lane["id"],
        trailer_code="T-OUT-1",
        trailer_cube_cuft=1000.00,
        dispatch_cut_time="2026-08-03T13:00:00Z",
    )
    world.scan(load["id"], small_count=300)
    exception = world.create_exception(
        center["id"],
        exception_type="MISSORT",
        package_count=200,
        from_destination_lane_id=source_lane["id"],
    )

    # The target lane has never been mapped to any chute, so the referential
    # error is reported and the empty-pool error never surfaces.
    unmapped = api.resolve_package_exception(
        exception["id"],
        f.resolve_exception_payload("REROUTE", to_destination_lane_id=fresh_lane["id"]),
        SORT_SUPERVISOR_HEADERS,
    )
    validate_error(unmapped, ERR_LANE_NOT_ASSIGNED_TO_CHUTE)
    assert world.exception(exception["id"])["status"] == "OPEN"
    assert world.exception(exception["id"])["resolution"] is None
    assert world.center(center["id"])["exception_hold_count"] == 200
    assert world.lane(fresh_lane["id"])["sorted_package_count"] == 0

    mapping = world.map_lane_to_chute(
        fast_chute["id"],
        fresh_lane["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    assert mapping["status"] == "ACTIVE"
    assert world.lane(fresh_lane["id"])["assigned_capacity_pph"] == 1800

    resolved = validate_success(
        api.resolve_package_exception(
            exception["id"],
            f.resolve_exception_payload(
                "REROUTE", to_destination_lane_id=fresh_lane["id"]
            ),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REROUTE"
    assert resolved["resolved_via_chute_id"] == fast_chute["id"]

    assert world.lane(fresh_lane["id"])["sorted_package_count"] == 200
    center_row = world.center(center["id"])
    assert center_row["exception_hold_count"] == 0
    assert center_row["missort_corrected_count"] == 200
    world.assert_ledgers(center["id"])


def test_forbidden_role_beats_malformed_payload_and_is_rejected(world, api):
    """PRD §2.7: "Because many operations carry several checks that could each fail, the order of evaluation is fixed."

    PRD §2.7 puts role authorization at position 2 and body shape at position 3 —
    "Role authorization for the called operation, else `ERR_FORBIDDEN_ROLE`." ahead
    of "Request-body shape on every creating or modifying operation — required
    fields present, enum values inside their declared sets, integer counts
    non-negative, percentages within 0 through 100 inclusive, cube and count fields
    strictly positive where the field requires it, and any pinned version field an
    integer — else `ERR_INVALID_REQUEST`." — and PRD §3.1 names the only role that
    may open a building: "Everything in this system hangs off a sort center, and a
    `FacilityAdmin` is the only role that may create one."

    Design: Corner/validations/forbidden_role_beats_malformed_payload_and_is_rejected
    """
    world.set_clock("2026-08-03T06:00:00Z")

    # This one request breaks two rules at once: a LaborPlanner may not create a
    # center, and 140 is outside the 0 through 100 percentage bound.
    response = api.create_sort_center(
        f.sort_center_payload(
            code="SC9",
            name="Wrong Role And Bad Percentage",
            automation_utilization_pct=140.00,
            flex_pool_total=5,
        ),
        LABOR_PLANNER_HEADERS,
    )
    validate_error(response, ERR_FORBIDDEN_ROLE)

    # Nothing was written, so the earlier check truly short-circuited the later.
    _, center_meta = validate_paginated(
        api.list_sort_centers(FACILITY_ADMIN_HEADERS)
    )
    assert center_meta["total_count"] == 0


def test_frozen_center_still_allows_recovery_and_closure(world, api):
    """PRD §2.5: "Everything that helps the building recover is deliberately still permitted while frozen: recording a jam hold, resuming an unload after a jam, filing and closing injury reports, creating a package exception, sealing or closing an outbound load, closing a shift plan, and all facility administration and labor-pipeline paperwork."

    PRD §2.5 lists what the same posture refuses, scanning among them: "While a
    center is `FROZEN`, the following operations are refused with
    `ERR_CENTER_FROZEN` (HTTP 409): recording a trailer arrival, starting an unload,
    completing an unload, scanning packages into an outbound load, dispatching an
    outbound load, approving a shift plan, creating a staff assignment, checking a
    worker in, and resolving a package exception."

    Design: Corner/validations/frozen_center_still_allows_recovery_and_closure
    """
    building = _sorting_building(world, "2026-08-03T05:00:00Z")
    center, chute, lane = building["center"], building["chute"], building["lane"]

    plan = _eight_hour_plan(world, center["id"])
    approved = world.approve_plan(plan["id"], center["id"])
    assert approved["status"] == "APPROVED"
    assert approved["flex_draw_count"] == 0

    load = world.stage_load(
        center["id"],
        building["outbound_door"]["id"],
        lane["id"],
        trailer_code="T-OUT-1",
        trailer_cube_cuft=1000.00,
        dispatch_cut_time="2026-08-03T13:00:00Z",
    )
    assert load["load_status"] == "STAGING"

    world.set_clock("2026-08-03T07:00:00Z")
    appointment = world.schedule_appointment(
        center["id"],
        building["inbound_door"]["id"],
        trailer_code="T-A",
        window_start="2026-08-03T07:00:00Z",
        window_end="2026-08-03T08:00:00Z",
        priority_class="STANDARD",
        manifest_package_count=3000,
    )
    validate_success(
        api.arrive_trailer_appointment(appointment["id"], INBOUND_COORDINATOR_HEADERS)
    )
    validate_success(api.start_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS))
    held = world.jam_hold(appointment["id"], chute["id"])
    assert held["status"] == "JAM_HELD"

    worker = world.create_worker(
        center["id"], full_name="Hurt Harper", hire_date="2026-08-01"
    )
    report = world.file_injury(
        center["id"],
        worker["id"],
        severity="SERIOUS",
        body_part="ANKLE",
        occurred_at="2026-08-03T07:10:00Z",
    )
    frozen_center = world.center(center["id"])
    assert frozen_center["ops_posture"] == "FROZEN"
    assert frozen_center["open_jam_count"] == 1
    assert frozen_center["open_serious_injury_count"] == 1

    # Scanning is one of the nine refused operations.
    blocked_scan = api.scan_packages(
        load["id"], f.scan_packages_payload(small_count=10), SORT_SUPERVISOR_HEADERS
    )
    validate_error(blocked_scan, ERR_CENTER_FROZEN)
    still_staging = world.load(load["id"])
    assert still_staging["load_status"] == "STAGING"
    assert still_staging["package_count"] == 0

    # Resuming the unload is explicitly permitted while frozen, and it clears the
    # jam without lifting the posture, because the injury still holds it down.
    resumed = validate_success(
        api.resume_unload(
            appointment["id"],
            f.resume_unload_payload(chute["id"]),
            INBOUND_COORDINATOR_HEADERS,
        )
    )
    assert resumed["status"] == "UNLOADING"
    after_resume = world.center(center["id"])
    assert after_resume["open_jam_count"] == 0
    assert after_resume["ops_posture"] == "FROZEN"

    # Closing the injury report is permitted too, and it thaws the building.
    closed_report = validate_success(
        api.close_injury_report(
            report["id"], f.close_injury_payload(3), OPS_MANAGER_HEADERS
        )
    )
    assert closed_report["status"] == "CLOSED"
    assert closed_report["lost_time_days"] == 3
    thawed = world.center(center["id"])
    assert thawed["ops_posture"] == "OPEN"
    assert thawed["open_serious_injury_count"] == 0

    # Closing the plan is on the permitted list as well; with no completed
    # assignments it settles at zero labor and pure overhead per package.
    closed_plan = validate_success(
        api.close_shift_plan(
            plan["id"],
            f.close_plan_payload(world.center_version(center["id"])),
            OPS_MANAGER_HEADERS,
        )
    )
    assert closed_plan["status"] == "CLOSED"
    assert closed_plan["actual_labor_cents"] == 0
    assert float(
        closed_plan["final_cost_per_package_cents"]
    ) == expected_final_cost_per_package(0, 0, 0)
    assert float(closed_plan["final_cost_per_package_cents"]) == 12000.00

    settled_center = world.center(center["id"])
    assert settled_center["flex_pool_available"] == 20
    assert settled_center["flex_pool_reserved"] == 0
