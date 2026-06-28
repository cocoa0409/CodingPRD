"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for setup calls so a setup failure surfaces as a
clear "setup failed" error rather than a confusing assertion failure deeper in a test.

Identity threading: every ownership-gated call for an entity-backed Member/Technician uses
make_member_headers(member["id"]) / make_technician_headers(technician["id"]) with the real
entity id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_location_payload, create_service_type_payload, create_room_payload,
    create_technician_payload, create_shift_payload, create_membership_plan_payload,
    create_member_payload, create_waiver_payload, create_subscription_payload,
    create_credit_pack_payload, create_booking_payload, unique_email,
)
from .test_users import TEST_USERS, make_member_headers, make_technician_headers

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Primitive setup helpers ────────────────────────────────────────────────
def set_clock(iso: str):
    """Set the server logical clock to a UTC instant."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


def run_billing():
    """Advance recurring billing; returns the billing-run summary dict."""
    return get_success_data(api_client.run_billing(ADMIN))


def create_location(name="Austin Lounge", state_code="TX", **overrides):
    return get_success_data(api_client.create_location(
        create_location_payload(name=name, state_code=state_code, **overrides), ADMIN))


def create_service_type(**overrides):
    return get_success_data(api_client.create_service_type(
        create_service_type_payload(**overrides), ADMIN))


def create_room(location_id, service_type_id, name="Room 1"):
    return get_success_data(api_client.create_room(
        location_id, create_room_payload(service_type_id, name=name), MANAGER))


def create_technician(location_id, full_name="Tech One"):
    return get_success_data(api_client.create_technician(
        location_id, create_technician_payload(full_name=full_name), MANAGER))


def create_shift(technician_id, location_id, starts_at, ends_at):
    return get_success_data(api_client.create_shift(
        technician_id, create_shift_payload(location_id, starts_at, ends_at), MANAGER))


def create_plan(**overrides):
    return get_success_data(api_client.create_membership_plan(
        create_membership_plan_payload(**overrides), ADMIN))


def create_member(home_location_id, email=None, state_code="TX", **overrides):
    payload = create_member_payload(home_location_id, state_code=state_code, **overrides)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_member(payload, MANAGER))


def sign_waiver(member_id, has_contraindication=False, screening_answers=None):
    payload = create_waiver_payload(has_contraindication=has_contraindication)
    if screening_answers is not None:
        payload["screening_answers"] = screening_answers
    return get_success_data(api_client.create_waiver(
        member_id, payload, make_member_headers(member_id)))


def subscribe(member_id, plan_id):
    return get_success_data(api_client.create_subscription(
        member_id, create_subscription_payload(plan_id), make_member_headers(member_id)))


def buy_pack(member_id, total_credits, is_intro=False):
    return get_success_data(api_client.create_credit_pack(
        member_id, create_credit_pack_payload(total_credits, is_intro),
        make_member_headers(member_id)))


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, MANAGER))


def get_room(room_id):
    return get_success_data(api_client.get_room(room_id, MANAGER))


def get_subscription(subscription_id):
    return get_success_data(api_client.get_subscription(subscription_id, MANAGER))


def get_credit_pack(pack_id):
    return get_success_data(api_client.get_credit_pack(pack_id, MANAGER))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, MANAGER))


def get_location(location_id):
    return get_success_data(api_client.get_location(location_id, MANAGER))


def list_invoices(subscription_id):
    """Return the list payload of invoices for a subscription (ascending by created_at)."""
    res = api_client.list_invoices(MANAGER, params={"subscription_id": subscription_id, "limit": 100})
    body = res.json()
    return body["data"]


def book(member_id, location_id, room_id, starts_at, expected_room_version):
    """Create a booking and return its data (lenient — for setup use)."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(member_id, location_id, room_id, starts_at, expected_room_version),
        make_member_headers(member_id)))


# ─── Tier 2/3: Bookable scenario builder ────────────────────────────────────
class BookableScenario:
    """Bundle of the entities needed to exercise the booking workflow.

    Attributes: plan, service, location, room, technician, shift, member, subscription,
    waiver. `room_version` tracks the room's current version (advances on each booking).
    """

    def __init__(self):
        self.plan = None
        self.service = None
        self.location = None
        self.room = None
        self.technician = None
        self.shift = None
        self.member = None
        self.subscription = None
        self.waiver = None

    @property
    def member_headers(self):
        return make_member_headers(self.member["id"])

    @property
    def technician_headers(self):
        return make_technician_headers(self.technician["id"])

    @property
    def room_version(self):
        """Fresh room version, re-read from the server (advances after each booking)."""
        return get_room(self.room["id"])["version"]


def setup_bookable_scenario(
    *,
    service_overrides=None,
    plan_overrides=None,
    clock="2026-06-15T09:00:00Z",
    shift_starts_at="2026-06-15T08:00:00Z",
    shift_ends_at="2026-06-15T18:00:00Z",
    with_shift=True,
    with_waiver=True,
    waiver_has_contraindication=False,
    with_subscription=True,
    member_state_code="TX",
) -> BookableScenario:
    """Build a complete bookable scenario.

    Order: plan -> service -> location -> room -> technician -> (shift) -> clock ->
    member -> (waiver) -> (subscription). Set with_shift/with_waiver/with_subscription
    to False to deliberately omit a precondition for negative tests.
    """
    s = BookableScenario()
    plan_overrides = plan_overrides or {}
    service_overrides = service_overrides or {}

    s.plan = create_plan(**plan_overrides)
    s.service = create_service_type(**service_overrides)
    s.location = create_location()
    s.room = create_room(s.location["id"], s.service["id"], name="Room 1")
    s.technician = create_technician(s.location["id"], full_name="Tech One")
    if with_shift:
        s.shift = create_shift(s.technician["id"], s.location["id"], shift_starts_at, shift_ends_at)
    set_clock(clock)
    s.member = create_member(s.location["id"], state_code=member_state_code)
    if with_waiver:
        s.waiver = sign_waiver(s.member["id"], has_contraindication=waiver_has_contraindication)
    if with_subscription:
        s.subscription = subscribe(s.member["id"], s.plan["id"])
    return s


def setup_booked_session(
    *,
    starts_at="2026-06-15T10:00:00Z",
    service_overrides=None,
    plan_overrides=None,
    clock="2026-06-15T09:00:00Z",
    shift_starts_at="2026-06-15T08:00:00Z",
    shift_ends_at="2026-06-15T18:00:00Z",
):
    """Build a bookable scenario AND create one BOOKED booking on it.

    Returns (scenario, booking).
    """
    s = setup_bookable_scenario(
        service_overrides=service_overrides,
        plan_overrides=plan_overrides,
        clock=clock,
        shift_starts_at=shift_starts_at,
        shift_ends_at=shift_ends_at,
    )
    booking = book(s.member["id"], s.location["id"], s.room["id"], starts_at, s.room_version)
    return s, booking


# ─── Subscription-only scenario (no booking machinery needed) ────────────────
def setup_subscribed_member(*, plan_overrides=None, clock="2026-06-01T00:00:00Z"):
    """Create a location, set the clock, create a member, subscribe them.

    Returns (member, subscription, plan).
    """
    plan_overrides = plan_overrides or {}
    plan = create_plan(**plan_overrides)
    location = create_location()
    set_clock(clock)
    member = create_member(location["id"])
    subscription = subscribe(member["id"], plan["id"])
    return member, subscription, plan
