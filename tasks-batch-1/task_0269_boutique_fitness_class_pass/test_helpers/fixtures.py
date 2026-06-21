"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

Identity threading: Member is entity_backed:Member. Every ownership-gated call
(reserve, cancel reservation, freeze/unfreeze/cancel membership, purchase) uses
make_member_headers(member["id"]) with the real Member.id. NetworkAdmin and
StudioManager are opaque and use the shared constants.

The reservation endpoint is OCC-guarded on the session version; every booking
bumps ClassSession.version. Helpers therefore re-read the live session version
(GET /sessions/{id}) immediately before each reservation so the correct
expected_session_version is supplied.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_studio_payload,
    create_room_payload,
    create_instructor_payload,
    create_class_template_payload,
    create_package_plan_payload,
    create_member_payload,
    create_membership_payload,
    create_session_payload,
    create_reservation_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["network_admin_headers"]
MANAGER = TEST_USERS["studio_manager_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Clock control
# ─────────────────────────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set the server's logical UTC clock."""
    get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADMIN))


# ─────────────────────────────────────────────────────────────────────────
# Tier 1: atomic configuration builders
# ─────────────────────────────────────────────────────────────────────────
def create_studio(name="Downtown", state_code="CA", **overrides):
    return get_success_data(
        api_client.create_studio(create_studio_payload(name=name, state_code=state_code, **overrides), ADMIN)
    )


def create_room(studio_id, name="Room A", physical_capacity=10, **overrides):
    return get_success_data(
        api_client.create_room(
            studio_id, create_room_payload(name=name, physical_capacity=physical_capacity, **overrides), ADMIN
        )
    )


def create_instructor(studio_id, full_name="Ina", **overrides):
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(studio_id, full_name=full_name, **overrides), ADMIN)
    )


def create_template(name="Flow", duration_min=60, credit_cost=5, late_cancel_window_hours=12, **overrides):
    return get_success_data(
        api_client.create_class_template(
            create_class_template_payload(
                name=name, duration_min=duration_min, credit_cost=credit_cost,
                late_cancel_window_hours=late_cancel_window_hours, **overrides,
            ),
            ADMIN,
        )
    )


def create_plan(kind="CREDIT_PACK", **overrides):
    return get_success_data(
        api_client.create_package_plan(create_package_plan_payload(kind=kind, **overrides), ADMIN)
    )


def create_member(studio_id, email="m1@x.com", full_name="M One", **overrides):
    return get_success_data(
        api_client.create_member(create_member_payload(studio_id, email=email, full_name=full_name, **overrides), ADMIN)
    )


def create_active_membership(member_id, plan_id):
    """Purchase a plan then capture payment so the membership is ACTIVE with its
    grant credited. Returns the captured (ACTIVE) membership."""
    membership = get_success_data(
        api_client.create_membership(member_id, create_membership_payload(plan_id), make_member_headers(member_id))
    )
    captured = get_success_data(
        api_client.capture_payment({"membership_id": membership["id"], "outcome": "CAPTURED"}, ADMIN)
    )
    return captured


def create_pending_membership(member_id, plan_id):
    """Purchase a plan but DO NOT capture payment. Returns PENDING_PAYMENT membership."""
    return get_success_data(
        api_client.create_membership(member_id, create_membership_payload(plan_id), make_member_headers(member_id))
    )


# ─────────────────────────────────────────────────────────────────────────
# Tier 2: network scaffolding
# ─────────────────────────────────────────────────────────────────────────
def setup_network(clock=None, template_overrides=None, plan_kind="CREDIT_PACK", plan_overrides=None):
    """Studio + one room + one instructor + one template + one package plan.

    Returns a dict with keys: studio, room, instructor, template, plan.
    """
    if clock is not None:
        set_clock(clock)
    studio = create_studio()
    room = create_room(studio["id"])
    instructor = create_instructor(studio["id"])
    template = create_template(**(template_overrides or {}))
    plan = create_plan(kind=plan_kind, **(plan_overrides or {}))
    return {
        "studio": studio,
        "room": room,
        "instructor": instructor,
        "template": template,
        "plan": plan,
    }


def setup_member_with_membership(studio_id, plan_id, email="m1@x.com", full_name="M One", active=True):
    """Register a member and give them either an ACTIVE or PENDING_PAYMENT membership.

    Returns (member, membership).
    """
    member = create_member(studio_id, email=email, full_name=full_name)
    if active:
        membership = create_active_membership(member["id"], plan_id)
    else:
        membership = create_pending_membership(member["id"], plan_id)
    return member, membership


# ─────────────────────────────────────────────────────────────────────────
# Tier 3: sessions and reservations
# ─────────────────────────────────────────────────────────────────────────
def create_published_session(studio_id, room_id, instructor_id, template_id,
                             starts_at="2026-06-20T10:00:00Z", seat_capacity=5,
                             waitlist_capacity=None):
    """Create a SCHEDULED session and publish it to OPEN. Returns the published session."""
    overrides = {"starts_at": starts_at, "seat_capacity": seat_capacity}
    if waitlist_capacity is not None:
        overrides["waitlist_capacity"] = waitlist_capacity
    session = get_success_data(
        api_client.create_session(
            create_session_payload(studio_id, room_id, instructor_id, template_id, **overrides), MANAGER
        )
    )
    return get_success_data(api_client.publish_session(session["id"], MANAGER))


def session_version(session_id):
    """Re-read the live session version (needed before each OCC-guarded reserve)."""
    return get_success_data(api_client.get_session(session_id, MANAGER))["version"]


def reserve(session_id, member_id, membership_id):
    """Reserve a seat with a freshly-read expected_session_version. Returns the reservation."""
    version = session_version(session_id)
    return get_success_data(
        api_client.create_reservation(
            session_id,
            create_reservation_payload(membership_id, version),
            make_member_headers(member_id),
        )
    )


def get_session(session_id):
    return get_success_data(api_client.get_session(session_id, MANAGER))


def get_membership(membership_id, member_id):
    return get_success_data(api_client.get_membership(membership_id, make_member_headers(member_id)))


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, ADMIN))


def get_reservation(reservation_id):
    return get_success_data(api_client.get_reservation(reservation_id, ADMIN))


# ─────────────────────────────────────────────────────────────────────────
# Tier 4: state / accumulation targeting
# ─────────────────────────────────────────────────────────────────────────
def drive_member_to_strikes(net, member, membership, num_strikes,
                            base_clock="2026-06-01T00:00:00Z", session_hour_start=6):
    """Drive a member to exactly `num_strikes` NO_SHOW strikes by booking them onto
    `num_strikes` single-seat sessions and running completion past each end.

    Each session is created in the shared room/instructor at a distinct hour so the
    room/instructor conflict checks pass (sessions are spaced > cleaning + travel
    buffers apart). After all bookings, the clock is advanced past the last end and
    a single run_completion marks all as NO_SHOW.

    Returns the list of reservation dicts created (in booking order).
    """
    set_clock(base_clock)
    day = base_clock.split("T")[0]
    reservations = []
    for i in range(num_strikes):
        hour = session_hour_start + i * 2
        starts = f"{day}T{hour:02d}:00:00Z"
        session = create_published_session(
            net["studio"]["id"], net["room"]["id"], net["instructor"]["id"],
            net["template"]["id"], starts_at=starts, seat_capacity=1,
        )
        res = reserve(session["id"], member["id"], membership["id"])
        reservations.append(res)
    # Advance past the last session end and complete them all -> NO_SHOWs.
    last_hour = session_hour_start + (num_strikes - 1) * 2 + 2
    set_clock(f"{day}T{last_hour:02d}:30:00Z")
    get_success_data(api_client.run_completion(ADMIN))
    return reservations


def setup_full_session_with_waitlist(net, booked_member, booked_membership,
                                     waitlisters, starts_at="2026-06-25T10:00:00Z",
                                     waitlist_capacity=5):
    """Single-seat session: `booked_member` takes the seat (-> FULL); each entry in
    `waitlisters` (list of (member, membership) tuples) is then WAITLISTED in order.

    Returns (session_id, booked_reservation, [waitlist_reservations...]).
    """
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"],
        net["template"]["id"], starts_at=starts_at, seat_capacity=1,
        waitlist_capacity=waitlist_capacity,
    )
    booked = reserve(session["id"], booked_member["id"], booked_membership["id"])
    waitlist = []
    for (m, sub) in waitlisters:
        waitlist.append(reserve(session["id"], m["id"], sub["id"]))
    return session["id"], booked, waitlist
