"""Scheduling guards, the two overlap geometries, delivery and cancellation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_trainee,
    assert_instant,
    create_class_session_payload,
    create_facility,
    create_instructor,
    create_session,
    make_instructor_headers,
    open_cohort_for_teaching,
    read_cohort,
    schedule_core_sessions,
    set_clock,
    setup_program_and_curriculum,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _schedule(api, ctx, module_key, starts_at, instructor_key="instructor1",
              facility_key="facility"):
    return api.create_class_session(
        create_class_session_payload(
            ctx["cohort"]["id"], ctx[module_key]["id"], ctx[facility_key]["id"],
            ctx[instructor_key]["id"], starts_at,
        ),
        COORD,
    )


# ---------------------------------------------------------------------------
# Facility interval geometry
# ---------------------------------------------------------------------------

def test_facility_buffer_makes_an_exactly_adjacent_session_collide(api):
    """PRD §3.3: "For the facility, a 30-minute turnover buffer is applied to both ends of
    the *candidate* session only; the candidate therefore occupies the room from 30 minutes
    before its `starts_at` until 30 minutes after its `ends_at`, and it conflicts with any
    existing session in the same facility standing at `SCHEDULED` or `DELIVERED` whose own
    unbuffered half-open interval — start inclusive, end exclusive — intersects that
    buffered span."
    PRD §3.3: "A consequence worth stating plainly: two sessions that are exactly back to
    back in the same room, where the candidate begins at the precise instant the existing
    one ends, **do** conflict, and the rejection is `ERR_FACILITY_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/facility_turnover_buffer_makes_exactly_adjacent_sessions_collide
    """
    ctx = setup_program_and_curriculum()
    session_a = create_session(
        ctx["cohort"]["id"], ctx["m101"]["id"], ctx["facility"]["id"],
        ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
    )
    ctx["session_a"] = session_a
    assert_instant(session_a["ends_at"], "2026-08-03T11:30:00Z", "session A ends_at")

    # A different instructor keeps the instructor rule out of the picture.
    validate_error(
        _schedule(api, ctx, "m102", "2026-08-03T11:30:00Z", instructor_key="instructor2"),
        ApiErrorId.ERR_FACILITY_DOUBLE_BOOKED.value,
    )

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"facility_id": ctx["facility"]["id"]})
    )
    assert meta["total_count"] == 1, "the rejected candidate must not be persisted"


def test_facility_buffer_admits_a_session_thirty_minutes_after_the_previous_end(api):
    """PRD §3.3: "For the facility, a 30-minute turnover buffer is applied to both ends of
    the *candidate* session only; the candidate therefore occupies the room from 30 minutes
    before its `starts_at` until 30 minutes after its `ends_at`, and it conflicts with any
    existing session in the same facility standing at `SCHEDULED` or `DELIVERED` whose own
    unbuffered half-open interval — start inclusive, end exclusive — intersects that
    buffered span."
    PRD §3.3: "`ends_at` is derived by the server as `starts_at` advanced by the module's
    `contact_hours` converted to minutes — a module worth 2.5 contact hours produces a
    session 150 minutes long — and a client-supplied end time is ignored."

    Design: Difficulty/resource_temporal_overlap/facility_turnover_buffer_makes_exactly_adjacent_sessions_collide
    """
    ctx = setup_program_and_curriculum()
    ctx["session_a"] = create_session(
        ctx["cohort"]["id"], ctx["m101"]["id"], ctx["facility"]["id"],
        ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
    )

    session_b = validate_success(
        _schedule(api, ctx, "m102", "2026-08-03T12:00:00Z", instructor_key="instructor2"),
        201,
    )
    assert_instant(session_b["ends_at"], "2026-08-03T14:30:00Z", "session B ends_at")

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"facility_id": ctx["facility"]["id"]})
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Instructor interval geometry and the aggregate daily cap
# ---------------------------------------------------------------------------

def _instructor_cap_scenario():
    ctx = setup_program_and_curriculum(instructor_max_hours=5.0)
    ctx["facility_b"] = create_facility(name="Riverside Annex", room_code="ANX-B",
                                        capacity_seats=40)
    ctx["session_a"] = create_session(
        ctx["cohort"]["id"], ctx["m101"]["id"], ctx["facility"]["id"],
        ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
    )
    return ctx


def test_instructor_overlap_rule_permits_exact_adjacency(api):
    """PRD §3.3: "For the instructor, no buffer is applied at either end; a candidate
    conflicts only when its own unbuffered half-open interval intersects the unbuffered
    half-open interval of another `SCHEDULED` or `DELIVERED` session taught by the same
    instructor. Exact adjacency is therefore perfectly legal for an instructor, and only
    genuine overlap is rejected, with `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/instructor_overlap_allows_adjacency_but_caps_aggregate_day_hours
    """
    ctx = _instructor_cap_scenario()

    session_b = validate_success(
        _schedule(api, ctx, "m102", "2026-08-03T11:30:00Z", facility_key="facility_b"), 201
    )
    assert_instant(session_b["ends_at"], "2026-08-03T14:00:00Z", "session B ends_at")
    assert session_b["instructor_id"] == ctx["instructor1"]["id"]

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"instructor_id": ctx["instructor1"]["id"]})
    )
    assert meta["total_count"] == 2


def test_instructor_daily_contact_hours_cap_is_aggregate_and_per_utc_day(api):
    """PRD §3.3: "That existing load plus the candidate module's own `contact_hours` must be
    less than or equal to the instructor's `max_daily_contact_hours` — a load landing
    exactly on the cap is permitted, and only a load strictly above it is refused, with
    `ERR_INSTRUCTOR_DAILY_LOAD_EXCEEDED`."
    PRD §3.3: "For the UTC calendar date on which the candidate's `starts_at` falls, the
    server sums the `contact_hours` of every session already taught by that instructor
    whose `starts_at` falls on that same UTC calendar date and whose status is `SCHEDULED`
    or `DELIVERED`; cancelled sessions are excluded and give their hours back."

    Design: Difficulty/resource_temporal_overlap/instructor_overlap_allows_adjacency_but_caps_aggregate_day_hours
    """
    ctx = _instructor_cap_scenario()
    ctx["session_b"] = validate_success(
        _schedule(api, ctx, "m102", "2026-08-03T11:30:00Z", facility_key="facility_b"), 201
    )

    # 2.5 + 2.5 already sits exactly on the 5.0-hour cap; another 5.0-hour module cannot fit.
    validate_error(
        _schedule(api, ctx, "m103", "2026-08-03T14:00:00Z"),
        ApiErrorId.ERR_INSTRUCTOR_DAILY_LOAD_EXCEEDED.value,
    )

    session_c = validate_success(
        _schedule(api, ctx, "m103", "2026-08-04T09:00:00Z", facility_key="facility_b"), 201
    )
    assert_instant(session_c["ends_at"], "2026-08-04T14:00:00Z", "session C ends_at")

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"instructor_id": ctx["instructor1"]["id"]})
    )
    assert meta["total_count"] == 3


def test_genuinely_overlapping_bookings_for_one_instructor_are_refused(api):
    """PRD §3.3: "For the instructor, no buffer is applied at either end; a candidate
    conflicts only when its own unbuffered half-open interval intersects the unbuffered
    half-open interval of another `SCHEDULED` or `DELIVERED` session taught by the same
    instructor. Exact adjacency is therefore perfectly legal for an instructor, and only
    genuine overlap is rejected, with `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

    Design: Corner/validations/instructor_booked_in_two_overlapping_rooms_is_refused
    """
    ctx = setup_program_and_curriculum()
    ctx["facility_b"] = create_facility(name="Riverside Annex", room_code="ANX-B",
                                        capacity_seats=40)
    ctx["session_a"] = create_session(
        ctx["cohort"]["id"], ctx["m101"]["id"], ctx["facility"]["id"],
        ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
    )

    validate_error(
        _schedule(api, ctx, "m101", "2026-08-03T10:00:00Z", facility_key="facility_b"),
        ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED.value,
    )

    other = validate_success(
        _schedule(api, ctx, "m101", "2026-08-03T10:00:00Z", instructor_key="instructor2",
                  facility_key="facility_b"),
        201,
    )
    assert other["instructor_id"] == ctx["instructor2"]["id"]
    assert_instant(other["ends_at"], "2026-08-03T12:30:00Z", "second session ends_at")

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"instructor_id": ctx["instructor1"]["id"]})
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Ordering of the scheduling guards
# ---------------------------------------------------------------------------

def test_expired_instructor_certification_is_reported_before_the_prerequisite_gap(api):
    """PRD §2.6: "Safety rules, in this relative order: segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`, 403), instructor certification currency
    (`ERR_INSTRUCTOR_CERT_EXPIRED`, 409), instructor and facility activeness
    (`ERR_RESOURCE_NOT_ACTIVE`, 409), then demonstration attempts exhausted
    (`ERR_DEMO_ATTEMPTS_EXHAUSTED`, 409)."
    PRD §2.6: "Referential business rules, in this relative order: prerequisite not
    scheduled (`ERR_PREREQUISITE_NOT_SCHEDULED`), prerequisite not passed
    (`ERR_PREREQUISITE_NOT_PASSED`), curriculum cycle (`ERR_CURRICULUM_CYCLE`), equipment
    outstanding (`ERR_EQUIPMENT_OUTSTANDING`), and roster commitment outstanding
    (`ERR_ROSTER_COMMITMENT_OUTSTANDING`) — all 409."
    PRD §3.3: "The instructor's own certification must outlast the class:
    `certification_expires_on` must fall strictly after the computed `ends_at` of the
    candidate session, and a certification expiring exactly at the closing bell is not good
    enough — that failure is `ERR_INSTRUCTOR_CERT_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_check_beats_referential_check_on_session_scheduling
    """
    ctx = setup_program_and_curriculum(instructor_cert_expiry="2026-08-02T00:00:00Z")

    validate_error(
        _schedule(api, ctx, "m102", "2026-08-04T09:00:00Z"),
        ApiErrorId.ERR_INSTRUCTOR_CERT_EXPIRED.value,
    )

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"cohort_id": ctx["cohort"]["id"]})
    )
    assert meta["total_count"] == 0


def test_repairing_the_certification_surfaces_the_missing_prerequisite_session(api):
    """PRD §3.3: "When the module being scheduled carries a non-null
    `prerequisite_module_id`, the prerequisite must already have a session on this same
    cohort standing at `SCHEDULED` or `DELIVERED` whose `ends_at` falls at or before the
    candidate's `starts_at`; otherwise the request fails with
    `ERR_PREREQUISITE_NOT_SCHEDULED`."
    PRD §3.1: "A coordinator may later revise an instructor's `certification_expires_on`,
    `max_daily_contact_hours`, or `status`, each revision incrementing the instructor's
    `version`."

    Design: Difficulty/priority_pair_validation_conflict/safety_check_beats_referential_check_on_session_scheduling
    """
    ctx = setup_program_and_curriculum(instructor_cert_expiry="2026-08-02T00:00:00Z")
    validate_error(
        _schedule(api, ctx, "m102", "2026-08-04T09:00:00Z"),
        ApiErrorId.ERR_INSTRUCTOR_CERT_EXPIRED.value,
    )

    patched = validate_success(
        api.patch_instructor(
            ctx["instructor1"]["id"],
            {"certification_expires_on": "2028-01-01T00:00:00Z"},
            COORD,
        )
    )
    assert patched["version"] == 2

    validate_error(
        _schedule(api, ctx, "m102", "2026-08-04T09:00:00Z"),
        ApiErrorId.ERR_PREREQUISITE_NOT_SCHEDULED.value,
    )

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"cohort_id": ctx["cohort"]["id"]})
    )
    assert meta["total_count"] == 0


def _tight_room_scenario():
    """A one-seat room, two confirmed seats, and one session already holding the room."""
    ctx = setup_program_and_curriculum(seat_capacity=2, facility_capacity=1)
    add_trainee(ctx, key="tara", full_name="Tara Nolan")
    ctx["session_a"] = create_session(
        ctx["cohort"]["id"], ctx["m101"]["id"], ctx["facility"]["id"],
        ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
    )
    add_trainee(ctx, key="dev", full_name="Dev Okafor")
    return ctx


def test_facility_double_booking_is_reported_before_room_capacity(api):
    """PRD §2.6: "Temporal rules, in this relative order: facility double-booking
    (`ERR_FACILITY_DOUBLE_BOOKED`), instructor double-booking
    (`ERR_INSTRUCTOR_DOUBLE_BOOKED`), session outside the cohort window
    (`ERR_SESSION_OUTSIDE_COHORT_WINDOW`), and call-out response window closed
    (`ERR_RESPONSE_WINDOW_CLOSED`) — all 409."
    PRD §2.6: "Remaining business constraints, in this relative order: attendance
    insufficient (`ERR_ATTENDANCE_INSUFFICIENT`, 422), duplicate completion
    (`ERR_DUPLICATE_COMPLETION`, 409), facility capacity insufficient
    (`ERR_FACILITY_CAPACITY_INSUFFICIENT`, 409), instructor daily load exceeded
    (`ERR_INSTRUCTOR_DAILY_LOAD_EXCEEDED`, 409), no eligible responders
    (`ERR_NO_ELIGIBLE_RESPONDERS`, 409), manually added trainee not eligible
    (`ERR_TRAINEE_NOT_ELIGIBLE`, 409), no asset available (`ERR_NO_ASSET_AVAILABLE`, 409),
    trainee already holding that kit type (`ERR_TRAINEE_ALREADY_ISSUED_KIT`, 409), refresher
    hours insufficient (`ERR_REFRESHER_HOURS_INSUFFICIENT`, 422), core modules incomplete
    (`ERR_CORE_MODULES_INCOMPLETE`, 422), credential already issued
    (`ERR_CREDENTIAL_ALREADY_ISSUED`, 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_check_beats_constraint_check_on_facility_booking
    """
    ctx = _tight_room_scenario()
    assert read_cohort(ctx)["seats_confirmed"] == 2

    validate_error(
        _schedule(api, ctx, "m102", "2026-08-03T11:30:00Z"),
        ApiErrorId.ERR_FACILITY_DOUBLE_BOOKED.value,
    )

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"cohort_id": ctx["cohort"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_free_day_still_surfaces_the_room_capacity_shortfall(api):
    """PRD §3.3: "The room must be able to hold the class: the facility's `capacity_seats`
    must be greater than or equal to the cohort's current `seats_confirmed`, otherwise
    `ERR_FACILITY_CAPACITY_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_check_beats_constraint_check_on_facility_booking
    """
    ctx = _tight_room_scenario()
    assert read_cohort(ctx)["seats_confirmed"] == 2

    validate_error(
        _schedule(api, ctx, "m102", "2026-08-04T09:00:00Z"),
        ApiErrorId.ERR_FACILITY_CAPACITY_INSUFFICIENT.value,
    )

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"cohort_id": ctx["cohort"]["id"]})
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Remaining scheduling guards
# ---------------------------------------------------------------------------

def test_sessions_must_fit_inside_the_cohort_teaching_window(api):
    """PRD §3.3: "The session must sit inside its cohort's teaching window: `starts_at`
    must be at or after the cohort's `session_window_start` and the computed `ends_at` must
    be at or before the cohort's `session_window_end`, failing which the request is
    rejected with `ERR_SESSION_OUTSIDE_COHORT_WINDOW`."

    Design: Corner/validations/session_outside_the_cohort_window_is_rejected
    """
    ctx = setup_program_and_curriculum()

    validate_error(
        _schedule(api, ctx, "m101", "2026-12-31T22:00:00Z"),
        ApiErrorId.ERR_SESSION_OUTSIDE_COHORT_WINDOW.value,
    )
    validate_error(
        _schedule(api, ctx, "m101", "2026-07-31T09:00:00Z"),
        ApiErrorId.ERR_SESSION_OUTSIDE_COHORT_WINDOW.value,
    )

    accepted = validate_success(_schedule(api, ctx, "m101", "2026-12-31T20:30:00Z"), 201)
    assert_instant(accepted["ends_at"], "2026-12-31T23:00:00Z", "boundary session ends_at")


def test_inactive_instructor_or_closed_facility_blocks_scheduling(api):
    """PRD §3.3: "The teaching staff must be usable at all: an instructor whose `status` is
    not `ACTIVE`, or a facility whose `status` is not `ACTIVE`, is rejected with
    `ERR_RESOURCE_NOT_ACTIVE`."
    PRD §3.1: "A coordinator may later revise an instructor's `certification_expires_on`,
    `max_daily_contact_hours`, or `status`, each revision incrementing the instructor's
    `version`."

    Design: Corner/validations/inactive_instructor_or_closed_facility_blocks_scheduling
    """
    ctx = setup_program_and_curriculum()
    ctx["instructor3"] = create_instructor(
        full_name="Sam Vale", certification_expires_on="2028-01-01T00:00:00Z",
        max_daily_contact_hours=8.0, status="INACTIVE",
    )
    ctx["facility_c"] = create_facility(name="Closed Annex", room_code="ANX-C",
                                        capacity_seats=20, status="CLOSED")

    validate_error(
        _schedule(api, ctx, "m101", "2026-08-03T09:00:00Z", instructor_key="instructor3"),
        ApiErrorId.ERR_RESOURCE_NOT_ACTIVE.value,
    )
    validate_error(
        _schedule(api, ctx, "m101", "2026-08-03T09:00:00Z", facility_key="facility_c"),
        ApiErrorId.ERR_RESOURCE_NOT_ACTIVE.value,
    )

    reactivated = validate_success(
        api.patch_instructor(ctx["instructor3"]["id"], {"status": "ACTIVE"}, COORD)
    )
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["version"] == 2

    session = validate_success(
        _schedule(api, ctx, "m101", "2026-08-03T09:00:00Z", instructor_key="instructor3"),
        201,
    )
    assert session["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Delivery and cancellation
# ---------------------------------------------------------------------------

def test_cancelling_a_session_twice_is_an_illegal_transition(api):
    """PRD §3.3: "Cancelling from `SCHEDULED` simply moves the session to `CANCELLED` and
    releases the facility and instructor intervals it was holding, so that time becomes
    available to both overlap checks again."
    PRD §3.3: "`CANCELLED` is terminal for a session."
    PRD §2.6: "Legality of the requested state transition (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/cancel_class_session_twice_returns_invalid_state
    """
    ctx = setup_program_and_curriculum()
    ctx["session_a"] = create_session(
        ctx["cohort"]["id"], ctx["m101"]["id"], ctx["facility"]["id"],
        ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
    )

    cancelled = validate_success(
        api.cancel_class_session(ctx["session_a"]["id"], {"reason": "Room flooded"}, COORD)
    )
    assert cancelled["status"] == "CANCELLED"

    validate_error(
        api.cancel_class_session(
            ctx["session_a"]["id"], {"reason": "Cancelled again by mistake"}, COORD
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert validate_success(
        api.get_class_session(ctx["session_a"]["id"], AUDITOR)
    )["status"] == "CANCELLED"
    assert read_cohort(ctx)["delivered_contact_hours"] == 0


def test_delivering_a_session_twice_does_not_double_count_cohort_hours(api):
    """PRD §3.3: "On success, `delivered_at` is stamped from the logical clock and the
    cohort's `delivered_contact_hours` is increased by the module's `contact_hours`."
    PRD §2.6: "Legality of the requested state transition (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/deliver_class_session_twice_returns_invalid_state
    """
    ctx = setup_program_and_curriculum()
    schedule_core_sessions(ctx)
    add_trainee(ctx, key="tara", full_name="Tara Nolan")
    open_cohort_for_teaching(ctx)
    set_clock("2026-08-03T12:00:00Z")

    headers = make_instructor_headers(ctx["instructor1"]["id"])
    delivered = validate_success(
        api.deliver_class_session(ctx["session_a"]["id"], headers)
    )
    assert delivered["status"] == "DELIVERED"
    assert_instant(delivered["delivered_at"], "2026-08-03T12:00:00Z", "delivered_at")
    assert read_cohort(ctx)["delivered_contact_hours"] == 2.5

    validate_error(
        api.deliver_class_session(ctx["session_a"]["id"], headers),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_cohort(ctx)["delivered_contact_hours"] == 2.5, (
        "a refused second delivery must not credit the hours again"
    )


def test_only_the_assigned_instructor_may_mark_a_session_delivered(api):
    """PRD §3.3: "Moving a session `SCHEDULED → DELIVERED` requires that the acting
    `X-User-ID` equals the session's `instructor_id`, that the owning cohort is
    `IN_SESSION`, that the logical clock has reached or passed the session's `starts_at`,
    and that the instructor's `certification_expires_on` is strictly after the logical
    clock at that moment — an instructor whose certification lapsed between scheduling and
    teaching is stopped with `ERR_INSTRUCTOR_CERT_EXPIRED`."
    PRD §2.1: "An entity-backed role acting on a resource it does not own is rejected with
    `ERR_NOT_RESOURCE_OWNER` and HTTP 403."

    Design: Corner/rbac/instructor_cannot_deliver_another_instructors_session
    """
    ctx = setup_program_and_curriculum()
    schedule_core_sessions(ctx)
    add_trainee(ctx, key="tara", full_name="Tara Nolan")
    open_cohort_for_teaching(ctx)
    set_clock("2026-08-03T12:00:00Z")

    validate_error(
        api.deliver_class_session(
            ctx["session_a"]["id"], make_instructor_headers(ctx["instructor2"]["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    assert validate_success(
        api.get_class_session(ctx["session_a"]["id"], AUDITOR)
    )["status"] == "SCHEDULED"

    delivered = validate_success(
        api.deliver_class_session(
            ctx["session_a"]["id"], make_instructor_headers(ctx["instructor1"]["id"])
        )
    )
    assert delivered["status"] == "DELIVERED"
    assert read_cohort(ctx)["delivered_contact_hours"] == 2.5


def test_class_session_listing_honours_every_declared_filter(api):
    """PRD §3.3: "Sessions may be listed and filtered by `cohort_id`, `module_id`,
    `facility_id`, `instructor_id`, and `status`."
    PRD §2.3: "For list responses the `meta` object carries `limit` and `offset` as they
    were applied, `total_count` giving the number of rows matching the filter before
    pagination is applied, and `has_more`, which is true exactly when the offset plus the
    number of returned rows is less than `total_count`."

    Design: Corner/endpoints/class_session_list_supports_every_declared_filter
    """
    ctx = setup_program_and_curriculum()
    cohort_id = ctx["cohort"]["id"]
    facility_id = ctx["facility"]["id"]
    session_a = create_session(cohort_id, ctx["m101"]["id"], facility_id,
                               ctx["instructor1"]["id"], "2026-08-03T09:00:00Z")
    create_session(cohort_id, ctx["m102"]["id"], facility_id,
                   ctx["instructor1"]["id"], "2026-08-04T09:00:00Z")
    session_c = create_session(cohort_id, ctx["m103"]["id"], facility_id,
                               ctx["instructor2"]["id"], "2026-08-05T09:00:00Z")
    validate_success(api.cancel_class_session(session_a["id"], {"reason": "Audit"}, COORD))

    _, meta = validate_paginated(api.list_class_sessions(AUDITOR, {"cohort_id": cohort_id}))
    assert meta["total_count"] == 3

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"instructor_id": ctx["instructor1"]["id"]})
    )
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"module_id": ctx["m103"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == session_c["id"]

    rows, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"cohort_id": cohort_id, "status": "CANCELLED"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == session_a["id"]

    rows, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"facility_id": facility_id, "limit": 2,
                                          "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
