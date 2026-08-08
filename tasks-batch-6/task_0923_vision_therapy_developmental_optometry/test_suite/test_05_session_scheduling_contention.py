"""Booking an in-office session: credentials, rooms, clinicians, the day cap and the pool."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_visit_unit_identity,
    auth_version,
    create_session_payload,
    new_therapist,
    read_authorization,
    schedule_session,
    setup_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def _book(api, scn, therapist_id, room_id, start, end, version=None):
    return api.create_session(
        scn["plan"],
        create_session_payload(
            therapist_id,
            room_id,
            start,
            end,
            version if version is not None else auth_version(scn["auth"]),
        ),
        scn["hdr_front"],
    )


# --------------------------------------------------------------------------
# Rung 16 (credential) versus rung 20 (room)
# --------------------------------------------------------------------------


def test_expired_credential_is_reported_before_the_room_collision(api):
    """PRD §2.7 rung 16: "**Credential currency.** The `Therapist` named in
    `therapist_id` has a `credential_expires_at` strictly after `scheduled_start_at`
    when the session is scheduled, and strictly after `performed_at` when the session
    is completed. An expiry exactly equal to the instant in question fails. Otherwise
    `ERR_CREDENTIAL_EXPIRED`, HTTP 422."
    PRD §2.7: "Every request walks the following thirty-six rungs from rung 1 downward
    and stops at the first rung whose condition is violated."
    PRD §2.7 rung 20: "**Room occupancy.** The requested room is free once a
    fifteen-minute turnover buffer is applied on both sides. Otherwise
    `ERR_ROOM_CONFLICT`, HTTP 409. Applies to in-office session scheduling."

    Design: Difficulty/priority_pair_validation_conflict/credential_expired_pre_empts_room_conflict
    """
    scn = setup_active_plan()
    expired = new_therapist(
        full_name="Dr Vale",
        credential="OPTOMETRIST",
        credential_expires_at="2026-06-05T00:00:00Z",
    )
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])

    response = _book(
        api,
        scn,
        expired["id"],
        scn["room_a"],
        "2026-06-10T09:30:00Z",
        "2026-06-10T10:30:00Z",
    )

    validate_error(response, ApiErrorId.ERR_CREDENTIAL_EXPIRED.value, 422)
    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 1 and pool["visits_remaining"] == 11
    assert_visit_unit_identity(pool)


def test_the_same_slot_with_a_current_credential_reports_the_room_collision(api):
    """PRD §3.5: "A **room** carries a fifteen-minute turnover buffer applied on both
    sides: the booking is refused when some other session on the same `room_id`, in
    `schedule_status` `SCHEDULED`, `CHECKED_IN` or `COMPLETED`, satisfies both of two
    conditions at once — the new session's `scheduled_start_at` is earlier than that
    session's `scheduled_end_at` advanced by fifteen minutes, and that session's
    `scheduled_start_at` is earlier than the new session's `scheduled_end_at` advanced
    by fifteen minutes."

    Design: Difficulty/priority_pair_validation_conflict/credential_expired_pre_empts_room_conflict
    """
    scn = setup_active_plan()
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])

    response = _book(
        api,
        scn,
        scn["od2"],
        scn["room_a"],
        "2026-06-10T09:30:00Z",
        "2026-06-10T10:30:00Z",
    )

    validate_error(response, ApiErrorId.ERR_ROOM_CONFLICT.value, 409)
    rows, meta = validate_paginated(
        api.list_sessions(scn["hdr_front"], {"plan_id": scn["plan"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1, f"Expected exactly one booking, got {meta['total_count']}"


# --------------------------------------------------------------------------
# Rung 20 (room) versus rung 23 (visit pool)
# --------------------------------------------------------------------------


def test_room_collision_is_reported_before_the_exhausted_pool(api):
    """PRD §2.7 rung 23: "**Visit pool.** The plan's authorization has at least one
    visit remaining. Otherwise `ERR_AUTH_VISITS_EXHAUSTED`, HTTP 409. Applies to
    in-office session scheduling."
    PRD §2.7 rung 20: "**Room occupancy.** The requested room is free once a
    fifteen-minute turnover buffer is applied on both sides. Otherwise
    `ERR_ROOM_CONFLICT`, HTTP 409. Applies to in-office session scheduling."
    PRD §3.3: "scheduling the session that takes the last unit consumes it, drives
    `visits_remaining` to 0 and moves the pool `ACTIVE → EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/room_conflict_pre_empts_visits_exhausted
    """
    scn = setup_active_plan(visits_authorized=1)
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])

    pool = read_authorization(scn["auth"])
    assert pool["status"] == "EXHAUSTED"
    assert pool["visits_remaining"] == 0

    response = _book(
        api,
        scn,
        scn["od2"],
        scn["room_a"],
        "2026-06-10T09:30:00Z",
        "2026-06-10T10:30:00Z",
    )

    validate_error(response, ApiErrorId.ERR_ROOM_CONFLICT.value, 409)


def test_a_free_room_against_an_exhausted_pool_reports_visits_exhausted(api):
    """PRD §3.3: "`EXHAUSTED` is deliberately treated as an *open* state, not an
    illegal one: a scheduling attempt against an exhausted pool is refused as a
    business failure with `ERR_AUTH_VISITS_EXHAUSTED`, never as `ERR_INVALID_STATE`."
    PRD §3.5: "The plan's pool must have at least one visit remaining, or the booking
    is refused with `ERR_AUTH_VISITS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/room_conflict_pre_empts_visits_exhausted
    """
    scn = setup_active_plan(visits_authorized=1)
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])

    response = _book(
        api,
        scn,
        scn["od2"],
        scn["room_b"],
        "2026-06-11T09:00:00Z",
        "2026-06-11T10:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_AUTH_VISITS_EXHAUSTED.value, 409)
    pool = read_authorization(scn["auth"])
    assert pool["visits_authorized"] == 1
    assert pool["visits_consumed"] == 1
    assert pool["visits_released"] == 0
    assert_visit_unit_identity(pool)


# --------------------------------------------------------------------------
# Rung 15: the plan-active gate
# --------------------------------------------------------------------------


def test_scheduling_against_a_suspended_plan_is_refused(api):
    """PRD §2.7 rung 15: "**The plan-active gate.** The `TherapyPlan` the request
    depends on has `status` `ACTIVE`. Otherwise `ERR_PLAN_NOT_ACTIVE`, HTTP 409.
    Applies to exactly six operations: scheduling an in-office session, logging a home
    session, advancing a phase, checking a session in, recording phase mastery, and
    creating a kit loan."
    PRD §3.4: "Suspension takes an `ACTIVE` plan to `SUSPENDED` and records why, in
    `suspension_reason`."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_blocked_by_suspended_plan
    """
    scn = setup_active_plan()
    suspended = validate_success(
        api.suspend_plan(scn["plan"], {"suspension_reason": "CLINICIAN_HOLD"}, scn["hdr_od1"]),
        200,
    )
    assert suspended["status"] == "SUSPENDED"

    response = _book(
        api,
        scn,
        scn["cvt1"],
        scn["room_a"],
        "2026-06-10T09:00:00Z",
        "2026-06-10T10:00:00Z",
        version=scn["auth_v1"],
    )

    validate_error(response, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value, 409)


def test_a_refused_booking_leaves_the_visit_pool_untouched(api):
    """PRD §3.5: "The plan must be in `status` `ACTIVE`, or `ERR_PLAN_NOT_ACTIVE`."
    PRD §3.5: "On success the pool gives up exactly one unit: `visits_consumed` rises
    by 1, `visits_remaining` falls by 1, the pool's `version` is bumped, and if
    `visits_remaining` reaches 0 the pool moves `ACTIVE → EXHAUSTED` in the same call."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_blocked_by_suspended_plan
    """
    scn = setup_active_plan()
    validate_success(
        api.suspend_plan(scn["plan"], {"suspension_reason": "CLINICIAN_HOLD"}, scn["hdr_od1"]),
        200,
    )

    _book(
        api,
        scn,
        scn["cvt1"],
        scn["room_a"],
        "2026-06-10T09:00:00Z",
        "2026-06-10T10:00:00Z",
        version=scn["auth_v1"],
    )

    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 0
    assert pool["visits_remaining"] == 12
    assert_visit_unit_identity(pool)
    rows, meta = validate_paginated(
        api.list_sessions(scn["hdr_front"], {"plan_id": scn["plan"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0 and rows == []


# --------------------------------------------------------------------------
# Rung 20 and rung 21: two different interval arithmetics
# --------------------------------------------------------------------------


def test_a_fourteen_minute_room_gap_collides_under_the_turnover_buffer(api):
    """PRD §3.5: "A gap of exactly fifteen minutes between two bookings in the same
    room is therefore accepted; a gap of fourteen minutes is refused with
    `ERR_ROOM_CONFLICT`."
    PRD §3.5: "A **room** carries a fifteen-minute turnover buffer applied on both
    sides: the booking is refused when some other session on the same `room_id`, in
    `schedule_status` `SCHEDULED`, `CHECKED_IN` or `COMPLETED`, satisfies both of two
    conditions at once — the new session's `scheduled_start_at` is earlier than that
    session's `scheduled_end_at` advanced by fifteen minutes, and that session's
    `scheduled_start_at` is earlier than the new session's `scheduled_end_at` advanced
    by fifteen minutes."

    Design: Difficulty/resource_temporal_overlap/room_buffered_overlap_rejects_fourteen_minute_gap
    """
    scn = setup_active_plan()
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])

    response = _book(
        api,
        scn,
        scn["od2"],
        scn["room_a"],
        "2026-06-10T10:14:00Z",
        "2026-06-10T11:14:00Z",
    )

    validate_error(response, ApiErrorId.ERR_ROOM_CONFLICT.value, 409)


def test_a_fifteen_minute_room_gap_is_accepted(api):
    """PRD §3.5: "A gap of exactly fifteen minutes between two bookings in the same
    room is therefore accepted; a gap of fourteen minutes is refused with
    `ERR_ROOM_CONFLICT`."
    PRD §3.5: "The created row has `modality` `IN_OFFICE`, `schedule_status`
    `SCHEDULED` and `billing_status` `PENDING`; its `patient_id` and its
    `authorization_id` are copied from the plan rather than supplied, `performed_at`,
    `timed_minutes`, `supervising_optometrist_id` and `cancel_reason` are null,
    `billable_units` is 0 and `charge_amount` is `0.00`."

    Design: Difficulty/resource_temporal_overlap/room_buffered_overlap_rejects_fourteen_minute_gap
    """
    scn = setup_active_plan()
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])

    data = validate_success(
        _book(
            api,
            scn,
            scn["od2"],
            scn["room_a"],
            "2026-06-10T10:15:00Z",
            "2026-06-10T11:15:00Z",
        ),
        201,
    )

    assert data["schedule_status"] == "SCHEDULED"
    rows, meta = validate_paginated(
        api.list_sessions(scn["hdr_front"], {"room_id": scn["room_a"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 2 and pool["visits_remaining"] == 10


def test_a_clinician_booking_starting_when_the_previous_ends_is_accepted(api):
    """PRD §3.5: "A **clinician** carries no buffer at all — the turnover allowance
    for a clinician is zero minutes — and plain half-open overlap decides: the booking
    is refused when some other session on the same `therapist_id`, in
    `schedule_status` `SCHEDULED`, `CHECKED_IN` or `COMPLETED`, has the new session
    starting strictly before that session ends and that session starting strictly
    before the new session ends."
    PRD §3.5: "Exact adjacency, where a booking starts at the very instant the
    previous one ends, is accepted; a genuine overlap is refused with
    `ERR_THERAPIST_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/therapist_adjacent_booking_allowed_but_overlap_rejected
    """
    scn = setup_active_plan()
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])

    data = validate_success(
        _book(
            api,
            scn,
            scn["cvt1"],
            scn["room_b"],
            "2026-06-10T10:00:00Z",
            "2026-06-10T11:00:00Z",
        ),
        201,
    )

    assert data["schedule_status"] == "SCHEDULED"
    rows, meta = validate_paginated(
        api.list_sessions(
            scn["hdr_front"], {"therapist_id": scn["cvt1"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2


def test_a_clinician_booking_overlapping_the_previous_one_is_refused(api):
    """PRD §2.7 rung 21: "**Therapist occupancy.** The requested clinician has no
    overlapping booking under unbuffered, half-open interval arithmetic. Otherwise
    `ERR_THERAPIST_CONFLICT`, HTTP 409. Applies to in-office session scheduling."
    PRD §3.5: "Exact adjacency, where a booking starts at the very instant the
    previous one ends, is accepted; a genuine overlap is refused with
    `ERR_THERAPIST_CONFLICT`."
    PRD §3.5: "If the total is strictly greater than one hundred and eighty minutes
    the booking is refused with `ERR_THERAPIST_DAILY_CAP_EXCEEDED`; a total of exactly
    one hundred and eighty is accepted."

    Design: Difficulty/resource_temporal_overlap/therapist_adjacent_booking_allowed_but_overlap_rejected
    """
    scn = setup_active_plan()
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])
    schedule_session(
        scn,
        therapist_id=scn["cvt1"],
        room_id=scn["room_b"],
        scheduled_start_at="2026-06-10T10:00:00Z",
        scheduled_end_at="2026-06-10T11:00:00Z",
    )

    response = _book(
        api,
        scn,
        scn["cvt1"],
        scn["room_c"],
        "2026-06-10T10:30:00Z",
        "2026-06-10T11:30:00Z",
    )

    validate_error(response, ApiErrorId.ERR_THERAPIST_CONFLICT.value, 409)
    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 2 and pool["visits_remaining"] == 10


# --------------------------------------------------------------------------
# Rungs 11, 19 and 22
# --------------------------------------------------------------------------


def test_booking_outside_the_authorization_window_is_refused(api):
    """PRD §2.7 rung 19: "**Authorization window.** The UTC calendar date of
    `scheduled_start_at` lies inside the plan's authorization window, inclusive of
    both `window_start_date` and `window_end_date`. Otherwise
    `ERR_SESSION_OUTSIDE_AUTH_WINDOW`, HTTP 422. Applies to in-office session
    scheduling."

    Design: Corner/validations/session_scheduled_outside_the_authorization_window_rejected
    """
    scn = setup_active_plan()

    response = _book(
        api,
        scn,
        scn["cvt1"],
        scn["room_a"],
        "2026-12-15T09:00:00Z",
        "2026-12-15T10:00:00Z",
        version=scn["auth_v1"],
    )

    validate_error(response, ApiErrorId.ERR_SESSION_OUTSIDE_AUTH_WINDOW.value, 422)
    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 0
    assert pool["visits_remaining"] == 12
    assert pool["status"] == "ACTIVE"


def test_the_day_cap_accepts_one_hundred_and_eighty_minutes_and_refuses_more(api):
    """PRD §3.5: "Take the UTC calendar date of the requested `scheduled_start_at`;
    sum, over every in-office session for that same clinician whose
    `scheduled_start_at` falls on that date and whose `schedule_status` is
    `SCHEDULED`, `CHECKED_IN`, `COMPLETED` or `NO_SHOW`, the whole minutes between its
    `scheduled_start_at` and its `scheduled_end_at`; add the whole minutes of the
    requested booking."
    PRD §3.5: "If the total is strictly greater than one hundred and eighty minutes
    the booking is refused with `ERR_THERAPIST_DAILY_CAP_EXCEEDED`; a total of exactly
    one hundred and eighty is accepted."

    Design: Corner/validations/therapist_daily_minute_cap_accepts_180_and_rejects_210
    """
    scn = setup_active_plan()
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])
    schedule_session(
        scn,
        therapist_id=scn["cvt1"],
        room_id=scn["room_b"],
        scheduled_start_at="2026-06-10T10:15:00Z",
        scheduled_end_at="2026-06-10T11:15:00Z",
    )
    schedule_session(
        scn,
        therapist_id=scn["cvt1"],
        room_id=scn["room_c"],
        scheduled_start_at="2026-06-10T11:30:00Z",
        scheduled_end_at="2026-06-10T12:30:00Z",
    )

    response = _book(
        api,
        scn,
        scn["cvt1"],
        scn["room_a"],
        "2026-06-10T12:45:00Z",
        "2026-06-10T13:15:00Z",
    )

    validate_error(response, ApiErrorId.ERR_THERAPIST_DAILY_CAP_EXCEEDED.value, 409)
    rows, meta = validate_paginated(
        api.list_sessions(
            scn["hdr_front"], {"therapist_id": scn["cvt1"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3
    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 3 and pool["visits_remaining"] == 9


def test_booking_into_an_unknown_room_reports_a_missing_reference(api):
    """PRD §2.7 rung 11: "**Other references.** Every other referenced row exists — a
    `Payer`, a `Therapist` named by `therapist_id`, `performed_by_therapist_id` or
    `supervising_optometrist_id`, a `TherapyRoom`, an `Authorization`, a `PlanPhase`,
    a `KitItem`, a `KitLoan`, a `Referral` or an `OcclusionPrescription`. Otherwise
    `ERR_REFERENCE_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/session_create_with_unknown_room_returns_reference_not_found
    """
    scn = setup_active_plan()

    response = _book(
        api,
        scn,
        scn["cvt1"],
        NON_EXISTENT_UUID,
        "2026-06-10T09:00:00Z",
        "2026-06-10T10:00:00Z",
        version=scn["auth_v1"],
    )

    validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404)
    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 0 and pool["visits_remaining"] == 12
