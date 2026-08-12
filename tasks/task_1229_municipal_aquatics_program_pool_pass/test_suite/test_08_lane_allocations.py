"""Lane allocation aggregate capacity and the reserve/release conservation
invariant across a lesson session's lifecycle (PRD §3.6, §3.7)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS, ApiErrorId,
    assert_lane_allocation,
    create_lane_allocation_payload, create_lesson_session_payload,
    make_facility, make_season, make_lesson_level, make_pass_holder,
    make_enrollment, set_clock, facility_version, get_facility,
    make_lifeguard, make_chemistry_log,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def _reserved_lane_allocations(facility_id):
    """All RESERVED allocations at the facility, filtered client-side from the
    full listing (PRD §2.3 pagination meta) so no unstated query-filter
    behavior is assumed."""
    data, meta = validate_paginated(
        api_client.list_lane_allocations(
            MANAGER, params={"facility_id": facility_id, "limit": 100}
        )
    )
    return [a for a in data if a["status"] == "RESERVED"]


def test_lane_allocation_aggregate_overlap_within_capacity(api):
    """PRD §3.7: "The same capacity rule applies — overlapping `RESERVED`
    allocations plus the new `lane_count` must not exceed `lap_lane_count`,
    on half-open intervals (`ERR_LANE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/resource_temporal_overlap/lane_allocation_aggregate_capacity_overlap
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    set_clock("2026-07-01T00:00:00Z")
    la1 = validate_success(
        api.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="SWIM_TEAM",
                start_datetime="2026-07-15T09:00:00Z",
                end_datetime="2026-07-15T11:00:00Z",
                lane_count=2,
            ),
            MANAGER,
        ),
        expected_status=201,
    )
    # Overlaps la1 by one hour; worst-instant sum is 2 + 2 = 4 <= 4.
    la2 = validate_success(
        api.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="LAP_SWIM",
                start_datetime="2026-07-15T10:00:00Z",
                end_datetime="2026-07-15T12:00:00Z",
                lane_count=2,
            ),
            MANAGER,
        ),
        expected_status=201,
    )
    assert_lane_allocation(la1)
    assert_lane_allocation(la2)
    assert la1["status"] == "RESERVED"
    assert la2["status"] == "RESERVED"


def test_lane_allocation_aggregate_overlap_beyond_capacity(api):
    """PRD §3.7: "The same capacity rule applies — overlapping `RESERVED`
    allocations plus the new `lane_count` must not exceed `lap_lane_count`,
    on half-open intervals (`ERR_LANE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/resource_temporal_overlap/lane_allocation_aggregate_capacity_overlap
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    set_clock("2026-07-01T00:00:00Z")
    get_success_data(
        api.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="SWIM_TEAM",
                start_datetime="2026-07-15T09:00:00Z",
                end_datetime="2026-07-15T11:00:00Z",
                lane_count=2,
            ),
            MANAGER,
        )
    )
    get_success_data(
        api.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="LAP_SWIM",
                start_datetime="2026-07-15T10:00:00Z",
                end_datetime="2026-07-15T12:00:00Z",
                lane_count=2,
            ),
            MANAGER,
        )
    )
    # Worst-instant sum would be 2 + 2 + 1 = 5 > 4.
    resp = api.create_lane_allocation(
        create_lane_allocation_payload(
            facility["id"],
            purpose="SWIM_TEAM",
            start_datetime="2026-07-15T10:30:00Z",
            end_datetime="2026-07-15T11:30:00Z",
            lane_count=1,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED)
    reserved = _reserved_lane_allocations(facility["id"])
    assert len(reserved) == 2


def _setup_lane_pool_invariant_scenario():
    """Facility (4 lanes) + season + level + LA0 (1 lane RESERVED) + DRAFT
    session (2 lanes) over 2026-07-01 09:00-10:00."""
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    season = make_season(facility["id"])
    level = make_lesson_level(
        level_code="L1", display_name="Lvl1", min_age_years=5,
        capacity_per_session=10,
    )
    set_clock("2026-06-25T00:00:00Z")
    la0 = get_success_data(
        api_client.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="SWIM_TEAM",
                start_datetime="2026-07-01T08:00:00Z",
                end_datetime="2026-07-01T12:00:00Z",
                lane_count=1,
            ),
            MANAGER,
        )
    )
    session = get_success_data(
        api_client.create_lesson_session(
            create_lesson_session_payload(
                facility["id"], level["id"], season["id"],
                start_datetime="2026-07-01T09:00:00Z",
                end_datetime="2026-07-01T10:00:00Z",
                lanes_required=2,
            ),
            MANAGER,
        )
    )
    return facility, season, level, la0, session


def test_lane_pool_reserve_then_release_on_completion(api):
    """PRD §3.6: "A successful schedule creates a `LaneAllocation` with
    `purpose` of `LESSON` and `owning_lesson_session_id` pointing at the new
    session, reserving `lanes_required` lanes for the session window."
    PRD §3.6: "when the end time is reached the session transitions to
    `COMPLETED`, releasing its owned lane allocation and moving every
    `ENROLLED` enrollment to `COMPLETED`."

    Design: Difficulty/compensating_invariant/lane_pool_reserve_release_invariant
    """
    facility, season, level, la0, session = _setup_lane_pool_invariant_scenario()
    fv = facility_version(facility["id"])
    scheduled = validate_success(
        api.schedule_lesson_session(
            session["id"], {"expected_facility_version": fv}, MANAGER
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    reserved_during = _reserved_lane_allocations(facility["id"])
    assert sum(a["lane_count"] for a in reserved_during) == 3, (
        "During the session the RESERVED lane sum must be 1 (pre-existing) "
        "+ 2 (lesson) = 3"
    )
    # Advance past the session end: the session completes and releases lanes.
    set_clock("2026-07-01T10:00:01Z")
    session_after = validate_success(api.get_lesson_session(session["id"], MANAGER))
    assert session_after["status"] == "COMPLETED"
    reserved_after = _reserved_lane_allocations(facility["id"])
    assert sum(a["lane_count"] for a in reserved_after) == 1, (
        "After completion only the pre-existing 1-lane allocation remains "
        "RESERVED"
    )
    lesson_allocations, _ = validate_paginated(
        api.list_session_lane_allocations(session["id"], MANAGER)
    )
    assert len(lesson_allocations) == 1
    assert lesson_allocations[0]["status"] == "RELEASED"


def test_lane_pool_release_moves_enrollments_to_completed(api):
    """PRD §3.6: "Sessions whose start time is reached while the facility is
    `OPEN` or `RESTRICTED` transition from `SCHEDULED` to `IN_PROGRESS`; when
    the end time is reached the session transitions to `COMPLETED`, releasing
    its owned lane allocation and moving every `ENROLLED` enrollment to
    `COMPLETED`."

    Design: Difficulty/compensating_invariant/lane_pool_reserve_release_invariant
    """
    facility, season, level, la0, session = _setup_lane_pool_invariant_scenario()
    fv = facility_version(facility["id"])
    get_success_data(
        api.schedule_lesson_session(
            session["id"], {"expected_facility_version": fv}, MANAGER
        )
    )
    holder = make_pass_holder(date_of_birth="2015-01-01T00:00:00Z")
    enrollment = make_enrollment(session["id"], holder["id"])
    assert enrollment["status"] == "ENROLLED"
    baseline = sum(
        a["lane_count"] for a in _reserved_lane_allocations(facility["id"])
    )
    set_clock("2026-07-01T10:00:01Z")
    session_after = validate_success(api.get_lesson_session(session["id"], MANAGER))
    assert session_after["status"] == "COMPLETED"
    enrollment_after = validate_success(
        api.get_enrollment(enrollment["id"], GATE)
    )
    assert enrollment_after["status"] == "COMPLETED"
    restored = sum(
        a["lane_count"] for a in _reserved_lane_allocations(facility["id"])
    )
    assert restored == baseline - 2, (
        "Completion must release exactly the session's reserved lanes"
    )
