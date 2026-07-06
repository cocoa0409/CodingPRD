"""Composite setup helpers.

Each fixture creates its own entities from scratch (the runner restarts the
API server before every test, so no state carries between tests).

Fixtures use `get_success_data()` internally — a lenient validator that
accepts any 2xx status — so setup failures produce clean errors instead of
downstream assertion tangles.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_household_payload,
    create_member_payload,
    create_pledge_campaign_payload,
    create_pledge_payload,
    create_donation_payload,
    create_event_payload,
    create_facility_payload,
    create_facility_booking_payload,
    create_volunteer_assignment_payload,
    create_small_group_payload,
    create_group_membership_payload,
)
from .test_users import TEST_USERS, make_member_headers


# ---------------------------------------------------------------------------
# Tier 0: Logical clock control (PRD §2.6)
# ---------------------------------------------------------------------------

def set_clock(iso: str) -> None:
    """Set the server's logical clock. Every temporal decision resolves against it."""
    resp = api_client.set_clock(iso, TEST_USERS["platform_admin_headers"])
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: Directory (Household + Member)
# ---------------------------------------------------------------------------

def create_household(name: str = "Household 1",
                     address_line1: str = "1 Main St",
                     postal_code: str = "10001") -> dict:
    resp = api_client.create_household(
        create_household_payload(name=name, address_line1=address_line1,
                                 postal_code=postal_code),
        TEST_USERS["registrar_headers"],
    )
    return get_success_data(resp)


def create_adult_member(household_id: str,
                        full_name: str = "M1",
                        email: str = "m1@example.com",
                        date_of_birth: str = "1990-01-01",
                        membership_status: str | None = None) -> dict:
    resp = api_client.create_member(
        create_member_payload(household_id=household_id, full_name=full_name,
                              email=email, date_of_birth=date_of_birth,
                              member_type="ADULT"),
        TEST_USERS["registrar_headers"],
    )
    member = get_success_data(resp)
    if membership_status:
        resp2 = api_client.patch_member(
            member["id"], {"membership_status": membership_status},
            TEST_USERS["registrar_headers"],
        )
        member = get_success_data(resp2)
    return member


def create_child_member(household_id: str,
                        guardian_ids: list,
                        full_name: str = "K1",
                        date_of_birth: str = "2020-01-01") -> dict:
    resp = api_client.create_member(
        create_member_payload(household_id=household_id, full_name=full_name,
                              date_of_birth=date_of_birth, member_type="CHILD",
                              guardian_member_ids=guardian_ids, email=None),
        TEST_USERS["registrar_headers"],
    )
    return get_success_data(resp)


def setup_household_with_adult(clock: str = "2026-06-01T00:00:00Z",
                               membership_status: str | None = None):
    """Convenience: clock -> household -> one adult member. Returns (h, m)."""
    set_clock(clock)
    h = create_household()
    m = create_adult_member(h["id"], membership_status=membership_status)
    return h, m


# ---------------------------------------------------------------------------
# Tier 2: Campaigns and Pledges
# ---------------------------------------------------------------------------

def create_campaign(name: str = "Test Campaign",
                    target_amount_cents: int = 100_000,
                    starts_on: str = "2026-05-01",
                    ends_on: str = "2026-12-31") -> dict:
    resp = api_client.create_pledge_campaign(
        create_pledge_campaign_payload(name=name, target_amount_cents=target_amount_cents,
                                       starts_on=starts_on, ends_on=ends_on),
        TEST_USERS["finance_admin_headers"],
    )
    return get_success_data(resp)


def activate_campaign(campaign_id: str) -> dict:
    resp = api_client.activate_pledge_campaign(campaign_id,
                                               TEST_USERS["finance_admin_headers"])
    return get_success_data(resp)


def create_and_activate_campaign(**overrides) -> dict:
    c = create_campaign(**overrides)
    return activate_campaign(c["id"])


def create_pledge(campaign_id: str, member_id: str,
                  pledged_amount_cents: int = 10_000,
                  frequency: str = "ONE_TIME",
                  first_expected_on: str = "2026-06-01") -> dict:
    resp = api_client.create_pledge(
        create_pledge_payload(campaign_id=campaign_id, member_id=member_id,
                              pledged_amount_cents=pledged_amount_cents,
                              frequency=frequency,
                              first_expected_on=first_expected_on),
        TEST_USERS["finance_admin_headers"],
    )
    return get_success_data(resp)


def cancel_pledge(pledge_id: str) -> dict:
    resp = api_client.cancel_pledge(pledge_id, TEST_USERS["finance_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: Donations
# ---------------------------------------------------------------------------

def create_donation(member_id: str, amount_cents: int, donation_date: str,
                    payment_method: str = "CHECK",
                    campaign_id: str | None = None,
                    pledge_id: str | None = None,
                    is_tax_deductible: bool | None = None,
                    split_across: bool | None = None) -> dict:
    payload = create_donation_payload(
        member_id=member_id,
        amount_cents=amount_cents,
        donation_date=donation_date,
        payment_method=payment_method,
    )
    if campaign_id is not None:
        payload["campaign_id"] = campaign_id
    if pledge_id is not None:
        payload["pledge_id"] = pledge_id
    if is_tax_deductible is not None:
        payload["is_tax_deductible"] = is_tax_deductible
    if split_across is not None:
        payload["split_across"] = split_across
    resp = api_client.create_donation(payload, TEST_USERS["finance_admin_headers"])
    return get_success_data(resp)


def refund_donation(donation_id: str) -> dict:
    resp = api_client.refund_donation(donation_id,
                                      TEST_USERS["finance_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: Facilities, Bookings, Events
# ---------------------------------------------------------------------------

def create_facility(name: str = "Sanctuary",
                    capacity: int = 200,
                    buffer_minutes: int = 0) -> dict:
    resp = api_client.create_facility(
        create_facility_payload(name=name, capacity=capacity,
                                buffer_minutes=buffer_minutes),
        TEST_USERS["coordinator_headers"],
    )
    return get_success_data(resp)


def create_facility_booking(facility_id: str, starts_at: str, ends_at: str,
                            headcount: int, expected_facility_version: int,
                            booking_type: str = "EXTERNAL",
                            event_id: str | None = None) -> dict:
    payload = create_facility_booking_payload(
        facility_id=facility_id, starts_at=starts_at, ends_at=ends_at,
        headcount=headcount, booking_type=booking_type,
        expected_facility_version=expected_facility_version,
    )
    if event_id is not None:
        payload["event_id"] = event_id
    resp = api_client.create_facility_booking(payload,
                                              TEST_USERS["coordinator_headers"])
    return get_success_data(resp)


def create_event(name: str = "Sun 10am",
                 event_type: str = "SERVICE",
                 starts_at: str = "2026-05-10T10:00:00Z",
                 ends_at: str = "2026-05-10T11:00:00Z",
                 expected_attendance: int = 50,
                 volunteer_slots: int = 2,
                 facility_id: str | None = None) -> dict:
    payload = create_event_payload(
        name=name, event_type=event_type,
        starts_at=starts_at, ends_at=ends_at,
        expected_attendance=expected_attendance,
        volunteer_slots=volunteer_slots,
    )
    if facility_id is not None:
        payload["facility_id"] = facility_id
    resp = api_client.create_event(payload, TEST_USERS["coordinator_headers"])
    return get_success_data(resp)


def get_facility(facility_id: str) -> dict:
    resp = api_client.get_facility(facility_id, TEST_USERS["coordinator_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: Volunteer assignments
# ---------------------------------------------------------------------------

def create_volunteer_assignment(event_id: str, member_id: str,
                                role_type: str = "USHER") -> dict:
    resp = api_client.create_volunteer_assignment(
        create_volunteer_assignment_payload(event_id=event_id,
                                            member_id=member_id,
                                            role_type=role_type),
        TEST_USERS["coordinator_headers"],
    )
    return get_success_data(resp)


def accept_volunteer_as_member(assignment_id: str, member_id: str) -> dict:
    resp = api_client.accept_volunteer_assignment(
        assignment_id, make_member_headers(member_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 6: Small groups, memberships
# ---------------------------------------------------------------------------

def create_small_group(leader_member_id: str,
                       name: str = "Bible Study",
                       ministry_area: str = "STUDY",
                       capacity: int = 10) -> dict:
    resp = api_client.create_small_group(
        create_small_group_payload(name=name, leader_member_id=leader_member_id,
                                   ministry_area=ministry_area, capacity=capacity),
        TEST_USERS["coordinator_headers"],
    )
    return get_success_data(resp)


def create_group_membership(group_id: str, member_id: str,
                            role: str = "MEMBER") -> dict:
    resp = api_client.create_group_membership(
        create_group_membership_payload(group_id=group_id, member_id=member_id,
                                        role=role),
        TEST_USERS["coordinator_headers"],
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 7: Child check-in
# ---------------------------------------------------------------------------

def create_child_checkin(child_member_id: str, event_id: str,
                         guardian_member_id: str) -> dict:
    resp = api_client.create_child_checkin(
        {"child_member_id": child_member_id, "event_id": event_id,
         "guardian_member_id": guardian_member_id},
        TEST_USERS["coordinator_headers"],
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Higher-level composite scenarios (multi-entity)
# ---------------------------------------------------------------------------

def setup_pledge_ready_to_fulfill(pledged_amount_cents: int = 10_000,
                                  clock: str = "2026-06-01T00:00:00Z"):
    """Clock + household + adult member + ACTIVE campaign + ACTIVE pledge.
    Returns (household, member, campaign, pledge)."""
    set_clock(clock)
    h = create_household()
    m = create_adult_member(h["id"])
    c = create_and_activate_campaign()
    p = create_pledge(c["id"], m["id"], pledged_amount_cents=pledged_amount_cents)
    return h, m, c, p


def setup_fulfilled_pledge(pledged_amount_cents: int = 10_000,
                           donation_date: str = "2026-06-01",
                           clock: str = "2026-06-15T00:00:00Z"):
    """Full path to a FULFILLED pledge via one auto-POSTED CHECK donation.
    Returns (household, member, campaign, pledge, donation)."""
    set_clock(clock)
    h = create_household()
    m = create_adult_member(h["id"])
    c = create_and_activate_campaign()
    p = create_pledge(c["id"], m["id"], pledged_amount_cents=pledged_amount_cents)
    d = create_donation(m["id"], pledged_amount_cents, donation_date,
                        payment_method="CHECK",
                        campaign_id=c["id"], pledge_id=p["id"])
    return h, m, c, p, d


def setup_child_checked_in(clock: str = "2026-05-10T09:30:00Z",
                           event_starts_at: str = "2026-05-10T10:00:00Z",
                           event_ends_at: str = "2026-05-10T11:00:00Z"):
    """Household + adult guardian + child + SCHEDULED event + CHECKED_IN check-in.
    Returns (household, guardian, child, event, checkin)."""
    set_clock(clock)
    h = create_household()
    g = create_adult_member(h["id"], full_name="Guardian", email="g@x.com")
    k = create_child_member(h["id"], guardian_ids=[g["id"]])
    e = create_event(name="Kids Church",
                     starts_at=event_starts_at, ends_at=event_ends_at,
                     expected_attendance=20, volunteer_slots=0)
    ch = create_child_checkin(k["id"], e["id"], g["id"])
    return h, g, k, e, ch


def setup_facility_with_booking(clock: str = "2026-05-01T09:00:00Z",
                                capacity: int = 200,
                                buffer_minutes: int = 0,
                                booking_starts: str = "2026-05-10T10:00:00Z",
                                booking_ends: str = "2026-05-10T11:00:00Z",
                                headcount: int = 100):
    """Facility + one CONFIRMED booking. Returns (facility, booking,
    new_facility_version) where new_facility_version was captured *after*
    the booking (used for a subsequent stale-version test)."""
    set_clock(clock)
    f = create_facility(capacity=capacity, buffer_minutes=buffer_minutes)
    b = create_facility_booking(f["id"], booking_starts, booking_ends,
                                headcount=headcount,
                                expected_facility_version=f["version"])
    f_after = get_facility(f["id"])
    return f, b, f_after["version"]


def setup_service_event_at_offset_hours(offset_hours: int,
                                        volunteer_slots: int = 4,
                                        clock: str = "2026-05-01T10:00:00Z",
                                        event_type: str = "SERVICE"):
    """Set clock, then create an Event whose starts_at is exactly
    ``offset_hours`` hours after the clock. Returns (event, clock)."""
    from datetime import datetime, timedelta, timezone
    set_clock(clock)
    base = datetime.strptime(clock, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    starts = base + timedelta(hours=offset_hours)
    ends = starts + timedelta(hours=1)
    e = create_event(
        event_type=event_type,
        starts_at=starts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ends_at=ends.strftime("%Y-%m-%dT%H:%M:%SZ"),
        expected_attendance=100, volunteer_slots=volunteer_slots,
    )
    return e, clock
