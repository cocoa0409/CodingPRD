"""Entity-level corner cases for the Package Sortation Peak Staffing API.

Every test in this module drives one documented endpoint family and asserts only
what the PRD narrative pins for it: creation projections, single-resource reads,
filtered listing with pagination, defaults, computed fields, and the four
existence / shape / cross-center rejections that guard a create.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_SHIFT_PLAN_NOT_FOUND,
    ERR_SORT_CENTER_NOT_FOUND,
    ERR_WORKER_CENTER_MISMATCH,
)
from test_helpers.assertions import (
    assert_chute_assignment,
    assert_dock_door,
    assert_fresh_entity,
    assert_sort_center,
    assert_sort_chute,
    assert_worker,
)
from test_helpers.test_users import (
    FACILITY_ADMIN_HEADERS,
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)


def test_sort_center_create_returns_full_projection(api):
    """PRD §3.1: "At creation the center's bench is entirely unspent, so `flex_pool_available` is initialized to `flex_pool_total` and `flex_pool_reserved` to 0, every package and jam counter (`open_jam_count`, `open_serious_injury_count`, `packages_inducted_count`, `wip_package_count`, `exception_hold_count`, `disposed_package_count`, `missort_corrected_count`) starts at 0, `last_posture_change_at` is null, and `version` is 1."

    Design: Corner/entities/sort_center_create_returns_full_projection
    """
    payload = f.sort_center_payload(
        name="Memphis Sort 1", automation_utilization_pct=70.00, flex_pool_total=20
    )

    data = validate_success(api.create_sort_center(payload, FACILITY_ADMIN_HEADERS), 201)

    assert_sort_center(data)
    assert_fresh_entity(data)
    assert data["code"] == payload["code"]
    assert data["name"] == "Memphis Sort 1"
    assert float(data["automation_utilization_pct"]) == 70.00
    assert data["flex_pool_total"] == 20
    assert data["flex_pool_available"] == 20
    assert data["flex_pool_reserved"] == 0
    assert data["ops_posture"] == "OPEN"
    assert data["last_posture_change_at"] is None
    for counter in (
        "open_jam_count",
        "open_serious_injury_count",
        "packages_inducted_count",
        "wip_package_count",
        "exception_hold_count",
        "disposed_package_count",
        "missort_corrected_count",
    ):
        assert data[counter] == 0, f"{counter} must start at 0"


def test_dock_door_get_returns_stored_row(api, world):
    """PRD §3.1: "Every door also carries `turnaround_buffer_min`, the mandatory clear time in minutes that must separate two appointments on that door; it defaults to 15 minutes when omitted and must be at least 0."

    Design: Corner/entities/dock_door_get_returns_stored_row
    """
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    created = world.create_door(
        center["id"], door_number=1, kind="INBOUND", turnaround_buffer_min=30
    )

    data = validate_success(api.get_dock_door(created["id"], INBOUND_COORDINATOR_HEADERS))

    assert_dock_door(data)
    assert data["id"] == created["id"]
    assert data["sort_center_id"] == center["id"]
    assert data["door_number"] == 1
    assert data["kind"] == "INBOUND"
    assert data["status"] == "ACTIVE"
    assert data["turnaround_buffer_min"] == 30
    assert data["version"] == 1


def test_workers_list_filtered_by_status_with_pagination(api, world):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside `meta`: `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the current window."

    Design: Corner/entities/workers_list_filtered_by_status_with_pagination
    """
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    worker_a = world.create_worker(
        center["id"], full_name="W-A", hire_class="CORE", hire_date="2026-07-30"
    )
    worker_b = world.create_worker(
        center["id"], full_name="W-B", hire_class="SEASONAL", hire_date="2026-07-30"
    )
    world.record_event(worker_b["id"], "ONBOARDING_STARTED")
    worker_c = world.create_worker(
        center["id"], full_name="W-C", hire_class="FLEX", hire_date="2026-07-30"
    )
    world.record_event(worker_c["id"], "ONBOARDING_STARTED")
    world.record_event(worker_c["id"], "BACKGROUND_CLEARED")

    applied, applied_meta = validate_paginated(
        api.list_workers(center["id"], LABOR_PLANNER_HEADERS, status="APPLIED")
    )
    assert [row["id"] for row in applied] == [worker_a["id"]]
    assert applied_meta["total_count"] == 1
    assert applied_meta["has_more"] is False

    page_one, meta_one = validate_paginated(
        api.list_workers(center["id"], LABOR_PLANNER_HEADERS, limit=2, offset=0)
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_workers(center["id"], LABOR_PLANNER_HEADERS, limit=2, offset=2)
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    windowed = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(windowed) == len(set(windowed)), "the two pages must not overlap"
    assert set(windowed) == {worker_a["id"], worker_b["id"], worker_c["id"]}


def test_get_shift_plan_unknown_id_returns_not_found(api):
    """PRD §2.7: "Beyond the center, existence failures are grouped by resource family so that the error identity itself tells the caller which family failed: a missing dock door, sortation chute, destination lane or chute assignment yields `ERR_FACILITY_RESOURCE_NOT_FOUND`; a missing trailer appointment yields `ERR_TRAILER_APPOINTMENT_NOT_FOUND`; a missing shift plan yields `ERR_SHIFT_PLAN_NOT_FOUND`; a missing worker or staff assignment yields `ERR_LABOR_RESOURCE_NOT_FOUND`; a missing outbound load or package exception yields `ERR_OUTBOUND_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/get_shift_plan_unknown_id_returns_not_found
    """
    error = validate_error(
        api.get_shift_plan(NON_EXISTENT_UUID, LABOR_PLANNER_HEADERS),
        ERR_SHIFT_PLAN_NOT_FOUND,
    )

    assert isinstance(error["message"], str) and error["message"], (
        "the error envelope must carry a human-readable message"
    )


def test_trailer_appointment_create_missing_manifest_count_invalid_request(api, world):
    """PRD §3.3: "The booking names the receiving facility as `sort_center_id`, the reserved door as `door_id`, the carrier's `trailer_code`, the half-open occupation window as `window_start` and `window_end`, an unload `priority_class` of `CRITICAL`, `EXPRESS`, `STANDARD` or `DEFERRED`, and the `manifest_package_count` declared by the carrier, which must be at least 0."

    PRD §2.7 puts request-body shape at priority 3: required fields present, else
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/trailer_appointment_create_missing_manifest_count_invalid_request
    """
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    door = world.create_door(center["id"], door_number=1, kind="INBOUND")

    validate_error(
        api.create_trailer_appointment(
            f.trailer_appointment_payload(
                center["id"], door["id"], manifest_package_count=f.OMIT
            ),
            INBOUND_COORDINATOR_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )

    rows, meta = validate_paginated(
        api.list_trailer_appointments(
            INBOUND_COORDINATOR_HEADERS, sort_center_id=center["id"]
        )
    )
    assert meta["total_count"] == 0, "the rejected booking must not persist a row"
    assert rows == []


def test_sort_chute_create_applies_concurrency_default(api, world):
    """PRD §3.1: "Commissioning one supplies a `chute_number` (at least 1, unique within the center), a rated `throughput_pph` of at least 1 package per hour, and optionally `max_concurrent_destinations` — the aggregate interval capacity governing how many active destination mappings may overlap on that chute at any instant — which defaults to 2 and must be at least 1."

    Design: Corner/entities/sort_chute_create_applies_concurrency_default
    """
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)

    data = validate_success(
        api.create_sort_chute(
            center["id"],
            f.sort_chute_payload(chute_number=1, throughput_pph=1200),
            FACILITY_ADMIN_HEADERS,
        ),
        201,
    )

    assert_sort_chute(data)
    assert data["max_concurrent_destinations"] == 2
    assert data["status"] == "ACTIVE"
    assert data["jam_hold_count"] == 0
    assert data["throughput_pph"] == 1200
    assert data["version"] == 1


def test_worker_create_computes_cohort_attrition_score(api, world):
    """PRD §3.6: "The tenure bucket contributes a baseline risk: 0.42 for a tenure of 14 days or fewer, 0.31 for 15 through 45 days, 0.18 for 46 through 120 days, and 0.09 from 121 days onward."

    A `CORE` hire adds nothing at all to that baseline, and with fewer than three
    completed assignments the basis is `COHORT_BASELINE`.

    Design: Corner/entities/worker_create_computes_cohort_attrition_score
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)

    data = validate_success(
        api.create_worker(
            center["id"],
            f.worker_payload(
                full_name="Core Casey", hire_class="CORE", hire_date="2026-08-01"
            ),
            LABOR_PLANNER_HEADERS,
        ),
        201,
    )

    assert_worker(data)
    assert data["status"] == "APPLIED"
    assert data["tenure_days"] == 2
    assert float(data["attrition_risk_score"]) == 0.4200
    assert data["attrition_risk_basis"] == "COHORT_BASELINE"
    assert data["attrition_flagged"] is False
    for counter in (
        "training_sessions_completed",
        "training_sessions_missed",
        "no_show_count",
        "completed_assignment_count",
        "consecutive_completed_shifts",
    ):
        assert data[counter] == 0, f"{counter} must start at 0"


def test_chute_assignment_create_generates_system_fields(api, world):
    """PRD §3.2: "A fresh assignment is born with `status` `ACTIVE`, `suspended_reason` null and `effective_window_end` null."

    PRD §3.2 also pins the parent side effects: every chute-assignment create
    increments the target chute's `version` by 1 and recomputes the destination
    lane's assigned capacity and pressure.

    Design: Corner/entities/chute_assignment_create_generates_system_fields
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    lane = world.create_lane(center["id"], forecast_hourly_volume=3000)
    assert chute["version"] == 1

    data = validate_success(
        api.create_chute_assignment(
            f.chute_assignment_payload(
                chute["id"],
                lane["id"],
                chute["version"],
                window_start="2026-08-03T06:00:00Z",
                window_end="2026-08-03T14:00:00Z",
            ),
            SORT_SUPERVISOR_HEADERS,
        ),
        201,
    )

    assert_chute_assignment(data)
    assert_fresh_entity(data)
    assert data["chute_id"] == chute["id"]
    assert data["destination_lane_id"] == lane["id"]
    assert data["status"] == "ACTIVE"
    assert data["effective_window_end"] is None
    assert data["suspended_reason"] is None

    assert world.chute(chute["id"])["version"] == 2
    stored_lane = world.lane(lane["id"])
    assert stored_lane["assigned_capacity_pph"] == 1200
    assert float(stored_lane["lane_pressure_ratio"]) == 0.0


def test_sort_center_create_out_of_range_automation_rejected(api, world):
    """PRD §3.1: "Automation utilization is a percentage between 0 and 100 inclusive carried to two decimal places and defaults to 0 when omitted; `flex_pool_total` must be at least 0, defaults to 0, and is immutable once the center exists — no later operation may change it."

    PRD §2.7 puts numeric range and enum membership together in the priority-3
    shape check: percentages within 0 through 100 inclusive and enum values
    inside their declared sets, else `ERR_INVALID_REQUEST`.

    Design: Corner/entities/sort_center_create_out_of_range_automation_rejected
    """
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    worker = world.create_worker(
        center["id"], full_name="Core Casey", hire_class="CORE", hire_date="2026-07-30"
    )
    rejected_code = f.unique_center_code()

    validate_error(
        api.create_sort_center(
            f.sort_center_payload(
                code=rejected_code,
                name="Bad Automation",
                automation_utilization_pct=101,
                flex_pool_total=5,
            ),
            FACILITY_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )
    _, meta = validate_paginated(
        api.list_sort_centers(FACILITY_ADMIN_HEADERS, code=rejected_code)
    )
    assert meta["total_count"] == 0, "the out-of-range center must not be persisted"

    validate_error(
        api.create_injury_report(
            f.injury_report_payload(
                center["id"],
                worker["id"],
                severity="CATASTROPHIC",
                body_part="BACK",
            ),
            SORT_SUPERVISOR_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )

    stored_center = world.center(center["id"])
    assert stored_center["ops_posture"] == "OPEN"
    assert stored_center["open_serious_injury_count"] == 0


def test_dock_door_create_under_unknown_center_not_found(api):
    """PRD §2.7: "Several resources are addressed as children of a sort center, and their path segments are resolved strictly left to right: the center named by the leading segment must exist before the child identifier is even considered."

    A center that does not exist yields `ERR_SORT_CENTER_NOT_FOUND`.

    Design: Corner/entities/dock_door_create_under_unknown_center_not_found
    """
    validate_error(
        api.create_dock_door(
            NON_EXISTENT_UUID,
            f.dock_door_payload(door_number=1, kind="INBOUND"),
            FACILITY_ADMIN_HEADERS,
        ),
        ERR_SORT_CENTER_NOT_FOUND,
    )


def test_outbound_load_lane_from_other_center_rejected(api, world):
    """PRD §3.8: "The door must be `ACTIVE` and its `kind` must be `OUTBOUND`, otherwise `ERR_DOOR_OUT_OF_SERVICE`; the `trailer_code` must not already be in use at that center by a live appointment or an undispatched load, otherwise `ERR_DUPLICATE_TRAILER_CODE`; the door, lane and center must be consistent, otherwise `ERR_WORKER_CENTER_MISMATCH`; and the destination lane must have at least one chute assignment on record in *any* status, otherwise `ERR_LANE_NOT_ASSIGNED_TO_CHUTE` — a destination that has never been mapped to a chute cannot receive packages, even historically."

    Design: Corner/entities/outbound_load_lane_from_other_center_rejected
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center_one = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    outbound_door = world.create_door(center_one["id"], door_number=1, kind="OUTBOUND")

    center_two = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    far_chute = world.create_chute(center_two["id"], chute_number=1, throughput_pph=1200)
    far_lane = world.create_lane(center_two["id"], forecast_hourly_volume=1000)
    world.map_lane_to_chute(
        far_chute["id"],
        far_lane["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )

    validate_error(
        api.create_outbound_load(
            f.outbound_load_payload(
                center_one["id"],
                outbound_door["id"],
                far_lane["id"],
                trailer_cube_cuft=1000.00,
                dispatch_cut_time="2026-08-03T13:00:00Z",
            ),
            SORT_SUPERVISOR_HEADERS,
        ),
        ERR_WORKER_CENTER_MISMATCH,
    )

    _, meta = validate_paginated(
        api.list_outbound_loads(SORT_SUPERVISOR_HEADERS, sort_center_id=center_one["id"])
    )
    assert meta["total_count"] == 0, "the cross-center load must not be persisted"
