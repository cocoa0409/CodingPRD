"""Composite setup helpers.

Each fixture builds its preconditions from scratch using only PRD-declared endpoints,
because the server restarts (empty DB) before every test. Setup calls use the lenient
get_success_data() so a setup failure surfaces clearly rather than as a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from . import factories as f
from .constants import PLAN_PLUS, PLAN_BASIC, PLAN_ELITE

STAFF = TEST_USERS["staff_headers"]

# Default clock pins used across fixtures.
DEFAULT_CLOCK = "2026-06-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the server clock without running any sweep."""
    return get_success_data(api_client.set_clock(f.set_clock_payload(iso), STAFF))


def run_sweep():
    """Run the time-driven delinquency / contract / guest-pass-expiry sweep at current clock."""
    return get_success_data(api_client.advance_dues(STAFF))


def create_plan(plan_shape=None, **overrides):
    """Create a membership plan. plan_shape defaults to the PLUS profile."""
    payload = dict(plan_shape or PLAN_PLUS)
    payload.update(overrides)
    return get_success_data(api_client.create_membership_plan(payload, STAFF))


def create_location(**overrides):
    return get_success_data(api_client.create_location(f.create_location_payload(**overrides), STAFF))


# ---------------------------------------------------------------------------
# Tier 1: registration & lifecycle state progression
# ---------------------------------------------------------------------------
def register_member(plan_id, location_id, clock=DEFAULT_CLOCK, **overrides):
    """Register a PENDING member with an OPEN joining invoice; pins the clock first.

    Returns (member, joining_invoice).
    """
    if clock is not None:
        set_clock(clock)
    payload = f.create_member_payload(plan_id, location_id, **overrides)
    member = get_success_data(api_client.create_member(payload, STAFF))
    invoices = get_success_data(api_client.list_dues_invoices(STAFF, params={"member_id": member["id"]}))
    joining_invoice = invoices[0]
    return member, joining_invoice


def pay_invoice(invoice_id, headers=STAFF):
    return get_success_data(api_client.pay_dues_invoice(invoice_id, headers))


def activate_member(member_id, headers=STAFF):
    return get_success_data(api_client.activate_member(member_id, headers))


def setup_active_member(plan_shape=None, clock=DEFAULT_CLOCK, location=None, plan=None, **member_overrides):
    """Full path to an ACTIVE member: plan + location + register + pay joining invoice + activate.

    Returns dict with keys: plan, location, member (refreshed ACTIVE), joining_invoice.
    """
    plan = plan or create_plan(plan_shape)
    location = location or create_location()
    member, joining_invoice = register_member(plan["id"], location["id"], clock=clock, **member_overrides)
    pay_invoice(joining_invoice["id"])
    member = activate_member(member["id"])
    return {
        "plan": plan,
        "location": location,
        "member": member,
        "joining_invoice": joining_invoice,
    }


def get_member(member_id, headers=STAFF):
    return get_success_data(api_client.get_member(member_id, headers))


# ---------------------------------------------------------------------------
# Tier 2: dues-axis progression (PAST_DUE / DELINQUENT / SUSPENDED)
# ---------------------------------------------------------------------------
def post_invoice(member_id, **overrides):
    """Post a recurring dues invoice for a member. Returns the OPEN invoice."""
    payload = f.create_dues_invoice_payload(member_id, **overrides)
    return get_success_data(api_client.create_dues_invoice(payload, STAFF))


def setup_suspended_member(plan_shape=None, **member_overrides):
    """ACTIVE member driven to dues_status SUSPENDED via an unpaid second invoice + 30-day sweep.

    Timeline: register 2026-06-10, activate; post a second invoice due 2026-07-01; set clock to
    2026-08-01 (>= 30 whole days past due) and sweep. Returns dict {plan, location, member, overdue_invoice}.
    """
    setup = setup_active_member(plan_shape=plan_shape, **member_overrides)
    overdue = post_invoice(
        setup["member"]["id"],
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
        due_date="2026-07-01T00:00:00Z",
    )
    set_clock("2026-08-01T00:00:00Z")
    run_sweep()
    setup["member"] = get_member(setup["member"]["id"])
    setup["overdue_invoice"] = overdue
    return setup


def setup_past_due_member(plan_shape=None, due_date="2026-06-20T00:00:00Z",
                          sweep_clock="2026-06-21T00:00:00Z", **member_overrides):
    """ACTIVE member with one overdue invoice, swept once to PAST_DUE.

    Returns dict {plan, location, member, overdue_invoice}.
    """
    setup = setup_active_member(plan_shape=plan_shape, **member_overrides)
    overdue = post_invoice(
        setup["member"]["id"],
        period_start=due_date,
        period_end="2026-07-20T00:00:00Z",
        due_date=due_date,
    )
    set_clock(sweep_clock)
    run_sweep()
    setup["member"] = get_member(setup["member"]["id"])
    setup["overdue_invoice"] = overdue
    return setup


# ---------------------------------------------------------------------------
# Tier 3: class sessions & bookings
# ---------------------------------------------------------------------------
def create_session(location_id, **overrides):
    """Create a SCHEDULED class session. Returns the session (carries version)."""
    payload = f.create_class_session_payload(location_id, **overrides)
    return get_success_data(api_client.create_class_session(payload, STAFF))


def get_session(session_id, headers=STAFF):
    return get_success_data(api_client.get_class_session(session_id, headers))


def book(session_id, member_id, expected_version, headers=STAFF):
    """Create a booking against a session. Returns the booking (BOOKED or WAITLISTED)."""
    payload = f.create_booking_payload(session_id, member_id, expected_version)
    return get_success_data(api_client.create_booking(payload, headers))


def setup_seat_and_waitlist(plan_shape=None, capacity=1, waitlist_cap=1,
                            starts_at="2026-06-20T09:00:00Z", ends_at="2026-06-20T10:00:00Z"):
    """Two ACTIVE members on one session: m_a BOOKED, m_b WAITLISTED.

    Returns dict: plan, location, session (after both bookings, re-fetched),
    member_a, member_b, booking_a, booking_b.
    """
    plan = create_plan(plan_shape)
    location = create_location()
    setup_a = setup_active_member(plan=plan, location=location)
    setup_b = setup_active_member(plan=plan, location=location)
    member_a, member_b = setup_a["member"], setup_b["member"]

    session = create_session(location["id"], capacity=capacity, waitlist_cap=waitlist_cap,
                             starts_at=starts_at, ends_at=ends_at)
    booking_a = book(session["id"], member_a["id"], session["version"])
    session = get_session(session["id"])
    booking_b = book(session["id"], member_b["id"], session["version"])
    session = get_session(session["id"])
    return {
        "plan": plan,
        "location": location,
        "session": session,
        "member_a": member_a,
        "member_b": member_b,
        "booking_a": booking_a,
        "booking_b": booking_b,
    }


# ---------------------------------------------------------------------------
# Tier 4: PT packages & sessions
# ---------------------------------------------------------------------------
def create_pt_package(member_id, headers=STAFF, **overrides):
    """Purchase a PT package. Returns the package (carries version)."""
    payload = f.create_pt_package_payload(member_id, **overrides)
    return get_success_data(api_client.create_pt_package(payload, headers))


def get_pt_package(package_id, headers=STAFF):
    return get_success_data(api_client.get_pt_package(package_id, headers))


def schedule_pt_session(package_id, expected_version, headers=STAFF, **overrides):
    """Schedule a PT session against a package. Returns the session."""
    payload = f.create_pt_session_payload(package_id, expected_version, **overrides)
    return get_success_data(api_client.create_pt_session(payload, headers))


def setup_pt_package_with_session(plan_shape=None, sessions_purchased=5, list_price_cents=50000,
                                  pt_clock="2026-06-12T00:00:00Z",
                                  pt_starts_at="2026-06-25T15:00:00Z"):
    """ACTIVE member buys a package and schedules one PT session.

    Returns dict: plan, location, member, package (re-fetched), pt_session, package_version
    (the package version AFTER the schedule, suitable for a subsequent cancel/schedule).
    """
    setup = setup_active_member(plan_shape=plan_shape or PLAN_ELITE, clock=pt_clock,
                                period_start=pt_clock, period_end="2026-07-01T00:00:00Z",
                                due_date=pt_clock)
    package = create_pt_package(setup["member"]["id"],
                                sessions_purchased=sessions_purchased,
                                list_price_cents=list_price_cents)
    pt_session = schedule_pt_session(package["id"], package["version"], starts_at=pt_starts_at)
    package = get_pt_package(package["id"])
    return {
        "plan": setup["plan"],
        "location": setup["location"],
        "member": setup["member"],
        "package": package,
        "pt_session": pt_session,
        "package_version": package["version"],
    }


# ---------------------------------------------------------------------------
# Tier 5: guest passes & check-ins
# ---------------------------------------------------------------------------
def issue_guest_pass(member_id, location_id, headers=STAFF, **overrides):
    payload = f.create_guest_pass_payload(member_id, location_id, **overrides)
    return get_success_data(api_client.create_guest_pass(payload, headers))


def check_in_member(member_id, location_id, headers=STAFF):
    payload = f.create_member_check_in_payload(member_id, location_id)
    return get_success_data(api_client.create_check_in(payload, headers))


def get_location(location_id, headers=STAFF):
    return get_success_data(api_client.get_location(location_id, headers))
