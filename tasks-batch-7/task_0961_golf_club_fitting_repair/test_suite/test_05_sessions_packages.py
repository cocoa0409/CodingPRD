"""Fitting sessions and lesson packages: overlap rules, credit consumption
boundary, bay maintenance, clock sweeps, listing pagination, and defaults."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, api_client, TEST_USERS,
    set_clock, create_customer, create_specialist, create_manager, create_bay,
    book_session, create_lesson_package, customer_headers, staff_headers,
    create_fitting_session_payload, create_bay_payload, create_staff,
)

ADMIN_HEADERS = TEST_USERS["shop_admin_headers"]


def _setup_booked_session(starts="2026-05-10T10:00:00Z", ends="2026-05-10T11:00:00Z",
                          buffer=15):
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer()
    specialist = create_specialist()
    bay = create_bay(cleanup_buffer_minutes=buffer)
    session = book_session(customer, bay, specialist, starts, ends)
    return {"customer": customer, "specialist": specialist, "bay": bay,
            "session": session}


def test_bay_overlap_gap_tighter_than_buffer_rejected(api):
    """PRD §3.2: "The bay check is buffered and half-open: a new session
    conflicts with an existing one unless the new `ends_at` is no later than
    the existing `starts_at` minus the bay's `cleanup_buffer_minutes`, or the
    new `starts_at` is no earlier than the existing `ends_at` plus that
    buffer — so a gap of exactly the buffer's minutes is allowed, and anything
    tighter is rejected with `ERR_BAY_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bay_buffered_half_open_overlap
    """
    ctx = _setup_booked_session()
    specialist2 = create_specialist()
    payload = create_fitting_session_payload(
        ctx["customer"]["id"], ctx["bay"]["id"], specialist2["id"],
        starts_at="2026-05-10T11:10:00Z", ends_at="2026-05-10T12:00:00Z",
    )
    resp = api_client.create_fitting_session(payload, staff_headers(specialist2))
    validate_error(resp, ApiErrorId.ERR_BAY_TIME_CONFLICT)

    s1 = get_success_data(
        api_client.get_fitting_session(ctx["session"]["id"],
                                       staff_headers(ctx["specialist"]))
    )
    assert s1["status"] == "BOOKED", "rejected attempt must not disturb the existing session"


def test_bay_overlap_exactly_buffer_gap_allowed(api):
    """PRD §3.2: "so a gap of exactly the buffer's minutes is allowed, and
    anything tighter is rejected with `ERR_BAY_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bay_buffered_half_open_overlap
    """
    ctx = _setup_booked_session()
    specialist2 = create_specialist()
    payload = create_fitting_session_payload(
        ctx["customer"]["id"], ctx["bay"]["id"], specialist2["id"],
        starts_at="2026-05-10T11:15:00Z", ends_at="2026-05-10T12:15:00Z",
    )
    resp = api_client.create_fitting_session(payload, staff_headers(specialist2))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "BOOKED", (
        f"a gap of exactly 15 minutes (the buffer) must be allowed, got {data['status']}"
    )


def test_specialist_adjacent_sessions_conflict(api):
    """PRD §3.2: "The specialist check, evaluated only after the bay check
    passes, is a closed interval with no buffer: any overlap at all between
    the intervals is a conflict, and adjacency — one session ending exactly
    when the next begins — counts as an overlap, rejected with
    `ERR_SPECIALIST_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/specialist_closed_interval_adjacency_conflict
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer()
    specialist = create_specialist()
    bay1 = create_bay()
    bay2 = create_bay()
    book_session(customer, bay1, specialist,
                 "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
    payload = create_fitting_session_payload(
        customer["id"], bay2["id"], specialist["id"],
        starts_at="2026-05-10T11:00:00Z", ends_at="2026-05-10T12:00:00Z",
    )
    resp = api_client.create_fitting_session(payload, staff_headers(specialist))
    validate_error(resp, ApiErrorId.ERR_SPECIALIST_TIME_CONFLICT)


def test_specialist_one_minute_gap_allowed(api):
    """PRD §3.2: "The specialist check, evaluated only after the bay check
    passes, is a closed interval with no buffer: any overlap at all between
    the intervals is a conflict, and adjacency — one session ending exactly
    when the next begins — counts as an overlap".

    Design: Difficulty/resource_temporal_overlap/specialist_closed_interval_adjacency_conflict
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer()
    specialist = create_specialist()
    bay1 = create_bay()
    bay2 = create_bay()
    book_session(customer, bay1, specialist,
                 "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
    payload = create_fitting_session_payload(
        customer["id"], bay2["id"], specialist["id"],
        starts_at="2026-05-10T11:01:00Z", ends_at="2026-05-10T12:00:00Z",
    )
    resp = api_client.create_fitting_session(payload, staff_headers(specialist))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "BOOKED", (
        "a one-minute gap suffices for a specialist (closed interval, no buffer)"
    )


def _setup_exhausted_package():
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Lou Lake")
    specialist = create_specialist()
    bay1 = create_bay()
    bay2 = create_bay()
    package = create_lesson_package(customer, total_credits=1, price_cents=20_000)
    session1 = book_session(customer, bay1, specialist,
                            lesson_package_id=package["id"])
    return {"customer": customer, "specialist": specialist, "bay2": bay2,
            "package": package, "session1": session1}


def test_last_credit_consumption_exhausts_package(api):
    """PRD §3.2: "On success the booking consumes exactly one credit: the
    package's `credits_used` increments by one (flipping the package to
    `EXHAUSTED` if that reaches the total), and the session's
    `credit_consumed` flag is set true." and "when credit consumption pushes
    `credits_used` to equal `total_credits`, the package flips from `ACTIVE`
    to `EXHAUSTED`"

    Design: Difficulty/boundary_precision_check/lesson_package_exactly_exhausted_blocks_booking
    """
    ctx = _setup_exhausted_package()
    assert ctx["session1"]["credit_consumed"] is True
    manager = create_manager()
    package = get_success_data(
        api_client.get_lesson_package(ctx["package"]["id"], staff_headers(manager))
    )
    assert package["credits_used"] == 1
    assert package["status"] == "EXHAUSTED", (
        f"package must flip to EXHAUSTED at exact equality (1 == 1), got {package['status']}"
    )


def test_booking_on_exhausted_package_rejected(api):
    """PRD §3.2: "its `credits_used` must still be below `total_credits`, or
    the booking is rejected with `ERR_NO_CREDITS_REMAINING` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/lesson_package_exactly_exhausted_blocks_booking
    """
    ctx = _setup_exhausted_package()
    # Book at a non-overlapping time so the priority-9 specialist overlap
    # check passes and the priority-10 credit-availability check is reached
    # (PRD §2.10 validation order: temporal rules before fiscal rules).
    payload = create_fitting_session_payload(
        ctx["customer"]["id"], ctx["bay2"]["id"], ctx["specialist"]["id"],
        starts_at="2026-05-10T12:00:00Z", ends_at="2026-05-10T13:00:00Z",
        lesson_package_id=ctx["package"]["id"],
    )
    resp = api_client.create_fitting_session(payload, staff_headers(ctx["specialist"]))
    validate_error(resp, ApiErrorId.ERR_NO_CREDITS_REMAINING)


def test_bay_maintenance_blocks_check_in(api):
    """PRD §3.1: "A bay in `MAINTENANCE` refuses check-ins — attempting to
    check a session in while its bay is under maintenance is rejected with
    `ERR_BAY_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/bay_maintenance_blocks_session_checkin
    """
    ctx = _setup_booked_session()
    manager = create_manager()
    get_success_data(
        api_client.set_bay_status(ctx["bay"]["id"], {"target_status": "MAINTENANCE"},
                                  staff_headers(manager))
    )
    set_clock("2026-05-10T10:05:00Z")
    resp = api_client.check_in_session(
        ctx["session"]["id"], staff_headers(ctx["specialist"])
    )
    validate_error(resp, ApiErrorId.ERR_BAY_UNAVAILABLE)


def test_bay_maintenance_leaves_session_booked(api):
    """PRD §3.1: "A bay in `MAINTENANCE` refuses check-ins — attempting to
    check a session in while its bay is under maintenance is rejected with
    `ERR_BAY_UNAVAILABLE` (HTTP 409)." and "Every session is born `BOOKED`"
    (§3.2).

    Design: Difficulty/cross_entity_state_dependency/bay_maintenance_blocks_session_checkin
    """
    ctx = _setup_booked_session()
    manager = create_manager()
    get_success_data(
        api_client.set_bay_status(ctx["bay"]["id"], {"target_status": "MAINTENANCE"},
                                  staff_headers(manager))
    )
    set_clock("2026-05-10T10:05:00Z")
    resp = api_client.check_in_session(
        ctx["session"]["id"], staff_headers(ctx["specialist"])
    )
    validate_error(resp, ApiErrorId.ERR_BAY_UNAVAILABLE)
    session = get_success_data(
        api_client.get_fitting_session(ctx["session"]["id"],
                                       staff_headers(ctx["specialist"]))
    )
    assert session["status"] == "BOOKED", (
        f"rejected check-in must leave the session BOOKED, got {session['status']}"
    )


def test_fitting_session_born_booked(api):
    """PRD §3.2: "Every session is born `BOOKED`." and "the session's
    `credit_consumed` flag is set true" only when a package credit is
    consumed; "the session's `credit_refunded` flag is set true" only on an
    early-cancel refund.

    Design: Corner/state_machines/fitting_session_initial_state_booked
    """
    ctx = _setup_booked_session()
    session = ctx["session"]
    assert session["status"] == "BOOKED"
    assert session["credit_consumed"] is False
    assert session["credit_refunded"] is False


def test_complete_from_booked_rejected(api):
    """PRD §3.2: "completion attempted on a session not in `CHECKED_IN` is
    rejected with `ERR_SESSION_NOT_CHECKED_IN`."

    Design: Corner/state_machines/session_complete_from_booked_rejected
    """
    ctx = _setup_booked_session()
    resp = api_client.complete_session(
        ctx["session"]["id"], staff_headers(ctx["specialist"])
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_CHECKED_IN)
    session = get_success_data(
        api_client.get_fitting_session(ctx["session"]["id"],
                                       staff_headers(ctx["specialist"]))
    )
    assert session["status"] == "BOOKED"


def test_check_in_after_cancel_rejected(api):
    """PRD §3.2: "Check-in or cancellation attempted on a session no longer in
    `BOOKED` is rejected with `ERR_SESSION_NOT_BOOKED`"

    Design: Corner/state_machines/session_checkin_after_cancel_rejected
    """
    ctx = _setup_booked_session()
    cancelled = get_success_data(
        api_client.cancel_session(ctx["session"]["id"], customer_headers(ctx["customer"]))
    )
    assert cancelled["status"] == "CANCELLED"
    resp = api_client.check_in_session(
        ctx["session"]["id"], staff_headers(ctx["specialist"])
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_BOOKED)
    session = get_success_data(
        api_client.get_fitting_session(ctx["session"]["id"],
                                       staff_headers(ctx["specialist"]))
    )
    assert session["status"] == "CANCELLED"


def test_no_show_sweep_via_clock(api):
    """PRD §2.5: "any fitting session still in `BOOKED` whose `ends_at`
    precedes the new current time is swept to `NO_SHOW`, forfeiting any
    lesson-package credit the booking consumed — a no-show never refunds."

    Design: Corner/state_machines/no_show_sweep_via_clock
    """
    ctx = _setup_booked_session()
    # A second session (different bay, different specialist) that gets checked
    # in must not be swept (only BOOKED sweeps).
    bay2 = create_bay()
    specialist2 = create_specialist()
    session2 = book_session(ctx["customer"], bay2, specialist2,
                            "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
    get_success_data(
        api_client.check_in_session(session2["id"], staff_headers(specialist2))
    )

    set_clock("2026-05-10T12:00:00Z")
    s1 = get_success_data(
        api_client.get_fitting_session(ctx["session"]["id"],
                                       staff_headers(ctx["specialist"]))
    )
    assert s1["status"] == "NO_SHOW", (
        f"BOOKED session past ends_at must be swept to NO_SHOW, got {s1['status']}"
    )
    s2 = get_success_data(
        api_client.get_fitting_session(session2["id"], staff_headers(ctx["specialist"]))
    )
    assert s2["status"] == "CHECKED_IN", (
        f"only BOOKED sessions are swept; expected CHECKED_IN, got {s2['status']}"
    )


def test_package_expiry_blocks_booking(api):
    """PRD §2.5: "Any lesson package whose `expires_at` lies in the past is
    swept from `ACTIVE` or `EXHAUSTED` to `EXPIRED`." PRD §3.2: "the package
    must not be `EXPIRED` — a booking that tries to consume an expired package
    is rejected with `ERR_PACKAGE_NOT_ACTIVE` (HTTP 409)".

    Design: Corner/state_machines/package_expiry_blocks_booking
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Hugh Holt")
    specialist = create_specialist()
    bay = create_bay()
    package = create_lesson_package(customer, total_credits=5, price_cents=50_000,
                                    expires_at="2026-06-01T00:00:00Z")
    set_clock("2026-06-02T00:00:00Z")
    manager = create_manager()
    swept = get_success_data(
        api_client.get_lesson_package(package["id"], staff_headers(manager))
    )
    assert swept["status"] == "EXPIRED", (
        f"package past expires_at must be swept to EXPIRED, got {swept['status']}"
    )

    payload = create_fitting_session_payload(
        customer["id"], bay["id"], specialist["id"],
        starts_at="2026-06-03T10:00:00Z", ends_at="2026-06-03T11:00:00Z",
        lesson_package_id=package["id"],
    )
    resp = api_client.create_fitting_session(payload, staff_headers(specialist))
    validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ACTIVE)

    after = get_success_data(
        api_client.get_lesson_package(package["id"], staff_headers(manager))
    )
    assert after["credits_used"] == 0, "no credit may be consumed on a rejected booking"


def test_fitting_session_list_pagination_and_filters(api):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
    exceed 100. `offset` defaults to 0." and "the `meta` object of a list
    response carries `limit`, `offset`, `total_count`, and `has_more` so
    clients can page deterministically." PRD §3.2: "Sessions can be listed
    with `customer_id`, `bay_id`, `specialist_id`, `lesson_package_id`, and
    `status` filters".

    Design: Corner/entities/fitting_session_list_pagination_filters
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Val Vale")
    specialist = create_specialist()
    bay = create_bay(cleanup_buffer_minutes=15)
    book_session(customer, bay, specialist,
                 "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
    book_session(customer, bay, specialist,
                 "2026-05-10T11:15:00Z", "2026-05-10T12:15:00Z")
    book_session(customer, bay, specialist,
                 "2026-05-10T12:30:00Z", "2026-05-10T13:30:00Z")

    manager = create_manager()
    mh = staff_headers(manager)
    page1, meta1 = validate_paginated(
        api_client.list_fitting_sessions(
            mh, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
    )
    assert meta1["total_count"] == 3, f"expected total_count 3, got {meta1['total_count']}"
    assert meta1["has_more"] is True
    assert len(page1) == 1

    page3, meta3 = validate_paginated(
        api_client.list_fitting_sessions(
            mh, params={"customer_id": customer["id"], "limit": 1, "offset": 2})
    )
    assert meta3["has_more"] is False
    assert len(page3) == 1
    assert page3[0]["id"] != page1[0]["id"], "pages must return different sessions"


def test_bay_cleanup_buffer_default_applied(api):
    """PRD §3.1: "A `ShopManager` or `ShopAdmin` registers a bay with a
    `bay_name` that must be unique and an optional `cleanup_buffer_minutes`,
    defaulting to 15". and "Bays are born `AVAILABLE`".

    Design: Corner/entities/bay_cleanup_buffer_default_applied
    """
    resp = api_client.create_bay(create_bay_payload(), ADMIN_HEADERS)
    data = validate_success(resp, expected_status=201)
    assert data["cleanup_buffer_minutes"] == 15, (
        f"omitted cleanup_buffer_minutes must default to 15, got {data['cleanup_buffer_minutes']}"
    )
    assert data["status"] == "AVAILABLE"
