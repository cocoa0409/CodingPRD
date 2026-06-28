"""Booking ladder validations: capacity, duplicate, bike availability, chargeable pack,
suspension, scope coverage, window, schedule conflict, waitlist join, retail stock,
plus the validation-priority pair conflicts.

Translates queue-A `boundary_precision_check`, `priority_pair_validation_conflict`,
`cross_entity_state_dependency`, `resource_temporal_overlap`, and queue-B `validations`
/ `errors` instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    fixtures,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / session_full_at_capacity_zero_free_bikes
#   SKIPPED — not uniquely PRD-derivable. PRD 3.4 orders the per-bike check
#   (ERR_BIKE_UNAVAILABLE: "must not already be held by another BOOKED reservation")
#   strictly BEFORE the capacity check ("Finally, capacity is checked: ...
#   ERR_SESSION_FULL"). In a per-bike booking model a full session has every bike
#   already held, so any booking attempt names a held bike and a faithful PRD reader
#   returns ERR_BIKE_UNAVAILABLE, never ERR_SESSION_FULL. The asserted ERR_SESSION_FULL
#   therefore fails the unique-derivability filter; the gap is left as a gap.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / strike_threshold_exactly_three_suspends
# ---------------------------------------------------------------------------
def test_strike_threshold_exactly_three_suspends(api):
    """PRD 2.9: "When a newly created strike-bearing charge causes the active strike
    count to reach three or more, the member's account transitions from `ACTIVE` to
    `SUSPENDED`. The threshold is inclusive — three strikes is enough."

    Design: Difficulty/boundary_precision_check/strike_threshold_exactly_three_suspends
    """
    # Two strikes accrued, member still ACTIVE; the third (trigger) suspends.
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=3, final_strike=False)
    member_id = ctx["member"]["id"]
    before = fixtures.get_member(member_id)
    assert before["active_strike_count"] == 2
    assert before["account_status"] == "ACTIVE"
    # Trigger the third late cancel.
    fixtures.set_clock(ctx["pending_cancel_clock"])
    fixtures.cancel_reservation(
        ctx["studio"]["id"], ctx["pending_session"]["id"],
        ctx["pending_reservation"]["id"], member_id,
    )
    after = fixtures.get_member(member_id)
    assert after["active_strike_count"] == 3
    assert after["account_status"] == "SUSPENDED"


def test_two_strikes_does_not_suspend(api):
    """PRD 2.9: "When a newly created strike-bearing charge causes the active strike
    count to reach three or more, the member's account transitions from `ACTIVE` to
    `SUSPENDED`. The threshold is inclusive — three strikes is enough."

    Design: Difficulty/boundary_precision_check/strike_threshold_exactly_three_suspends
    """
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=2, final_strike=True)
    member = fixtures.get_member(ctx["member"]["id"])
    assert member["active_strike_count"] == 2
    assert member["account_status"] == "ACTIVE", "2 strikes is below the inclusive threshold of 3"


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / suspended_beats_session_full
# ---------------------------------------------------------------------------
def test_suspended_member_booking_full_session_reports_suspended(api):
    """PRD 3.4: "Only then does it confirm the member's account is `ACTIVE` rather than
    `SUSPENDED`, rejecting a suspended booker with `ERR_MEMBER_SUSPENDED`."
    PRD 3.4: "Finally, capacity is checked: a booking is rejected with
    `ERR_SESSION_FULL` when the session's `booked_count` is at or above its `capacity`".

    Design: Difficulty/priority_pair_validation_conflict/suspended_beats_session_full
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]
    member_a, _ = fixtures.setup_member_with_pack(
        studio_id, email="ma@x.com", full_name="Mem A", purchased_credits=10
    )
    member_b, _ = fixtures.setup_member_with_pack(
        studio_id, email="mb@x.com", full_name="Mem B", purchased_credits=10
    )

    # member A books the only bike on a far-future session (so it is full, version current).
    full_session = fixtures.create_session(
        studio_id, estate["room"]["id"], instr_id,
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    fixtures.book(studio_id, full_session["id"], member_a["id"], bike_id, full_session["version"])

    # Suspend member B via 3 late cancels on their own dedicated sessions.
    for i in range(3):
        day = 8 + i
        s = fixtures.create_session(
            studio_id, estate["room"]["id"], instr_id,
            start_utc=f"2026-06-{day:02d}T18:00:00Z", end_utc=f"2026-06-{day:02d}T19:00:00Z",
        )
        r = fixtures.book(studio_id, s["id"], member_b["id"], bike_id, s["version"])
        fixtures.set_clock(f"2026-06-{day:02d}T12:00:00Z")
        fixtures.cancel_reservation(studio_id, s["id"], r["id"], member_b["id"])
    assert fixtures.get_member(member_b["id"])["account_status"] == "SUSPENDED"

    fixtures.set_clock("2026-06-11T00:00:00Z")
    live = fixtures.get_session(full_session["id"], member_b["id"])
    resp = api.create_reservation(
        studio_id, full_session["id"],
        {
            "member_id": member_b["id"],
            "bike_id": bike_id,
            "expected_session_version": live["version"],
        },
        make_member_headers(member_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value, expected_status=403)


def test_suspension_check_precedes_capacity_check(api):
    """PRD 3.4: "Only then does it confirm the member's account is `ACTIVE` rather than
    `SUSPENDED`, rejecting a suspended booker with `ERR_MEMBER_SUSPENDED`."
    PRD 3.4: "Finally, capacity is checked: a booking is rejected with
    `ERR_SESSION_FULL` when the session's `booked_count` is at or above its `capacity`".

    Design: Difficulty/priority_pair_validation_conflict/suspended_beats_session_full
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]
    member_a, _ = fixtures.setup_member_with_pack(
        studio_id, email="ma@x.com", full_name="Mem A", purchased_credits=10
    )
    member_b, _ = fixtures.setup_member_with_pack(
        studio_id, email="mb@x.com", full_name="Mem B", purchased_credits=10
    )
    full_session = fixtures.create_session(
        studio_id, estate["room"]["id"], instr_id,
        start_utc="2026-06-25T18:00:00Z", end_utc="2026-06-25T19:00:00Z",
    )
    fixtures.book(studio_id, full_session["id"], member_a["id"], bike_id, full_session["version"])
    # Suspend member B.
    for i in range(3):
        day = 8 + i
        s = fixtures.create_session(
            studio_id, estate["room"]["id"], instr_id,
            start_utc=f"2026-06-{day:02d}T18:00:00Z", end_utc=f"2026-06-{day:02d}T19:00:00Z",
        )
        r = fixtures.book(studio_id, s["id"], member_b["id"], bike_id, s["version"])
        fixtures.set_clock(f"2026-06-{day:02d}T12:00:00Z")
        fixtures.cancel_reservation(studio_id, s["id"], r["id"], member_b["id"])
    assert fixtures.get_member(member_b["id"])["account_status"] == "SUSPENDED"
    fixtures.set_clock("2026-06-11T00:00:00Z")
    live = fixtures.get_session(full_session["id"], member_b["id"])
    assert live["booked_count"] >= live["capacity"], "session is genuinely full"
    resp = api.create_reservation(
        studio_id, full_session["id"],
        {
            "member_id": member_b["id"],
            "bike_id": bike_id,
            "expected_session_version": live["version"],
        },
        make_member_headers(member_b["id"]),
    )
    # Suspension is checked before capacity, so the error is suspension, not full.
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value, expected_status=403)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / not_found_beats_bike_unavailable
# ---------------------------------------------------------------------------
def test_nonexistent_session_reports_not_found_over_bike(api):
    """PRD 2.5: "The system validates path identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` at the first identifier that does not
    resolve to an existing resource."
    PRD 3.4: "Authentication is checked first, then role permission, then the existence
    and scope of every path resource ... After those gates, the business constraints on
    the seat itself are evaluated."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_bike_unavailable
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(studio_id)
    resp = api.create_reservation(
        studio_id, "00000000-0000-4000-8000-000000000000",
        {
            "member_id": member["id"],
            "bike_id": estate["bikes"][0]["id"],
            "expected_session_version": pack["version"],
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_nonexistent_session_not_found_even_with_retired_bike(api):
    """PRD 2.5: "The system validates path identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` at the first identifier that does not
    resolve to an existing resource."
    PRD 3.4: "The chosen bike must be `ACTIVE` ... any of these failures yields
    `ERR_BIKE_UNAVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_bike_unavailable
    """
    # The bike is RETIRED (a business-constraint failure) AND the session id is missing;
    # the missing path resource (existence) is reported first.
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(studio_id)
    api.retire_bike(studio_id, estate["room"]["id"], estate["bikes"][0]["id"], MGR)
    resp = api.create_reservation(
        studio_id, "00000000-0000-4000-8000-000000000000",
        {
            "member_id": member["id"],
            "bike_id": estate["bikes"][0]["id"],
            "expected_session_version": pack["version"],
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / booking_requires_member_active
# ---------------------------------------------------------------------------
def test_suspended_member_cannot_book_open_session(api):
    """PRD 2.9: "A suspended member is barred from creating new reservations and from
    joining waitlists; such attempts are rejected with `ERR_MEMBER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_member_active
    """
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=3, final_strike=True)
    member_id = ctx["member"]["id"]
    studio_id = ctx["studio"]["id"]
    assert fixtures.get_member(member_id)["account_status"] == "SUSPENDED"
    fixtures.set_clock("2026-06-08T00:00:00Z")
    open_session = fixtures.create_session(
        studio_id, ctx["room"]["id"], ctx["instructor"]["id"],
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    resp = api.create_reservation(
        studio_id, open_session["id"],
        {
            "member_id": member_id,
            "bike_id": ctx["bikes"][0]["id"],
            "expected_session_version": open_session["version"],
        },
        make_member_headers(member_id),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value, expected_status=403)


def test_active_member_can_still_book_before_suspension(api):
    """PRD 2.9: "A suspended member is barred from creating new reservations and from
    joining waitlists; such attempts are rejected with `ERR_MEMBER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_member_active
    """
    # A member with only 2 strikes (ACTIVE) can still book.
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=2, final_strike=True)
    member_id = ctx["member"]["id"]
    assert fixtures.get_member(member_id)["account_status"] == "ACTIVE"
    fixtures.set_clock("2026-06-08T00:00:00Z")
    session = fixtures.create_session(
        ctx["studio"]["id"], ctx["room"]["id"], ctx["instructor"]["id"],
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    res = fixtures.book(
        ctx["studio"]["id"], session["id"], member_id, ctx["bikes"][0]["id"], session["version"]
    )
    assert res["attendance_status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / booking_requires_chargeable_pack_in_scope
# ---------------------------------------------------------------------------
def test_home_only_pack_at_other_studio_no_chargeable_pack(api):
    """PRD 3.4: "a `HOME_ONLY` pack covers the booking only when the session's
    `studio_id` equals the member's `home_studio_id` (its grant list is ignored)".
    PRD 3.4: "If the candidate set is empty, the booking fails with
    `ERR_NO_CHARGEABLE_PACK`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_chargeable_pack_in_scope
    """
    two = fixtures.setup_two_studios()
    studio_a, studio_b = two["studio_a"], two["studio_b"]
    instr_id = two["instructor"]["id"]
    member = fixtures.register_member(studio_a["id"])
    # Only pack is HOME_ONLY at studio A.
    fixtures.create_credit_pack(
        member["id"], purchased_credits=5, price_cents=5000, scope="HOME_ONLY"
    )
    # Consume the first-ride comp with a real ride at studio A.
    sa = fixtures.create_session(
        studio_a["id"], two["room_a"]["id"], instr_id,
        start_utc="2026-06-10T18:00:00Z", end_utc="2026-06-10T19:00:00Z",
    )
    ra = fixtures.book(studio_a["id"], sa["id"], member["id"], two["bike_a"]["id"], sa["version"])
    fixtures.set_clock("2026-06-10T18:30:00Z")
    fixtures.check_in(studio_a["id"], sa["id"], ra["id"], instr_id)
    # Now book at studio B -> HOME_ONLY pack does not cover -> no chargeable pack.
    sb = fixtures.create_session(
        studio_b["id"], two["room_b"]["id"], instr_id,
        start_utc="2026-06-12T18:00:00Z", end_utc="2026-06-12T19:00:00Z",
    )
    resp = api.create_reservation(
        studio_b["id"], sb["id"],
        {
            "member_id": member["id"],
            "bike_id": two["bike_b"]["id"],
            "expected_session_version": sb["version"],
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_CHARGEABLE_PACK.value, expected_status=402)


def test_no_pack_at_all_no_chargeable_pack_after_first_ride(api):
    """PRD 3.4: "unless the first-ride comp applies, a chargeable pack must exist, and
    if none does the booking is rejected with `ERR_NO_CHARGEABLE_PACK`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_chargeable_pack_in_scope
    """
    two = fixtures.setup_two_studios()
    studio_a, studio_b = two["studio_a"], two["studio_b"]
    instr_id = two["instructor"]["id"]
    member = fixtures.register_member(studio_a["id"])
    fixtures.create_credit_pack(
        member["id"], purchased_credits=5, price_cents=5000, scope="HOME_ONLY"
    )
    # First-ride comp consumed at A.
    sa = fixtures.create_session(
        studio_a["id"], two["room_a"]["id"], instr_id,
        start_utc="2026-06-10T18:00:00Z", end_utc="2026-06-10T19:00:00Z",
    )
    ra = fixtures.book(studio_a["id"], sa["id"], member["id"], two["bike_a"]["id"], sa["version"])
    fixtures.set_clock("2026-06-10T18:30:00Z")
    fixtures.check_in(studio_a["id"], sa["id"], ra["id"], instr_id)
    # HOME_ONLY pack cannot fund a studio-B booking.
    sb = fixtures.create_session(
        studio_b["id"], two["room_b"]["id"], instr_id,
        start_utc="2026-06-12T18:00:00Z", end_utc="2026-06-12T19:00:00Z",
    )
    resp = api.create_reservation(
        studio_b["id"], sb["id"],
        {
            "member_id": member["id"],
            "bike_id": two["bike_b"]["id"],
            "expected_session_version": sb["version"],
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_CHARGEABLE_PACK.value, expected_status=402)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_instructor_double_booking_overlap_rejected(api):
    """PRD 3.2: "Neither the chosen instructor nor the chosen room may already be
    committed to another `SCHEDULED` session whose time interval overlaps the new one;
    an overlap on either the instructor or the room is rejected with
    `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/instructor_double_booking_overlap
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    room1 = fixtures.create_room(studio["id"], name="R1")
    fixtures.create_bike(studio["id"], room1["id"], label="A1")
    room2 = fixtures.create_room(studio["id"], name="R2")
    fixtures.create_bike(studio["id"], room2["id"], label="B1")
    instr = fixtures.create_instructor()
    fixtures.create_session(
        studio["id"], room1["id"], instr["id"],
        start_utc="2026-06-15T18:00:00Z", end_utc="2026-06-15T19:00:00Z",
    )
    # New session in a different room but the SAME instructor, overlapping time.
    resp = api.create_session(
        studio["id"],
        {
            "room_id": room2["id"],
            "instructor_id": instr["id"],
            "start_utc": "2026-06-15T18:30:00Z",
            "end_utc": "2026-06-15T19:30:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, expected_status=409)


def test_instructor_identical_time_in_other_room_rejected(api):
    """PRD 3.2: "Neither the chosen instructor nor the chosen room may already be
    committed to another `SCHEDULED` session whose time interval overlaps the new one;
    an overlap on either the instructor or the room is rejected with
    `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/instructor_double_booking_overlap
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    room1 = fixtures.create_room(studio["id"], name="R1")
    fixtures.create_bike(studio["id"], room1["id"], label="A1")
    room2 = fixtures.create_room(studio["id"], name="R2")
    fixtures.create_bike(studio["id"], room2["id"], label="B1")
    instr = fixtures.create_instructor()
    fixtures.create_session(
        studio["id"], room1["id"], instr["id"],
        start_utc="2026-06-15T18:00:00Z", end_utc="2026-06-15T19:00:00Z",
    )
    # Exact same interval, different room, same instructor -> overlap on the instructor.
    resp = api.create_session(
        studio["id"],
        {
            "room_id": room2["id"],
            "instructor_id": instr["id"],
            "start_utc": "2026-06-15T18:00:00Z",
            "end_utc": "2026-06-15T19:00:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, expected_status=409)


def test_room_double_booking_overlap_rejected(api):
    """PRD 3.2: "Neither the chosen instructor nor the chosen room may already be
    committed to another `SCHEDULED` session whose time interval overlaps the new one;
    an overlap on either the instructor or the room is rejected with
    `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_double_booking_overlap
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    room1 = fixtures.create_room(studio["id"], name="R1")
    fixtures.create_bike(studio["id"], room1["id"], label="A1")
    instr1 = fixtures.create_instructor(email="i1@x.com", full_name="Instr One")
    instr2 = fixtures.create_instructor(email="i2@x.com", full_name="Instr Two")
    fixtures.create_session(
        studio["id"], room1["id"], instr1["id"],
        start_utc="2026-06-15T18:00:00Z", end_utc="2026-06-15T19:00:00Z",
    )
    # New session: different instructor, SAME room, overlapping time.
    resp = api.create_session(
        studio["id"],
        {
            "room_id": room1["id"],
            "instructor_id": instr2["id"],
            "start_utc": "2026-06-15T18:30:00Z",
            "end_utc": "2026-06-15T19:30:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, expected_status=409)


def test_room_double_booking_enclosed_overlap_rejected(api):
    """PRD 3.2: "Neither the chosen instructor nor the chosen room may already be
    committed to another `SCHEDULED` session whose time interval overlaps the new one;
    an overlap on either the instructor or the room is rejected with
    `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_double_booking_overlap
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    room1 = fixtures.create_room(studio["id"], name="R1")
    fixtures.create_bike(studio["id"], room1["id"], label="A1")
    instr1 = fixtures.create_instructor(email="i1@x.com", full_name="Instr One")
    instr2 = fixtures.create_instructor(email="i2@x.com", full_name="Instr Two")
    fixtures.create_session(
        studio["id"], room1["id"], instr1["id"],
        start_utc="2026-06-15T18:00:00Z", end_utc="2026-06-15T20:00:00Z",
    )
    # New session entirely enclosed within the existing one, SAME room, other instructor.
    resp = api.create_session(
        studio["id"],
        {
            "room_id": room1["id"],
            "instructor_id": instr2["id"],
            "start_utc": "2026-06-15T18:30:00Z",
            "end_utc": "2026-06-15T19:30:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, expected_status=409)


# ---------------------------------------------------------------------------
# Queue B: validations / errors
# ---------------------------------------------------------------------------
def test_waitlist_full_rejects_join(api):
    """PRD 3.6: "A waitlist join is rejected with `ERR_WAITLIST_FULL` when the count of
    entries in `WAITING` is already at the session's `waitlist_capacity`".

    Design: Corner/validations/waitlist_full_rejects_join
    """
    ctx = fixtures.setup_full_session_with_waitlist(waitlist_capacity=1, n_waiters=1)
    studio_id = ctx["studio"]["id"]
    member_c, pack_c = fixtures.setup_member_with_pack(
        studio_id, email="mc@x.com", full_name="Mem C"
    )
    resp = api.join_waitlist(
        studio_id, ctx["session"]["id"],
        {"member_id": member_c["id"], "credit_pack_id": pack_c["id"]},
        make_member_headers(member_c["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WAITLIST_FULL.value, expected_status=409)


def test_join_waitlist_on_not_full_session_rejected(api):
    """PRD 3.6: "Joining is meaningful only for a full session; a join attempted on a
    session that still has free capacity is rejected with `ERR_SESSION_NOT_FULL`, since
    the member should simply book."

    Design: Corner/validations/join_waitlist_on_not_full_session_rejected
    """
    estate = fixtures.setup_studio_estate(n_bikes=2)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(studio_id)
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"]
    )
    resp = api.join_waitlist(
        studio_id, session["id"],
        {"member_id": member["id"], "credit_pack_id": pack["id"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_FULL.value, expected_status=409)


def test_insufficient_stock_rejects_order(api):
    """PRD 3.10: "refused with `ERR_INSUFFICIENT_STOCK` if the requested quantity
    exceeds the product's `stock_qty`".

    Design: Corner/validations/insufficient_stock_rejects_order
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    member = fixtures.register_member(studio["id"])
    product = fixtures.create_product(
        studio["id"], sku="TOWEL", name="Towel", unit_price_cents=800, stock_qty=2
    )
    resp = api.create_retail_order(
        {
            "member_id": member["id"],
            "studio_id": studio["id"],
            "product_id": product["id"],
            "quantity": 5,
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value, expected_status=409)
    prod = validate_success(api.get_product(product["id"], MGR))
    assert prod["stock_qty"] == 2, "stock unchanged on a rejected order"


def test_cancel_after_start_window_closed(api):
    """PRD 3.5: "Cancellation is permitted only while the reservation is `BOOKED` and
    the session is `SCHEDULED`; a cancellation attempted at or after the session's start
    is rejected with `ERR_WINDOW_CLOSED`."

    Design: Corner/validations/cancel_after_start_window_closed
    """
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
    )
    fixtures.set_clock("2026-06-05T18:30:00Z")  # after start, before end
    resp = api.cancel_reservation(
        ctx["studio"]["id"], ctx["session"]["id"], ctx["reservation"]["id"],
        make_member_headers(ctx["member"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED.value, expected_status=409)


def test_duplicate_reservation_rejected(api):
    """PRD 3.4: "The member must not already hold a `BOOKED` reservation on the same
    session — one bike per member per class — and a second attempt yields
    `ERR_DUPLICATE_RESERVATION`."

    Design: Corner/validations/duplicate_reservation_rejected
    """
    estate = fixtures.setup_studio_estate(n_bikes=2)
    studio_id = estate["studio"]["id"]
    member, _ = fixtures.setup_member_with_pack(studio_id)
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"]
    )
    fixtures.book(
        studio_id, session["id"], member["id"], estate["bikes"][0]["id"], session["version"]
    )
    live = fixtures.get_session(session["id"], member["id"])
    resp = api.create_reservation(
        studio_id, session["id"],
        {
            "member_id": member["id"],
            "bike_id": estate["bikes"][1]["id"],
            "expected_session_version": live["version"],
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESERVATION.value, expected_status=409)


def test_book_retired_bike_unavailable(api):
    """PRD 3.4: "The chosen bike must be `ACTIVE`, must belong to the session's room,
    and must not already be held by another `BOOKED` reservation on this session; any of
    these failures yields `ERR_BIKE_UNAVAILABLE`."

    Design: Corner/validations/book_retired_bike_unavailable
    """
    estate = fixtures.setup_studio_estate(n_bikes=2)
    studio_id = estate["studio"]["id"]
    member, _ = fixtures.setup_member_with_pack(studio_id)
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"]
    )
    # Retire bike #2 after the session is scheduled (capacity stays 2).
    api.retire_bike(studio_id, estate["room"]["id"], estate["bikes"][1]["id"], MGR)
    live = fixtures.get_session(session["id"], member["id"])
    resp = api.create_reservation(
        studio_id, session["id"],
        {
            "member_id": member["id"],
            "bike_id": estate["bikes"][1]["id"],
            "expected_session_version": live["version"],
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BIKE_UNAVAILABLE.value, expected_status=409)


def test_booking_with_expired_pack_no_chargeable_pack(api):
    """PRD 3.3: "once the clock reaches or passes a pack's `expires_at`, the pack
    becomes `EXPIRED` ... and its remaining credits are forfeited".
    PRD 3.4: "unless the first-ride comp applies, a chargeable pack must exist, and if
    none does the booking is rejected with `ERR_NO_CHARGEABLE_PACK`."

    Design: Corner/errors/error_pack_expired_on_booking
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    estate = fixtures.setup_studio_estate(n_bikes=2, clock="2026-01-01T00:00:00Z")
    studio_id = estate["studio"]["id"]
    member = fixtures.register_member(studio_id)
    fixtures.create_credit_pack(
        member["id"], purchased_credits=5, price_cents=5000, expires_at="2026-02-01T00:00:00Z"
    )
    # Consume the first-ride comp before the pack expires.
    s1 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-01-15T18:00:00Z", end_utc="2026-01-15T19:00:00Z",
    )
    r1 = fixtures.book(studio_id, s1["id"], member["id"], estate["bikes"][0]["id"], s1["version"])
    fixtures.set_clock("2026-01-15T18:30:00Z")
    fixtures.check_in(studio_id, s1["id"], r1["id"], estate["instructor"]["id"])
    # Advance past expiry, then attempt a fresh booking.
    fixtures.set_clock("2026-02-02T00:00:00Z")
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-02-20T18:00:00Z", end_utc="2026-02-20T19:00:00Z",
    )
    resp = api.create_reservation(
        studio_id, s2["id"],
        {
            "member_id": member["id"],
            "bike_id": estate["bikes"][0]["id"],
            "expected_session_version": s2["version"],
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_CHARGEABLE_PACK.value, expected_status=402)
