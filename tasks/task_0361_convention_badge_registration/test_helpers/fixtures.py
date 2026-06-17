"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: after creating an Attendee/Exhibitor, every ownership-gated
call uses make_attendee_headers(att_id) / make_exhibitor_headers(exh_id) with the
real entity id (PRD §2.1), never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_convention_payload,
    create_ticket_type_payload,
    create_attendee_payload,
    create_order_payload,
    line_item,
    create_session_payload,
    create_session_reservation_payload,
    create_waitlist_entry_payload,
    create_exhibitor_payload,
    create_booth_payload,
    create_booth_booking_payload,
)
from .test_users import (
    TEST_USERS,
    make_attendee_headers,
    make_exhibitor_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Primitive creators ──────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Pin the server clock (admin-only test-driving capability)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_convention(**overrides) -> dict:
    return get_success_data(api_client.create_convention(create_convention_payload(**overrides), ADMIN))


def create_ticket_type(convention_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_ticket_type(convention_id, create_ticket_type_payload(**overrides), ADMIN)
    )


def create_attendee(**overrides) -> dict:
    return get_success_data(api_client.create_attendee(create_attendee_payload(**overrides), ANON))


def create_exhibitor(convention_id, **overrides) -> dict:
    return get_success_data(api_client.create_exhibitor(create_exhibitor_payload(convention_id, **overrides), ANON))


def create_session(convention_id, **overrides) -> dict:
    return get_success_data(api_client.create_session(convention_id, create_session_payload(**overrides), ADMIN))


def create_booth(convention_id, **overrides) -> dict:
    return get_success_data(api_client.create_booth(convention_id, create_booth_payload(**overrides), ADMIN))


def convention_version(convention_id) -> int:
    conv = get_success_data(api_client.get_convention(convention_id, ADMIN))
    return conv["version"]


def session_version(session_id) -> int:
    sess = get_success_data(api_client.get_session(session_id, ADMIN))
    return sess["version"]


# ─── Tier 1/2: convention + ticket type + attendee setup ─────────────────────

def setup_convention_with_ticket_type(conv_overrides=None, tt_overrides=None):
    """Fresh OPEN convention + one ticket type. Returns (convention, ticket_type)."""
    conv = create_convention(**(conv_overrides or {}))
    tt = create_ticket_type(conv["id"], **(tt_overrides or {}))
    return conv, tt


# ─── Tier 3: order lifecycle shortcuts ───────────────────────────────────────

def create_draft_order(convention_id, attendee_id, lines):
    """Create a DRAFT order. `lines` is a list of (ticket_type_id, quantity) tuples."""
    headers = make_attendee_headers(attendee_id)
    payload = create_order_payload(
        convention_id, attendee_id,
        [line_item(tt_id, qty) for tt_id, qty in lines],
    )
    return get_success_data(api_client.create_order(payload, headers))


def create_submitted_order(convention_id, attendee_id, lines):
    """Create + submit an order, leaving it PENDING_PAYMENT. Returns the priced order."""
    order = create_draft_order(convention_id, attendee_id, lines)
    headers = make_attendee_headers(attendee_id)
    return get_success_data(api_client.submit_order(order["id"], headers))


def create_paid_order(convention_id, attendee_id, lines):
    """Create → submit → pay an order (carrying the current convention version).
    Returns the PAID order. Capacity must be sufficient for the pay to succeed."""
    order = create_submitted_order(convention_id, attendee_id, lines)
    headers = make_attendee_headers(attendee_id)
    conv_v = convention_version(convention_id)
    return get_success_data(
        api_client.pay_order(order["id"], {"expected_convention_version": conv_v}, headers)
    )


def badges_for_order(order_id, attendee_id) -> list:
    """List the badges issued against an order, owned by the purchaser."""
    headers = make_attendee_headers(attendee_id)
    data, _meta_or_data = _list(api_client.list_badges(headers, params={"order_id": order_id}))
    return data


def first_badge_for_order(order_id, attendee_id) -> dict:
    return badges_for_order(order_id, attendee_id)[0]


def setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z", conv_overrides=None,
                                tt_overrides=None, quantity=1):
    """Convention + ticket type + attendee + a PAID order of `quantity` GENERAL badges.

    Returns dict with: convention, ticket_type, attendee, order, badge (first badge),
    and badges (full list).
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides, tt_overrides)
    att = create_attendee()
    if clock:
        set_clock(clock)
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], quantity)])
    badges = badges_for_order(order["id"], att["id"])
    return {
        "convention": conv,
        "ticket_type": tt,
        "attendee": att,
        "order": order,
        "badge": badges[0],
        "badges": badges,
    }


# ─── Session reservation fixtures ────────────────────────────────────────────

def reserve_session(session_id, badge_id, attendee_id, **extra):
    """Create a session reservation for a badge, carrying the current session version."""
    headers = make_attendee_headers(attendee_id)
    sess_v = session_version(session_id)
    payload = create_session_reservation_payload(session_id, badge_id, sess_v, **extra)
    return get_success_data(api_client.create_session_reservation(payload, headers))


def setup_session_capacity1_confirmed_and_waitlisted(clock="2026-07-01T00:00:00Z",
                                                     session_overrides=None):
    """Capacity-1 session: badge A holds the CONFIRMED reservation, badge B is WAITLISTED.

    Two distinct attendees each pay for one GENERAL badge on the same convention.
    Returns dict: convention, ticket_type, session, attendee_a, attendee_b,
    badge_a, badge_b, reservation_a (CONFIRMED), reservation_b (WAITLISTED).
    """
    conv, tt = setup_convention_with_ticket_type()
    session = create_session(conv["id"], **(dict(seat_capacity=1, **(session_overrides or {}))))
    att_a = create_attendee()
    att_b = create_attendee()
    if clock:
        set_clock(clock)
    order_a = create_paid_order(conv["id"], att_a["id"], [(tt["id"], 1)])
    order_b = create_paid_order(conv["id"], att_b["id"], [(tt["id"], 1)])
    badge_a = first_badge_for_order(order_a["id"], att_a["id"])
    badge_b = first_badge_for_order(order_b["id"], att_b["id"])
    resv_a = reserve_session(session["id"], badge_a["id"], att_a["id"])  # CONFIRMED (seat free)
    resv_b = reserve_session(session["id"], badge_b["id"], att_b["id"])  # WAITLISTED (full)
    return {
        "convention": conv,
        "ticket_type": tt,
        "session": session,
        "attendee_a": att_a,
        "attendee_b": att_b,
        "order_a": order_a,
        "order_b": order_b,
        "badge_a": badge_a,
        "badge_b": badge_b,
        "reservation_a": resv_a,
        "reservation_b": resv_b,
    }


# ─── Waitlist / lottery fixtures ─────────────────────────────────────────────

def create_waitlist_entry(convention_id, attendee_id, **overrides):
    headers = make_attendee_headers(attendee_id)
    payload = create_waitlist_entry_payload(attendee_id, **overrides)
    return get_success_data(api_client.create_waitlist_entry(convention_id, payload, headers))


# ─── Booth / exhibitor fixtures ──────────────────────────────────────────────

def create_booth_booking(booth_id, exhibitor_id, **overrides):
    headers = make_exhibitor_headers(exhibitor_id)
    payload = create_booth_booking_payload(booth_id, exhibitor_id, **overrides)
    return get_success_data(api_client.create_booth_booking(payload, headers))


def check_in_booking(booking_id, exhibitor_id):
    headers = make_exhibitor_headers(exhibitor_id)
    return get_success_data(api_client.check_in_booth_booking(booking_id, headers))


def release_booking(booking_id, exhibitor_id):
    headers = make_exhibitor_headers(exhibitor_id)
    return get_success_data(api_client.release_booth_booking(booking_id, headers))


def get_exhibitor(exhibitor_id):
    headers = make_exhibitor_headers(exhibitor_id)
    return get_success_data(api_client.get_exhibitor(exhibitor_id, headers))


# ─── Internal helper ─────────────────────────────────────────────────────────

def _list(response):
    """Extract (data_list, meta) from a list response without strict envelope checks."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})
