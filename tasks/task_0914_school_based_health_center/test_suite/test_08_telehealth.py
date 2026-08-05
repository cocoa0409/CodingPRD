"""Telehealth into the classroom: the two resource axes, the booked-minutes
identity and the encounter that waits on its session."""

from test_helpers import (
    ADMIN,
    REGISTRAR,
    ApiErrorId,
    add_telehealth_visit,
    assert_same_instant,
    assert_telehealth_session,
    book_session,
    close_session,
    create_clinician,
    make_clinician_headers,
    school_booked_minutes,
    set_clock,
    setup_booked_session,
    setup_telehealth_enrolled_student,
    setup_telehealth_visit,
    start_visit,
    telehealth_session_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_clinician_site():
    """One site at capacity 1 with two MEDICAL clinicians and a student holding
    both consents a telehealth encounter needs."""
    ctx = setup_telehealth_enrolled_student(capacity=1)
    ctx["clinician_b"] = create_clinician(
        full_name="Sam Cole MD", discipline="MEDICAL", license_number="MD-2002"
    )
    ctx["clinician_b_headers"] = make_clinician_headers(ctx["clinician_b"]["id"])
    return ctx


def test_clinician_conflict_is_reported_when_a_window_fails_both_axes(api):
    """PRD §2.6: "A telehealth window that collides with the same clinician's other
    session *and* exhausts the site's capacity produces
    `ERR_CLINICIAN_SLOT_CONFLICT` (rung 26 precedes rung 27)."
    PRD §3.6: "The proposed window conflicts with an existing session of the same
    clinician — considering only sessions whose status is `SCHEDULED` or
    `COMPLETED`, and excluding the very row being rescheduled from its own check —
    when the proposed start is earlier than that session's end extended forward by
    15 minutes **and** that session's start is earlier than the proposed end
    extended forward by 15 minutes."

    Design: Difficulty/priority_pair_validation_conflict/clinician_temporal_rung_beats_school_capacity_constraint_rung_on_session_create
    """
    ctx = _two_clinician_site()
    first_visit = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:00:00Z")
    second_visit = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:15:00Z")
    booked = book_session(
        first_visit["id"], ctx["clinician"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:30:00Z"
    )

    resp = api.create_telehealth_session(
        telehealth_session_payload(
            second_visit["id"], "2026-05-04T09:15:00Z", "2026-05-04T09:45:00Z"
        ),
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SLOT_CONFLICT.value, 409)

    _rows, meta = validate_paginated(
        api.list_telehealth_sessions(ADMIN, params={"school_id": ctx["school"]["id"]})
    )
    assert meta["total_count"] == 1, f"Only the original session may exist, got {meta['total_count']}"
    assert validate_success(api.get_telehealth_session(booked["id"], ADMIN))["status"] == "SCHEDULED"
    assert school_booked_minutes(ctx["school"]["id"]) == 30


def test_capacity_rung_surfaces_when_only_the_site_axis_fails(api):
    """PRD §3.6: "If that count has reached the site's
    `telehealth_concurrent_capacity`, the booking is refused with
    `ERR_SCHOOL_CAPACITY_EXCEEDED`; the booking is permitted only while the count
    is strictly below capacity."
    PRD §3.6: "The clinician check runs before the site check, so a window that
    fails both reports the clinician conflict."

    Design: Difficulty/priority_pair_validation_conflict/clinician_temporal_rung_beats_school_capacity_constraint_rung_on_session_create
    """
    ctx = _two_clinician_site()
    first_visit = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:00:00Z")
    other_clinician_visit = add_telehealth_visit(
        ctx, ctx["clinician_b"]["id"], "2026-05-04T09:15:00Z"
    )
    session = book_session(
        first_visit["id"], ctx["clinician"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:30:00Z"
    )

    resp = api.create_telehealth_session(
        telehealth_session_payload(
            other_clinician_visit["id"], "2026-05-04T09:15:00Z", "2026-05-04T09:45:00Z"
        ),
        ctx["clinician_b_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_SCHOOL_CAPACITY_EXCEEDED.value, 409)

    _rows, meta = validate_paginated(
        api.list_telehealth_sessions(ADMIN, params={"school_id": ctx["school"]["id"]})
    )
    assert meta["total_count"] == 1
    stored = validate_success(api.get_telehealth_session(session["id"], ADMIN))
    assert stored["duration_minutes"] == 30
    assert school_booked_minutes(ctx["school"]["id"]) == 30


def test_a_fourteen_minute_gap_collides_on_the_buffered_clinician_axis(api):
    """PRD §3.6: "A clinician needs turnaround time between classrooms, and that
    turnaround is 15 minutes."
    PRD §3.6: "A gap of exactly 15 minutes on either side therefore does **not**
    conflict: an existing session running 09:00 to 09:30 leaves a proposed 09:45 to
    10:15 session free, while a proposed 09:44 to 10:14 session collides. A
    collision is refused with `ERR_CLINICIAN_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/clinician_buffered_closed_interval_allows_exact_15_minute_gap
    """
    ctx = setup_telehealth_enrolled_student(capacity=1)
    first_visit = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:00:00Z")
    near_visit = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:44:00Z")
    book_session(
        first_visit["id"], ctx["clinician"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:30:00Z"
    )

    resp = api.create_telehealth_session(
        telehealth_session_payload(near_visit["id"], "2026-05-04T09:44:00Z", "2026-05-04T10:14:00Z"),
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SLOT_CONFLICT.value, 409)
    assert school_booked_minutes(ctx["school"]["id"]) == 30


def test_an_exactly_fifteen_minute_gap_is_accepted_on_the_clinician_axis(api):
    """PRD §3.6: "A gap of exactly 15 minutes on either side therefore does **not**
    conflict: an existing session running 09:00 to 09:30 leaves a proposed 09:45 to
    10:15 session free, while a proposed 09:44 to 10:14 session collides."
    PRD §3.6: "A successful booking copies `clinician_id` and `school_id` from the
    parent encounter onto the session, computes `duration_minutes`, opens the row in
    `SCHEDULED`, adds `duration_minutes` to the site's
    `telehealth_booked_minutes_total` and increments the site's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/clinician_buffered_closed_interval_allows_exact_15_minute_gap
    """
    ctx = setup_telehealth_enrolled_student(capacity=1)
    first_visit = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:00:00Z")
    gap_visit = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:45:00Z")
    book_session(
        first_visit["id"], ctx["clinician"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:30:00Z"
    )

    resp = api.create_telehealth_session(
        telehealth_session_payload(gap_visit["id"], "2026-05-04T09:45:00Z", "2026-05-04T10:15:00Z"),
        ctx["clinician_headers"],
    )
    session = validate_success(resp, 201)

    assert_telehealth_session(session)
    assert session["status"] == "SCHEDULED"
    assert session["duration_minutes"] == 30
    assert session["clinician_id"] == ctx["clinician"]["id"]

    _rows, meta = validate_paginated(
        api.list_telehealth_sessions(ADMIN, params={"clinician_id": ctx["clinician"]["id"]})
    )
    assert meta["total_count"] == 2, f"Both sessions belong to the clinician, got {meta['total_count']}"
    assert school_booked_minutes(ctx["school"]["id"]) == 60


def test_an_adjacent_session_does_not_consume_site_capacity(api):
    """PRD §3.6: "The server counts the sessions at the same site, again only those
    whose status is `SCHEDULED` or `COMPLETED`, whose window overlaps the proposed
    one — meaning the proposed start is strictly earlier than the existing end and
    the existing start is strictly earlier than the proposed end. Adjacency is
    therefore fine on this axis: an existing 09:00 to 09:30 session and a proposed
    09:30 to 10:00 session do not overlap at all."

    Design: Difficulty/resource_temporal_overlap/school_half_open_capacity_allows_adjacent_session_rejects_overlap
    """
    ctx = _two_clinician_site()
    visit_a = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:00:00Z")
    visit_b = add_telehealth_visit(ctx, ctx["clinician_b"]["id"], "2026-05-04T09:30:00Z")
    book_session(
        visit_a["id"], ctx["clinician"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:30:00Z"
    )

    resp = api.create_telehealth_session(
        telehealth_session_payload(visit_b["id"], "2026-05-04T09:30:00Z", "2026-05-04T10:00:00Z"),
        ctx["clinician_b_headers"],
    )
    adjacent = validate_success(resp, 201)

    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["school_id"] == ctx["school"]["id"]
    assert school_booked_minutes(ctx["school"]["id"]) == 60


def test_an_overlapping_session_exceeds_the_site_capacity(api):
    """PRD §3.6: "If that count has reached the site's
    `telehealth_concurrent_capacity`, the booking is refused with
    `ERR_SCHOOL_CAPACITY_EXCEEDED`; the booking is permitted only while the count is
    strictly below capacity."
    PRD §3.1: "Registration may optionally supply
    `telehealth_concurrent_capacity`, the number of telehealth sessions the site's
    classroom and presenter staff can host at overlapping times; when it is omitted
    the value defaults to 1, and any supplied value must be at least 1 and at most
    4."

    Design: Difficulty/resource_temporal_overlap/school_half_open_capacity_allows_adjacent_session_rejects_overlap
    """
    ctx = _two_clinician_site()
    clinician_c = create_clinician(
        full_name="Iris Vega PA", discipline="MEDICAL", license_number="PA-3003"
    )
    visit_a = add_telehealth_visit(ctx, ctx["clinician"]["id"], "2026-05-04T09:00:00Z")
    visit_b = add_telehealth_visit(ctx, ctx["clinician_b"]["id"], "2026-05-04T09:30:00Z")
    visit_c = add_telehealth_visit(ctx, clinician_c["id"], "2026-05-04T09:29:00Z")
    book_session(
        visit_a["id"], ctx["clinician"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:30:00Z"
    )
    book_session(
        visit_b["id"], ctx["clinician_b"]["id"], "2026-05-04T09:30:00Z", "2026-05-04T10:00:00Z"
    )

    resp = api.create_telehealth_session(
        telehealth_session_payload(visit_c["id"], "2026-05-04T09:29:00Z", "2026-05-04T09:59:00Z"),
        make_clinician_headers(clinician_c["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_SCHOOL_CAPACITY_EXCEEDED.value, 409)

    _rows, meta = validate_paginated(
        api.list_telehealth_sessions(ADMIN, params={"school_id": ctx["school"]["id"]})
    )
    assert meta["total_count"] == 2, f"Only the two accepted sessions exist, got {meta['total_count']}"
    assert school_booked_minutes(ctx["school"]["id"]) == 60


def test_booking_a_session_adds_its_duration_to_the_site_total(api):
    """PRD §2.10: "A school's `telehealth_booked_minutes_total` is always the sum
    of the durations of that school's telehealth sessions whose status is
    `SCHEDULED` or `COMPLETED`; booking a session and then cancelling it must
    return the total to exactly its pre-booking value."
    PRD §3.6: "A successful booking copies `clinician_id` and `school_id` from the
    parent encounter onto the session, computes `duration_minutes`, opens the row in
    `SCHEDULED`, adds `duration_minutes` to the site's
    `telehealth_booked_minutes_total` and increments the site's `version` by 1."

    Design: Difficulty/compensating_invariant/school_booked_minutes_restored_after_session_cancellation
    """
    ctx = setup_telehealth_visit()
    assert school_booked_minutes(ctx["school"]["id"]) == 0

    resp = api.create_telehealth_session(
        telehealth_session_payload(
            ctx["visit"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:30:00Z"
        ),
        ctx["clinician_headers"],
    )
    session = validate_success(resp, 201)

    assert session["duration_minutes"] == 30
    assert school_booked_minutes(ctx["school"]["id"]) == 30


def test_cancelling_a_session_restores_the_site_total_to_its_pre_booking_value(api):
    """PRD §2.10: "A school's `telehealth_booked_minutes_total` is always the sum
    of the durations of that school's telehealth sessions whose status is
    `SCHEDULED` or `COMPLETED`; booking a session and then cancelling it must
    return the total to exactly its pre-booking value."
    PRD §3.6: "Closing one with an `outcome` of `CANCELLED` is accepted from
    `SCHEDULED`, where it releases the booking by decrementing
    `telehealth_booked_minutes_total` by `duration_minutes` and incrementing the
    site's `version` by 1"

    Design: Difficulty/compensating_invariant/school_booked_minutes_restored_after_session_cancellation
    """
    ctx = setup_booked_session()
    assert school_booked_minutes(ctx["school"]["id"]) == 30

    closed = validate_success(
        api.close_telehealth_session(
            ctx["session"]["id"],
            {"outcome": "CANCELLED", "closure_reason": "Family withdrew the request"},
            ctx["clinician_headers"],
        )
    )

    assert closed["status"] == "CANCELLED"
    assert school_booked_minutes(ctx["school"]["id"]) == 0

    rows, meta = validate_paginated(
        api.list_telehealth_sessions(ADMIN, params={"school_id": ctx["school"]["id"]})
    )
    assert meta["total_count"] == 1, "A cancelled session stays queryable"
    assert len(rows) == 1
    assert validate_success(api.get_visit(ctx["visit"]["id"], REGISTRAR))[
        "clinical_status"
    ] == "SCHEDULED"


def _telehealth_encounter_ready_to_complete():
    """A TIER_A self-pay family, a TELEHEALTH encounter in IN_PROGRESS and one
    SCHEDULED session behind it."""
    ctx = setup_booked_session(
        financial={
            "household_income_annual_cents": 3_000_000,
            "household_size": 4,
            "payer_route": "SELF_PAY",
        }
    )
    ctx["visit"] = start_visit(ctx["visit"]["id"], ctx["clinician"]["id"])
    return ctx


def test_telehealth_encounter_cannot_complete_while_its_session_is_scheduled(api):
    """PRD §3.5: "If the encounter is delivered by telehealth, completion
    additionally demands that a telehealth session belonging to this encounter has
    itself reached `COMPLETED`; attempting to complete a telehealth encounter with
    no completed session behind it is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/telehealth_visit_complete_gated_by_session_completion
    """
    ctx = _telehealth_encounter_ready_to_complete()
    assert ctx["visit"]["clinical_status"] == "IN_PROGRESS"

    resp = api.complete_visit(
        ctx["visit"]["id"],
        {"disposition": "TREATED_RETURNED_TO_CLASS"},
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    assert validate_success(api.get_telehealth_session(ctx["session"]["id"], ADMIN))[
        "status"
    ] == "SCHEDULED"
    assert validate_success(api.get_visit(ctx["visit"]["id"], REGISTRAR))[
        "clinical_status"
    ] == "IN_PROGRESS"


def test_telehealth_encounter_completes_once_its_session_has_completed(api):
    """PRD §3.6: "Completing one moves it `SCHEDULED → COMPLETED` and leaves the
    booked-minutes total untouched — a completed session keeps its booking — and it
    is completion of the session that unlocks completion of the parent encounter."
    PRD §3.10: "The encounter itself yields exactly one charge whose
    `service_category` is derived from how the encounter was delivered: any
    encounter with a `delivery_mode` of `TELEHEALTH` yields `TELEHEALTH_ENCOUNTER`,
    and that override beats the visit type"

    Design: Difficulty/cross_entity_state_dependency/telehealth_visit_complete_gated_by_session_completion
    """
    ctx = _telehealth_encounter_ready_to_complete()
    validate_error(
        api.complete_visit(
            ctx["visit"]["id"],
            {"disposition": "TREATED_RETURNED_TO_CLASS"},
            ctx["clinician_headers"],
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    session = validate_success(
        api.complete_telehealth_session(ctx["session"]["id"], ctx["clinician_headers"])
    )
    assert session["status"] == "COMPLETED"

    completed = validate_success(
        api.complete_visit(
            ctx["visit"]["id"],
            {"disposition": "TREATED_RETURNED_TO_CLASS"},
            ctx["clinician_headers"],
        )
    )

    assert completed["clinical_status"] == "COMPLETED"
    assert completed["billing_status"] == "PENDING_CHARGES"

    charges, meta = validate_paginated(
        api.list_charges(REGISTRAR, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 1, f"Expected exactly one charge, got {meta['total_count']}"
    charge = charges[0]
    assert charge["service_category"] == "TELEHEALTH_ENCOUNTER"
    assert charge["gross_amount_cents"] == 11_000
    assert charge["provisional_patient_responsibility_cents"] == 0
    assert charge["floor_adjustment_cents"] == 500
    assert charge["patient_responsibility_cents"] == 500
    assert completed["patient_responsibility_total_cents"] == 500
    assert school_booked_minutes(ctx["school"]["id"]) == 30, (
        "A completed session keeps its booking"
    )


def test_session_duration_bounds_are_inclusive_at_fifteen_and_sixty_minutes(api):
    """PRD §3.6: "The window itself must have `end_at` strictly after `start_at`,
    and the resulting `duration_minutes` — the whole number of minutes between the
    two instants — must be at least 15 and at most 60, both bounds inclusive; a
    15-minute or 60-minute session is fine, a 14-minute or 61-minute one is refused
    with `ERR_INVALID_SESSION_WINDOW`."

    Design: Corner/validations/telehealth_session_duration_outside_fifteen_to_sixty_minutes_rejected
    """
    ctx = setup_telehealth_visit()

    too_short = api.create_telehealth_session(
        telehealth_session_payload(
            ctx["visit"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:10:00Z"
        ),
        ctx["clinician_headers"],
    )
    validate_error(too_short, ApiErrorId.ERR_INVALID_SESSION_WINDOW.value, 400)

    too_long = api.create_telehealth_session(
        telehealth_session_payload(
            ctx["visit"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T10:30:00Z"
        ),
        ctx["clinician_headers"],
    )
    validate_error(too_long, ApiErrorId.ERR_INVALID_SESSION_WINDOW.value, 400)

    accepted = validate_success(
        api.create_telehealth_session(
            telehealth_session_payload(
                ctx["visit"]["id"], "2026-05-04T09:00:00Z", "2026-05-04T09:15:00Z"
            ),
            ctx["clinician_headers"],
        ),
        201,
    )

    assert accepted["duration_minutes"] == 15
    assert accepted["status"] == "SCHEDULED"
    assert school_booked_minutes(ctx["school"]["id"]) == 15


def test_third_reschedule_of_the_same_session_is_refused(api):
    """PRD §3.6: "Rescheduling closes the loop `SCHEDULED → NO_SHOW → SCHEDULED`.
    It is accepted only from `NO_SHOW`, is capped at 2 reschedules per row so that a
    third attempt is refused with `ERR_RESCHEDULE_LIMIT_EXCEEDED`, and re-runs every
    window check that creation ran — the same 15-to-60-minute duration bounds, the
    same 15-minute buffered clinician check and the same half-open site-capacity
    check."
    PRD §3.6: "Closing one with an `outcome` of `NO_SHOW` is accepted only from
    `SCHEDULED` and only once the current logical instant has reached `start_at` plus
    10 minutes inclusive, otherwise `ERR_NO_SHOW_TOO_EARLY`; it releases the booking
    and increments the site's `version` by 1."

    Design: Corner/state_machines/telehealth_session_reschedule_capped_at_two
    """
    ctx = setup_booked_session()
    session_id = ctx["session"]["id"]

    set_clock("2026-05-04T09:15:00Z")
    close_session(session_id, ctx["clinician"]["id"], "NO_SHOW")
    validate_success(
        api.reschedule_telehealth_session(
            session_id,
            {"start_at": "2026-05-04T11:00:00Z", "end_at": "2026-05-04T11:30:00Z"},
            ctx["clinician_headers"],
        )
    )

    set_clock("2026-05-04T11:15:00Z")
    close_session(session_id, ctx["clinician"]["id"], "NO_SHOW")
    validate_success(
        api.reschedule_telehealth_session(
            session_id,
            {"start_at": "2026-05-04T13:00:00Z", "end_at": "2026-05-04T13:30:00Z"},
            ctx["clinician_headers"],
        )
    )

    set_clock("2026-05-04T13:15:00Z")
    close_session(session_id, ctx["clinician"]["id"], "NO_SHOW")

    resp = api.reschedule_telehealth_session(
        session_id,
        {"start_at": "2026-05-04T15:00:00Z", "end_at": "2026-05-04T15:30:00Z"},
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_RESCHEDULE_LIMIT_EXCEEDED.value, 409)

    session = validate_success(api.get_telehealth_session(session_id, ADMIN))
    assert session["status"] == "NO_SHOW"
    assert session["reschedule_count"] == 2
    assert_same_instant(session["start_at"], "2026-05-04T13:00:00.000Z", "TelehealthSession.start_at")
    assert school_booked_minutes(ctx["school"]["id"]) == 0
