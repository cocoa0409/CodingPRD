"""Workshop rooms, sessions, and registrations: seat-capacity waitlisting, room
half-open double-booking, the OPEN-session registration gate, cascade cancel, and
registration ownership."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client,
    new_customer, new_room, new_session, open_session, new_open_session, register,
    create_workshop_session_payload, create_registration_payload,
    cancel_workshop_session, make_customer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Difficulty: boundary_precision_check / seats waitlist at capacity ─────
def _setup_open_session_cap2_three_customers():
    room, session = new_open_session(capacity=2, seat_capacity=20,
                                     start_at="2026-07-10T18:00:00Z",
                                     end_at="2026-07-10T20:00:00Z")
    c1 = new_customer(email="w1@x.com", full_name="W One")
    c2 = new_customer(email="w2@x.com", full_name="W Two")
    c3 = new_customer(email="w3@x.com", full_name="W Three")
    return session, c1, c2, c3


def test_registrations_below_capacity_are_registered(api):
    """PRD §3.8: "A registration is created `REGISTERED` when the session's
    `seats_taken` is below its `capacity` at creation time, and `WAITLISTED`
    otherwise; `seats_taken` is the count of the session's registrations whose
    `status` is `REGISTERED`, recomputed on every registration change."

    Design: Difficulty/boundary_precision_check/workshop_seats_boundary_waitlist_at_capacity
    """
    session, c1, c2, c3 = _setup_open_session_cap2_three_customers()
    r1 = register(session["id"], c1["id"])
    r2 = register(session["id"], c2["id"])
    assert r1["status"] == "REGISTERED"
    assert r2["status"] == "REGISTERED"
    refreshed = validate_success(api.get_workshop_session(session["id"], ADMIN))
    assert refreshed["seats_taken"] == 2


def test_registration_at_capacity_is_waitlisted(api):
    """PRD §3.8: "A registration is created `REGISTERED` when the session's
    `seats_taken` is below its `capacity` at creation time, and `WAITLISTED`
    otherwise".

    Design: Difficulty/boundary_precision_check/workshop_seats_boundary_waitlist_at_capacity
    """
    session, c1, c2, c3 = _setup_open_session_cap2_three_customers()
    register(session["id"], c1["id"])
    register(session["id"], c2["id"])
    r3 = register(session["id"], c3["id"])
    assert r3["status"] == "WAITLISTED"


# ─── Difficulty: resource_temporal_overlap / room half-open double-booking ─
def _room_with_morning_session():
    room = new_room(name="Studio C", seat_capacity=20)
    new_session(room["id"], "2026-07-12T09:00:00Z", "2026-07-12T12:00:00Z", capacity=10,
                title="Morning")
    return room


def test_adjacent_room_session_accepted(api):
    """PRD §3.8: "The session's half-open interval from start up to (but not
    including) end must not overlap any existing non-`CANCELLED` session in the
    same room; two sessions that merely abut — one ending exactly when the next
    begins — do not conflict, but any genuine overlap is rejected with
    `ERR_ROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/room_halfopen_overlap_adjacency_allowed
    """
    room = _room_with_morning_session()
    res = api.create_workshop_session(
        create_workshop_session_payload(room["id"], "2026-07-12T12:00:00Z",
                                        "2026-07-12T14:00:00Z", 10, title="Adjacent"),
        ADMIN,
    )
    session = validate_success(res, expected_status=201)
    assert session["status"] == "SCHEDULED"


def test_overlapping_room_session_rejected(api):
    """PRD §3.8: "two sessions that merely abut — one ending exactly when the next
    begins — do not conflict, but any genuine overlap is rejected with
    `ERR_ROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/room_halfopen_overlap_adjacency_allowed
    """
    room = _room_with_morning_session()
    res = api.create_workshop_session(
        create_workshop_session_payload(room["id"], "2026-07-12T11:00:00Z",
                                        "2026-07-12T13:00:00Z", 10, title="Overlap"),
        ADMIN,
    )
    validate_error(res, "ERR_ROOM_DOUBLE_BOOKED")


# ─── Difficulty: cross_entity_state_dependency / registration needs OPEN ───
def test_register_scheduled_session_rejected(api):
    """PRD §3.8: "Registration is permitted only while a session is `OPEN`;
    attempting to register against a session in any other status is rejected with
    `ERR_SESSION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/registration_requires_session_open
    """
    room = new_room(name="Studio B", seat_capacity=10)
    session = new_session(room["id"], "2026-07-11T18:00:00Z", "2026-07-11T20:00:00Z",
                          capacity=5, title="Aquaponics 101")
    customer = new_customer(email="cx@x.com", full_name="C X")
    headers = make_customer_headers(customer["id"])
    res = api.create_registration(session["id"],
                                  create_registration_payload(customer["id"]), headers)
    validate_error(res, "ERR_SESSION_NOT_OPEN")


def test_register_open_session_succeeds(api):
    """PRD §3.8: "A `StoreAdmin` opens a `SCHEDULED` session, moving it
    `SCHEDULED → OPEN` and enabling registration."
    PRD §3.8: "A `Customer` registers for an `OPEN` session by naming their own
    `customer_id`".

    Design: Difficulty/cross_entity_state_dependency/registration_requires_session_open
    """
    room = new_room(name="Studio B2", seat_capacity=10)
    session = new_session(room["id"], "2026-07-11T18:00:00Z", "2026-07-11T20:00:00Z",
                          capacity=5, title="Aquaponics 101")
    open_session(session["id"])
    customer = new_customer(email="cx2@x.com", full_name="C X2")
    registration = register(session["id"], customer["id"])
    assert registration["status"] == "REGISTERED"


# ─── Corner: state_machines / cancel session cascades registrations ────────
def test_cancel_session_cascades_registrations(api):
    """PRD §3.8: "A `StoreAdmin` may cancel a session that is `SCHEDULED` or
    `OPEN`; cancellation cascades to every non-terminal registration under the
    session — each `REGISTERED` or `WAITLISTED` registration is moved to
    `CANCELLED` — and the session's `seats_taken` is recomputed as those
    cancellations land."

    Design: Corner/state_machines/workshop_cancel_cascades_registrations
    """
    room, session = new_open_session(capacity=5, seat_capacity=20,
                                     start_at="2026-07-13T18:00:00Z",
                                     end_at="2026-07-13T20:00:00Z")
    customer = new_customer(email="wc@x.com", full_name="W C")
    reg = register(session["id"], customer["id"])
    cancel_workshop_session(session["id"])

    reg_after = validate_success(api.get_registration(reg["id"], ADMIN))
    assert reg_after["status"] == "CANCELLED"
    session_after = validate_success(api.get_workshop_session(session["id"], ADMIN))
    assert session_after["seats_taken"] == 0


# ─── Corner: rbac / customer registering another customer → ownership ──────
def test_customer_registering_other_customer_rejected(api):
    """PRD §2.1: "ownership checks on any resource that references a `Customer`
    compare the resource's `customer_id` to `X-User-ID`."
    PRD §2.1: "Whenever an entity-backed principal (`Customer`, `CommercialBuyer`,
    or `Consultant`) targets a resource they do not own, the request is rejected
    with `ERR_OWNERSHIP_REQUIRED`."

    Design: Corner/rbac/ownership_customer_registers_other_returns_403
    """
    room, session = new_open_session(capacity=5, seat_capacity=20,
                                     start_at="2026-07-14T18:00:00Z",
                                     end_at="2026-07-14T20:00:00Z")
    c1 = new_customer(email="o1@x.com", full_name="O One")
    c2 = new_customer(email="o2@x.com", full_name="O Two")
    actor = make_customer_headers(c1["id"])
    res = api.create_registration(session["id"],
                                  create_registration_payload(c2["id"]), actor)
    validate_error(res, "ERR_OWNERSHIP_REQUIRED")
