"""Booking and capacity resolution: the bookable_capacity calculation (nested min/max with
a room-downgrade clamp), waitlist-full boundary, credit charging, and session bookability gates.

Translates difficulty instances `bookable_capacity_nested_min_max`,
`waitlist_full_empty_seat_boundary`, and corner instances from sections
`entities`, `state_machines`, `validations`, and `errors`.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    set_clock, create_room, create_teacher, create_member,
    create_active_entitlement, create_published_session, current_session_version,
    book_reservation,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: bookable_capacity_nested_min_max (effective = min(published, station))
# ---------------------------------------------------------------------------
def _setup_two_booked_then_downgrade(published_capacity=4, downgraded_station=2):
    """Room cap 4 + session published_capacity 4 + 2 BOOKED members, then PATCH the room
    down to `downgraded_station`. Returns (room, session, third_member, third_entitlement)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    m1 = create_member(email="m1@x.com", full_name="M1")
    m2 = create_member(email="m2@x.com", full_name="M2")
    m3 = create_member(email="m3@x.com", full_name="M3")
    e1 = create_active_entitlement(m1["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    e2 = create_active_entitlement(m2["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    e3 = create_active_entitlement(m3["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-15T10:00:00Z",
                                       end_utc="2026-02-15T11:00:00Z",
                                       published_capacity=published_capacity, waitlist_capacity=5)
    book_reservation(m1["id"], session["id"], e1["id"])
    book_reservation(m2["id"], session["id"], e2["id"])
    api_client.update_room(room["id"], {"station_capacity": downgraded_station,
                                        "expected_room_version": room["version"]}, MGR)
    return room, session, m3, e3


def test_bookable_capacity_clamped_by_room_downgrade_waitlists(api):
    """PRD §3.5: "The effective capacity is the smaller of `published_capacity` and
    `station_capacity` — so that a room downgrade can clamp the bookable seats below what was
    advertised, while a session whose published capacity is within the room's ceiling simply uses
    its published capacity."
    PRD §3.5: "if there are no open seats but the session's `waitlisted_count` is below its
    `waitlist_capacity` the reservation lands `WAITLISTED`"

    Design: Difficulty/combinatorial_formula/bookable_capacity_nested_min_max
    """
    room, session, m3, e3 = _setup_two_booked_then_downgrade()
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": m3["id"], "class_session_id": session["id"], "entitlement_id": e3["id"],
         "expected_class_session_version": version},
        make_member_headers(m3["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "WAITLISTED", "min(4,2)=2 effective; 2 booked -> 0 open seats"


def test_bookable_capacity_clamped_waitlist_position_is_one(api):
    """PRD §3.5: "A reservation that lands `WAITLISTED` is assigned `waitlist_position` equal to
    the session's prior `waitlisted_count` plus one"

    Design: Difficulty/combinatorial_formula/bookable_capacity_nested_min_max
    """
    room, session, m3, e3 = _setup_two_booked_then_downgrade()
    res = book_reservation(m3["id"], session["id"], e3["id"])
    assert res["status"] == "WAITLISTED"
    assert res["waitlist_position"] == 1


# ---------------------------------------------------------------------------
# Difficulty: waitlist_full_empty_seat_boundary (waitlisted_count == waitlist_capacity)
# ---------------------------------------------------------------------------
def _setup_full_session_at_waitlist_cap():
    """REFORMER room cap 1, session cap 1 + waitlist_capacity 1: M1 BOOKED (fills the seat ->
    FULL), M2 WAITLISTED (waitlisted_count == 1 == cap). Returns (session, m3, e3)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=1)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    m1 = create_member(email="g1@x.com", full_name="G1")
    m2 = create_member(email="g2@x.com", full_name="G2")
    m3 = create_member(email="g3@x.com", full_name="G3")
    e1 = create_active_entitlement(m1["id"], price_cents=10000, credits_total=-1)
    e2 = create_active_entitlement(m2["id"], price_cents=10000, credits_total=-1)
    e3 = create_active_entitlement(m3["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-18T10:00:00Z",
                                       end_utc="2026-02-18T11:00:00Z",
                                       published_capacity=1, waitlist_capacity=1)
    book_reservation(m1["id"], session["id"], e1["id"])
    book_reservation(m2["id"], session["id"], e2["id"])
    return session, m3, e3


def test_waitlist_full_rejects_further_booking(api):
    """PRD §3.5: "if the waitlist is also full the booking is rejected with `ERR_WAITLIST_FULL`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/waitlist_full_empty_seat_boundary
    """
    session, m3, e3 = _setup_full_session_at_waitlist_cap()
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": m3["id"], "class_session_id": session["id"], "entitlement_id": e3["id"],
         "expected_class_session_version": version},
        make_member_headers(m3["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WAITLIST_FULL.value, 409)


def test_second_waitlister_within_cap_lands_waitlisted(api):
    """PRD §3.5: "if there are no open seats but the session's `waitlisted_count` is below its
    `waitlist_capacity` the reservation lands `WAITLISTED`"

    Design: Difficulty/boundary_precision_check/waitlist_full_empty_seat_boundary
    """
    # Same FULL session but waitlist_capacity 2 so the third booker lands WAITLISTED (below cap).
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=1)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    m1 = create_member(email="g1@x.com", full_name="G1")
    m2 = create_member(email="g2@x.com", full_name="G2")
    e1 = create_active_entitlement(m1["id"], price_cents=10000, credits_total=-1)
    e2 = create_active_entitlement(m2["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-18T10:00:00Z",
                                       end_utc="2026-02-18T11:00:00Z",
                                       published_capacity=1, waitlist_capacity=2)
    book_reservation(m1["id"], session["id"], e1["id"])  # BOOKED -> FULL
    res2 = book_reservation(m2["id"], session["id"], e2["id"])
    assert res2["status"] == "WAITLISTED"
    assert res2["waitlist_position"] == 1


# ---------------------------------------------------------------------------
# Corner: computed credits, no-credits, not-bookable, version-required
# ---------------------------------------------------------------------------
def test_computed_credits_remaining_after_booking(api):
    """PRD §3.5: "A reservation that lands `BOOKED` charges one credit: `credits_used` on the
    entitlement increases by one and `credit_charged` becomes true."
    PRD §3.3: "`credits_remaining` is `credits_total` minus `credits_used` for finite
    entitlements"

    Design: Corner/entities/computed_credits_remaining_after_booking
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="cr@x.com", full_name="Cr")
    ent = create_active_entitlement(member["id"], kind="CLASS_PACK", price_cents=5000, credits_total=5)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-20T10:00:00Z",
                                       end_utc="2026-02-20T11:00:00Z", published_capacity=10)
    book_reservation(member["id"], session["id"], ent["id"])
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["credits_used"] == 1
    assert data["credits_remaining"] == 4


def test_book_with_no_credits_remaining(api):
    """PRD §3.5: "For a finite entitlement, `credits_remaining` must be at least 1; an unlimited
    membership (whose `credits_total` is -1) is exempt from this check, but a finite entitlement
    with no credits left is rejected with `ERR_NO_CREDITS_REMAINING` (HTTP 409)."

    Design: Corner/validations/book_with_no_credits_remaining
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="nc@x.com", full_name="Nc")
    ent = create_active_entitlement(member["id"], kind="CLASS_PACK", price_cents=2000, credits_total=1)
    s1 = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                  start_utc="2026-02-10T10:00:00Z",
                                  end_utc="2026-02-10T11:00:00Z", published_capacity=10)
    book_reservation(member["id"], s1["id"], ent["id"])  # spends the single credit
    s2 = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                  start_utc="2026-02-11T10:00:00Z",
                                  end_utc="2026-02-11T11:00:00Z", published_capacity=10)
    version = current_session_version(s2["id"])
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": s2["id"], "entitlement_id": ent["id"],
         "expected_class_session_version": version},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_CREDITS_REMAINING.value, 409)


def test_book_session_not_bookable_after_start(api):
    """PRD §3.5: "Booking is only permitted before the session begins — the logical clock must be
    earlier than the session's `start_utc`, and the session must not be `IN_PROGRESS` or in a
    terminal state — otherwise the booking is rejected with `ERR_SESSION_NOT_BOOKABLE` (HTTP 409)."

    Design: Corner/errors/book_session_not_bookable_after_start
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="nb@x.com", full_name="Nb")
    ent = create_active_entitlement(member["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-10T10:00:00Z",
                                       end_utc="2026-02-10T11:00:00Z", published_capacity=10)
    set_clock("2026-02-10T10:00:00Z")
    api.start_class_session(session["id"], MGR)
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": session["id"], "entitlement_id": ent["id"],
         "expected_class_session_version": version},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_BOOKABLE.value, 409)


def test_version_required_missing_on_booking(api):
    """PRD §2.7: "This field is mandatory for booking; if it is absent the request is rejected
    with `ERR_VERSION_REQUIRED` (HTTP 422)."

    Design: Corner/errors/version_required_missing_on_booking
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="vr@x.com", full_name="Vr")
    ent = create_active_entitlement(member["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-20T10:00:00Z",
                                       end_utc="2026-02-20T11:00:00Z", published_capacity=10)
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": session["id"], "entitlement_id": ent["id"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VERSION_REQUIRED.value, 422)
