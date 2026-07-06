"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every test.
All setup calls use get_success_data() (lenient) so a setup break surfaces as a
clear "Setup failed" rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_venue_payload,
    create_membership_payload,
    activate_membership_payload,
    create_show_payload,
    create_show_booking_payload,
    create_group_booking_payload,
    create_program_payload,
    create_registration_payload,
    create_rental_payload,
    create_sponsor_payload,
    create_contribution_payload,
    create_accommodation_payload,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
GROUP_SALES = TEST_USERS["group_sales_headers"]
CLERK = TEST_USERS["membership_clerk_headers"]
PROGRAM = TEST_USERS["program_coordinator_headers"]
EVENTS = TEST_USERS["events_manager_headers"]
DEV = TEST_USERS["development_officer_headers"]
ACCESS = TEST_USERS["accessibility_headers"]


# --- Tier 1: basic entity creation ---

def create_venue(**overrides) -> dict:
    """Create a venue (defaults to a DOME). Returns the Venue."""
    payload = create_venue_payload(**overrides)
    return get_success_data(api_client.create_venue(payload, ADMIN))


def create_dome(seated_capacity=50, accessible_seats=0, turnover_buffer_minutes=None,
                name="Test Dome") -> dict:
    """Create a DOME venue for shows."""
    overrides = {"name": name, "venue_type": "DOME", "seated_capacity": seated_capacity,
                 "accessible_seats": accessible_seats}
    if turnover_buffer_minutes is not None:
        overrides["turnover_buffer_minutes"] = turnover_buffer_minutes
    return create_venue(**overrides)


def create_classroom(seated_capacity=30, name="Test Room") -> dict:
    """Create a CLASSROOM venue for programs."""
    return create_venue(name=name, venue_type="CLASSROOM", seated_capacity=seated_capacity)


def create_rental_hall(seated_capacity=80, name="Test Hall") -> dict:
    """Create a RENTAL_HALL venue for rentals."""
    return create_venue(name=name, venue_type="RENTAL_HALL", seated_capacity=seated_capacity)


def create_membership(tier="FAMILY", home_zip="90210", party_size=None,
                      primary_member_name="Test Member") -> dict:
    """Create a membership in PENDING. Returns the Membership."""
    overrides = {"tier": tier, "home_zip": home_zip, "primary_member_name": primary_member_name}
    if party_size is not None:
        overrides["party_size"] = party_size
    payload = create_membership_payload(**overrides)
    return get_success_data(api_client.create_membership(payload, CLERK))


def create_active_membership(tier="FAMILY", home_zip="90210", party_size=None,
                             dues_cents=12000, primary_member_name="Test Member") -> dict:
    """Create then activate a membership. Returns the ACTIVE Membership."""
    m = create_membership(tier=tier, home_zip=home_zip, party_size=party_size,
                          primary_member_name=primary_member_name)
    return get_success_data(api_client.activate_membership(
        m["id"], activate_membership_payload(dues_cents=dues_cents), CLERK))


def create_sponsor(pledged_cents=10000, sponsor_kind="SPONSOR", org_name="Test Sponsor") -> dict:
    """Create a sponsor in PLEDGED. Returns the Sponsor."""
    payload = create_sponsor_payload(pledged_cents=pledged_cents, sponsor_kind=sponsor_kind,
                                     org_name=org_name)
    return get_success_data(api_client.create_sponsor(payload, DEV))


# --- Tier 2: show + state progression ---

def create_show(venue_id, base_price_cents=1000, feature_surcharge_cents=None,
                title="Test Show", starts_at="2026-04-01T10:00:00Z",
                ends_at="2026-04-01T11:00:00Z") -> dict:
    """Create a SCHEDULED show in the given venue. Returns the ShowEvent."""
    overrides = {"venue_id": venue_id, "base_price_cents": base_price_cents, "title": title,
                 "starts_at": starts_at, "ends_at": ends_at}
    if feature_surcharge_cents is not None:
        overrides["feature_surcharge_cents"] = feature_surcharge_cents
    return get_success_data(api_client.create_show(create_show_payload(**overrides), BOX_OFFICE))


def create_open_show(seated_capacity=50, accessible_seats=0, base_price_cents=1000,
                     feature_surcharge_cents=None, title="Open Show",
                     starts_at="2026-04-01T10:00:00Z", ends_at="2026-04-01T11:00:00Z") -> dict:
    """Create a DOME venue + a show and open it. Returns the OPEN ShowEvent
    (its version reflects the post-open value)."""
    dome = create_dome(seated_capacity=seated_capacity, accessible_seats=accessible_seats)
    show = create_show(dome["id"], base_price_cents=base_price_cents,
                       feature_surcharge_cents=feature_surcharge_cents, title=title,
                       starts_at=starts_at, ends_at=ends_at)
    opened = get_success_data(api_client.open_show(show["id"], BOX_OFFICE))
    return opened


def get_show_version(show_id) -> int:
    """Fetch the live ShowEvent version (for OCC echo on the next hold)."""
    return get_success_data(api_client.get_show(show_id, BOX_OFFICE))["version"]


def create_hold(show_id, party_size=1, membership_id=None, accessible_seats_requested=None,
                expected_show_version=None) -> dict:
    """Create a seat hold on an open show. If expected_show_version is omitted it is
    fetched live. Returns the ShowBooking."""
    if expected_show_version is None:
        expected_show_version = get_show_version(show_id)
    overrides = {"show_event_id": show_id, "party_size": party_size,
                 "expected_show_version": expected_show_version}
    if membership_id is not None:
        overrides["membership_id"] = membership_id
    if accessible_seats_requested is not None:
        overrides["accessible_seats_requested"] = accessible_seats_requested
    return get_success_data(api_client.create_show_booking(
        create_show_booking_payload(**overrides), BOX_OFFICE))


def create_confirmed_booking(show_id, party_size=1, membership_id=None) -> dict:
    """Create a hold and confirm it. Returns the CONFIRMED ShowBooking."""
    booking = create_hold(show_id, party_size=party_size, membership_id=membership_id)
    return get_success_data(api_client.confirm_show_booking(booking["id"], BOX_OFFICE))


# --- Tier 3: group booking lifecycle ---

def create_group_booking(show_id, student_count=10, chaperone_count=1,
                         organization_name="Test School") -> dict:
    """Request a group block (REQUESTED). Returns the GroupBooking."""
    payload = create_group_booking_payload(show_event_id=show_id, student_count=student_count,
                                          chaperone_count=chaperone_count,
                                          organization_name=organization_name)
    return get_success_data(api_client.create_group_booking(payload, GROUP_SALES))


def create_deposit_paid_group(show_id, student_count=10, chaperone_count=1,
                              organization_name="Test School") -> dict:
    """Request a group block and pay its deposit. Returns the DEPOSIT_PAID GroupBooking
    (the show must already be OPEN with room for the block)."""
    gb = create_group_booking(show_id, student_count=student_count, chaperone_count=chaperone_count,
                             organization_name=organization_name)
    return get_success_data(api_client.pay_group_deposit(gb["id"], GROUP_SALES))


# --- Tier 4: program + registration ---

def create_program(venue_id, capacity=5, tuition_cents=5000, min_age=5, max_age=99,
                   program_kind="CAMP", title="Test Program",
                   starts_at="2026-07-01T09:00:00Z") -> dict:
    """Create an ENROLLING program session in the given classroom. Returns the ProgramSession."""
    payload = create_program_payload(venue_id=venue_id, capacity=capacity, tuition_cents=tuition_cents,
                                     min_age=min_age, max_age=max_age, program_kind=program_kind,
                                     title=title, starts_at=starts_at)
    return get_success_data(api_client.create_program(payload, PROGRAM))


def create_classroom_program(capacity=5, tuition_cents=5000, min_age=5, max_age=99,
                             program_kind="CAMP", title="Test Program",
                             starts_at="2026-07-01T09:00:00Z") -> dict:
    """Create a CLASSROOM venue + a program. Returns the ProgramSession."""
    room = create_classroom()
    return create_program(room["id"], capacity=capacity, tuition_cents=tuition_cents,
                          min_age=min_age, max_age=max_age, program_kind=program_kind,
                          title=title, starts_at=starts_at)


def get_program_version(program_id) -> int:
    """Fetch the live ProgramSession version (for OCC echo on the next registration)."""
    return get_success_data(api_client.get_program(program_id, PROGRAM))["version"]


def create_registration(program_id, participant_name="Test Participant", participant_age=10,
                        membership_id=None, expected_session_version=None) -> dict:
    """Register a participant. If expected_session_version is omitted it is fetched live.
    Returns the Registration (ENROLLED or WAITLISTED depending on capacity)."""
    if expected_session_version is None:
        expected_session_version = get_program_version(program_id)
    overrides = {"program_session_id": program_id, "participant_name": participant_name,
                 "participant_age": participant_age,
                 "expected_session_version": expected_session_version}
    if membership_id is not None:
        overrides["membership_id"] = membership_id
    return get_success_data(api_client.create_registration(
        create_registration_payload(**overrides), PROGRAM))


# --- Tier 5: rental lifecycle ---

def create_rental(venue_id, guest_count=10, base_rental_cents=30000, host_name="Test Host",
                  starts_at="2026-05-02T14:00:00Z", ends_at="2026-05-02T17:00:00Z") -> dict:
    """Create a rental inquiry (INQUIRY). Returns the RentalEvent."""
    payload = create_rental_payload(venue_id=venue_id, guest_count=guest_count,
                                   base_rental_cents=base_rental_cents, host_name=host_name,
                                   starts_at=starts_at, ends_at=ends_at)
    return get_success_data(api_client.create_rental(payload, EVENTS))


def create_held_rental(venue_id, guest_count=10, base_rental_cents=30000, host_name="Test Host",
                       starts_at="2026-05-02T14:00:00Z", ends_at="2026-05-02T17:00:00Z") -> dict:
    """Create a rental inquiry and hold it. Returns the HELD RentalEvent."""
    rental = create_rental(venue_id, guest_count=guest_count, base_rental_cents=base_rental_cents,
                          host_name=host_name, starts_at=starts_at, ends_at=ends_at)
    return get_success_data(api_client.hold_rental(rental["id"], EVENTS))


# --- Tier 6: sponsor + contribution ---

def record_contribution(sponsor_id, amount_cents, expected_sponsor_version=None) -> dict:
    """Record a contribution. If expected_sponsor_version is omitted it is fetched live.
    Returns the Contribution."""
    if expected_sponsor_version is None:
        expected_sponsor_version = get_success_data(api_client.get_sponsor(sponsor_id, DEV))["version"]
    payload = create_contribution_payload(amount_cents=amount_cents,
                                         expected_sponsor_version=expected_sponsor_version)
    return get_success_data(api_client.create_contribution(sponsor_id, payload, DEV))


# --- Tier 7: accommodations ---

def submit_accommodation(subject_type, accommodation_kind="WHEELCHAIR", show_booking_id=None,
                         registration_id=None, rental_event_id=None) -> dict:
    """Submit an accommodation request. Returns the SUBMITTED AccommodationRequest."""
    overrides = {"subject_type": subject_type, "accommodation_kind": accommodation_kind}
    if show_booking_id is not None:
        overrides["show_booking_id"] = show_booking_id
    if registration_id is not None:
        overrides["registration_id"] = registration_id
    if rental_event_id is not None:
        overrides["rental_event_id"] = rental_event_id
    return get_success_data(api_client.create_accommodation(
        create_accommodation_payload(**overrides), ACCESS))


def submit_and_approve_accommodation(subject_type, accommodation_kind="WHEELCHAIR",
                                     show_booking_id=None, registration_id=None,
                                     rental_event_id=None) -> dict:
    """Submit then approve an accommodation. Returns the APPROVED AccommodationRequest."""
    acc = submit_accommodation(subject_type, accommodation_kind=accommodation_kind,
                              show_booking_id=show_booking_id, registration_id=registration_id,
                              rental_event_id=rental_event_id)
    return get_success_data(api_client.approve_accommodation(acc["id"], ACCESS))


# --- Tier 8: clock / sweep ---

def set_clock(to_iso8601) -> None:
    """Advance the server logical clock."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweeps() -> None:
    """Run deferred expiry/hold sweeps."""
    get_success_data(api_client.run_sweeps(ADMIN))
