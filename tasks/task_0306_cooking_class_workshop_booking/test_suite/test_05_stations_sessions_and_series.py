"""Station temporal exclusivity, session lifecycle, and series cascades.

Queue A: boundary_precision_check (adjacency), resource_temporal_overlap (station
buffer), cross_entity_state_dependency (confirm needs OPEN; series publish needs
PUBLISHED template), transitive_cascade (series cancel depth-3). Queue B: session
state machine and consistency-model instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_instructor,
    create_member,
    create_published_template,
    create_session,
    create_open_session,
    create_booking,
    confirm_booking,
    create_confirmed_booking,
    add_ingredient_line,
    create_published_series,
    set_clock,
    get_session_version,
    make_instructor_headers,
    make_member_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["studio_admin_headers"]


def test_station_adjacency_zero_gap_opens_successfully(api):
    """PRD §3.4: "A session's station occupation runs from prep_minutes before its
    start_at to cleanup_minutes after its end_at, treated as a half-open interval,
    so two occupations that merely touch at a shared endpoint do not overlap."

    Session A occupies [13:00,16:30) (prep 60, cleanup 30 around 14:00-16:00);
    session B occupies [16:30,18:00). They touch at 16:30 exactly, so B opens with
    no ERR_STATION_DOUBLE_BOOKED.

    Design: Difficulty/boundary_precision_check/station_overlap_adjacency_zero_gap_open_endpoint
    """
    instr = create_instructor()
    tmpl_a = create_published_template(
        title="AdjA", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=60, cleanup_minutes=30,
    )
    tmpl_b = create_published_template(
        title="AdjB", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=0, cleanup_minutes=0,
    )
    sess_a = create_session(
        tmpl_a["id"], instr["id"], station_id="ST-ADJ",
        start_at="2026-07-01T14:00:00Z", end_at="2026-07-01T16:00:00Z", planned_seats=4,
    )
    add_ingredient_line(sess_a["id"], instr["id"], name="a", qty_per_seat=1, unit_cost_cents=1)
    validate_success(api.open_session(sess_a["id"], make_instructor_headers(instr["id"])), 200)

    sess_b = create_session(
        tmpl_b["id"], instr["id"], station_id="ST-ADJ",
        start_at="2026-07-01T16:30:00Z", end_at="2026-07-01T18:00:00Z", planned_seats=4,
    )
    add_ingredient_line(sess_b["id"], instr["id"], name="b", qty_per_seat=1, unit_cost_cents=1)
    opened_b = validate_success(api.open_session(sess_b["id"], make_instructor_headers(instr["id"])), 200)
    assert opened_b["status"] == "OPEN", "adjacency at a shared endpoint is not an overlap"


def test_station_adjacency_cleanup_side_opens_successfully(api):
    """PRD §3.4: "A session's station occupation runs from prep_minutes before its
    start_at to cleanup_minutes after its end_at, treated as a half-open interval,
    so two occupations that merely touch at a shared endpoint do not overlap."

    A second adjacency witness on the prep-buffer side: session B (prep 30) starts
    at 16:00 so its occupation begins [15:30,...); session A (cleanup 30) ends 16:00
    so its occupation ends [...,15:30) when A is 13:00-15:00 — they touch at exactly
    15:30 and B opens with no ERR_STATION_DOUBLE_BOOKED.

    Design: Difficulty/boundary_precision_check/station_overlap_adjacency_zero_gap_open_endpoint
    """
    instr = create_instructor()
    tmpl_a = create_published_template(
        title="AdjA2", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=0, cleanup_minutes=30,
    )
    tmpl_b = create_published_template(
        title="AdjB2", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=30, cleanup_minutes=0,
    )
    # A occupies [13:00, 15:30) (13:00-15:00 + 30 cleanup).
    sess_a = create_session(
        tmpl_a["id"], instr["id"], station_id="ST-ADJ2",
        start_at="2026-07-02T13:00:00Z", end_at="2026-07-02T15:00:00Z", planned_seats=4,
    )
    add_ingredient_line(sess_a["id"], instr["id"], name="a", qty_per_seat=1, unit_cost_cents=1)
    validate_success(api.open_session(sess_a["id"], make_instructor_headers(instr["id"])), 200)
    # B occupies [15:30, 18:00) (16:00-18:00 - 30 prep) -> touches A at 15:30.
    sess_b = create_session(
        tmpl_b["id"], instr["id"], station_id="ST-ADJ2",
        start_at="2026-07-02T16:00:00Z", end_at="2026-07-02T18:00:00Z", planned_seats=4,
    )
    add_ingredient_line(sess_b["id"], instr["id"], name="b", qty_per_seat=1, unit_cost_cents=1)
    opened_b = validate_success(api.open_session(sess_b["id"], make_instructor_headers(instr["id"])), 200)
    assert opened_b["status"] == "OPEN", "adjacency at a shared endpoint is not an overlap"


def test_station_overlap_with_prep_buffer_rejected(api):
    """PRD §3.4: "If any other session sharing the same station_id and currently
    in SCHEDULED, OPEN, FULL, or LOCKED has an occupation interval that overlaps
    the opening session's occupation interval, the open is rejected with
    ERR_STATION_DOUBLE_BOOKED."

    Session A occupies [13:00,16:30); session C starts 16:00 with prep 60 ->
    occupation [15:00,17:00) which overlaps A; opening C is rejected and C stays
    SCHEDULED.

    Design: Difficulty/resource_temporal_overlap/station_overlap_with_prep_buffer_rejected
    """
    instr = create_instructor()
    tmpl_a = create_published_template(
        title="BufA", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=60, cleanup_minutes=30,
    )
    tmpl_c = create_published_template(
        title="BufC", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=60, cleanup_minutes=0,
    )
    sess_a = create_session(
        tmpl_a["id"], instr["id"], station_id="ST-BUF",
        start_at="2026-07-01T14:00:00Z", end_at="2026-07-01T16:00:00Z", planned_seats=4,
    )
    add_ingredient_line(sess_a["id"], instr["id"], name="a", qty_per_seat=1, unit_cost_cents=1)
    validate_success(api.open_session(sess_a["id"], make_instructor_headers(instr["id"])), 200)

    sess_c = create_session(
        tmpl_c["id"], instr["id"], station_id="ST-BUF",
        start_at="2026-07-01T16:00:00Z", end_at="2026-07-01T17:00:00Z", planned_seats=4,
    )
    add_ingredient_line(sess_c["id"], instr["id"], name="c", qty_per_seat=1, unit_cost_cents=1)
    res = api.open_session(sess_c["id"], make_instructor_headers(instr["id"]))
    validate_error(res, "ERR_STATION_DOUBLE_BOOKED", expected_status=409)
    sess_c_after = validate_success(api.get_session(sess_c["id"], ADMIN), 200)
    assert sess_c_after["status"] == "SCHEDULED"


def test_station_overlap_with_cleanup_buffer_rejected(api):
    """PRD §3.4: "A session's station occupation runs from prep_minutes before its
    start_at to cleanup_minutes after its end_at, treated as a half-open interval".
    PRD §3.4: "If any other session sharing the same station_id and currently in
    SCHEDULED, OPEN, FULL, or LOCKED has an occupation interval that overlaps the
    opening session's occupation interval, the open is rejected with
    ERR_STATION_DOUBLE_BOOKED."

    A second buffered-overlap witness on the cleanup side: session A (cleanup 60)
    occupying [14:00,17:00) overlaps session D occupying [16:30,18:00) by 30
    minutes; opening D is rejected and D stays SCHEDULED.

    Design: Difficulty/resource_temporal_overlap/station_overlap_with_prep_buffer_rejected
    """
    instr = create_instructor()
    tmpl_a = create_published_template(
        title="ClnA", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=0, cleanup_minutes=60,
    )
    tmpl_d = create_published_template(
        title="ClnD", skill_level="BEGINNER", base_price_cents=5000,
        default_capacity=4, station_fixed_cost_cents=1000, prep_minutes=0, cleanup_minutes=0,
    )
    sess_a = create_session(
        tmpl_a["id"], instr["id"], station_id="ST-CLN",
        start_at="2026-07-03T14:00:00Z", end_at="2026-07-03T16:00:00Z", planned_seats=4,
    )  # occupation [14:00, 17:00)
    add_ingredient_line(sess_a["id"], instr["id"], name="a", qty_per_seat=1, unit_cost_cents=1)
    validate_success(api.open_session(sess_a["id"], make_instructor_headers(instr["id"])), 200)
    sess_d = create_session(
        tmpl_d["id"], instr["id"], station_id="ST-CLN",
        start_at="2026-07-03T16:30:00Z", end_at="2026-07-03T18:00:00Z", planned_seats=4,
    )  # occupation [16:30, 18:00) overlaps [14:00,17:00) by 30 min
    add_ingredient_line(sess_d["id"], instr["id"], name="d", qty_per_seat=1, unit_cost_cents=1)
    res = api.open_session(sess_d["id"], make_instructor_headers(instr["id"]))
    validate_error(res, "ERR_STATION_DOUBLE_BOOKED", expected_status=409)
    after = validate_success(api.get_session(sess_d["id"], ADMIN), 200)
    assert after["status"] == "SCHEDULED"


def test_confirm_requires_session_open(api):
    """PRD §3.5: "A confirm is permitted only when the booking is PENDING, the
    session is OPEN, the member's booking_status is GOOD_STANDING, the seat block
    fits, and the supplied expected_session_version matches the session's current
    version."

    With the session still SCHEDULED (never opened), confirming a PENDING booking
    is rejected ERR_INVALID_STATE; the booking stays PENDING.

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_session_open
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=2,
        station_fixed_cost_cents=1000,
    )
    session = create_session(
        tmpl["id"], instr["id"], station_id="ST-SCHED",
        start_at="2026-09-25T14:00:00Z", end_at="2026-09-25T16:00:00Z", planned_seats=2,
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    sv = get_session_version(session["id"])
    res = api.confirm_booking(booking["id"], sv, make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert after["lifecycle_status"] == "PENDING"


def test_series_publish_requires_published_template(api):
    """PRD §3.3: "Before it may publish, three preconditions must hold: the
    referenced template must itself be PUBLISHED, the referenced instructor must
    be ACTIVE".
    PRD §2.9: "a state error surfaces before a stale-version error".

    A series referencing a DRAFT (never-published) template cannot publish; the
    publish is rejected ERR_INVALID_STATE and the series stays DRAFT.

    Design: Difficulty/cross_entity_state_dependency/series_publish_requires_instructor_active_and_template_published
    """
    instr = create_instructor()
    tmpl_res = api.create_template(
        {"title": "DraftTmpl", "skill_level": "BEGINNER", "base_price_cents": 5000,
         "default_capacity": 4, "station_fixed_cost_cents": 1000,
         "prep_minutes": 0, "cleanup_minutes": 0},
        ADMIN,
    )
    tmpl = validate_success(tmpl_res, 201)  # left in DRAFT
    series = validate_success(
        api.create_series(
            {"template_id": tmpl["id"], "instructor_id": instr["id"], "cadence": "WEEKLY",
             "occurrence_count": 2, "first_start_at": "2026-10-01T14:00:00Z"},
            ADMIN,
        ), 201,
    )
    res = api.publish_series(series["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_series(series["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_confirm_requires_session_open_locked_witness(api):
    """PRD §3.5: "A confirm is permitted only when the booking is PENDING, the
    session is OPEN, the member's booking_status is GOOD_STANDING, the seat block
    fits, and the supplied expected_session_version matches the session's current
    version."
    PRD §3.10: "Locking ... advances it to LOCKED, which freezes the roster: no
    new bookings and no waitlist promotions occur on a locked session".

    A second witness on the Booking->ClassSession dependency: with the session
    LOCKED (again not OPEN), confirming a PENDING booking created before the lock
    is rejected ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_session_open
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-LOCKCONF",
            "start_at": "2026-09-26T14:00:00Z", "end_at": "2026-09-26T16:00:00Z",
        },
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)  # PENDING while OPEN
    validate_success(api.lock_session(session["id"], make_instructor_headers(instr["id"])), 200)
    sv = get_session_version(session["id"])
    res = api.confirm_booking(booking["id"], sv, make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_series_republish_already_published_rejected(api):
    """PRD §3.3: "Publishing a series is restricted to a StudioAdmin and is
    permitted only while the series is in DRAFT."

    A second witness on the RecurringSeries DRAFT->PUBLISHED state precondition:
    a series already PUBLISHED cannot be published again; the re-publish is rejected
    ERR_INVALID_STATE and the series stays PUBLISHED.

    Design: Difficulty/cross_entity_state_dependency/series_publish_requires_instructor_active_and_template_published
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    series = create_published_series(
        tmpl["id"], instr["id"], cadence="WEEKLY", occurrence_count=1,
        first_start_at="2026-10-02T14:00:00Z",
    )
    assert series["status"] == "PUBLISHED"
    res = api.publish_series(series["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_series(series["id"], ADMIN), 200)
    assert after["status"] == "PUBLISHED"


def test_series_cancel_cascades_to_sessions_and_bookings(api):
    """PRD §3.3: "On a successful publish, the series transitions DRAFT -> PUBLISHED
    and spawns exactly occurrence_count sessions ... Every spawned session is
    created in SCHEDULED, carries this series' identifier in its series_id, copies
    the template's default_capacity into its planned_seats, and is a group event."
    PRD §3.3: "The cancellation transitions the series PUBLISHED -> CANCELLED and
    cascades: every child session whose status is neither COMPLETED nor CANCELLED
    is itself cancelled ..., and the series' active_session_count is set to 0."

    A published 2-session series: cancelling the series cancels both spawned child
    sessions (SCHEDULED -> CANCELLED) and zeroes active_session_count.

    Note: PRD §3.3 equips a spawned session only with a derived start_at,
    planned_seats, series_id, and GROUP type -- it assigns no end_at or station_id,
    so a spawned session is not openable (the §3.4 open path needs both for the
    station-exclusivity interval). The session-cancel -> booking-refund sub-cascade
    is therefore witnessed separately on a standalone (openable) session in
    test_studio_cancel_credits_wallet_in_same_response; this test witnesses the
    series -> child-session layer of the cascade.

    Design: Difficulty/transitive_cascade/series_cancel_cascades_sessions_then_bookings_depth3
    """
    set_clock("2026-07-01T00:00:00Z")
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="INTERMEDIATE", base_price_cents=8500, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    series = create_published_series(
        tmpl["id"], instr["id"], cadence="WEEKLY", occurrence_count=2,
        first_start_at="2026-09-05T14:00:00Z",
    )
    assert series["active_session_count"] == 2
    data, _meta = validate_paginated(api.list_series_sessions(series["id"], ADMIN))
    assert len(data) == 2
    for child in data:
        assert child["status"] == "SCHEDULED"
        assert child["series_id"] == series["id"]

    cancelled = validate_success(api.cancel_series(series["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["active_session_count"] == 0
    for child in data:
        child_after = validate_success(api.get_session(child["id"], ADMIN), 200)
        assert child_after["status"] == "CANCELLED", "every non-terminal child session is cascaded to CANCELLED"


def test_studio_cancel_expires_waitlist_entries(api):
    """PRD §3.8: "When a session is cancelled by the studio, every WAITING entry on
    it is expired (WAITING -> EXPIRED) as part of that cascade."
    PRD §3.10: "A StudioAdmin may cancel a session from any of SCHEDULED, OPEN,
    FULL, or LOCKED, moving it to CANCELLED. ... every WAITING waitlist entry on
    the session is expired".

    A FULL session carrying a WAITING waitlist entry: when the studio cancels the
    session, that entry is expired (WAITING -> EXPIRED) and the session is
    CANCELLED. (The same expiry behavior is what a series cancel cascades into per
    §3.3, but it is witnessed here on a standalone, openable session: PRD §3.3
    equips series-spawned sessions with no end_at or station_id, so they cannot be
    opened or driven to FULL.)

    Design: Difficulty/transitive_cascade/series_cancel_cascades_sessions_then_bookings_depth3
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 1,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 1, "station_id": "ST-WLEXP",
            "start_at": "2026-09-12T14:00:00Z", "end_at": "2026-09-12T16:00:00Z",
        },
        ingredient_overrides={"name": "milk", "qty_per_seat": 0.2, "unit_cost_cents": 90},
    )
    mem_a = create_member()
    mem_b = create_member()
    create_confirmed_booking(session["id"], mem_a["id"], 1)  # session FULL (planned_seats=1)
    from test_helpers import join_waitlist
    wl = join_waitlist(session["id"], mem_b["id"], 1)

    validate_success(api.cancel_session(session["id"], ADMIN), 200)
    entry_after = validate_success(api.get_waitlist_entry(wl["id"], make_member_headers(mem_b["id"])), 200)
    assert entry_after["queue_status"] == "EXPIRED"
    session_after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert session_after["status"] == "CANCELLED"


def test_studio_cancel_credits_wallet_in_same_response(api):
    """PRD §2.7: "every such cascade completes fully or not at all within the
    triggering request."
    PRD §3.10: "every child booking that is PENDING or CONFIRMED is cancelled with
    a full refund of its entire charge - the 300-cent cancellation fee is waived -
    its payment_status set to REFUNDED and the refund credited to the member's
    wallet".

    Studio-cancelling a session with one CONFIRMED 9000 booking returns the session
    CANCELLED and the booking CANCELLED with the member's wallet already credited
    9000 in the same atomic request.

    Design: Corner/consistency_model/cancel_cascade_visible_in_same_response
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-IMMED",
            "start_at": "2026-12-05T14:00:00Z", "end_at": "2026-12-05T16:00:00Z",
        },
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_confirmed_booking(session["id"], member["id"], 1)

    cancelled = validate_success(api.cancel_session(session["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    booking_after = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert booking_after["lifecycle_status"] == "CANCELLED"
    member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert member_after["wallet_credit_cents"] == 9000, "full refund credited immediately"


def test_new_session_starts_scheduled(api):
    """PRD §3.4: "A standalone session is created by a StudioAdmin in SCHEDULED
    with a series_id of null."

    A freshly created session has status SCHEDULED.

    Design: Corner/state_machines/new_session_starts_scheduled
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    res = api.create_session(
        {"template_id": tmpl["id"], "instructor_id": instr["id"], "station_id": "ST-INIT",
         "event_type": "GROUP", "start_at": "2026-11-09T14:00:00Z",
         "end_at": "2026-11-09T16:00:00Z", "planned_seats": 4},
        ADMIN,
    )
    session = validate_success(res, 201)
    assert session["status"] == "SCHEDULED"


def test_open_already_open_session_invalid_state(api):
    """PRD §3.4: "Opening requires that the session currently be SCHEDULED and
    that it have at least one ingredient line."

    Opening a session already in OPEN is rejected ERR_INVALID_STATE; it stays OPEN.

    Design: Corner/state_machines/open_already_open_session_returns_invalid_state
    """
    instr, _tmpl, session = create_open_session(
        session_overrides={"station_id": "ST-REOPEN"},
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    res = api.open_session(session["id"], make_instructor_headers(instr["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert after["status"] == "OPEN"


def test_open_session_without_ingredient_lines_rejected(api):
    """PRD §3.4: "Opening requires that the session currently be SCHEDULED and
    that it have at least one ingredient line."

    Opening a SCHEDULED session with zero ingredient lines is rejected
    ERR_INVALID_STATE; it stays SCHEDULED.

    Design: Corner/state_machines/open_session_without_ingredient_lines_rejected
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    session = create_session(
        tmpl["id"], instr["id"], station_id="ST-NOING",
        start_at="2026-11-05T14:00:00Z", end_at="2026-11-05T16:00:00Z", planned_seats=4,
    )
    res = api.open_session(session["id"], make_instructor_headers(instr["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert after["status"] == "SCHEDULED"


def test_completed_session_cannot_be_cancelled(api):
    """PRD §3.10: "Completing is an Instructor action permitted only while the
    session is LOCKED and advances it LOCKED -> COMPLETED."
    PRD §3.10: "A StudioAdmin may cancel a session from any of SCHEDULED, OPEN,
    FULL, or LOCKED, moving it to CANCELLED."

    A COMPLETED session is terminal; cancelling it is rejected ERR_INVALID_STATE
    and it stays COMPLETED.

    Design: Corner/state_machines/terminal_completed_session_cannot_cancel
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        session_overrides={
            "station_id": "ST-TERM",
            "start_at": "2026-11-06T14:00:00Z", "end_at": "2026-11-06T16:00:00Z",
        },
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    instr_headers = make_instructor_headers(instr["id"])
    validate_success(api.lock_session(session["id"], instr_headers), 200)
    validate_success(api.complete_session(session["id"], instr_headers), 200)
    res = api.cancel_session(session["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert after["status"] == "COMPLETED"
