"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

Identity threading: Member and Guardian are entity-backed roles. Whenever a
fixture creates a Member and a later call is ownership-gated, it passes the real
Member.id through make_member_headers(member_id). The opaque ParkManager/FrontDesk
constants are used for operator-only calls.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_park_payload, create_slot_payload, create_participant_payload,
    create_waiver_payload, create_jump_pass_payload, create_add_on_payload,
    create_member_payload, create_membership_payload, create_room_payload,
    create_package_payload, create_party_booking_payload, create_incident_payload,
)
from .test_users import (
    TEST_USERS, make_park_manager_headers, make_front_desk_headers,
    make_member_headers,
)

PM = TEST_USERS["park_manager_headers"]
FD = TEST_USERS["front_desk_headers"]

# Canonical fixed timestamps used across the design indices.
DEFAULT_CLOCK = "2026-06-15T00:00:00Z"
SLOT_START = "2026-06-20T10:00:00Z"
SLOT_END = "2026-06-20T12:00:00Z"


# ─── Tier 0: Park + clock ─────────────────────────────
def create_park(**overrides):
    """Bootstrap a park (ParkManager). Returns the park entity."""
    return get_success_data(api_client.create_park(create_park_payload(**overrides), PM))


def set_clock(to_iso8601: str):
    """Move the park's logical clock (ParkManager). Returns the park."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PM))


def create_park_with_clock(clock=DEFAULT_CLOCK, **park_overrides):
    """Bootstrap a park then set the clock. Returns the park."""
    park = create_park(**park_overrides)
    set_clock(clock)
    return park


# ─── Tier 1: Slots ────────────────────────────────────
def create_slot(park_id: str, **overrides):
    """Create a session slot (ParkManager). Returns the slot."""
    return get_success_data(
        api_client.create_slot(create_slot_payload(park_id, **overrides), PM))


def get_slot(slot_id: str):
    """Read a slot (FrontDesk). Returns the slot with derived seats_taken/status/version."""
    return get_success_data(api_client.get_slot(slot_id, FD))


def get_slot_version(slot_id: str) -> int:
    return get_slot(slot_id)["version"]


def setup_park_and_slot(clock=DEFAULT_CLOCK, slot_overrides=None, park_overrides=None):
    """Park + clock + one slot. Returns (park, slot)."""
    park = create_park_with_clock(clock, **(park_overrides or {}))
    slot = create_slot(park["id"], **(slot_overrides or {}))
    return park, slot


# ─── Tier 2: Participants & waivers ───────────────────
def create_participant(park_id: str, headers=None, **overrides):
    """Register a participant (FrontDesk by default)."""
    return get_success_data(
        api_client.create_participant(create_participant_payload(park_id, **overrides),
                                      headers or FD))


def create_adult(park_id: str, full_name="Adult Jumper", **overrides):
    """Adult participant (no guardian). Returns the participant."""
    return create_participant(park_id, full_name=full_name,
                              birthdate="1990-01-01T00:00:00Z", **overrides)


def create_guardian_and_minor(park_id: str, minor_birthdate="2016-01-01T00:00:00Z"):
    """Adult guardian + minor referencing them. Returns (guardian, minor)."""
    guardian = create_adult(park_id, full_name="Guardian A")
    minor = create_participant(park_id, full_name="Kid K", birthdate=minor_birthdate,
                               guardian_participant_id=guardian["id"])
    return guardian, minor


def sign_waiver(participant_id: str, signed_by_participant_id: str, headers=None,
                signature_text="Adult Jumper"):
    """E-sign a waiver (FrontDesk by default). Returns the waiver."""
    return get_success_data(api_client.create_waiver(
        create_waiver_payload(participant_id, signed_by_participant_id,
                              signature_text=signature_text),
        headers or FD))


# ─── Tier 3: Members & memberships ────────────────────
def create_member(park_id: str, email="m1@x.com", full_name="Member One", **overrides):
    """Create a member account (FrontDesk). Returns the member."""
    return get_success_data(api_client.create_member(
        create_member_payload(park_id, email=email, full_name=full_name, **overrides), FD))


def create_membership(member_id: str, tier="GOLD", cycle_anchor_at="2026-06-01T00:00:00Z"):
    """Subscribe a member to a tier, acting as the owning Member. Returns the membership."""
    return get_success_data(api_client.create_membership(
        create_membership_payload(member_id, tier=tier, cycle_anchor_at=cycle_anchor_at),
        make_member_headers(member_id)))


def create_member_with_membership(park_id: str, tier="GOLD", email="m1@x.com",
                                  cycle_anchor_at="2026-06-01T00:00:00Z"):
    """Member account + fresh membership. Returns (member, membership)."""
    member = create_member(park_id, email=email)
    membership = create_membership(member["id"], tier=tier, cycle_anchor_at=cycle_anchor_at)
    return member, membership


# ─── Tier 4: Jump passes ──────────────────────────────
def create_jump_pass(slot_id: str, participant_id: str, expected_slot_version: int,
                     headers=None, **overrides):
    """Create a jump pass. Uses FrontDesk unless headers provided (e.g. member-owned)."""
    return get_success_data(api_client.create_jump_pass(
        create_jump_pass_payload(slot_id, participant_id, expected_slot_version, **overrides),
        headers or FD))


def create_reservation_pass(slot_id: str, participant_id: str, slot_version: int,
                            headers=None, **overrides):
    """RESERVATION pass. Returns the pass."""
    return create_jump_pass(slot_id, participant_id, slot_version,
                            headers=headers, channel="RESERVATION", **overrides)


def create_paid_reservation_pass(slot, participant_id, headers=None, **overrides):
    """Create a RESERVATION pass on `slot` and pay it. Returns the paid pass."""
    pass_headers = headers or FD
    pas = create_reservation_pass(slot["id"], participant_id, get_slot_version(slot["id"]),
                                  headers=pass_headers, **overrides)
    return get_success_data(api_client.pay_jump_pass(pas["id"], pass_headers))


def create_member_pass_paid(slot, member_id, participant_id, **overrides):
    """Member RESERVATION pass created + paid as the owning Member. Returns paid pass."""
    mh = make_member_headers(member_id)
    pas = create_reservation_pass(slot["id"], participant_id, get_slot_version(slot["id"]),
                                  headers=mh, member_id=member_id, **overrides)
    return get_success_data(api_client.pay_jump_pass(pas["id"], mh))


# ─── Tier 5: Party rooms, packages, bookings ──────────
def create_room(park_id: str, **overrides):
    return get_success_data(api_client.create_room(create_room_payload(park_id, **overrides), PM))


def create_package(park_id: str, **overrides):
    return get_success_data(
        api_client.create_package(create_package_payload(park_id, **overrides), PM))


def setup_party_prereqs(clock=DEFAULT_CLOCK, slot_overrides=None, room_overrides=None,
                        package_overrides=None, park_overrides=None):
    """Park + clock + slot + room + package. Returns (park, slot, room, package)."""
    park = create_park_with_clock(clock, **(park_overrides or {}))
    slot = create_slot(park["id"], **(slot_overrides or {}))
    room = create_room(park["id"], **(room_overrides or {}))
    package = create_package(park["id"], **(package_overrides or {}))
    return park, slot, room, package


def create_party_booking(package_id, room_id, slot_id, guest_count=6, headers=None,
                         **overrides):
    """Create a PENDING booking. Returns the booking."""
    return get_success_data(api_client.create_party_booking(
        create_party_booking_payload(package_id, room_id, slot_id,
                                     guest_count=guest_count, **overrides),
        headers or FD))


def hold_party_deposit(booking_id, slot_id, headers=None):
    """Hold the deposit using the slot's current version. Returns the DEPOSIT_HELD booking."""
    return get_success_data(api_client.hold_deposit(
        booking_id, {"expected_slot_version": get_slot_version(slot_id)}, headers or FD))


def create_deposit_held_booking(package_id, room_id, slot_id, guest_count=6, headers=None,
                                **overrides):
    """Create + hold a party booking. Returns the DEPOSIT_HELD booking."""
    booking = create_party_booking(package_id, room_id, slot_id, guest_count=guest_count,
                                    headers=headers, **overrides)
    return hold_party_deposit(booking["id"], slot_id, headers=headers)


# ─── Tier 6: Incidents ────────────────────────────────
def setup_checked_in_walkin_pass(clock="2026-06-20T10:05:00Z", slot_overrides=None):
    """Park + slot + adult + waiver + a WALKIN pass (born CHECKED_IN) inside the window.
    Returns (park, slot, participant, pass)."""
    park, slot = setup_park_and_slot(clock=clock, slot_overrides=slot_overrides)
    participant = create_adult(park["id"], full_name="Walk J")
    sign_waiver(participant["id"], participant["id"], signature_text="Walk J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=1)
    return park, slot, participant, pas


def file_incident(park_id, jump_pass_id, severity="MINOR", headers=None, **overrides):
    """File an incident (FrontDesk). Returns the incident."""
    return get_success_data(api_client.create_incident(
        create_incident_payload(park_id, jump_pass_id, severity=severity, **overrides),
        headers or FD))
