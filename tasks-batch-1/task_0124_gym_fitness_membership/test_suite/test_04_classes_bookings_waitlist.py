"""Class booking, waitlisting, promotion, cascades, and capacity/credit gates.

Difficulty design index:
  non_linear_state_machine / booking_waitlist_promotion_cycle_back_to_booked
  transitive_cascade / freeze_cancels_booking_then_promotes_waitlist_depth3
  priority_pair_validation_conflict / booking_stale_version_beats_session_full
  priority_pair_validation_conflict / booking_member_not_bookable_beats_no_class_credits
  resource_temporal_overlap / class_booking_overlapping_session_windows_rejected
  compensating_invariant / class_credit_conserved_under_book_then_cancel
Corner design index:
  calculations / booking_full_session_goes_to_waitlist
  state_machines / session_complete_marks_booked_no_show_and_waitlisted_cancelled
  validations / booking_no_class_credits_returns_402
  errors / error_session_full_when_both_pools_full
  cross_cutting_complexity_layers / cascading_member_cancel_voids_packages_and_cancels_bookings
  cross_cutting_complexity_layers / derived_field_session_counts_reconcile_after_booking
  consistency_model / immediate_consistency_booking_visible_in_create_response
"""
from test_helpers import (
    validate_success, validate_error,
    setup_active_member, setup_suspended_member, setup_seat_and_waitlist,
    create_plan, create_location, create_session, get_session, book,
    create_pt_package, schedule_pt_session, set_clock,
    PLAN_PLUS, PLAN_ELITE,
    ApiErrorId, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ===========================================================================
# non_linear_state_machine / booking_waitlist_promotion_cycle_back_to_booked
# ===========================================================================
def test_waitlisted_booking_promoted_to_booked_on_seat_cancel(api):
    """PRD §3.5: "Promotion moves the chosen booking from WAITLISTED to BOOKED, sets its
    booked_at to the current clock, sets credit_charged to true, and debits one class credit
    from that member."

    Design: Difficulty/non_linear_state_machine/booking_waitlist_promotion_cycle_back_to_booked
    """
    setup = setup_seat_and_waitlist(capacity=1, waitlist_cap=1,
                                    starts_at="2026-06-12T09:00:00Z", ends_at="2026-06-12T10:00:00Z")
    booking_a, booking_b = setup["booking_a"], setup["booking_b"]
    assert booking_b["status"] == "WAITLISTED"
    validate_success(api.cancel_booking(booking_a["id"], STAFF), 200)
    promoted = validate_success(api.get_booking(booking_b["id"], STAFF), 200)
    assert promoted["status"] == "BOOKED"
    assert promoted["waitlist_position"] is None
    assert promoted["credit_charged"] is True


def test_cancelled_seat_booking_reaches_cancelled(api):
    """PRD §3.5: "if the booking had `credit_charged` set — restores one class credit to the
    member and clears `credit_charged`."

    Design: Difficulty/non_linear_state_machine/booking_waitlist_promotion_cycle_back_to_booked
    """
    setup = setup_seat_and_waitlist(capacity=1, waitlist_cap=1,
                                    starts_at="2026-06-12T09:00:00Z", ends_at="2026-06-12T10:00:00Z")
    booking_a = setup["booking_a"]
    data = validate_success(api.cancel_booking(booking_a["id"], STAFF), 200)
    assert data["status"] == "CANCELLED"


# ===========================================================================
# transitive_cascade / freeze_cancels_booking_then_promotes_waitlist_depth3
# ===========================================================================
def test_freeze_cancels_booking_and_promotes_waitlist(api):
    """PRD §3.3: "every future-dated BOOKED booking the member holds on a SCHEDULED session that
    starts after the freeze instant is cancelled. Each such cancellation runs the
    waitlist-promotion cascade on its session (described in §3.5) and restores one class credit
    to the member if that booking had credit_charged set."

    Design: Difficulty/transitive_cascade/freeze_cancels_booking_then_promotes_waitlist_depth3
    """
    setup = setup_seat_and_waitlist(capacity=1, waitlist_cap=1,
                                    starts_at="2026-06-20T09:00:00Z", ends_at="2026-06-20T10:00:00Z")
    member_a, booking_a, booking_b = setup["member_a"], setup["booking_a"], setup["booking_b"]
    set_clock("2026-06-15T00:00:00Z")  # before the future-dated session
    frozen = validate_success(api.freeze_member(member_a["id"], {"freeze_days": 5}, STAFF), 200)
    assert frozen["membership_status"] == "FROZEN"
    cancelled = validate_success(api.get_booking(booking_a["id"], STAFF), 200)
    assert cancelled["status"] == "CANCELLED"
    promoted = validate_success(api.get_booking(booking_b["id"], STAFF), 200)
    assert promoted["status"] == "BOOKED"
    assert promoted["credit_charged"] is True


def test_freeze_sets_membership_frozen(api):
    """PRD §3.3: "When a freeze succeeds, membership_status moves to FROZEN, the requested span
    is added to cumulative_freeze_days, and the member's version increments."

    Design: Difficulty/transitive_cascade/freeze_cancels_booking_then_promotes_waitlist_depth3
    """
    setup = setup_seat_and_waitlist(capacity=1, waitlist_cap=1,
                                    starts_at="2026-06-20T09:00:00Z", ends_at="2026-06-20T10:00:00Z")
    member_a = setup["member_a"]
    set_clock("2026-06-15T00:00:00Z")
    frozen = validate_success(api.freeze_member(member_a["id"], {"freeze_days": 5}, STAFF), 200)
    assert frozen["membership_status"] == "FROZEN"
    assert frozen["cumulative_freeze_days"] == 5


# ===========================================================================
# priority_pair_validation_conflict / booking_stale_version_beats_session_full
# ===========================================================================
def test_stale_session_version_beats_session_full(api):
    """PRD §2.10: "Then, on guarded writes, the optimistic-concurrency version check runs
    (HTTP 412). Then the target resource's state is checked for transition validity
    (ERR_INVALID_STATE), followed by any operation-specific business rules described in §3."
    PRD §2.7: "If that value does not equal the session's current version, the create is
    rejected with ERR_STALE_SESSION_VERSION (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/booking_stale_version_beats_session_full
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    setup_a = setup_active_member(plan=plan, location=location)
    setup_c = setup_active_member(plan=plan, location=location)
    session = create_session(location["id"], capacity=1, waitlist_cap=0,
                             starts_at="2026-06-15T09:00:00Z", ends_at="2026-06-15T10:00:00Z")
    stale_v = session["version"]
    book(session["id"], setup_a["member"]["id"], stale_v)  # takes the seat, advances version
    # m_c books carrying the stale pre-seat version against a now-full session.
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": setup_c["member"]["id"],
         "expected_session_version": stale_v}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SESSION_VERSION.value, expected_status=412)


def test_stale_session_version_rejection_creates_no_booking(api):
    """PRD §2.7: "If that value does not equal the session's current version, the create is
    rejected with ERR_STALE_SESSION_VERSION (HTTP 412). This protects the case where the last
    open seat was taken by another booking — which advances the session's version and changes
    its booked_count — so the current writer's view of available capacity is stale and cannot be
    trusted."

    Design: Difficulty/priority_pair_validation_conflict/booking_stale_version_beats_session_full
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    setup_a = setup_active_member(plan=plan, location=location)
    setup_c = setup_active_member(plan=plan, location=location)
    session = create_session(location["id"], capacity=1, waitlist_cap=0,
                             starts_at="2026-06-15T09:00:00Z", ends_at="2026-06-15T10:00:00Z")
    stale_v = session["version"]
    book(session["id"], setup_a["member"]["id"], stale_v)
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": setup_c["member"]["id"],
         "expected_session_version": stale_v}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SESSION_VERSION.value, expected_status=412)
    # The rejected stale-version write must not have created a booking for m_c.
    from test_helpers import validate_paginated
    data, meta = validate_paginated(
        api.list_bookings(STAFF, params={"member_id": setup_c["member"]["id"]})
    )
    assert meta["total_count"] == 0, "stale-version booking must create no Booking"


def test_session_full_when_both_pools_full(api):
    """PRD §3.5: "when the seated pool is full (booked_count has reached capacity) and the
    waitlist pool is also full (waitlisted_count has reached waitlist_cap), the booking is
    rejected with ERR_SESSION_FULL (HTTP 409)."

    Design: Corner/errors/error_session_full_when_both_pools_full
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    setup_a = setup_active_member(plan=plan, location=location)
    setup_c = setup_active_member(plan=plan, location=location)
    session = create_session(location["id"], capacity=1, waitlist_cap=0,
                             starts_at="2026-06-22T09:00:00Z", ends_at="2026-06-22T10:00:00Z")
    book(session["id"], setup_a["member"]["id"], session["version"])
    fresh = get_session(session["id"])  # carry the fresh post-seat version
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": setup_c["member"]["id"],
         "expected_session_version": fresh["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)


# ===========================================================================
# priority_pair_validation_conflict / booking_member_not_bookable_beats_no_class_credits
# ===========================================================================
def test_member_not_bookable_beats_no_class_credits(api):
    """PRD §3.5: "booking is permitted only while the member's membership_status is ACTIVE and
    their dues_status is not SUSPENDED; otherwise the request is rejected with
    ERR_MEMBER_NOT_BOOKABLE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/booking_member_not_bookable_beats_no_class_credits
    """
    # Plan with zero credits, then drive to SUSPENDED: both gates would fire; bookability wins.
    plan = create_plan(PLAN_PLUS, included_class_credits=0)
    setup = setup_suspended_member(plan=plan)
    member = setup["member"]
    assert member["dues_status"] == "SUSPENDED"
    assert member["class_credits_remaining"] == 0
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-08-05T09:00:00Z", ends_at="2026-08-05T10:00:00Z")
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": member["id"],
         "expected_session_version": session["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_BOOKABLE.value)


def test_suspended_zero_credit_member_blocked_creates_no_booking(api):
    """PRD §3.5: "booking is permitted only while the member's membership_status is ACTIVE and
    their dues_status is not SUSPENDED; otherwise the request is rejected with
    ERR_MEMBER_NOT_BOOKABLE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/booking_member_not_bookable_beats_no_class_credits
    """
    plan = create_plan(PLAN_PLUS, included_class_credits=0)
    setup = setup_suspended_member(plan=plan)
    member = setup["member"]
    assert member["dues_status"] == "SUSPENDED" and member["class_credits_remaining"] == 0
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-08-06T09:00:00Z", ends_at="2026-08-06T10:00:00Z")
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": member["id"],
         "expected_session_version": session["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_BOOKABLE.value)
    from test_helpers import validate_paginated
    data, meta = validate_paginated(api.list_bookings(STAFF, params={"member_id": member["id"]}))
    assert meta["total_count"] == 0, "blocked booking must create no Booking"


def test_no_class_credits_rejected_when_member_bookable(api):
    """PRD §3.5: "this debits one class credit, so it requires class_credits_remaining to be at
    least one — a member with no remaining credits is rejected with ERR_NO_CLASS_CREDITS
    (HTTP 402)."

    Design: Corner/validations/booking_no_class_credits_returns_402
    """
    plan = create_plan(PLAN_PLUS, included_class_credits=0)
    setup = setup_active_member(plan=plan)  # ACTIVE, not suspended, but zero credits
    member = setup["member"]
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-19T09:00:00Z", ends_at="2026-06-19T10:00:00Z")
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": member["id"],
         "expected_session_version": session["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_NO_CLASS_CREDITS.value)


# ===========================================================================
# resource_temporal_overlap / class_booking_overlapping_session_windows_rejected
# ===========================================================================
def test_overlapping_session_windows_rejected(api):
    """PRD §3.5: "if the member already holds a non-terminal booking — one in BOOKED or
    WAITLISTED status — on another session whose half-open time interval from its starts_at up to
    but not including its ends_at overlaps this session's interval, the request is rejected with
    ERR_BOOKING_TIME_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/class_booking_overlapping_session_windows_rejected
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    loc = setup["location"]
    s1 = create_session(loc["id"], capacity=5, waitlist_cap=5,
                        starts_at="2026-06-13T09:00:00Z", ends_at="2026-06-13T10:00:00Z")
    s2 = create_session(loc["id"], capacity=5, waitlist_cap=5,
                        starts_at="2026-06-13T09:30:00Z", ends_at="2026-06-13T10:30:00Z")
    book(s1["id"], member["id"], s1["version"])
    resp = api.create_booking(
        {"session_id": s2["id"], "member_id": member["id"],
         "expected_session_version": s2["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_TIME_OVERLAP.value)


def test_non_overlapping_second_booking_succeeds(api):
    """PRD §3.5: "If the seated pool has room (booked_count is below capacity), the booking is
    created BOOKED: this debits one class credit ... and on success it sets credit_charged to
    true, sets booked_at to the current clock, and decrements the member's
    class_credits_remaining."

    Design: Difficulty/resource_temporal_overlap/class_booking_overlapping_session_windows_rejected
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    loc = setup["location"]
    s1 = create_session(loc["id"], capacity=5, waitlist_cap=5,
                        starts_at="2026-06-13T09:00:00Z", ends_at="2026-06-13T10:00:00Z")
    s2 = create_session(loc["id"], capacity=5, waitlist_cap=5,
                        starts_at="2026-06-13T11:00:00Z", ends_at="2026-06-13T12:00:00Z")
    book(s1["id"], member["id"], s1["version"])
    resp = api.create_booking(
        {"session_id": s2["id"], "member_id": member["id"],
         "expected_session_version": s2["version"]}, STAFF
    )
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# ===========================================================================
# compensating_invariant / class_credit_conserved_under_book_then_cancel
# ===========================================================================
def test_class_credit_conserved_under_book_then_cancel(api):
    """PRD §3.5: "Cancelling a booking ... sets the booking to CANCELLED, and — if the booking
    had credit_charged set — restores one class credit to the member and clears credit_charged."

    Design: Difficulty/compensating_invariant/class_credit_conserved_under_book_then_cancel
    """
    plan = create_plan(PLAN_PLUS)  # included_class_credits 8
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-14T09:00:00Z", ends_at="2026-06-14T10:00:00Z")
    booking = book(session["id"], member["id"], session["version"])
    data = validate_success(api.cancel_booking(booking["id"], STAFF), 200)
    assert data["status"] == "CANCELLED"
    assert data["credit_charged"] is False
    member_data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert member_data["class_credits_remaining"] == 8, (
        "book (debit 1) then cancel (restore 1) leaves credits back at 8"
    )


def test_booking_debits_one_credit(api):
    """PRD §3.5: "this debits one class credit ... and on success it sets credit_charged to
    true, sets booked_at to the current clock, and decrements the member's
    class_credits_remaining."

    Design: Difficulty/compensating_invariant/class_credit_conserved_under_book_then_cancel
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-14T09:00:00Z", ends_at="2026-06-14T10:00:00Z")
    booking = book(session["id"], member["id"], session["version"])
    assert booking["credit_charged"] is True
    member_data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert member_data["class_credits_remaining"] == 7, "8 - 1 booked seat = 7"


# ===========================================================================
# calculations / booking_full_session_goes_to_waitlist
# ===========================================================================
def test_booking_full_seated_pool_goes_to_waitlist(api):
    """PRD §3.5: "If the seated pool is full but the waitlist has room, the booking is created
    WAITLISTED instead; waitlisting holds no credit, so credit_charged stays false, booked_at
    stays null, and no credit check applies."
    PRD §3.5: "A waitlisted booking's waitlist_position is its one-based rank among the session's
    WAITLISTED bookings ordered by created_at ascending"

    Design: Corner/calculations/booking_full_session_goes_to_waitlist
    """
    setup = setup_seat_and_waitlist(capacity=1, waitlist_cap=2,
                                    starts_at="2026-06-18T09:00:00Z", ends_at="2026-06-18T10:00:00Z")
    booking_b, member_b = setup["booking_b"], setup["member_b"]
    assert booking_b["status"] == "WAITLISTED"
    assert booking_b["waitlist_position"] == 1
    assert booking_b["credit_charged"] is False
    member_data = validate_success(api.get_member(member_b["id"], STAFF), 200)
    assert member_data["class_credits_remaining"] == 8, "waitlisting holds no credit"


# ===========================================================================
# state_machines / session_complete_marks_booked_no_show_and_waitlisted_cancelled
# ===========================================================================
def test_session_complete_marks_no_show_and_cancels_waitlist(api):
    """PRD §3.5: "every booking still in BOOKED becomes NO_SHOW because the member never attended
    — and a no-show forfeits the credit, so no credit is restored — while every WAITLISTED
    booking becomes CANCELLED since it never held a credit."

    Design: Corner/state_machines/session_complete_marks_booked_no_show_and_waitlisted_cancelled
    """
    setup = setup_seat_and_waitlist(capacity=1, waitlist_cap=1,
                                    starts_at="2026-06-11T09:00:00Z", ends_at="2026-06-11T10:00:00Z")
    session, booking_a, booking_b = setup["session"], setup["booking_a"], setup["booking_b"]
    member_a = setup["member_a"]
    set_clock("2026-06-11T11:00:00Z")  # past ends_at
    fresh = get_session(session["id"])
    completed = validate_success(api.complete_class_session(session["id"], {"expected_session_version": fresh["version"]}, STAFF), 200)
    assert completed["status"] == "COMPLETED"
    bk_a = validate_success(api.get_booking(booking_a["id"], STAFF), 200)
    bk_b = validate_success(api.get_booking(booking_b["id"], STAFF), 200)
    assert bk_a["status"] == "NO_SHOW"
    assert bk_b["status"] == "CANCELLED"
    member_data = validate_success(api.get_member(member_a["id"], STAFF), 200)
    assert member_data["class_credits_remaining"] == 7, "no-show forfeits the credit (stays at 7)"


# ===========================================================================
# cross_cutting / derived_field_session_counts_reconcile_after_booking
# ===========================================================================
def test_session_counts_reconcile_after_booking(api):
    """PRD §2.6: "A class session's booked_count is the number of bookings on it in BOOKED
    status and never exceeds capacity; its waitlisted_count is the number in WAITLISTED status
    and never exceeds waitlist_cap."

    Design: Corner/cross_cutting_complexity_layers/derived_field_session_counts_reconcile_after_booking
    """
    setup = setup_seat_and_waitlist(capacity=1, waitlist_cap=2,
                                    starts_at="2026-06-24T09:00:00Z", ends_at="2026-06-24T10:00:00Z")
    session = setup["session"]
    data = validate_success(api.get_class_session(session["id"], STAFF), 200)
    assert data["booked_count"] == 1
    assert data["waitlisted_count"] == 1


# ===========================================================================
# consistency_model / immediate_consistency_booking_visible_in_create_response
# ===========================================================================
def test_booking_immediately_consistent_in_create_response(api):
    """PRD §2.6: "The implementation must apply all of these consistently and immediately."
    PRD §3.5: "Either way the session's version increments to reflect the count change."

    Design: Corner/consistency_model/immediate_consistency_booking_visible_in_create_response
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-27T09:00:00Z", ends_at="2026-06-27T10:00:00Z")
    data = validate_success(
        api.create_booking(
            {"session_id": session["id"], "member_id": member["id"],
             "expected_session_version": session["version"]}, STAFF
        ), 201
    )
    assert data["status"] == "BOOKED"
    sess_data = validate_success(api.get_class_session(session["id"], STAFF), 200)
    assert sess_data["booked_count"] == 1
    member_data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert member_data["class_credits_remaining"] == 7


# ===========================================================================
# cross_cutting / cascading_member_cancel_voids_packages_and_cancels_bookings
# ===========================================================================
def test_member_cancel_cascades_across_entities(api):
    """PRD §3.7: "Every future-dated booking the member holds in BOOKED or WAITLISTED status on
    a SCHEDULED session is cancelled ... Every ACTIVE PT package the member owns is voided to
    VOID, and each such package's SCHEDULED PT sessions are cancelled"

    Design: Corner/cross_cutting_complexity_layers/cascading_member_cancel_voids_packages_and_cancels_bookings
    """
    plan = create_plan(PLAN_ELITE)
    setup = setup_active_member(plan=plan, clock="2026-06-12T00:00:00Z",
                                period_start="2026-06-12T00:00:00Z",
                                period_end="2026-07-01T00:00:00Z", due_date="2026-06-12T00:00:00Z")
    member = setup["member"]
    loc = setup["location"]
    session = create_session(loc["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-28T09:00:00Z", ends_at="2026-06-28T10:00:00Z")
    booking = book(session["id"], member["id"], session["version"])
    package = create_pt_package(member["id"], sessions_purchased=5, list_price_cents=50000)
    pt_session = schedule_pt_session(package["id"], package["version"],
                                     starts_at="2026-06-29T15:00:00Z")
    validate_success(api.cancel_member(member["id"], STAFF), 200)
    assert validate_success(api.get_booking(booking["id"], STAFF), 200)["status"] == "CANCELLED"
    assert validate_success(api.get_pt_package(package["id"], STAFF), 200)["status"] == "VOID"
    assert validate_success(api.get_pt_session(pt_session["id"], STAFF), 200)["status"] == "CANCELLED"
