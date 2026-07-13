"""Composite setup helpers.

Each function drives the PRD-declared endpoints from an empty database (the
runner restarts the server before every test) to reach the state a test needs.
Setup steps use get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion later.

All ownership-gated instructor actions thread the real instructor id through
make_instructor_headers(); FrontDesk / Manager are opaque and use the shared
constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    abort_flight_payload,
    assign_instructor_payload,
    create_booking_payload,
    create_coaching_payload,
    create_flight_payload,
    create_instructor_payload,
    create_member_payload,
    create_membership_payload,
    create_package_payload,
    create_session_payload,
    create_tunnel_payload,
    create_waiver_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_instructor_headers

MANAGER = TEST_USERS["manager_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]


# --------------------------------------------------------------------------
# Granular single-entity helpers
# --------------------------------------------------------------------------
def make_tunnel(api, **overrides):
    return get_success_data(api.create_tunnel(create_tunnel_payload(**overrides), MANAGER))


def make_instructor(api, **overrides):
    return get_success_data(api.create_instructor(create_instructor_payload(**overrides), MANAGER))


def make_package(api, **overrides):
    return get_success_data(api.create_package(create_package_payload(**overrides), MANAGER))


def make_member(api, **overrides):
    return get_success_data(api.create_member(create_member_payload(**overrides), FRONTDESK))


def make_waiver(api, member_id, **overrides):
    return get_success_data(api.create_waiver(create_waiver_payload(member_id, **overrides), FRONTDESK))


def make_membership(api, member_id, tier):
    return get_success_data(
        api.create_membership(create_membership_payload(member_id, tier), FRONTDESK)
    )


def make_booking(api, member_id, package_id, **overrides):
    return get_success_data(
        api.create_booking(create_booking_payload(member_id, package_id, **overrides), FRONTDESK)
    )


def make_session(api, tunnel_id, **overrides):
    return get_success_data(api.create_session(create_session_payload(tunnel_id, **overrides), FRONTDESK))


def assign_session_instructor(api, session_id, instructor_id, expected_version):
    return get_success_data(
        api.assign_instructor(
            session_id,
            assign_instructor_payload(instructor_id, expected_version),
            FRONTDESK,
        )
    )


def make_flight(api, booking_id, session_id, member_id, scheduled_minutes=2):
    return get_success_data(
        api.create_flight(
            create_flight_payload(booking_id, session_id, member_id, scheduled_minutes),
            FRONTDESK,
        )
    )


def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock(set_clock_payload(to_iso8601), FRONTDESK))


# --------------------------------------------------------------------------
# Tier: staffed session (assigned instructor; op_status OPEN)
# --------------------------------------------------------------------------
def setup_staffed_session(api, *, tunnel_kw=None, session_kw=None):
    """Tunnel + instructor + session with an instructor assigned (STAFFED, OPEN)."""
    tunnel = make_tunnel(api, **(tunnel_kw or {}))
    instructor = make_instructor(api)
    session = make_session(api, tunnel["id"], **(session_kw or {}))
    session = assign_session_instructor(api, session["id"], instructor["id"], session["version"])
    return {"tunnel": tunnel, "instructor": instructor, "session": session}


def setup_running_session(api, *, tunnel_kw=None, session_kw=None):
    """Staffed session advanced to RUNNING (op_status RUNNING, STAFFED)."""
    ctx = setup_staffed_session(api, tunnel_kw=tunnel_kw, session_kw=session_kw)
    ctx["session"] = get_success_data(api.start_session(ctx["session"]["id"], FRONTDESK))
    return ctx


# --------------------------------------------------------------------------
# Tier: full chain to a SCHEDULED flight
# --------------------------------------------------------------------------
def setup_scheduled_flight(
    api,
    *,
    tunnel_kw=None,
    member_kw=None,
    package_kw=None,
    booking_kw=None,
    session_kw=None,
    scheduled_minutes=2,
    sign_waiver=True,
    start=True,
):
    """Full chain: tunnel + instructor + package + member (+waiver) + booking +
    staffed session (+start) + one SCHEDULED flight.

    Returns a dict with keys: tunnel, instructor, package, member, waiver
    (or None), booking, session, flight.
    """
    tunnel = make_tunnel(api, **(tunnel_kw or {}))
    instructor = make_instructor(api)
    package = make_package(api, **(package_kw or {}))
    member = make_member(api, **(member_kw or {}))
    waiver = None
    if sign_waiver:
        waiver = make_waiver(api, member["id"], weight_kg_declared=member["weight_kg"])
    booking = make_booking(api, member["id"], package["id"], **(booking_kw or {}))
    session = make_session(api, tunnel["id"], **(session_kw or {}))
    session = assign_session_instructor(api, session["id"], instructor["id"], session["version"])
    if start:
        session = get_success_data(api.start_session(session["id"], FRONTDESK))
    flight = make_flight(api, booking["id"], session["id"], member["id"], scheduled_minutes)
    return {
        "tunnel": tunnel,
        "instructor": instructor,
        "package": package,
        "member": member,
        "waiver": waiver,
        "booking": booking,
        "session": session,
        "flight": flight,
    }


def setup_checked_in_flight(api, **kwargs):
    """As setup_scheduled_flight, then check the flight in (CHECKED_IN)."""
    ctx = setup_scheduled_flight(api, **kwargs)
    ctx["flight"] = get_success_data(api.check_in_flight(ctx["flight"]["id"], FRONTDESK))
    return ctx


def setup_aborted_flight(api, *, flown_minutes=1, **kwargs):
    """As setup_checked_in_flight, then abort with flown_minutes (ABORTED).

    Requires a RUNNING session (abort precondition), so `start` defaults True.
    """
    kwargs.setdefault("start", True)
    ctx = setup_checked_in_flight(api, **kwargs)
    instr_headers = make_instructor_headers(ctx["instructor"]["id"])
    ctx["flight"] = get_success_data(
        api.abort_flight(ctx["flight"]["id"], abort_flight_payload(flown_minutes), instr_headers)
    )
    return ctx


def setup_exhausted_booking_checked_in(api, *, tunnel_kw=None, member_kw=None):
    """Party-1 booking whose 2-minute pool is fully consumed by one flight, so the
    booking is EXHAUSTED and the member's confirmed_booking_count is 0; the flight
    is CHECKED_IN in a RUNNING session. Used for the abort depth-3 cascade.
    """
    return setup_checked_in_flight(
        api,
        tunnel_kw=tunnel_kw,
        member_kw=member_kw,
        package_kw={"included_minutes": 2},
        booking_kw={"party_size": 1},
        scheduled_minutes=2,
        sign_waiver=True,
        start=True,
    )


# --------------------------------------------------------------------------
# Tier: add-on statement scenario (member with a discount + one scheduled flight)
# --------------------------------------------------------------------------
def setup_member_with_scheduled_flight_and_membership(api, *, tier):
    """A member enrolled in `tier`, with one SCHEDULED flight on a staffed session
    (not started). Returns the setup dict plus 'membership'.
    """
    ctx = setup_scheduled_flight(
        api,
        booking_kw={"party_size": 1},
        scheduled_minutes=2,
        sign_waiver=False,
        start=False,
    )
    # enrol AFTER member creation but BEFORE add-ons so the discount applies.
    ctx["membership"] = make_membership(api, ctx["member"]["id"], tier)
    return ctx


def add_coaching(api, flight_id, instructor_id, minutes):
    return get_success_data(
        api.create_coaching(create_coaching_payload(flight_id, instructor_id, minutes), FRONTDESK)
    )
