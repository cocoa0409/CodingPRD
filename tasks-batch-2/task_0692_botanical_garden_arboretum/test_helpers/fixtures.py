"""Composite setup helpers.

The harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Setup
calls use get_success_data() (lenient) so a setup error surfaces as a clear
"Setup failed" rather than a confusing assertion mismatch.

Identity threading: a Visitor (entity_backed:Membership) acting on an
ownership-gated resource must present X-User-ID == owning Membership.id. Every
fixture that activates/renews/cancels/reinstates a membership, or cancels a
reservation/withdraws a registration/cancels a rental on a member-owned
resource, uses make_visitor_headers(membership_id) for that call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_visitor_headers,
)
from .constants import CLOCK_DEFAULT_UTC

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
RENTAL = TEST_USERS["rental_coordinator_headers"]
DEV = TEST_USERS["development_officer_headers"]
VISITOR = TEST_USERS["visitor_headers"]


# =============================================================================
# Clock helpers
# =============================================================================
def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; returns the sweep report data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def reset_clock_to_default() -> dict:
    return set_clock(CLOCK_DEFAULT_UTC)


# =============================================================================
# Catalog primitives
# =============================================================================
def create_garden(**overrides) -> dict:
    payload = {"name": "Test Garden"}
    payload.update(overrides)
    return get_success_data(api_client.create_garden(payload, ADMIN))


def create_plan(garden_id, tier="INDIVIDUAL", annual_fee_cents=12000, **overrides) -> dict:
    payload = {"garden_id": garden_id, "tier": tier, "annual_fee_cents": annual_fee_cents}
    payload.update(overrides)
    return get_success_data(api_client.create_plan(payload, ADMIN))


def create_time_slot(garden_id, starts_at, ends_at, capacity=10, ga_price_cents=2000, **overrides) -> dict:
    payload = {
        "garden_id": garden_id, "starts_at": starts_at, "ends_at": ends_at,
        "capacity": capacity, "ga_price_cents": ga_price_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_time_slot(payload, STAFF))


def create_program_session(garden_id, title="Test Session", starts_at="2026-07-01T09:00:00Z",
                           capacity=5, tuition_cents=10000, **overrides) -> dict:
    payload = {
        "garden_id": garden_id, "title": title, "starts_at": starts_at,
        "capacity": capacity, "tuition_cents": tuition_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_program_session(payload, STAFF))


def create_venue(garden_id, name="Test Hall", hourly_rate_cents=20000, **overrides) -> dict:
    payload = {"garden_id": garden_id, "name": name, "hourly_rate_cents": hourly_rate_cents}
    payload.update(overrides)
    return get_success_data(api_client.create_venue(payload, RENTAL))


def create_conservancy_fund(garden_id, **overrides) -> dict:
    payload = {"garden_id": garden_id}
    payload.update(overrides)
    return get_success_data(api_client.create_conservancy_fund(payload, DEV))


# =============================================================================
# Membership lifecycle (Tier 1: state progression)
# =============================================================================
def create_pending_membership(garden_id, plan_id, primary_member_name="Test Member", **overrides) -> dict:
    """Create a PENDING membership. Visitor create is not ownership-gated."""
    payload = {"garden_id": garden_id, "plan_id": plan_id, "primary_member_name": primary_member_name}
    payload.update(overrides)
    return get_success_data(api_client.create_membership(payload, VISITOR))


def create_active_membership(garden_id, plan_id, primary_member_name="Test Member", **overrides) -> dict:
    """Create + activate a membership -> ACTIVE. Activation is ownership-gated,
    so it is performed with the membership's own id as X-User-ID."""
    membership = create_pending_membership(garden_id, plan_id, primary_member_name, **overrides)
    activated = get_success_data(
        api_client.activate_membership(membership["id"], make_visitor_headers(membership["id"]))
    )
    return activated


def setup_active_membership(tier="INDIVIDUAL", annual_fee_cents=12000, garden_overrides=None,
                            plan_overrides=None, membership_overrides=None):
    """Garden + plan(tier) + ACTIVE membership at the default clock.

    Returns (garden, plan, membership). The membership term_end is
    2027-04-01T00:00:00Z (activation at default clock + 365 days).
    """
    garden = create_garden(**(garden_overrides or {}))
    plan = create_plan(garden["id"], tier=tier, annual_fee_cents=annual_fee_cents,
                       **(plan_overrides or {}))
    membership = create_active_membership(garden["id"], plan["id"], **(membership_overrides or {}))
    return garden, plan, membership


def lapse_membership(membership_id) -> dict:
    """Force a membership to LAPSED via the administrative forced-lapse endpoint."""
    return get_success_data(api_client.lapse_membership(membership_id, STAFF))


# =============================================================================
# Reservations (Tier 2/3)
# =============================================================================
def create_nonmember_reservation(garden_id, time_slot_id, paid_heads=1, **overrides) -> dict:
    """A non-member (paid GA) reservation. Carries no membership/version."""
    payload = {"garden_id": garden_id, "time_slot_id": time_slot_id, "paid_heads": paid_heads}
    payload.update(overrides)
    return get_success_data(api_client.create_reservation(payload, VISITOR))


def create_member_reservation(garden_id, time_slot_id, membership_id, membership_version,
                              **head_split) -> dict:
    """A member reservation carrying expected_membership_version (OCC). Created
    by the Visitor whose X-User-ID == membership_id."""
    payload = {
        "garden_id": garden_id,
        "time_slot_id": time_slot_id,
        "membership_id": membership_id,
        "expected_membership_version": membership_version,
    }
    payload.update(head_split)
    return get_success_data(
        api_client.create_reservation(payload, make_visitor_headers(membership_id))
    )


def setup_household_member_with_slot(guest_pass_grant_household=4, slot_capacity=10,
                                     slot_starts="2026-04-20T10:00:00Z",
                                     slot_ends="2026-04-20T12:00:00Z"):
    """ACTIVE HOUSEHOLD membership (guest passes granted) + a time slot.

    Returns (garden, plan, membership, slot). The membership's current version
    (post-activation) is read back so callers can supply expected_membership_version.
    """
    garden = create_garden(guest_pass_grant_household=guest_pass_grant_household)
    plan = create_plan(garden["id"], tier="HOUSEHOLD", annual_fee_cents=9000, admission_included=True)
    membership = create_active_membership(garden["id"], plan["id"])
    slot = create_time_slot(garden["id"], slot_starts, slot_ends, capacity=slot_capacity)
    return garden, plan, membership, slot


# =============================================================================
# Program sessions + registrations (Tier 2)
# =============================================================================
def create_registration(garden_id, session_id, participant_name="Participant",
                        membership_id=None, headers=None) -> dict:
    """Create a registration (ENROLLED if room else WAITLISTED). For a member
    registration the create itself is not ownership-gated, but supply
    make_visitor_headers(membership_id) if you want owner identity."""
    payload = {"garden_id": garden_id, "program_session_id": session_id,
               "participant_name": participant_name}
    if membership_id:
        payload["membership_id"] = membership_id
    return get_success_data(api_client.create_registration(payload, headers or VISITOR))


def setup_session_with_enrolled_and_waitlist(capacity=1, tuition_cents=10000, num_waitlisted=1):
    """OPEN session at `capacity`; one ENROLLED non-member registration plus
    `num_waitlisted` WAITLISTED non-member registrations (ranks 1..N).

    Returns (garden, session, enrolled_reg, [waitlisted_regs...]).
    """
    garden = create_garden()
    session = create_program_session(garden["id"], capacity=capacity, tuition_cents=tuition_cents)
    enrolled = create_registration(garden["id"], session["id"], participant_name="Enrolled")
    waitlisted = []
    for i in range(num_waitlisted):
        reg = create_registration(garden["id"], session["id"], participant_name=f"Wait{i + 1}")
        waitlisted.append(reg)
    return garden, session, enrolled, waitlisted


# =============================================================================
# Venues + rentals (Tier 3)
# =============================================================================
def create_rental(garden_id, venue_id, starts_at, ends_at, membership_id=None, headers=None) -> dict:
    payload = {"garden_id": garden_id, "venue_id": venue_id,
               "starts_at": starts_at, "ends_at": ends_at}
    if membership_id:
        payload["membership_id"] = membership_id
    return get_success_data(api_client.create_rental(payload, headers or VISITOR))


def confirm_rental(rental_id) -> dict:
    return get_success_data(api_client.confirm_rental(rental_id, RENTAL))


def setup_confirmed_rental(buffer_minutes=60, hourly_rate_cents=20000,
                           starts_at="2026-05-01T10:00:00Z", ends_at="2026-05-01T13:30:00Z"):
    """Venue + one CONFIRMED rental occupying [starts_at, ends_at).

    Returns (garden, venue, confirmed_rental).
    """
    garden = create_garden()
    venue = create_venue(garden["id"], hourly_rate_cents=hourly_rate_cents, buffer_minutes=buffer_minutes)
    rental = create_rental(garden["id"], venue["id"], starts_at, ends_at)
    confirmed = confirm_rental(rental["id"])
    return garden, venue, confirmed


# =============================================================================
# Donations + conservancy fund (Tier 1/4)
# =============================================================================
def create_donation(garden_id, amount_cents=5000, designation=None, headers=None) -> dict:
    payload = {"garden_id": garden_id, "amount_cents": amount_cents}
    if designation:
        payload["designation"] = designation
    return get_success_data(api_client.create_donation(payload, headers or DEV))


def setup_open_fund(garden_id=None, match_ratio=0.5, match_cap_cents=10000):
    """Garden + an OPEN ConservancyFund with the given match params.

    Returns (garden, fund).
    """
    if garden_id is None:
        garden = create_garden()
        garden_id = garden["id"]
    else:
        garden = get_success_data(api_client.get_garden(garden_id, ADMIN))
    fund = create_conservancy_fund(garden_id, match_ratio=match_ratio, match_cap_cents=match_cap_cents)
    return garden, fund


# =============================================================================
# Event tickets
# =============================================================================
def create_event_ticket(garden_id, exhibit_name="Test Exhibit", list_price_cents=2000,
                        quantity=1, membership_id=None, headers=None) -> dict:
    payload = {"garden_id": garden_id, "exhibit_name": exhibit_name,
               "list_price_cents": list_price_cents, "quantity": quantity}
    if membership_id:
        payload["membership_id"] = membership_id
    return get_success_data(api_client.create_event_ticket(payload, headers or VISITOR))
