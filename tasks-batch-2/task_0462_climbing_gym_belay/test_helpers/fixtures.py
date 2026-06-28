"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors, not confusing assertion failures.

Identity threading: after creating a Member, ownership-gated membership/
enrollment calls use make_member_headers(member["id"]) — never the shared
Member constant, which would never equal any real Member id.

Every test runs against a freshly-restarted (empty) database, so each fixture
builds its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_member_payload, create_waiver_payload, create_membership_payload,
    create_certification_payload, grade_payload, create_facility_payload,
    create_route_payload, create_checkin_payload, create_clinic_payload,
    create_enrollment_payload, create_rental_payload, create_incident_payload,
    unique_email,
)
from .test_users import TEST_USERS, make_member_headers, make_setter_headers


FD = TEST_USERS["frontdesk_headers"]
EX = TEST_USERS["examiner_headers"]
SETTER = TEST_USERS["setter_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Advance the logical clock to an absolute UTC instant (GymAdmin only)."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ─── Tier 1: Single-entity creation ───────────────────────────────────────
def create_member(full_name="Test Member", email=None, date_of_birth="1990-01-01"):
    """Register a member. Returns the Member dict."""
    payload = create_member_payload(
        full_name=full_name,
        email=email or unique_email("member"),
        date_of_birth=date_of_birth,
    )
    return get_success_data(api_client.create_member(payload, FD))


def create_waiver(member_id, minor_guardian_name=None):
    """Sign a waiver for a member. Pass minor_guardian_name for youth members."""
    overrides = {}
    if minor_guardian_name is not None:
        overrides["minor_guardian_name"] = minor_guardian_name
    payload = create_waiver_payload(member_id, **overrides)
    return get_success_data(api_client.create_waiver(payload, FD))


def create_member_with_waiver(date_of_birth="1990-01-01", minor_guardian_name=None,
                              email=None):
    """Member + a fresh VALID waiver. Returns (member, waiver)."""
    member = create_member(date_of_birth=date_of_birth, email=email)
    waiver = create_waiver(member["id"], minor_guardian_name=minor_guardian_name)
    return member, waiver


def create_facility(name="Test Wall", floor_capacity=10, requires_belay_cert=False):
    """Create a facility. Returns the Facility dict (version starts at 1)."""
    payload = create_facility_payload(
        name=name, floor_capacity=floor_capacity, requires_belay_cert=requires_belay_cert)
    return get_success_data(api_client.create_facility(payload, ADMIN))


def create_clinic(title="Test Clinic", starts_at="2026-07-01T09:00:00Z",
                  ends_at="2026-07-01T11:00:00Z", seat_capacity=5):
    """Schedule a clinic. Returns the Clinic dict (version starts at 1)."""
    payload = create_clinic_payload(
        title=title, starts_at=starts_at, ends_at=ends_at, seat_capacity=seat_capacity)
    return get_success_data(api_client.create_clinic(payload, ADMIN))


def create_route(facility_id, grade=5, style="OVERHANG", setter_user_id="setter-1"):
    """Log a route on a facility under a named setter. Returns the Route dict."""
    payload = create_route_payload(facility_id, grade=grade, style=style)
    headers = make_setter_headers(setter_user_id)
    return get_success_data(api_client.create_route(payload, headers))


def create_rental(member_id, item_kind="HARNESS", deposit_cents=5000):
    """Check out a gear rental (status OUT). Returns the Rental dict."""
    payload = create_rental_payload(member_id, item_kind=item_kind, deposit_cents=deposit_cents)
    return get_success_data(api_client.create_rental(payload, FD))


# ─── Tier 2: Membership lifecycle shortcuts ───────────────────────────────
def create_membership(member_id, plan_tier="BASIC"):
    """Open an ACTIVE/CURRENT membership for a member. Returns the Membership dict."""
    payload = create_membership_payload(member_id, plan_tier=plan_tier)
    return get_success_data(api_client.create_membership(payload, FD))


def create_member_with_active_membership(plan_tier="BASIC", date_of_birth="1990-01-01"):
    """Member + ACTIVE membership. Returns (member, membership)."""
    member = create_member(date_of_birth=date_of_birth)
    membership = create_membership(member["id"], plan_tier=plan_tier)
    return member, membership


def create_frozen_membership(plan_tier="BASIC", date_of_birth="1990-01-01"):
    """Member + membership frozen via the owner. Returns (member, membership_after_freeze)."""
    member = create_member(date_of_birth=date_of_birth)
    membership = create_membership(member["id"], plan_tier=plan_tier)
    headers = make_member_headers(member["id"])
    frozen = get_success_data(api_client.freeze_membership(
        membership["id"], {"expected_membership_version": membership["version"]}, headers))
    return member, frozen


def create_past_due_membership(plan_tier="BASIC"):
    """Member + membership driven to PAST_DUE via a FAILED run-billing past cycle_end.

    Anchors the clock at 2026-05-01 (create), 2026-06-01 (FAILED). Returns
    (member, membership_after_fail). Leaves the clock at 2026-06-01.
    """
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier=plan_tier)
    set_clock("2026-06-01T00:00:00Z")
    past_due = get_success_data(api_client.run_billing(
        membership["id"], {"outcome": "FAILED"}, FD))
    return member, past_due


# ─── Tier 3: Certification lifecycle shortcuts ────────────────────────────
def register_certification(member_id, discipline="BELAY"):
    """Register a REGISTERED certification. Returns the Certification dict."""
    payload = create_certification_payload(member_id, discipline=discipline)
    return get_success_data(api_client.create_certification(payload, EX))


def create_passed_belay_cert(member_id):
    """Register + grade a BELAY cert to PASSED (knot 90/cmd 85/catch 70/lower 95
    → weighted 84, min 70). Returns the graded Certification dict."""
    cert = register_certification(member_id, discipline="BELAY")
    graded = get_success_data(api_client.grade_certification(
        cert["id"], grade_payload(knot=90, commands=85, catch=70, lower=95), EX))
    return graded


def create_member_with_passed_belay(date_of_birth="1990-01-01"):
    """Member + PASSED BELAY cert. Returns (member, cert)."""
    member = create_member(date_of_birth=date_of_birth)
    cert = create_passed_belay_cert(member["id"])
    return member, cert


# ─── Tier 4: Check-in shortcuts ───────────────────────────────────────────
def check_in(member_id, facility_id, expected_facility_version,
             entry_kind="DAY_PASS", gear_bundle=None):
    """Create an ON_FLOOR check-in. Returns the CheckIn dict."""
    overrides = {}
    if gear_bundle is not None:
        overrides["gear_bundle"] = gear_bundle
    payload = create_checkin_payload(
        member_id, facility_id, expected_facility_version,
        entry_kind=entry_kind, **overrides)
    return get_success_data(api_client.create_checkin(payload, FD))


def fill_facility_to_capacity(facility, count):
    """Create `count` waivered DAY_PASS check-ins to drive occupancy up by `count`.

    Threads facility.version forward through each check-in. Returns the facility
    version after the last check-in (the live token a caller must pass next).
    """
    version = facility["version"]
    for i in range(count):
        member = create_member(email=unique_email("cap"))
        create_waiver(member["id"])
        ci = check_in(member["id"], facility["id"], version)
        # version captured fresh from the facility after the check-in bump.
        fac = get_success_data(api_client.get_facility(facility["id"], FD))
        version = fac["version"]
    return version


# ─── Tier 5: Clinic / enrollment shortcuts ────────────────────────────────
def enroll(clinic_id, member_id, expected_clinic_version, as_member=True):
    """Enroll a member into a clinic. By default acts as the owning Member.
    Returns the Enrollment dict."""
    payload = create_enrollment_payload(clinic_id, member_id, expected_clinic_version)
    headers = make_member_headers(member_id) if as_member else FD
    return get_success_data(api_client.create_enrollment(payload, headers))


def create_clinic_with_one_enrollment(seat_capacity=5, starts_at="2026-07-01T09:00:00Z",
                                      ends_at="2026-07-01T11:00:00Z"):
    """Clinic + one ENROLLED member (enrolled_count 1).

    Returns (clinic_after_enroll, member, enrollment). The clinic dict reflects
    the post-enroll version so callers can chain a cancel/strip immediately.
    """
    member = create_member(date_of_birth="2009-01-01", email=unique_email("clinic"))
    clinic = create_clinic(seat_capacity=seat_capacity, starts_at=starts_at, ends_at=ends_at)
    enrollment = enroll(clinic["id"], member["id"], clinic["version"])
    clinic_after = get_success_data(api_client.get_clinic(clinic["id"], FD))
    return clinic_after, member, enrollment


# ─── Tier 6: Composite cascade scenario ───────────────────────────────────
def setup_serious_incident_scenario():
    """Build the full precondition for the 3-hop SERIOUS-incident cascade:
    a member with a PASSED BELAY cert, an ACTIVE BASIC membership, a VALID waiver,
    and an ON_FLOOR check-in on a belay-required facility.

    Returns a dict with member, cert, membership, facility, checkin (all fresh).
    Clock is anchored at 2026-06-01 by the caller before invoking.
    """
    member = create_member(date_of_birth="1990-06-06")
    create_waiver(member["id"])
    membership = create_membership(member["id"], plan_tier="BASIC")
    cert = create_passed_belay_cert(member["id"])
    facility = create_facility(
        name="Lead Wall", floor_capacity=10, requires_belay_cert=True)
    checkin = check_in(
        member["id"], facility["id"], facility["version"], entry_kind="MEMBERSHIP")
    return {
        "member": member,
        "cert": cert,
        "membership": membership,
        "facility": facility,
        "checkin": checkin,
    }
