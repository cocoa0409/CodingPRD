"""Booking rooms, staffing them and moving a session out of DRAFT."""
from test_helpers import (
    ApiErrorId,
    TEST_CALENDAR,
    add_certified_proctor,
    add_proctor,
    assign_proctor_to_session,
    complete_training,
    create_proctor_assignment_payload,
    create_school,
    create_session,
    create_session_payload,
    create_transition_payload,
    make_officer_headers,
    make_school_coordinator_headers,
    move_session,
    move_window,
    read_session,
    set_clock,
    setup_program,
    setup_program_with_certified_proctor,
    sign_affidavit,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Room occupancy: half-open intervals widened by the turnover buffer ────

def test_room_booked_ten_minutes_after_the_previous_session_conflicts(api):
    """PRD §3.3: "Occupancy is checked on the pairing of `school_id` and
    `room_code` against every existing session at that school and room whose
    status is `DRAFT`, `SCHEDULED`, `ACTIVE`, or `CLOSED`, and the check builds
    in a mandatory 15-minute turnover buffer for clearing and resetting the
    room."
    PRD §3.3: "The proposed session conflicts with an existing one exactly when
    the proposed start falls strictly before the existing end plus 15 minutes
    **and** the existing start falls strictly before the proposed end plus 15
    minutes; if either comparison is not strict, there is no conflict."
    PRD §3.3: "A conflict is reported as `ERR_ROOM_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_occupancy_uses_half_open_intervals_plus_turnover_buffer
    """
    ctx = setup_program(district_code="NG-0015", school_code="OH-01",
                        lot_code="LOT-N1", seal_start=1800,
                        max_concurrent_seats=90)
    create_session(ctx["window"]["id"], ctx["school"]["id"], room_code="R101",
                   seat_capacity=25)

    response = api.create_session(
        create_session_payload(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101",
                               scheduled_start="2026-09-08T12:10:00Z",
                               scheduled_end="2026-09-08T14:00:00Z",
                               seat_capacity=25),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_ROOM_TIME_CONFLICT.value, 409)

    data, meta = validate_paginated(api.list_sessions(
        make_officer_headers(), params={"window_id": ctx["window"]["id"]}))
    assert meta["total_count"] == 1, "the conflicting booking must not be written"


def test_room_booked_exactly_fifteen_minutes_later_or_elsewhere_fits(api):
    """PRD §3.3: "The proposed session conflicts with an existing one exactly
    when the proposed start falls strictly before the existing end plus 15
    minutes **and** the existing start falls strictly before the proposed end
    plus 15 minutes; if either comparison is not strict, there is no conflict."
    PRD §3.3: "A proposed session that starts exactly 15 minutes after an
    existing session ends therefore fits, while one that starts fourteen minutes
    after does not."

    Design: Difficulty/resource_temporal_overlap/room_occupancy_uses_half_open_intervals_plus_turnover_buffer
    """
    ctx = setup_program(district_code="NG-0015", school_code="OH-01",
                        lot_code="LOT-N1", seal_start=1800,
                        max_concurrent_seats=90)
    create_session(ctx["window"]["id"], ctx["school"]["id"], room_code="R101",
                   seat_capacity=25)

    on_the_buffer = validate_success(api.create_session(
        create_session_payload(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101",
                               scheduled_start="2026-09-08T12:15:00Z",
                               scheduled_end="2026-09-08T14:00:00Z",
                               seat_capacity=25),
        make_school_coordinator_headers(ctx["school"]["id"])), expected_status=201)
    assert on_the_buffer["scheduled_start"] == "2026-09-08T12:15:00.000Z"
    assert on_the_buffer["status"] == "DRAFT"

    other_room = validate_success(api.create_session(
        create_session_payload(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R102",
                               scheduled_start="2026-09-08T12:10:00Z",
                               scheduled_end="2026-09-08T14:00:00Z",
                               seat_capacity=25),
        make_school_coordinator_headers(ctx["school"]["id"])), expected_status=201)
    assert other_room["room_code"] == "R102", (
        "occupancy is scoped to the school and room pairing")

    data, meta = validate_paginated(api.list_sessions(
        make_officer_headers(), params={"window_id": ctx["window"]["id"]}))
    assert meta["total_count"] == 3


# ─── Proctor availability: closed intervals with no buffer ────────────────

def test_proctor_assigned_to_a_touching_interval_conflicts(api):
    """PRD §3.3: "And the proctor must be free: availability is checked against
    every session already assigned to that proctor whose status is `DRAFT`,
    `SCHEDULED`, or `ACTIVE`, **across every school and every window in the
    program**, using closed intervals and no buffer at all."
    PRD §3.3: "The assignment conflicts exactly when the proposed start is at or
    before the existing end and the existing start is at or before the proposed
    end — so two sessions that merely touch, where one begins at the very
    instant the other ends, do conflict."
    PRD §3.3: "A collision is `ERR_PROCTOR_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/proctor_availability_uses_closed_intervals_with_no_buffer
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0016", school_code="PH-01", lot_code="LOT-P1",
        seal_start=1900, max_concurrent_seats=90)
    session_a = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101", seat_capacity=25)
    assign_proctor_to_session(session_a, ctx["proctor"]["id"], ctx["school"]["id"])

    session_b = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R102", seat_capacity=25,
                               scheduled_start="2026-09-08T12:00:00Z",
                               scheduled_end="2026-09-08T15:00:00Z")

    response = api.assign_proctor(
        session_b["id"],
        create_proctor_assignment_payload(ctx["proctor"]["id"],
                                          session_b["version"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_PROCTOR_TIME_CONFLICT.value, 409)

    assert read_session(session_b["id"])["proctor_id"] is None, (
        "the refused assignment must leave the session unstaffed")


def test_proctor_assigned_one_minute_after_the_previous_end_is_accepted(api):
    """PRD §3.3: "The assignment conflicts exactly when the proposed start is at
    or before the existing end and the existing start is at or before the
    proposed end — so two sessions that merely touch, where one begins at the
    very instant the other ends, do conflict."
    PRD §2.3: "Sessions may be narrowed by `window_id`, `school_id`,
    `proctor_id`, `status`, and `session_type`."

    Design: Difficulty/resource_temporal_overlap/proctor_availability_uses_closed_intervals_with_no_buffer
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0016", school_code="PH-01", lot_code="LOT-P1",
        seal_start=1900, max_concurrent_seats=90)
    session_a = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101", seat_capacity=25)
    session_a = assign_proctor_to_session(session_a, ctx["proctor"]["id"],
                                          ctx["school"]["id"])
    session_c = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R103", seat_capacity=25,
                               scheduled_start="2026-09-08T12:01:00Z",
                               scheduled_end="2026-09-08T15:00:00Z")

    assigned = validate_success(api.assign_proctor(
        session_c["id"],
        create_proctor_assignment_payload(ctx["proctor"]["id"],
                                          session_c["version"]),
        make_school_coordinator_headers(ctx["school"]["id"])))

    assert assigned["proctor_id"] == ctx["proctor"]["id"]
    assert read_session(session_a["id"])["proctor_id"] == ctx["proctor"]["id"]

    data, meta = validate_paginated(api.list_sessions(
        make_officer_headers(), params={"proctor_id": ctx["proctor"]["id"]}))
    assert meta["total_count"] == 2


# ─── Certification currency at scheduling time ────────────────────────────

def test_certification_expires_on_the_clock_after_the_training_validity(api):
    """PRD §3.1: "If `revoked_at` is not null, `certification_status` is
    `REVOKED`. Otherwise, if `training_status` is anything other than `PASSED`,
    it is `NOT_CERTIFIED`. Otherwise, if the logical clock has reached or passed
    the instant 365 days after `training_completed_at`, it is `EXPIRED`.
    Otherwise it is `CERTIFIED`."
    PRD §3.1: "Certification therefore decays on its own: a proctor who was
    certified when assigned to a session can be uncertified by the time that
    session is scheduled, which is precisely why the check is repeated at both
    moments."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_depends_on_proctor_certification_currency
    """
    ctx = setup_program(
        district_code="NG-0014", school_code="NH-01", lot_code="LOT-M1",
        seal_start=1700,
        window_overrides={"name": "Fall 2027 ELA G9-12",
                          "window_start": "2027-09-07T08:00:00Z",
                          "window_end": "2027-09-18T18:00:00Z",
                          "makeup_start": "2027-09-21T08:00:00Z",
                          "makeup_end": "2027-09-25T18:00:00Z"})
    proctor = add_proctor(ctx["school"]["id"])
    proctor = complete_training(proctor["id"], ctx["school"]["id"], 92.0)
    assert proctor["certification_status"] == "CERTIFIED"

    set_clock("2027-09-02T08:00:00Z")

    lapsed = validate_success(api.get_proctor(proctor["id"], make_officer_headers()))
    assert lapsed["certification_status"] == "EXPIRED", (
        "365 days after 2026-09-01T08:00:00Z the standing decays to EXPIRED")
    assert lapsed["training_status"] == "PASSED", (
        "the training record itself is untouched by the decay")
    assert lapsed["training_completed_at"] == "2026-09-01T08:00:00.000Z"


def test_scheduling_a_session_whose_proctor_certification_lapsed_is_refused(api):
    """PRD §3.3: "The assigned proctor's `certification_status` must, at this
    moment and not merely at assignment time, still be `CERTIFIED`, failing with
    `ERR_PROCTOR_NOT_CERTIFIED`."
    PRD §3.1: "If `revoked_at` is not null, `certification_status` is `REVOKED`.
    Otherwise, if `training_status` is anything other than `PASSED`, it is
    `NOT_CERTIFIED`. Otherwise, if the logical clock has reached or passed the
    instant 365 days after `training_completed_at`, it is `EXPIRED`. Otherwise
    it is `CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_depends_on_proctor_certification_currency
    """
    ctx = setup_program(
        district_code="NG-0014", school_code="NH-01", lot_code="LOT-M1",
        seal_start=1700,
        window_overrides={"name": "Fall 2027 ELA G9-12",
                          "window_start": "2027-09-07T08:00:00Z",
                          "window_end": "2027-09-18T18:00:00Z",
                          "makeup_start": "2027-09-21T08:00:00Z",
                          "makeup_end": "2027-09-25T18:00:00Z"})
    proctor = add_proctor(ctx["school"]["id"])
    proctor = complete_training(proctor["id"], ctx["school"]["id"], 92.0)
    sign_affidavit(proctor["id"], ctx["window"]["id"],
                   expected_proctor_version=proctor["version"])
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=25,
                             scheduled_start="2027-09-08T09:00:00Z",
                             scheduled_end="2027-09-08T12:00:00Z")
    session = assign_proctor_to_session(session, proctor["id"], ctx["school"]["id"])
    assert session["proctor_id"] == proctor["id"]

    set_clock("2027-09-02T08:00:00Z")

    response = api.transition_session(
        session["id"], create_transition_payload("SCHEDULED"),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_PROCTOR_NOT_CERTIFIED.value, 422)

    unchanged = read_session(session["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["proctor_id"] == proctor["id"]


# ─── Corner cases around the DRAFT session ────────────────────────────────

def test_scheduling_an_unstaffed_session_is_refused(api):
    """PRD §3.3: "The session's `proctor_id` must not be null — attempting to
    schedule an unstaffed session is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/session_scheduling_without_a_proctor_is_rejected
    """
    ctx = setup_program(district_code="NG-1009", school_code="UH-01",
                        lot_code="LOT-Z5", seal_start=2600)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)

    response = api.transition_session(
        session["id"], create_transition_payload("SCHEDULED"),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    unchanged = read_session(session["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["proctor_id"] is None


def test_session_interval_reaching_past_the_window_end_is_refused(api):
    """PRD §3.3: "The session's interval must also sit entirely inside the
    matching phase's own dates — an `INITIAL` session requires `window_start` to
    be at or before `scheduled_start` and `scheduled_end` to be at or before
    `window_end`, and a `MAKEUP` session requires `makeup_start` to be at or
    before `scheduled_start` and `scheduled_end` to be at or before
    `makeup_end`."
    PRD §3.3: "A session that pokes outside its bounds at either end is rejected
    with `ERR_SESSION_OUTSIDE_WINDOW`."

    Design: Corner/validations/session_interval_outside_the_window_bounds_is_rejected
    """
    ctx = setup_program(district_code="NG-1024", school_code="LD-01",
                        lot_code="LOT-X6", seal_start=4100,
                        max_concurrent_seats=40)

    response = api.create_session(
        create_session_payload(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101",
                               scheduled_start="2026-09-18T16:00:00Z",
                               scheduled_end="2026-09-19T10:00:00Z",
                               seat_capacity=20),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_SESSION_OUTSIDE_WINDOW.value, 422)

    inside = validate_success(api.create_session(
        create_session_payload(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101",
                               scheduled_start="2026-09-18T14:00:00Z",
                               scheduled_end="2026-09-18T18:00:00Z",
                               seat_capacity=20),
        make_school_coordinator_headers(ctx["school"]["id"])), expected_status=201)
    assert inside["scheduled_end"] == "2026-09-18T18:00:00.000Z", (
        "an interval ending exactly on window_end sits inside the bounds")

    data, meta = validate_paginated(api.list_sessions(
        make_officer_headers(), params={"window_id": ctx["window"]["id"]}))
    assert meta["total_count"] == 1


def test_makeup_session_may_only_be_built_while_the_window_is_in_makeup(api):
    """PRD §3.3: "The window's phase governs which kind of session may be built
    at all: an `INITIAL` session may only be created while its window is `OPEN`,
    and a `MAKEUP` session only while its window is `MAKEUP`. A mismatch is
    `ERR_WINDOW_PHASE_INVALID`."

    Design: Corner/validations/makeup_session_type_must_match_the_window_phase
    """
    ctx = setup_program(district_code="NG-1025", school_code="MB-01",
                        lot_code="LOT-X7", seal_start=4200,
                        max_concurrent_seats=40)
    makeup_body = create_session_payload(
        ctx["window"]["id"], ctx["school"]["id"], room_code="R101",
        scheduled_start=TEST_CALENDAR["MAKEUP_SESSION_START"],
        scheduled_end=TEST_CALENDAR["MAKEUP_SESSION_END"],
        seat_capacity=20, session_type="MAKEUP")

    too_early = api.create_session(
        makeup_body, make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(too_early, ApiErrorId.ERR_WINDOW_PHASE_INVALID.value, 409)

    set_clock(TEST_CALENDAR["AFTER_WINDOW_END"])
    window = move_window(ctx["window"]["id"], "MAKEUP")
    assert window["status"] == "MAKEUP"

    accepted = validate_success(api.create_session(
        makeup_body, make_school_coordinator_headers(ctx["school"]["id"])),
        expected_status=201)
    assert accepted["session_type"] == "MAKEUP"
    assert accepted["status"] == "DRAFT"


def test_coordinator_cannot_build_a_session_for_another_school(api):
    """PRD §2.1: "A session or proctor may only be created with a `school_id`
    equal to `X-User-ID`; session and registration writes require `X-User-ID` to
    equal the owning Session's `school_id`; and for a custody movement, the
    acting School's `district_id` must equal the lot's `district_id`."
    PRD §2.1: "A violation of any of these ownership rules is rejected with
    `ERR_SCOPE_VIOLATION`."

    Design: Corner/validations/coordinator_acting_outside_its_own_school_returns_scope_violation
    """
    ctx = setup_program(district_code="NG-1023", school_code="JB-01",
                        lot_code="LOT-X5", seal_start=3900,
                        max_concurrent_seats=40)
    school_b = create_school(ctx["district"]["id"], name="Kalmia High",
                             school_code="KA-01", max_concurrent_seats=40)

    response = api.create_session(
        create_session_payload(ctx["window"]["id"], school_b["id"],
                               room_code="R101", seat_capacity=20),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_SCOPE_VIOLATION.value, 403)

    data, meta = validate_paginated(api.list_sessions(
        make_officer_headers(), params={"school_id": school_b["id"]}))
    assert meta["total_count"] == 0


def test_proctor_assignment_replayed_with_a_stale_session_version_is_refused(api):
    """PRD §2.8: "Assigning a proctor to a session — the write served by
    `POST /sessions/{session_id}/proctor-assignments` — requires
    `expected_session_version` in the request body, carrying the `version` of
    the Session as the client last read it."
    PRD §2.8: "If that value does not equal the session's current `version`, the
    request is rejected with `ERR_STALE_SESSION_VERSION` and HTTP 412; this
    prevents a coordinator from silently displacing an assignment it never
    observed."
    PRD §3.3: "A successful assignment writes `proctor_id`, replacing any
    previous assignment outright, and increments the session's `version`."

    Design: Corner/cross_cutting_complexity_layers/proctor_assignment_with_stale_session_version_returns_412
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-1041", school_code="BR-01", lot_code="LOT-T3",
        seal_start=5700)
    proctor_two, _ = add_certified_proctor(ctx)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)
    observed_version = session["version"]

    assigned = validate_success(api.assign_proctor(
        session["id"],
        create_proctor_assignment_payload(ctx["proctor"]["id"], observed_version),
        make_school_coordinator_headers(ctx["school"]["id"])))
    assert assigned["version"] == observed_version + 1
    assert assigned["proctor_id"] == ctx["proctor"]["id"]

    replay = api.assign_proctor(
        session["id"],
        create_proctor_assignment_payload(proctor_two["id"], observed_version),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(replay, ApiErrorId.ERR_STALE_SESSION_VERSION.value, 412)
    assert read_session(session["id"])["proctor_id"] == ctx["proctor"]["id"], (
        "the stale replay must not displace the standing assignment")

    refreshed = read_session(session["id"])
    superseded = validate_success(api.assign_proctor(
        session["id"],
        create_proctor_assignment_payload(proctor_two["id"], refreshed["version"]),
        make_school_coordinator_headers(ctx["school"]["id"])))
    assert superseded["proctor_id"] == proctor_two["id"], (
        "the refreshed version supersedes the first proctor outright")
    assert superseded["version"] == refreshed["version"] + 1


def test_session_list_narrows_by_status(api):
    """PRD §2.3: "Sessions may be narrowed by `window_id`, `school_id`,
    `proctor_id`, `status`, and `session_type`."
    PRD §3.6: "Both `DRAFT → CANCELLED` and `SCHEDULED → CANCELLED` behave
    identically: the `status` becomes `CANCELLED`, every registration on the
    session whose `attendance_status` is still `PENDING` moves
    `PENDING → WITHDRAWN`, the session then recomputes `seats_consumed`,
    `separate_setting_count`, and `effective_seat_capacity` over the surviving
    roster, and the session's `version` increments."

    Design: Corner/endpoints/session_list_filter_by_status_narrows_the_result_set
    """
    ctx = setup_program(district_code="NG-1036", school_code="WS-01",
                        lot_code="LOT-U2", seal_start=5300)
    session_a = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101", seat_capacity=20)
    session_b = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R102", seat_capacity=20)
    move_session(session_b["id"], "CANCELLED", school_id=ctx["school"]["id"])

    filtered, filtered_meta = validate_paginated(api.list_sessions(
        make_officer_headers(),
        params={"window_id": ctx["window"]["id"], "status": "CANCELLED"}))
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == session_b["id"]

    everything, all_meta = validate_paginated(api.list_sessions(
        make_officer_headers(), params={"window_id": ctx["window"]["id"]}))
    assert all_meta["total_count"] == 2
    assert read_session(session_a["id"])["status"] == "DRAFT"
