"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server against an empty database before each test).
Setup calls use get_success_data() so a setup failure surfaces clearly.

Nearly all setup runs as PlatformAdmin (opaque, override authority, exempt from
tenant isolation) and guests act as Guest (opaque); neither identity is compared
to any entity id, so the shared TEST_USERS constants are the correct headers here.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_funeral_home_payload,
    create_venue_payload,
    create_operator_payload,
    create_service_order_payload,
    create_venue_booking_payload,
    create_camera_assignment_payload,
    create_guestbook_entry_payload,
    create_donation_payload,
    create_tribute_video_payload,
)

ADMIN = TEST_USERS["admin_headers"]
GUEST = TEST_USERS["guest_headers"]


# --- Logical clock -----------------------------------------------------------
def set_clock(iso_instant: str):
    """Set the server logical clock (PRD §2.11)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso_instant}, ADMIN))


# --- Primitive builders ------------------------------------------------------
def create_home(*, initial_credits: int = 0, **overrides) -> dict:
    payload = create_funeral_home_payload(initial_credits=initial_credits, **overrides)
    return get_success_data(api_client.create_funeral_home(payload, ADMIN))


def grant_credits(home_id: str, credit_amount: int) -> dict:
    return get_success_data(
        api_client.grant_credits(home_id, {"credit_amount": credit_amount}, ADMIN)
    )


def create_venue(home_id: str, *, turnaround_minutes: int = 0, **overrides) -> dict:
    payload = create_venue_payload(home_id, turnaround_minutes=turnaround_minutes, **overrides)
    return get_success_data(api_client.create_venue(payload, ADMIN))


def create_operator(home_id: str, *, skill: str = "CAMERA", **overrides) -> dict:
    payload = create_operator_payload(home_id, skill=skill, **overrides)
    return get_success_data(api_client.create_operator(payload, ADMIN))


def set_operator_duty(operator_id: str, duty_status: str) -> dict:
    return get_success_data(
        api_client.set_duty(operator_id, {"duty_status": duty_status}, ADMIN)
    )


def create_order(home_id: str, venue_id: str, **overrides) -> dict:
    payload = create_service_order_payload(home_id, venue_id, **overrides)
    return get_success_data(api_client.create_service_order(payload, ADMIN))


def create_booking(order_id: str, venue_id: str, window_start: str, window_end: str,
                   expected_order_version: int) -> dict:
    payload = create_venue_booking_payload(
        order_id, venue_id, window_start, window_end, expected_order_version
    )
    return get_success_data(api_client.create_venue_booking(payload, ADMIN))


def confirm_booking(booking_id: str) -> dict:
    return get_success_data(api_client.confirm_venue_booking(booking_id, ADMIN))


def create_assignment(order_id: str, operator_id: str, role: str = "CAMERA") -> dict:
    payload = create_camera_assignment_payload(order_id, operator_id, role)
    return get_success_data(api_client.create_camera_assignment(payload, ADMIN))


def transition_order(order_id: str, action: str, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.transition_service_order(order_id, payload, ADMIN))


def transition_donation(donation_id: str, action: str) -> dict:
    return get_success_data(
        api_client.transition_donation(donation_id, {"action": action}, ADMIN)
    )


def transition_tribute(tribute_id: str, action: str) -> dict:
    return get_success_data(
        api_client.transition_tribute_video(tribute_id, {"action": action}, ADMIN)
    )


def create_donation(order_id: str, gross_amount_cents: int, donor_name: str = "Donor") -> dict:
    payload = create_donation_payload(
        order_id, gross_amount_cents=gross_amount_cents, donor_name=donor_name
    )
    return get_success_data(api_client.create_donation(payload, GUEST))


def create_guestbook_entry(order_id: str, **overrides) -> dict:
    payload = create_guestbook_entry_payload(order_id, **overrides)
    return get_success_data(api_client.create_guestbook_entry(payload, GUEST))


def create_tribute(order_id: str, **overrides) -> dict:
    payload = create_tribute_video_payload(order_id, **overrides)
    return get_success_data(api_client.create_tribute_video(payload, ADMIN))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_service_order(order_id, ADMIN))


def get_home(home_id: str) -> dict:
    return get_success_data(api_client.get_funeral_home(home_id, ADMIN))


def get_donation(donation_id: str) -> dict:
    return get_success_data(api_client.get_donation(donation_id, ADMIN))


def get_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_venue_booking(booking_id, ADMIN))


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_camera_assignment(assignment_id, ADMIN))


def get_tribute(tribute_id: str) -> dict:
    return get_success_data(api_client.get_tribute_video(tribute_id, ADMIN))


# --- Tier 1/2: home + venue + order -----------------------------------------
def setup_home_and_venue(*, initial_credits: int = 0, turnaround_minutes: int = 0) -> dict:
    """A funeral home and one venue. Returns {'home', 'venue'}."""
    home = create_home(initial_credits=initial_credits)
    venue = create_venue(home["id"], turnaround_minutes=turnaround_minutes)
    return {"home": home, "venue": venue}


def setup_draft_order(*, initial_credits: int = 0, turnaround_minutes: int = 0,
                      **order_overrides) -> dict:
    """A home, venue, and a fresh DRAFT service order. Returns {'home','venue','order'}."""
    base = setup_home_and_venue(initial_credits=initial_credits,
                                turnaround_minutes=turnaround_minutes)
    order = create_order(base["home"]["id"], base["venue"]["id"], **order_overrides)
    base["order"] = order
    return base


# --- Tier 3: schedulable / scheduled order shortcuts -------------------------
def setup_booking_confirmed_order(*, initial_credits: int = 1, **order_overrides) -> dict:
    """Home + venue + order with a CONFIRMED booking and stream READY, still DRAFT.
    The booking window matches the order's scheduled window. Returns
    {'home','venue','order','booking'} with order re-fetched (current version)."""
    base = setup_draft_order(initial_credits=initial_credits, **order_overrides)
    order = base["order"]
    booking = create_booking(
        order["id"], base["venue"]["id"],
        order["scheduled_start"], order["scheduled_end"], order["version"],
    )
    confirm_booking(booking["id"])
    transition_order(order["id"], "SET_STREAM_READY")
    base["booking"] = booking
    base["order"] = get_order(order["id"])
    return base


def setup_scheduled_order(*, initial_credits: int = 1, **order_overrides) -> dict:
    """Home + venue + order taken all the way to broadcast_status SCHEDULED
    (booking CONFIRMED, stream READY, one credit consumed).
    Returns {'home','venue','order','booking'} with order in SCHEDULED state."""
    base = setup_booking_confirmed_order(initial_credits=initial_credits, **order_overrides)
    base["order"] = transition_order(base["order"]["id"], "SCHEDULE")
    return base


def run_broadcast(order_id: str, go_live_at: str, end_at: str) -> dict:
    """From SCHEDULED: set clock, GO_LIVE, set clock, END. Returns the ENDED order."""
    set_clock(go_live_at)
    transition_order(order_id, "GO_LIVE")
    set_clock(end_at)
    return transition_order(order_id, "END")


def setup_ended_order(*, initial_credits: int = 1, go_live_at: str, end_at: str,
                      **order_overrides) -> dict:
    """A schedulable order run through GO_LIVE and END for a given actual window.
    Returns {'home','venue','order','booking'} with order ENDED / recording RAW."""
    base = setup_scheduled_order(initial_credits=initial_credits, **order_overrides)
    base["order"] = run_broadcast(base["order"]["id"], go_live_at, end_at)
    return base


def setup_invoiced_order(*, initial_credits: int = 1, go_live_at: str, end_at: str,
                         **order_overrides) -> dict:
    """A schedulable order run through END then INVOICE (final_invoice_cents set).
    Returns {'home','venue','order','booking'} with settlement INVOICED."""
    base = setup_ended_order(initial_credits=initial_credits,
                             go_live_at=go_live_at, end_at=end_at, **order_overrides)
    base["order"] = transition_order(base["order"]["id"], "INVOICE")
    return base


# --- Tier 4: memorial / donation state ---------------------------------------
def setup_published_memorial_order(**order_overrides) -> dict:
    """Home + venue + order with memorial_status PUBLISHED (guest actions enabled).
    Returns {'home','venue','order'}."""
    base = setup_draft_order(**order_overrides)
    transition_order(base["order"]["id"], "PUBLISH_MEMORIAL")
    base["order"] = get_order(base["order"]["id"])
    return base


def setup_pledged_donation(gross_amount_cents: int = 1000) -> dict:
    """Published-memorial order with one PLEDGED donation.
    Returns {'home','venue','order','donation'}."""
    base = setup_published_memorial_order()
    donation = create_donation(base["order"]["id"], gross_amount_cents)
    base["donation"] = donation
    return base


def setup_settled_donation(gross_amount_cents: int = 1000) -> dict:
    """Published-memorial order with one SETTLED donation.
    Returns {'home','venue','order','donation'}."""
    base = setup_pledged_donation(gross_amount_cents)
    base["donation"] = transition_donation(base["donation"]["id"], "SETTLE")
    return base
