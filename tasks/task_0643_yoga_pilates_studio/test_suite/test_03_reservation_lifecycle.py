"""Reservation lifecycle: the BOOKED<->WAITLISTED cycle, room-downgrade demotion +
auto-promote, waitlist re-pack, session-cancel cascades, settlement on completion, the
credit-conservation invariant, and session state-machine guards.

Translates difficulty instances `reservation_waitlist_cycle_booked_waitlisted_booked`,
`session_cancel_cascade_refund_repack_depth2`, `credit_conservation_book_then_early_cancel`,
and corner instances from `state_machines`, `endpoints`, `consistency_model`, and
`cross_cutting_complexity_layers`.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    set_clock, create_room, create_teacher, create_member,
    create_active_entitlement, create_published_session, current_session_version,
    book_reservation,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: reservation_waitlist_cycle_booked_waitlisted_booked
# ---------------------------------------------------------------------------
def _setup_demoted_holder():
    """Room cap 2 + session cap 2: r1 (m1, earliest BOOKED), r2 (m2, latest BOOKED). Then the
    room is downgraded to cap 1, demoting r2 BOOKED->WAITLISTED. Returns (r1, r2, m1)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=2)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    m1 = create_member(email="c1@x.com", full_name="C1")
    m2 = create_member(email="c2@x.com", full_name="C2")
    e1 = create_active_entitlement(m1["id"], price_cents=10000, credits_total=-1)
    e2 = create_active_entitlement(m2["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-20T10:00:00Z",
                                       end_utc="2026-02-20T11:00:00Z", published_capacity=2)
    r1 = book_reservation(m1["id"], session["id"], e1["id"])
    # Advance the logical clock one second so r2 is strictly later-booked than r1
    # (booked_at_utc is the logical-clock instant per PRD §3.4); per PRD §3.5 the
    # most-recently-booked holder (latest booked_at_utc) is demoted first.
    set_clock("2026-02-01T00:00:01Z")
    r2 = book_reservation(m2["id"], session["id"], e2["id"])
    api_client.update_room(room["id"], {"station_capacity": 1,
                                        "expected_room_version": room["version"]}, MGR)
    return r1, r2, m1


def test_room_downgrade_demotes_latest_booked_holder_to_waitlisted(api):
    """PRD §3.5: "The system demotes over-capacity holders from `BOOKED` to `WAITLISTED`,
    choosing the most-recently-booked holder first (latest `booked_at_utc`, breaking ties by
    earliest `created_at`), and places each demoted reservation at the head of the queue —
    `waitlist_position` 1 — with the existing waitlist shifted down behind it."

    Design: Difficulty/non_linear_state_machine/reservation_waitlist_cycle_booked_waitlisted_booked
    """
    r1, r2, m1 = _setup_demoted_holder()
    data = validate_success(api.get_reservation(r2["id"], MGR), 200)
    assert data["status"] == "WAITLISTED"
    assert data["waitlist_position"] == 1


def test_waitlisted_holder_auto_promotes_back_to_booked_on_seat_free(api):
    """PRD §3.6: "the waitlisted reservation with the lowest `waitlist_position` is promoted from
    `WAITLISTED` to `BOOKED`: its `waitlist_position` is cleared to null, its already-held credit
    simply remains charged, and every remaining waitlisted reservation decrements its
    `waitlist_position` by one to close the gap."

    Design: Difficulty/non_linear_state_machine/reservation_waitlist_cycle_booked_waitlisted_booked
    """
    r1, r2, m1 = _setup_demoted_holder()
    # r1 cancels (early) -> a seat frees -> r2 (the only WAITLISTED) auto-promotes to BOOKED.
    api.cancel_reservation(r1["id"], make_member_headers(m1["id"]))
    data = validate_success(api.get_reservation(r2["id"], MGR), 200)
    assert data["status"] == "BOOKED"
    assert data["waitlist_position"] is None


# ---------------------------------------------------------------------------
# Difficulty: session_cancel_cascade_refund_repack_depth2
# ---------------------------------------------------------------------------
def _setup_booked_and_waitlisted_on_cap1():
    """REFORMER room cap 1, session cap 1: M1 BOOKED, M2 WAITLISTED (each a 5-credit pack,
    credits_used=1). Returns (session, r1, r2, e1, e2)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=1)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    m1 = create_member(email="w1@x.com", full_name="W1")
    m2 = create_member(email="w2@x.com", full_name="W2")
    e1 = create_active_entitlement(m1["id"], kind="CLASS_PACK", price_cents=5000, credits_total=5)
    e2 = create_active_entitlement(m2["id"], kind="CLASS_PACK", price_cents=5000, credits_total=5)
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-25T10:00:00Z",
                                       end_utc="2026-02-25T11:00:00Z",
                                       published_capacity=1, waitlist_capacity=5)
    r1 = book_reservation(m1["id"], session["id"], e1["id"])
    r2 = book_reservation(m2["id"], session["id"], e2["id"])
    return session, r1, r2, e1, e2


def test_session_cancel_moves_waitlisted_reservation_to_cancelled_early(api):
    """PRD §3.6: "When a manager cancels a `SCHEDULED`, `OPEN`, or `FULL` session, every
    reservation that is `BOOKED`, `WAITLISTED`, or `CHECKED_IN` moves to `CANCELLED_EARLY`, no
    late-cancel or no-show fee is assessed"

    Design: Difficulty/transitive_cascade/session_cancel_cascade_refund_repack_depth2
    """
    session, r1, r2, e1, e2 = _setup_booked_and_waitlisted_on_cap1()
    api.cancel_class_session(session["id"], MGR)
    data = validate_success(api.get_reservation(r2["id"], MGR), 200)
    assert data["status"] == "CANCELLED_EARLY"


def test_session_cancel_refunds_waitlisted_held_credit(api):
    """PRD §3.6: "every such reservation that had `credit_charged` true has its credit returned
    to the owning entitlement (the entitlement's `credits_used` decreases by one)."

    Design: Difficulty/transitive_cascade/session_cancel_cascade_refund_repack_depth2
    """
    session, r1, r2, e1, e2 = _setup_booked_and_waitlisted_on_cap1()
    api.cancel_class_session(session["id"], MGR)
    data = validate_success(api.get_entitlement(e2["id"], MGR), 200)
    assert data["credits_used"] == 0, "held credit refunded on studio cancel"


# ---------------------------------------------------------------------------
# Difficulty: credit_conservation_book_then_early_cancel
# ---------------------------------------------------------------------------
def _setup_pack_member_open_session():
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="ic@x.com", full_name="Ivy")
    ent = create_active_entitlement(member["id"], kind="CLASS_PACK", price_cents=5000, credits_total=5)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-22T10:00:00Z",
                                       end_utc="2026-02-22T11:00:00Z", published_capacity=10)
    return member, ent, session


def test_book_debits_one_credit_from_finite_pack(api):
    """PRD §3.5: "A reservation that lands `BOOKED` charges one credit: `credits_used` on the
    entitlement increases by one and `credit_charged` becomes true."

    Design: Difficulty/compensating_invariant/credit_conservation_book_then_early_cancel
    """
    member, ent, session = _setup_pack_member_open_session()
    book_reservation(member["id"], session["id"], ent["id"])
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["credits_used"] == 1
    assert data["credits_remaining"] == 4


def test_early_cancel_refunds_credit_conserving_the_pool(api):
    """PRD §3.6: "A `BOOKED` reservation cancelled in the early window moves to `CANCELLED_EARLY`:
    its credit is refunded (the entitlement's `credits_used` decreases by one and `credit_charged`
    becomes false), and the system auto-promotes the head of the session's waitlist into the freed
    seat."

    Design: Difficulty/compensating_invariant/credit_conservation_book_then_early_cancel
    """
    member, ent, session = _setup_pack_member_open_session()
    res = book_reservation(member["id"], session["id"], ent["id"])
    api.cancel_reservation(res["id"], make_member_headers(member["id"]))
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["credits_used"] == 0
    assert data["credits_remaining"] == 5
    assert data["credits_used"] + data["credits_remaining"] == 5, "net drift == 0"


# ---------------------------------------------------------------------------
# Corner: session settlement cascade end-to-end + waitlist re-pack
# ---------------------------------------------------------------------------
def test_session_complete_settlement_cascade_end_to_end(api):
    """PRD §3.6: "Each reservation still `CHECKED_IN` becomes `ATTENDED` (its credit charge
    stands)"
    PRD §3.6: "Each reservation still `WAITLISTED` becomes `CANCELLED_EARLY`"

    Design: Corner/cross_cutting_complexity_layers/session_complete_settlement_cascade_end_to_end
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=1)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    m1 = create_member(email="ca1@x.com", full_name="Ca1")
    m2 = create_member(email="ca2@x.com", full_name="Ca2")
    e1 = create_active_entitlement(m1["id"], price_cents=10000, credits_total=-1)
    e2 = create_active_entitlement(m2["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-12T10:00:00Z",
                                       end_utc="2026-02-12T11:00:00Z",
                                       published_capacity=1, waitlist_capacity=5)
    r1 = book_reservation(m1["id"], session["id"], e1["id"])
    r2 = book_reservation(m2["id"], session["id"], e2["id"])  # WAITLISTED
    set_clock("2026-02-12T10:00:00Z")
    api.start_class_session(session["id"], MGR)
    api.check_in_reservation(r1["id"], make_member_headers(m1["id"]))
    api.complete_class_session(session["id"], MGR)
    assert validate_success(api.get_reservation(r1["id"], MGR), 200)["status"] == "ATTENDED"
    assert validate_success(api.get_reservation(r2["id"], MGR), 200)["status"] == "CANCELLED_EARLY"


def test_waitlist_promote_repacks_positions(api):
    """PRD §3.6: "the waitlisted reservation with the lowest `waitlist_position` is promoted from
    `WAITLISTED` to `BOOKED`: its `waitlist_position` is cleared to null, its already-held credit
    simply remains charged, and every remaining waitlisted reservation decrements its
    `waitlist_position` by one to close the gap."

    Design: Corner/state_machines/waitlist_promote_repacks_positions
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=1)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    m1 = create_member(email="k1@x.com", full_name="K1")
    m2 = create_member(email="k2@x.com", full_name="K2")
    m3 = create_member(email="k3@x.com", full_name="K3")
    e1 = create_active_entitlement(m1["id"], price_cents=10000, credits_total=-1)
    e2 = create_active_entitlement(m2["id"], price_cents=10000, credits_total=-1)
    e3 = create_active_entitlement(m3["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-26T10:00:00Z",
                                       end_utc="2026-02-26T11:00:00Z",
                                       published_capacity=1, waitlist_capacity=5)
    r1 = book_reservation(m1["id"], session["id"], e1["id"])   # BOOKED
    r2 = book_reservation(m2["id"], session["id"], e2["id"])   # WAITLISTED pos 1
    r3 = book_reservation(m3["id"], session["id"], e3["id"])   # WAITLISTED pos 2
    api.cancel_reservation(r1["id"], make_member_headers(m1["id"]))  # frees the seat
    assert validate_success(api.get_reservation(r2["id"], MGR), 200)["status"] == "BOOKED"
    r3_data = validate_success(api.get_reservation(r3["id"], MGR), 200)
    assert r3_data["status"] == "WAITLISTED"
    assert r3_data["waitlist_position"] == 1, "re-packed from 2 down to 1"


# ---------------------------------------------------------------------------
# Corner: session/reservation state-machine guards + reads
# ---------------------------------------------------------------------------
def test_newly_created_session_initial_state_scheduled(api):
    """PRD §3.2: "At creation the session enters `status` `SCHEDULED`, and its derived
    `booked_count` and `waitlisted_count` both begin at 0."

    Design: Corner/state_machines/newly_created_session_initial_state_scheduled
    """
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    resp = api.create_class_session(
        {"room_id": room["id"], "teacher_id": teacher["id"], "discipline": "VINYASA",
         "start_utc": "2026-03-01T10:00:00Z", "end_utc": "2026-03-01T11:00:00Z",
         "published_capacity": 10},
        MGR,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["booked_count"] == 0
    assert data["waitlisted_count"] == 0


def test_start_session_before_start_utc_returns_invalid_state(api):
    """PRD §3.2: "A manager starts a session, advancing it from `OPEN` or `FULL` to `IN_PROGRESS`,
    only once the logical clock has reached `start_utc`"

    Design: Corner/state_machines/start_session_before_start_utc_returns_invalid_state
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-20T10:00:00Z",
                                       end_utc="2026-02-20T11:00:00Z", published_capacity=10)
    resp = api.start_class_session(session["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_cancel_reservation_from_attended_returns_invalid_state(api):
    """PRD §3.6: "A member checks in to an `IN_PROGRESS` session, moving their `BOOKED`
    reservation to `CHECKED_IN`; check-in requires the reservation to be `BOOKED` and the session
    to be `IN_PROGRESS`."
    PRD §3.6: "Each reservation still `CHECKED_IN` becomes `ATTENDED` (its credit charge stands)"

    Design: Corner/state_machines/cancel_reservation_from_attended_returns_invalid_state
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="at@x.com", full_name="At")
    ent = create_active_entitlement(member["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-05T10:00:00Z",
                                       end_utc="2026-02-05T11:00:00Z", published_capacity=10)
    res = book_reservation(member["id"], session["id"], ent["id"])
    set_clock("2026-02-05T10:00:00Z")
    api.start_class_session(session["id"], MGR)
    api.check_in_reservation(res["id"], make_member_headers(member["id"]))
    api.complete_class_session(session["id"], MGR)  # -> ATTENDED (terminal)
    resp = api.cancel_reservation(res["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_list_session_reservations_filtered(api):
    """PRD §2.3: "Unless otherwise specified, all list endpoints return resources sorted by their
    creation timestamp (`created_at`) in ascending order."
    PRD §3.5: "A reservation that lands `BOOKED` charges one credit: `credits_used` on the
    entitlement increases by one and `credit_charged` becomes true."

    Design: Corner/endpoints/list_session_reservations_filtered
    """
    member, ent, session = _setup_pack_member_open_session()
    res = book_reservation(member["id"], session["id"], ent["id"])
    resp = api.list_class_session_reservations(session["id"], MGR, params={"status": "BOOKED"})
    data, meta = validate_paginated(resp)
    booked = [r for r in data if r["status"] == "BOOKED"]
    assert len(booked) == 1
    assert booked[0]["id"] == res["id"]


def test_booking_visible_in_same_response(api):
    """PRD §3.5: "A reservation that lands `BOOKED` charges one credit: `credits_used` on the
    entitlement increases by one and `credit_charged` becomes true."

    Design: Corner/consistency_model/booking_visible_in_same_response
    """
    member, ent, session = _setup_pack_member_open_session()
    version = current_session_version(session["id"])
    resp = api.create_reservation(
        {"member_id": member["id"], "class_session_id": session["id"], "entitlement_id": ent["id"],
         "expected_class_session_version": version},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"
    ent_data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert ent_data["credits_used"] == 1, "credit debit reflected immediately on re-read"
