"""Session booking gates, the two interval regimes, and credit accounting."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_session,
    complete_session,
    create_client,
    create_coach,
    get_enrollment,
    get_session,
    make_client_headers,
    make_coach_headers,
    pause_enrollment,
    set_clock,
    setup_active_enrollment,
    setup_multi_client_active_enrollments,
    validate_error,
    validate_success,
)

PM = TEST_USERS["practice_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
# session_booking_gated_by_enrollment_lifecycle
# ---------------------------------------------------------------------------

def test_session_booking_rejected_when_enrollment_paused(api):
    """PRD §3.4: "Booking requires the enrollment's `lifecycle_status` to
    stand `ACTIVE` (otherwise `ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/session_booking_gated_by_enrollment_lifecycle
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    pause_enrollment(enrollment["id"], client)
    resp = api.book_session(
        enrollment["id"],
        {"scheduled_start": "2026-08-10T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_enrollment(enrollment["id"])["lifecycle_status"] == "PAUSED"


def test_session_booking_rejected_when_enrollment_pending_payment(api):
    """PRD §3.4: "Booking requires the enrollment's `lifecycle_status` to
    stand `ACTIVE` (otherwise `ERR_INVALID_STATE`)". A PENDING_PAYMENT
    enrollment (never activated) is not ACTIVE, so booking is rejected.

    Design: Difficulty/cross_entity_state_dependency/session_booking_gated_by_enrollment_lifecycle
    """
    from test_helpers import (
        create_fit_approved_enrollment,
        create_tier,
        setup_coach_pair,
    )
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier()
    enrollment = create_fit_approved_enrollment(client, coach_a, coach_b, tier)
    assert enrollment["lifecycle_status"] == "PENDING_PAYMENT"
    resp = api.book_session(
        enrollment["id"],
        {"scheduled_start": "2026-08-10T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / session_overlap_half_open_with_buffer
# ---------------------------------------------------------------------------

def _setup_two_active_enrollments_same_coach(api):
    ctx = setup_multi_client_active_enrollments(2)
    return ctx


def test_session_overlap_rejected_inside_buffered_interval(api):
    """PRD §2.9: "A newly booked or rescheduled session for a coach conflicts
    when the interval from its `scheduled_start` up to — but not including —
    start plus `duration_minutes` plus the fifteen-minute buffer intersects
    the identically computed interval of any other `SCHEDULED` session for
    the same coach."
    PRD §2.9: "A collision is rejected with `ERR_SESSION_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/session_overlap_half_open_with_buffer
    """
    ctx = _setup_two_active_enrollments_same_coach(api)
    coach_a = ctx["coach_a"]
    c1, c2 = ctx["clients"]
    e1, e2 = ctx["enrollments"]
    book_session(e1["id"], c1, scheduled_start="2026-08-10T10:00:00Z")
    # Existing occupies [10:00, 11:15); 11:14 start intersects.
    resp = api.book_session(
        e2["id"],
        {"scheduled_start": "2026-08-10T11:14:00Z", "duration_minutes": 60},
        make_client_headers(c2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)


def test_session_booking_allowed_at_touching_half_open_endpoint(api):
    """PRD §2.9: "Because the interval is half-open, two sessions that merely
    touch — one's buffered end exactly equal to the other's start — do not
    collide."

    Design: Difficulty/resource_temporal_overlap/session_overlap_half_open_with_buffer
    """
    ctx = _setup_two_active_enrollments_same_coach(api)
    c1, c2 = ctx["clients"]
    e1, e2 = ctx["enrollments"]
    book_session(e1["id"], c1, scheduled_start="2026-08-10T10:00:00Z")
    # Existing occupies [10:00, 11:15); 11:15 start merely touches it.
    resp = api.book_session(
        e2["id"],
        {"scheduled_start": "2026-08-10T11:15:00Z", "duration_minutes": 60},
        make_client_headers(c2["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["session_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap /
# discovery_call_overlap_closed_interval_no_buffer
# ---------------------------------------------------------------------------

def test_discovery_call_overlap_rejected_at_touching_endpoint(api):
    """PRD §2.9: "A new or rescheduled discovery call occupies the span from
    its `scheduled_start` through start plus `duration_minutes`, both
    endpoints included, and it collides with any other discovery call in
    `SCHEDULED` status for the same coach whose closed span intersects it —
    touching endpoints, where one call's end exactly equals another's start,
    do count as a collision. The rejection is `ERR_DISCOVERY_CALL_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/discovery_call_overlap_closed_interval_no_buffer
    """
    from test_helpers import create_discovery_call_payload, setup_coach_pair
    coach_a, _coach_b = setup_coach_pair()
    c1 = create_client()
    c2 = create_client()
    resp = api.create_discovery_call(
        create_discovery_call_payload(
            c1["id"], coach_a["id"],
            scheduled_start="2026-08-05T10:00:00Z", duration_minutes=30),
        make_client_headers(c1["id"]),
    )
    validate_success(resp, expected_status=201)
    resp = api.create_discovery_call(
        create_discovery_call_payload(
            c2["id"], coach_a["id"],
            scheduled_start="2026-08-05T10:30:00Z", duration_minutes=30),
        make_client_headers(c2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISCOVERY_CALL_OVERLAP)


def test_discovery_call_allowed_one_minute_past_touching_endpoint(api):
    """PRD §2.9: "Discovery calls use closed-interval arithmetic with no
    buffer at all. A new or rescheduled discovery call occupies the span from
    its `scheduled_start` through start plus `duration_minutes`, both
    endpoints included". A call starting one minute after the prior call's
    closed end does not intersect [10:00, 10:30].

    Design: Difficulty/resource_temporal_overlap/discovery_call_overlap_closed_interval_no_buffer
    """
    from test_helpers import create_discovery_call_payload, setup_coach_pair
    coach_a, _coach_b = setup_coach_pair()
    c1 = create_client()
    c2 = create_client()
    resp = api.create_discovery_call(
        create_discovery_call_payload(
            c1["id"], coach_a["id"],
            scheduled_start="2026-08-05T10:00:00Z", duration_minutes=30),
        make_client_headers(c1["id"]),
    )
    validate_success(resp, expected_status=201)
    resp = api.create_discovery_call(
        create_discovery_call_payload(
            c2["id"], coach_a["id"],
            scheduled_start="2026-08-05T10:31:00Z", duration_minutes=30),
        make_client_headers(c2["id"]),
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant /
# session_credit_conservation_across_book_cancel_cycles
# ---------------------------------------------------------------------------

def test_session_credit_returned_on_cancel(api):
    """PRD §3.4: "An enrollment's `sessions_consumed` counts its sessions in
    `COMPLETED` or `NO_SHOW`. Its `sessions_remaining` is `sessions_total`
    minus the consumed count, minus the sessions still `SCHEDULED`, minus the
    sessions `FORFEITED`; a `CANCELLED` session returns its credit to the
    pool."
    PRD §3.4: "The client may instead cancel a `SCHEDULED` session, which
    consumes nothing: the credit returns".

    Design: Difficulty/compensating_invariant/session_credit_conservation_across_book_cancel_cycles
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-06T10:00:00Z")
    data = get_enrollment(enrollment["id"])
    assert data["sessions_consumed"] == 0
    assert data["sessions_remaining"] == 7, \
        "one SCHEDULED session holds one credit (8 - 0 - 1 - 0 = 7)"
    resp = api.cancel_session(sess["id"], make_client_headers(client["id"]))
    validate_success(resp)
    data = get_enrollment(enrollment["id"])
    assert data["sessions_consumed"] == 0
    assert data["sessions_remaining"] == 8, "the cancelled credit returns"


def test_session_credit_consumed_on_completion(api):
    """PRD §3.4: "An enrollment's `sessions_consumed` counts its sessions in
    `COMPLETED` or `NO_SHOW`." PRD §3.4: "The session becomes `COMPLETED`
    with its `version` advancing, the enrollment's `sessions_consumed`
    recomputes with its `version` advancing".

    Design: Difficulty/compensating_invariant/session_credit_conservation_across_book_cancel_cycles
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    coach_a = ctx["coach_a"]
    enrollment = ctx["enrollment"]
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-07T10:00:00Z")
    set_clock("2026-08-07T10:30:00Z")
    complete_session(sess["id"], coach_a)
    data = get_enrollment(enrollment["id"])
    assert data["sessions_consumed"] == 1
    assert data["sessions_remaining"] == 7, \
        "consumed + remaining + scheduled + forfeited == sessions_total (1+7+0+0=8)"


# ---------------------------------------------------------------------------
# Corner instances: invalid transitions, credit exhaustion, window, duration.
# ---------------------------------------------------------------------------

def test_complete_cancelled_session_returns_invalid_state(api):
    """PRD §2.11: "Fourth, the target's state must permit the operation —
    booking a session additionally requires the parent enrollment to be
    `ACTIVE`, and a habit check-in requires its goal to be `OPEN` — else
    `ERR_INVALID_STATE` (HTTP 409)." PRD §3.4: completing a session is a
    transition out of `SCHEDULED`; a CANCELLED session has no such transition.

    Design: Corner/state_machines/complete_cancelled_session_returns_invalid_state
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    coach_a = ctx["coach_a"]
    enrollment = ctx["enrollment"]
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-06T10:00:00Z")
    validate_success(
        api.cancel_session(sess["id"], make_client_headers(client["id"])))
    set_clock("2026-08-06T10:30:00Z")
    resp = api.complete_session(sess["id"], make_coach_headers(coach_a["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_session(sess["id"])["session_status"] == "CANCELLED"
    assert get_enrollment(enrollment["id"])["sessions_consumed"] == 0


def test_booking_ninth_session_returns_no_sessions_remaining(api):
    """PRD §3.4: "it requires credit — `sessions_remaining` at exactly one
    still books, while at zero the request is `ERR_NO_SESSIONS_REMAINING`".

    Design: Corner/validations/booking_ninth_session_returns_no_sessions_remaining
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    for i in range(7):  # days 04..10
        book_session(
            enrollment["id"], client,
            scheduled_start=f"2026-08-{4 + i:02d}T10:00:00Z")
    # 8th booking: sessions_remaining == 1 beforehand -> allowed.
    resp = api.book_session(
        enrollment["id"],
        {"scheduled_start": "2026-08-11T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_success(resp, expected_status=201)
    # 9th booking: sessions_remaining == 0 -> rejected.
    resp = api.book_session(
        enrollment["id"],
        {"scheduled_start": "2026-08-12T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_SESSIONS_REMAINING)


def test_session_outside_program_window_rejected(api):
    """PRD §3.3: "The program window then runs from `activated_at` up to but
    not including `activated_at` plus `duration_days`."
    PRD §3.4: "the `scheduled_start` must lie inside the program window
    (otherwise `ERR_OUTSIDE_PROGRAM_WINDOW`)".

    Design: Corner/validations/session_outside_program_window_rejected
    """
    ctx = setup_active_enrollment()  # ACTIVE 2026-08-03, duration 56 -> window
    client = ctx["client"]           # [2026-08-03T00:00:00Z, 2026-09-28T00:00:00Z)
    enrollment = ctx["enrollment"]
    resp = api.book_session(
        enrollment["id"],
        {"scheduled_start": "2026-09-28T00:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_PROGRAM_WINDOW)
    resp = api.book_session(
        enrollment["id"],
        {"scheduled_start": "2026-09-27T23:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_success(resp, expected_status=201)


def test_session_duration_below_minimum_returns_invalid_request(api):
    """PRD §2.11: "Request-shape validation closes the chain and is evaluated
    last, yielding `ERR_INVALID_REQUEST` (HTTP 400): required fields present,
    enum members valid, and numeric ranges honored — a session's
    `duration_minutes` between 30 and 120 inclusive, a discovery call's
    `duration_minutes` at least 15, a testimonial's `outcome_rating` between
    1 and 5 inclusive, a cohort's `capacity` at least 2, a goal's
    `target_count` at least 1, an assessment's `commitment_score` between 0
    and 100 inclusive, a coach's `max_concurrent_clients` at least 1, and
    tier figures at their floors (`session_count` at least 1, `price_cents`
    at least 0, `duration_days` at least 1, `installment_count_allowed` at
    least 1, `reschedule_cap` at least 0)."

    Design: Corner/validations/session_duration_below_minimum_returns_invalid_request
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    resp = api.book_session(
        enrollment["id"],
        {"scheduled_start": "2026-08-10T10:00:00Z", "duration_minutes": 20},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / reschedule_free_window_exact_24h_boundary
# ---------------------------------------------------------------------------

def test_reschedule_exactly_24h_before_start_is_free(api):
    """PRD §3.4: "Timing decides cost: a move requested twenty-four hours or
    more before the original start is free — exactly twenty-four hours ahead
    is free, to the second — while a move strictly inside that window is
    counted: the new session's `is_late_reschedule` is set true, the
    enrollment's `late_reschedules_used` increments".

    Design: Difficulty/boundary_precision_check/reschedule_free_window_exact_24h_boundary
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-10T10:00:00Z")
    # Clock at exactly 86400 seconds before the original start.
    set_clock("2026-08-09T10:00:00Z")
    resp = api.reschedule_session(
        sess["id"],
        {"scheduled_start": "2026-08-14T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    new_sess = validate_success(resp)
    assert new_sess["is_late_reschedule"] is False
    assert get_enrollment(enrollment["id"])["late_reschedules_used"] == 0
    old = get_session(sess["id"])
    assert old["session_status"] == "CANCELLED"
    assert old["successor_session_id"] == new_sess["id"]


def test_reschedule_one_second_inside_24h_window_is_counted(api):
    """PRD §3.4: "a move strictly inside that window is counted: the new
    session's `is_late_reschedule` is set true, the enrollment's
    `late_reschedules_used` increments, and the enrollment's `version`
    advances."

    Design: Difficulty/boundary_precision_check/reschedule_free_window_exact_24h_boundary
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-12T10:00:00Z")
    # Clock at 86399 seconds before the original start.
    set_clock("2026-08-11T10:00:01Z")
    resp = api.reschedule_session(
        sess["id"],
        {"scheduled_start": "2026-08-15T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    new_sess = validate_success(resp)
    assert new_sess["is_late_reschedule"] is True
    assert get_enrollment(enrollment["id"])["late_reschedules_used"] == 1


def test_late_reschedule_beyond_cap_rejected(api):
    """PRD §3.4: "When that counter has already reached the tier's
    `reschedule_cap`, a late move is rejected with
    `ERR_RESCHEDULE_CAP_REACHED`."

    Design: Corner/validations/late_reschedule_beyond_cap_rejected
    """
    ctx = setup_active_enrollment(tier_overrides={"reschedule_cap": 1})
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-08-10T10:00:00Z")
    set_clock("2026-08-09T12:00:00Z")  # 22h before start -> late
    resp = api.reschedule_session(
        sess["id"],
        {"scheduled_start": "2026-08-14T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    successor = validate_success(resp)
    assert successor["is_late_reschedule"] is True
    set_clock("2026-08-13T12:00:00Z")  # 22h before the new start -> late again
    resp = api.reschedule_session(
        successor["id"],
        {"scheduled_start": "2026-08-16T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESCHEDULE_CAP_REACHED)
    assert get_enrollment(enrollment["id"])["late_reschedules_used"] == 1
