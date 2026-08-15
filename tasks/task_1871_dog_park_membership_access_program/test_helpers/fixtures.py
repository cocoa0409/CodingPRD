"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Member and Steward calls are entity-backed by Member, so
ownership-gated calls always use make_member_headers(member["id"]) /
make_steward_headers(member["id"]) built from the real entity id — never the
shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_STARTUP_DEFAULT
from .factories import (
    advance_report_payload,
    check_in_payload,
    create_area_payload,
    create_closure_payload,
    create_dog_payload,
    create_member_payload,
    create_waste_station_payload,
    file_incident_payload,
    purchase_guest_pass_payload,
    resubmit_dog_payload,
    verify_dog_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_steward_headers

ADMIN = TEST_USERS["park_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

DEFAULT_CLOCK = CLOCK_STARTUP_DEFAULT
DEFAULT_VAX = "2027-06-01"


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Advance the server's logical clock (PRD §2.4). Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and state progression
# ---------------------------------------------------------------------------

def register_member(full_name="Test Member", email=None) -> dict:
    """Register a member account (born PENDING_VERIFICATION, version 1)."""
    overrides = {"full_name": full_name}
    if email is not None:
        overrides["email"] = email
    payload = create_member_payload(**overrides)
    return get_success_data(api_client.create_member(payload, ANON), 201)


def add_dog(member_id, name="Rex", size_class="LARGE", license_number="LIC-1",
            vaccination_expires_on=DEFAULT_VAX, as_headers=None) -> dict:
    """Register a dog for a member (born SUBMITTED). Caller defaults to the
    owning member."""
    headers = as_headers or make_member_headers(member_id)
    payload = create_dog_payload(
        name=name, size_class=size_class, license_number=license_number,
        vaccination_expires_on=vaccination_expires_on)
    return get_success_data(api_client.create_dog(member_id, payload, headers),
                            201)


def verify_dog(dog_id, decision="VERIFIED", reason=None) -> dict:
    """ParkAdmin verification decision on a SUBMITTED dog."""
    payload = verify_dog_payload(decision=decision, reason=reason)
    return get_success_data(api_client.verify_dog(dog_id, payload, ADMIN))


def purchase_membership(member_id, as_headers=None) -> dict:
    """Purchase the initial annual membership. Caller defaults to the member.
    Requires >= 1 VERIFIED dog; flips the member to ACTIVE."""
    headers = as_headers or make_member_headers(member_id)
    return get_success_data(api_client.purchase_membership(member_id, headers),
                            201)


def create_park_area(name="Main Field", size_class_restriction="LARGE",
                     capacity=4, peak_capacity=None, peak_windows=None) -> dict:
    """Create a park area (born with occupancy 0, effective_capacity == capacity
    when outside any peak window and no ACTIVE closure)."""
    payload = create_area_payload(
        name=name, size_class_restriction=size_class_restriction,
        capacity=capacity,
        peak_capacity=peak_capacity if peak_capacity is not None else capacity)
    if peak_windows is not None:
        payload["peak_windows"] = peak_windows
    return get_success_data(api_client.create_area(payload, ADMIN), 201)


def schedule_closure(area_id, starts_at, ends_at, reason="maintenance") -> dict:
    """Schedule a closure window (born SCHEDULED)."""
    payload = create_closure_payload(starts_at=starts_at, ends_at=ends_at,
                                     reason=reason)
    return get_success_data(api_client.create_closure(area_id, payload, ADMIN),
                            201)


def create_station(area_id, name="North Bin") -> dict:
    """Install a waste station (born fill_pct 0, OK, last_serviced_at null)."""
    payload = create_waste_station_payload(name=name)
    return get_success_data(
        api_client.create_waste_station(area_id, payload, ADMIN), 201)


# ---------------------------------------------------------------------------
# Tier 2: the active member (member + verified dogs + ACTIVE membership)
# ---------------------------------------------------------------------------

def setup_active_member(clock=DEFAULT_CLOCK, num_dogs=1, size_class="LARGE",
                        vaccination_expires_on=DEFAULT_VAX,
                        full_name="Test Member", email=None,
                        set_clock_first=True) -> dict:
    """Member + num_dogs VERIFIED dogs + ACTIVE membership.

    Returns {member, dogs, membership, member_headers}."""
    if set_clock_first:
        set_clock(clock)
    member = register_member(full_name=full_name, email=email)
    headers = make_member_headers(member["id"])
    dogs = []
    for i in range(num_dogs):
        dog = add_dog(member["id"], name=f"Dog{i + 1}", size_class=size_class,
                      license_number=f"LIC-{i + 1}",
                      vaccination_expires_on=vaccination_expires_on)
        dogs.append(verify_dog(dog["id"]))
    membership = purchase_membership(member["id"])
    return {
        "member": member,
        "dogs": dogs,
        "membership": membership,
        "member_headers": headers,
    }


def get_member(member_id, headers=None) -> dict:
    return get_success_data(api_client.get_member(member_id, headers or ADMIN))


def get_membership(member_id) -> dict:
    """Read the member's single membership back (as ParkAdmin)."""
    data, _meta = _list_memberships(member_id)
    assert len(data) == 1, f"Expected exactly one membership, got {len(data)}"
    return data[0]


def _list_memberships(member_id, headers=None):
    return validate_paginated(
        api_client.list_memberships(member_id, headers or ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: gate operations (visits)
# ---------------------------------------------------------------------------

def check_in_dog(member, dog, area) -> dict:
    """Check a member's own dog into an area. Returns the OPEN visit."""
    payload = check_in_payload(area["id"], dog_id=dog["id"])
    return get_success_data(
        api_client.check_in(payload, make_member_headers(member["id"])), 201)


def check_in_guest(member, guest_pass, area) -> dict:
    """Redeem a guest pass at the gate (sponsor is the caller). Returns the
    OPEN guest visit."""
    payload = check_in_payload(area["id"], guest_pass_id=guest_pass["id"])
    return get_success_data(
        api_client.check_in(payload, make_member_headers(member["id"])), 201)


def check_out_visit(member, visit) -> dict:
    """Voluntary check-out by the visit's owning member."""
    return get_success_data(api_client.check_out(
        visit["id"], make_member_headers(member["id"])))


def visit_in_out(member, dog, area) -> dict:
    """One check-in/check-out pair. Returns the CLOSED visit."""
    visit = check_in_dog(member, dog, area)
    return check_out_visit(member, visit)


# ---------------------------------------------------------------------------
# Tier 4: guest passes
# ---------------------------------------------------------------------------

def purchase_pass(member, guest_dog_size_class="SMALL",
                  valid_on="2026-08-03") -> dict:
    """Purchase a guest day pass (sponsor = the calling member)."""
    payload = purchase_guest_pass_payload(
        guest_dog_size_class=guest_dog_size_class, valid_on=valid_on)
    return get_success_data(api_client.purchase_guest_pass(
        payload, make_member_headers(member["id"])), 201)


# ---------------------------------------------------------------------------
# Tier 5: incident pipeline and suspension
# ---------------------------------------------------------------------------

def file_report(subject_member_id, severity="MINOR",
                occurred_at="2026-08-01T10:00:00Z",
                description="rough play near the gate", as_headers=None,
                subject_dog_id=None, area_id=None) -> dict:
    """File an incident report (born FILED). Default caller is ParkAdmin, so
    reporter_member_id records null."""
    headers = as_headers or ADMIN
    overrides = {}
    if subject_dog_id is not None:
        overrides["subject_dog_id"] = subject_dog_id
    if area_id is not None:
        overrides["area_id"] = area_id
    payload = file_incident_payload(
        subject_member_id, severity=severity, occurred_at=occurred_at,
        description=description, **overrides)
    return get_success_data(
        api_client.file_incident_report(payload, headers), 201)


def advance_report(report_id, to, headers=None, resolution_note=None) -> dict:
    """Advance a report along its pipeline. Default caller is ParkAdmin."""
    payload = advance_report_payload(to, resolution_note=resolution_note)
    return get_success_data(
        api_client.advance_incident_report(report_id, payload,
                                           headers or ADMIN))


def confirm_report(report_id) -> dict:
    """Walk a report FILED -> UNDER_REVIEW -> CONFIRMED (both as ParkAdmin)."""
    advance_report(report_id, "UNDER_REVIEW")
    return advance_report(report_id, "CONFIRMED")


def suspend_member_via_report(member_id, severity="SEVERE",
                              occurred_at="2026-08-02T10:00:00Z") -> dict:
    """File + confirm a report whose confirmed points reach the suspension
    threshold (SEVERE = 30). Returns the CONFIRMED report."""
    report = file_report(member_id, severity=severity,
                         occurred_at=occurred_at,
                         description="serious aggression incident")
    return confirm_report(report["id"])


# ---------------------------------------------------------------------------
# Tier 6: stewards
# ---------------------------------------------------------------------------

def grant_steward(member_id) -> dict:
    """ParkAdmin grants the volunteer-steward flag."""
    return get_success_data(api_client.set_steward_status(member_id, True,
                                                          ADMIN))


def create_steward(full_name="Ste Ward", email=None) -> dict:
    """Register a member and grant is_steward. Returns {member,
    steward_headers}."""
    member = register_member(full_name=full_name, email=email)
    member = grant_steward(member["id"])
    return {
        "member": member,
        "steward_headers": make_steward_headers(member["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 7: the nightly service run
# ---------------------------------------------------------------------------

def run_nightly() -> dict:
    """Execute the nightly service-run epoch. Returns the tally payload."""
    return get_success_data(api_client.run_nightly_service_run(ADMIN), 201)


# ---------------------------------------------------------------------------
# Tier 8: multi-member area scenarios (capacity / occupancy / overlap)
# ---------------------------------------------------------------------------

def setup_area_with_members(n_members=3, size_class="SMALL", capacity=2,
                            peak_capacity=None, clock="2026-08-03T10:00:00Z",
                            area_name="Small Side", peak_windows=None,
                            vaccination_expires_on=DEFAULT_VAX) -> dict:
    """One area plus n active members, each with one VERIFIED dog of the
    matching size class and an ACTIVE membership.

    Returns {area, members: [{member, dog, membership, member_headers}, ...]}.
    """
    set_clock(clock)
    area = create_park_area(name=area_name, size_class_restriction=size_class,
                            capacity=capacity, peak_capacity=peak_capacity,
                            peak_windows=peak_windows)
    members = []
    for i in range(n_members):
        bundle = setup_active_member(clock=clock, num_dogs=1,
                                     size_class=size_class,
                                     vaccination_expires_on=vaccination_expires_on,
                                     full_name=f"Member {i + 1}",
                                     set_clock_first=False)
        members.append({
            "member": bundle["member"],
            "dog": bundle["dogs"][0],
            "membership": bundle["membership"],
            "member_headers": bundle["member_headers"],
        })
    return {"area": area, "members": members}
