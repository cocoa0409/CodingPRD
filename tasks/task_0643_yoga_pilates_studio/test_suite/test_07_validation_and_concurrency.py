"""Validation precedence, cross-entity preconditions, room/teacher temporal overlap at publish,
and peer ownership isolation.

Translates difficulty instances `suspended_member_beats_entitlement_frozen`,
`invalid_state_beats_capacity_exceeds_room`, `reservation_requires_entitlement_active_unfrozen`,
`session_publish_requires_room_open_and_teacher_active`, `room_session_overlap_half_open`,
`room_workshop_overlap_buffer_inclusive`, and corner instance
`member_cannot_cancel_other_members_reservation`.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    set_clock, create_room, create_teacher, create_member,
    create_active_entitlement, create_published_session, current_session_version,
    create_session, book_reservation,
    make_member_established, drive_member_no_show_strikes,
    create_workshop,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: suspended_member_beats_entitlement_frozen (p7 before p8)
# ---------------------------------------------------------------------------
def _setup_suspended_member_with_frozen_membership():
    """Member SUSPENDED (3 no-shows) AND holding a FROZEN ACTIVE membership, plus a published
    OPEN session S with open seats. Returns (member, ent, session)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="sp@x.com", full_name="Spar")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    make_member_established(member["id"], room["id"], teacher["id"], ent["id"],
                           discipline="VINYASA",
                           start_utc="2026-02-01T02:00:00Z", end_utc="2026-02-01T02:30:00Z")
    drive_member_no_show_strikes(member["id"], room["id"], teacher["id"], ent["id"], 3,
                                 discipline="VINYASA")  # -> SUSPENDED
    # Freeze the entitlement so the booking violates both p7 and p8.
    api_client.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-10T10:00:00Z",
                                       end_utc="2026-02-10T11:00:00Z", published_capacity=10)
    return member, ent, session


def test_suspended_member_booking_reports_member_suspended(api):
    """PRD §3.10: "then member standing (`ERR_MEMBER_SUSPENDED` on booking and enrollment), then
    entitlement usability (`ERR_ENTITLEMENT_NOT_USABLE` on booking)."
    PRD §3.5: "The acting member's `account_status` must be `ACTIVE`; a suspended member is
    rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_member_beats_entitlement_frozen
    """
    member, ent, session = _setup_suspended_member_with_frozen_membership()
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": session["id"], "entitlement_id": ent["id"],
         "expected_class_session_version": version},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value, 409)


def test_suspended_member_booking_returns_http_409(api):
    """PRD §3.5: "The acting member's `account_status` must be `ACTIVE`; a suspended member is
    rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_member_beats_entitlement_frozen
    """
    member, ent, session = _setup_suspended_member_with_frozen_membership()
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": session["id"], "entitlement_id": ent["id"],
         "expected_class_session_version": version},
        make_member_headers(member["id"]),
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_MEMBER_SUSPENDED"


# ---------------------------------------------------------------------------
# Difficulty: invalid_state_beats_capacity_exceeds_room (p5 before p13)
# ---------------------------------------------------------------------------
def _setup_open_session_then_room_downgraded():
    """Session S created cap 4 in a cap-4 room, published OPEN, then the room is downgraded to
    cap 2 (so published_capacity 4 > station_capacity 2). Returns the OPEN session S."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-15T10:00:00Z",
                                       end_utc="2026-02-15T11:00:00Z", published_capacity=4)
    api_client.update_room(room["id"], {"station_capacity": 2,
                                        "expected_room_version": room["version"]}, MGR)
    return session


def test_republish_open_session_reports_invalid_state(api):
    """PRD §3.10: "After those come the state-validity check for the requested transition
    (`ERR_INVALID_STATE`)"
    PRD §3.2: "Publication requires that the session is currently `SCHEDULED`"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_capacity_exceeds_room
    """
    session = _setup_open_session_then_room_downgraded()
    resp = api.publish_class_session(session["id"], MGR)  # already OPEN, also capacity>room
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_republish_open_session_invalid_state_beats_capacity(api):
    """PRD §3.10: "the business-constraint checks follow in order: intro eligibility
    (`ERR_INTRO_NOT_ELIGIBLE`), teacher certification at publish (`ERR_TEACHER_NOT_CERTIFIED`),
    room overlap at publish (`ERR_ROOM_DOUBLE_BOOKED`), teacher overlap at publish
    (`ERR_TEACHER_DOUBLE_BOOKED`), capacity versus room (`ERR_CAPACITY_EXCEEDS_ROOM`),
    finite-credit availability (`ERR_NO_CREDITS_REMAINING`), waitlist room (`ERR_WAITLIST_FULL`),
    the freeze ceiling (`ERR_FREEZE_LIMIT_REACHED`), and bookability of the session by clock and
    state (`ERR_SESSION_NOT_BOOKABLE`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_capacity_exceeds_room
    """
    session = _setup_open_session_then_room_downgraded()
    resp = api.publish_class_session(session["id"], MGR)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_INVALID_STATE", "p5 wins over p13"


# ---------------------------------------------------------------------------
# Difficulty: reservation_requires_entitlement_active_unfrozen
# ---------------------------------------------------------------------------
def _setup_member_with_frozen_membership_and_open_session():
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="cf@x.com", full_name="Cy")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    api_client.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-12T10:00:00Z",
                                       end_utc="2026-02-12T11:00:00Z", published_capacity=10)
    return member, ent, session


def test_booking_with_frozen_entitlement_rejected(api):
    """PRD §3.5: "The charged entitlement must belong to the booking member, be lifecycle
    `ACTIVE`, and be `UNFROZEN`; otherwise the booking is rejected with `ERR_ENTITLEMENT_NOT_USABLE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_entitlement_active_unfrozen
    """
    member, ent, session = _setup_member_with_frozen_membership_and_open_session()
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": session["id"], "entitlement_id": ent["id"],
         "expected_class_session_version": version},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_NOT_USABLE.value, 409)


def test_frozen_entitlement_blocks_booking_despite_open_seats(api):
    """PRD §3.4: "On a successful freeze the system records `frozen_at_utc` as the current logical
    clock, and new reservations against the entitlement are rejected while it is `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_entitlement_active_unfrozen
    """
    member, ent, session = _setup_member_with_frozen_membership_and_open_session()
    assert session["status"] == "OPEN", "session has open seats"
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": session["id"], "entitlement_id": ent["id"],
         "expected_class_session_version": version},
        make_member_headers(member["id"]),
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_ENTITLEMENT_NOT_USABLE"


# ---------------------------------------------------------------------------
# Difficulty: session_publish_requires_room_open_and_teacher_active
# ---------------------------------------------------------------------------
def _setup_scheduled_session_in_closed_room():
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    session = create_session(room["id"], teacher["id"], discipline="REFORMER",
                             start_utc="2026-02-20T10:00:00Z",
                             end_utc="2026-02-20T11:00:00Z", published_capacity=4)
    api_client.update_room(room["id"], {"status": "CLOSED",
                                        "expected_room_version": room["version"]}, MGR)
    return session


def test_publish_into_closed_room_rejected(api):
    """PRD §3.2: "Publication requires that the session is currently `SCHEDULED`, that the hosting
    room is `OPEN` (publishing into a closed room is rejected with `ERR_ROOM_CLOSED`), and that the
    assigned teacher is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/session_publish_requires_room_open_and_teacher_active
    """
    session = _setup_scheduled_session_in_closed_room()
    resp = api.publish_class_session(session["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_ROOM_CLOSED.value, 409)


def test_publish_into_closed_room_returns_http_409(api):
    """PRD §3.1: "A new room opens in `status` `OPEN`; a room may also be `CLOSED`, and a `CLOSED`
    room cannot host newly scheduled sessions or workshops."

    Design: Difficulty/cross_entity_state_dependency/session_publish_requires_room_open_and_teacher_active
    """
    session = _setup_scheduled_session_in_closed_room()
    resp = api.publish_class_session(session["id"], MGR)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == "ERR_ROOM_CLOSED"


# ---------------------------------------------------------------------------
# Difficulty: room_session_overlap_half_open
# ---------------------------------------------------------------------------
def _setup_two_sessions_interior_overlap():
    """Session A published 10:00-11:00; session B (same room, different teacher) 10:30-11:30
    created (interior overlap). Returns (room, teacher2, session_b)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    teacher2 = create_teacher(full_name="Toby", certifications=["REFORMER"])
    create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                             start_utc="2026-02-14T10:00:00Z",
                             end_utc="2026-02-14T11:00:00Z", published_capacity=4)
    b = create_session(room["id"], teacher2["id"], discipline="REFORMER",
                       start_utc="2026-02-14T10:30:00Z",
                       end_utc="2026-02-14T11:30:00Z", published_capacity=4)
    return room, teacher2, b


def test_interior_room_overlap_rejected_on_publish(api):
    """PRD §3.2: "No other non-cancelled session may occupy the same room over an interval that
    overlaps the new session's interval, treated as half-open from `start_utc` up to but not
    including `end_utc`; a room conflict is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_session_overlap_half_open
    """
    room, teacher2, b = _setup_two_sessions_interior_overlap()
    resp = api.publish_class_session(b["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value, 409)


def test_adjacent_room_session_allowed_half_open(api):
    """PRD §3.2: "No other non-cancelled session may occupy the same room over an interval that
    overlaps the new session's interval, treated as half-open from `start_utc` up to but not
    including `end_utc`; a room conflict is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_session_overlap_half_open
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    teacher2 = create_teacher(full_name="Toby", certifications=["REFORMER"])
    create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                             start_utc="2026-02-14T10:00:00Z",
                             end_utc="2026-02-14T11:00:00Z", published_capacity=4)
    # B starts exactly at A's end (11:00) -> adjacency allowed under half-open semantics.
    b = create_session(room["id"], teacher2["id"], discipline="REFORMER",
                       start_utc="2026-02-14T11:00:00Z",
                       end_utc="2026-02-14T12:00:00Z", published_capacity=4)
    data = validate_success(api.publish_class_session(b["id"], MGR), 200)
    assert data["status"] == "OPEN", "start_utc == prior end_utc does not overlap"


# ---------------------------------------------------------------------------
# Difficulty: room_workshop_overlap_buffer_inclusive
# ---------------------------------------------------------------------------
def _setup_session_then_workshop_within_buffer():
    """Session A published 10:00-11:00; workshop W (same room) starting 11:15 (within the 30-min
    buffer of A's 11:00 end). Returns workshop W."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    teacher2 = create_teacher(full_name="Theo", certifications=["VINYASA"])
    create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                             start_utc="2026-02-16T10:00:00Z",
                             end_utc="2026-02-16T11:00:00Z", published_capacity=10)
    workshop = create_workshop(room["id"], teacher2["id"], kind="WORKSHOP",
                               start_utc="2026-02-16T11:15:00Z", end_utc="2026-02-16T13:00:00Z",
                               seat_capacity=8, deposit_cents=2000, price_cents=8000)
    return workshop


def test_workshop_within_session_buffer_rejected_on_publish(api):
    """PRD §3.9: "the workshop's interval must clear every other non-cancelled workshop **and**
    every non-cancelled class session in the same room by a buffer of 30 minutes on each side; a
    violation is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_workshop_overlap_buffer_inclusive
    """
    workshop = _setup_session_then_workshop_within_buffer()
    resp = api.publish_workshop(workshop["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value, 409)


def test_workshop_clearing_buffer_publishes(api):
    """PRD §3.9: "the workshop's interval must clear every other non-cancelled workshop **and**
    every non-cancelled class session in the same room by a buffer of 30 minutes on each side; a
    violation is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_workshop_overlap_buffer_inclusive
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    teacher2 = create_teacher(full_name="Theo", certifications=["VINYASA"])
    create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                             start_utc="2026-02-16T10:00:00Z",
                             end_utc="2026-02-16T11:00:00Z", published_capacity=10)
    # Workshop starts 11:31 -> > 30 min after the 11:00 session end, clearing the buffer.
    workshop = create_workshop(room["id"], teacher2["id"], kind="WORKSHOP",
                               start_utc="2026-02-16T11:31:00Z", end_utc="2026-02-16T13:00:00Z",
                               seat_capacity=8, deposit_cents=2000, price_cents=8000)
    data = validate_success(api.publish_workshop(workshop["id"], MGR), 200)
    assert data["status"] == "OPEN", "workshop clears the 30-min buffer"


# ---------------------------------------------------------------------------
# Corner: peer ownership isolation
# ---------------------------------------------------------------------------
def test_member_cannot_cancel_other_members_reservation(api):
    """PRD §2.1: "any ownership check on a resource that references a `Member` compares that
    resource's owning member foreign key (for example `member_id` on a `Reservation`,
    `Entitlement`, `FeeCharge`, or `Enrollment`) to `X-User-ID`. A member acting on a resource
    they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/member_cannot_cancel_other_members_reservation
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member_a = create_member(email="pa@x.com", full_name="Pa")
    member_b = create_member(email="pb@x.com", full_name="Pb")
    ent = create_active_entitlement(member_a["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-20T10:00:00Z",
                                       end_utc="2026-02-20T11:00:00Z", published_capacity=10)
    res = book_reservation(member_a["id"], session["id"], ent["id"])
    resp = api.cancel_reservation(res["id"], make_member_headers(member_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
