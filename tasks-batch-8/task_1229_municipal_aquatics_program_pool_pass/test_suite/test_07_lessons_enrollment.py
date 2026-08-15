"""Swim lesson sessions, lane gating, enrollment prerequisites, and the
waitlist promotion loop (PRD §3.6)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS, ApiErrorId,
    assert_lesson_session, assert_enrollment,
    create_lesson_level_payload, create_lesson_session_payload,
    create_enrollment_payload, create_lane_allocation_payload,
    make_facility, make_season, make_pass_holder, make_lesson_level,
    make_enrollment, set_clock, facility_version, get_facility,
    setup_scheduled_lesson_session, make_passholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def test_lesson_session_initial_state_draft(api):
    """PRD §3.6: "A `LessonSession` is created in `DRAFT` against a
    `facility_id`, `level_id`, and `season_id`, with a `start_datetime`, an
    `end_datetime` strictly after it, and a `lanes_required` of at least 1."

    Design: Corner/state_machines/lesson_session_initial_state_draft
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    season = make_season(facility["id"])
    level = make_lesson_level(level_code="L1", display_name="L1")
    session = validate_success(
        api.create_lesson_session(
            create_lesson_session_payload(
                facility["id"], level["id"], season["id"]
            ),
            MANAGER,
        ),
        expected_status=201,
    )
    assert_lesson_session(session)
    assert session["status"] == "DRAFT"
    assert session["enrolled_count"] == 0


def test_session_outside_season_returns_422(api):
    """PRD §3.6: "The session window must lie entirely inside its season —
    `start_datetime` on or after `start_date`, and `end_datetime` no later
    than the day after `end_date` — otherwise creation (and later scheduling)
    is rejected with `ERR_SESSION_OUTSIDE_SEASON` (HTTP 422)."

    Design: Corner/validations/session_outside_season_returns_422
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    season = make_season(facility["id"])
    level = make_lesson_level(level_code="L1", display_name="L1")
    resp = api.create_lesson_session(
        create_lesson_session_payload(
            facility["id"], level["id"], season["id"],
            start_datetime="2026-08-01T09:00:00Z",
            end_datetime="2026-09-15T10:00:00Z",
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_OUTSIDE_SEASON)


def test_lesson_prerequisite_not_met_returns_422(api):
    """PRD §3.6: "The prerequisite check compares this evidence against the
    level's `prerequisite_level_id`: enrollment is allowed when the level has
    no prerequisite, or when the evidence level matches the declared
    prerequisite exactly; the patron's age on the session's start date must
    also be at least `min_age_years`. Violations are rejected with
    `ERR_PREREQUISITE_NOT_MET` (HTTP 422)."

    Design: Corner/validations/lesson_prerequisite_not_met_returns_422
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    season = make_season(facility["id"])
    l1 = make_lesson_level(level_code="L1", display_name="L1")
    l2 = make_lesson_level(
        level_code="L2", display_name="L2", min_age_years=6,
        prerequisite_level_id=l1["id"],
    )
    session = get_success_data(
        api.create_lesson_session(
            create_lesson_session_payload(
                facility["id"], l2["id"], season["id"]
            ),
            MANAGER,
        )
    )
    fv = facility_version(facility["id"])
    get_success_data(
        api.schedule_lesson_session(
            session["id"], {"expected_facility_version": fv}, MANAGER
        )
    )
    holder = make_pass_holder(date_of_birth="2015-01-01T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    resp = api.create_enrollment(
        create_enrollment_payload(session["id"], holder["id"]), GATE
    )
    validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET)


def test_lesson_schedule_blocked_when_lanes_exhausted(api):
    """PRD §3.6: "it also requires the facility to be `OPEN`
    (`ERR_FACILITY_CLOSED` otherwise) and requires lane availability: at every
    instant of the session window, the sum of `lane_count` over overlapping
    `RESERVED` lane allocations plus the session's `lanes_required` must not
    exceed the facility's `lap_lane_count`, with overlap evaluated on
    half-open intervals (`ERR_LANE_CAPACITY_EXCEEDED` when insufficient)."

    Design: Difficulty/cross_entity_state_dependency/lesson_session_schedule_gated_by_lane_availability
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=2)
    season = make_season(facility["id"])
    level = make_lesson_level(
        level_code="L1", display_name="Lvl1", capacity_per_session=5
    )
    set_clock("2026-06-20T00:00:00Z")
    allocation = get_success_data(
        api.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="SWIM_TEAM",
                start_datetime="2026-07-08T09:00:00Z",
                end_datetime="2026-07-08T11:00:00Z",
                lane_count=2,
            ),
            MANAGER,
        )
    )
    session = get_success_data(
        api.create_lesson_session(
            create_lesson_session_payload(
                facility["id"], level["id"], season["id"],
                start_datetime="2026-07-08T09:00:00Z",
                end_datetime="2026-07-08T10:00:00Z",
                lanes_required=1,
            ),
            MANAGER,
        )
    )
    fv = facility_version(facility["id"])
    resp = api.schedule_lesson_session(
        session["id"], {"expected_facility_version": fv}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED)
    session_after = validate_success(api.get_lesson_session(session["id"], MANAGER))
    assert session_after["status"] == "DRAFT"


def test_lesson_schedule_succeeds_when_lanes_available(api):
    """PRD §3.6: "A successful schedule creates a `LaneAllocation` with
    `purpose` of `LESSON` and `owning_lesson_session_id` pointing at the new
    session, reserving `lanes_required` lanes for the session window."
    PRD §3.6: "at every instant of the session window, the sum of `lane_count`
    over overlapping `RESERVED` lane allocations plus the session's
    `lanes_required` must not exceed the facility's `lap_lane_count`".

    Design: Difficulty/cross_entity_state_dependency/lesson_session_schedule_gated_by_lane_availability
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    season = make_season(facility["id"])
    level = make_lesson_level(level_code="L1", display_name="Lvl1")
    set_clock("2026-06-20T00:00:00Z")
    # Two lanes reserved 09:00-11:00; a 1-lane session fits (2 + 1 <= 4).
    get_success_data(
        api.create_lane_allocation(
            create_lane_allocation_payload(
                facility["id"],
                purpose="SWIM_TEAM",
                start_datetime="2026-07-08T09:00:00Z",
                end_datetime="2026-07-08T11:00:00Z",
                lane_count=2,
            ),
            MANAGER,
        )
    )
    session = get_success_data(
        api.create_lesson_session(
            create_lesson_session_payload(
                facility["id"], level["id"], season["id"],
                start_datetime="2026-07-08T09:00:00Z",
                end_datetime="2026-07-08T10:00:00Z",
                lanes_required=1,
            ),
            MANAGER,
        )
    )
    fv = facility_version(facility["id"])
    scheduled = validate_success(
        api.schedule_lesson_session(
            session["id"], {"expected_facility_version": fv}, MANAGER
        )
    )
    assert_lesson_session(scheduled)
    assert scheduled["status"] == "SCHEDULED"
    allocations, meta = validate_paginated(
        api.list_session_lane_allocations(session["id"], MANAGER)
    )
    assert len(allocations) == 1
    assert allocations[0]["purpose"] == "LESSON"
    assert allocations[0]["owning_lesson_session_id"] == session["id"]
    assert allocations[0]["lane_count"] == 1
    assert allocations[0]["status"] == "RESERVED"


def _setup_waitlist_scenario(capacity=1):
    """Session (capacity `capacity`) with holders; clock before start."""
    facility, season, level, session = setup_scheduled_lesson_session(
        clock="2026-06-15T00:00:00Z",
        facility_overrides=dict(max_bather_capacity=100, lap_lane_count=4),
        level_overrides=dict(
            level_code="L1", display_name="Water Acclimation",
            min_age_years=5, capacity_per_session=capacity,
        ),
        session_overrides=dict(
            start_datetime="2026-07-01T09:00:00Z",
            end_datetime="2026-07-31T10:00:00Z",
            lanes_required=1,
        ),
    )
    return facility, season, level, session


def test_waitlist_promotion_on_enrolled_drop(api):
    """PRD §3.6: "When the session is full, the enrollment is created in
    `WAITLISTED` and assigned the next `waitlist_position` — one more than
    the count of existing `WAITLISTED` enrollments for that session, so the
    first waitlisted patron is position 1."
    PRD §3.6: "Dropping an `ENROLLED` enrollment decrements the session's
    `enrolled_count`, promotes the waitlist head — the `WAITLISTED`
    enrollment with the lowest `waitlist_position`, ties broken by earliest
    `created_at` — to `ENROLLED`, sets that promoted enrollment's
    `waitlist_position` to null, increments `enrolled_count` back by 1".

    Design: Difficulty/non_linear_state_machine/lesson_enrollment_waitlist_promotion_loop
    """
    facility, season, level, session = _setup_waitlist_scenario(capacity=1)
    a = make_pass_holder(full_name="A", date_of_birth="2015-01-01T00:00:00Z")
    b = make_pass_holder(full_name="B", date_of_birth="2015-06-01T00:00:00Z")
    enr_a = make_enrollment(session["id"], a["id"])
    enr_b = make_enrollment(session["id"], b["id"])
    assert_enrollment(enr_a)
    assert_enrollment(enr_b)
    assert enr_a["status"] == "ENROLLED"
    assert enr_b["status"] == "WAITLISTED"
    assert enr_b["waitlist_position"] == 1
    dropped = validate_success(
        api.drop_enrollment(enr_a["id"], make_passholder_headers(a["id"]))
    )
    assert dropped["status"] == "DROPPED"
    enr_b_after = validate_success(api.get_enrollment(enr_b["id"], GATE))
    assert enr_b_after["status"] == "ENROLLED"
    assert enr_b_after["waitlist_position"] is None
    session_after = validate_success(
        api.get_lesson_session(session["id"], MANAGER)
    )
    assert session_after["enrolled_count"] == 1


def test_waitlist_renumbering_after_promotion(api):
    """PRD §3.6: "Dropping an `ENROLLED` enrollment decrements the session's
    `enrolled_count`, promotes the waitlist head — the `WAITLISTED`
    enrollment with the lowest `waitlist_position`, ties broken by earliest
    `created_at` — to `ENROLLED`, sets that promoted enrollment's
    `waitlist_position` to null, increments `enrolled_count` back by 1, and
    re-numbers the remaining waitlist so positions shift up by 1."

    Design: Difficulty/non_linear_state_machine/lesson_enrollment_waitlist_promotion_loop
    """
    facility, season, level, session = _setup_waitlist_scenario(capacity=1)
    a = make_pass_holder(full_name="A", date_of_birth="2015-01-01T00:00:00Z")
    b = make_pass_holder(full_name="B", date_of_birth="2015-06-01T00:00:00Z")
    c = make_pass_holder(full_name="C", date_of_birth="2015-03-01T00:00:00Z")
    enr_a = make_enrollment(session["id"], a["id"])
    enr_b = make_enrollment(session["id"], b["id"])
    enr_c = make_enrollment(session["id"], c["id"])
    assert enr_a["status"] == "ENROLLED"
    assert enr_b["status"] == "WAITLISTED" and enr_b["waitlist_position"] == 1
    assert enr_c["status"] == "WAITLISTED" and enr_c["waitlist_position"] == 2
    validate_success(api.drop_enrollment(enr_a["id"], make_passholder_headers(a["id"])))
    enr_b_after = validate_success(api.get_enrollment(enr_b["id"], GATE))
    enr_c_after = validate_success(api.get_enrollment(enr_c["id"], GATE))
    assert enr_b_after["status"] == "ENROLLED"
    assert enr_b_after["waitlist_position"] is None
    assert enr_c_after["status"] == "WAITLISTED"
    assert enr_c_after["waitlist_position"] == 1, (
        "Remaining waitlist positions must shift up by 1 after promotion"
    )
    session_after = validate_success(
        api.get_lesson_session(session["id"], MANAGER)
    )
    assert session_after["enrolled_count"] == 1


def test_passholder_cannot_drop_other_holder_enrollment(api):
    """PRD §3.6: "Dropping an enrollment is permitted for the patron
    themselves (when `X-User-ID` equals the enrollment's `pass_holder_id`) or
    for a manager."
    PRD §2.1: "A request whose role is well-formed but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/passholder_cannot_drop_other_holder_enrollment
    """
    facility, season, level, session = _setup_waitlist_scenario(capacity=10)
    a = make_pass_holder(full_name="A", date_of_birth="2015-01-01T00:00:00Z")
    b = make_pass_holder(full_name="B", date_of_birth="2015-01-01T00:00:00Z")
    enr = make_enrollment(session["id"], a["id"])
    resp = api.drop_enrollment(enr["id"], make_passholder_headers(b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    enr_after = validate_success(api.get_enrollment(enr["id"], GATE))
    assert enr_after["status"] == "ENROLLED"
