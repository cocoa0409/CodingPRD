"""Composite setup helpers.

The test harness restarts the API server before every test, so each test
builds its own preconditions from scratch using only PRD-declared endpoints.
These helpers encapsulate the multi-step chains (tier -> member -> airframe
-> slot -> reservation -> checkout -> flight -> land -> reconcile) so tests
can focus on assertions. All setup calls use the lenient get_success_data()
validator so a failed precondition reports as a clear setup error.

Identity threading (PRD §2.1): Member / DutyOfficer / Instructor / TowPilot
are entity-backed roles, so every ownership-gated call is made with
make_<role>_headers(<member id>); ClubAdmin uses the shared opaque constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_ANNUAL_DUE
from .factories import (
    aircraft_payload,
    availability_payload,
    clock_payload,
    duty_slot_payload,
    flight_payload,
    land_payload,
    maintenance_payload,
    member_payload,
    payment_payload,
    progress_payload,
    reservation_payload,
    tier_payload,
    tow_slot_payload,
)
from .test_users import (
    TEST_USERS,
    make_duty_officer_headers,
    make_instructor_headers,
    make_member_headers,
)

ADMIN = TEST_USERS["club_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators (all return validated response data)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def create_tier(**overrides) -> dict:
    return get_success_data(api_client.create_tier(tier_payload(**overrides), ADMIN))


def create_member(tier_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_member(member_payload(tier_id, **overrides), ADMIN))


def create_aircraft(registration: str, kind: str, annual_due_date: str = DEFAULT_ANNUAL_DUE) -> dict:
    payload = aircraft_payload(
        registration=registration, kind=kind, annual_due_date=annual_due_date
    )
    return get_success_data(api_client.create_aircraft(payload, ADMIN))


def create_tow_slot(
    tow_plane_id: str, tow_pilot_id: str, start_at: str, end_at: str, capacity: int = 4
) -> dict:
    payload = tow_slot_payload(tow_plane_id, tow_pilot_id, start_at, end_at, capacity)
    return get_success_data(api_client.create_tow_slot(payload, ADMIN))


def create_availability(instructor_id: str, start_at: str, end_at: str) -> dict:
    """Publish an OPEN window; the owning Instructor publishes for themselves."""
    payload = availability_payload(instructor_id, start_at, end_at)
    return get_success_data(
        api_client.create_availability(payload, make_instructor_headers(instructor_id))
    )


def create_duty_slot(duty_date: str, member_id: str) -> dict:
    return get_success_data(api_client.create_duty_slot(duty_slot_payload(duty_date, member_id), ADMIN))


def create_progress(student_id: str, instructor_id: str, kind: str) -> dict:
    """Open a PENDING progression record as the endorsing instructor."""
    payload = progress_payload(student_id, instructor_id, kind)
    return get_success_data(
        api_client.create_progress(payload, make_instructor_headers(instructor_id))
    )


def create_maintenance_record(
    aircraft_id: str, kind: str, performed_at: str, hobbs_hours_at_service: float, notes: str = None
) -> dict:
    payload = maintenance_payload(kind, performed_at, hobbs_hours_at_service, notes)
    return get_success_data(api_client.create_maintenance_record(aircraft_id, payload, ADMIN))


def record_payment(member_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.record_payment(member_id, payment_payload(amount_cents), ADMIN)
    )


def close_ops_day() -> dict:
    return get_success_data(api_client.close_ops_day(ADMIN))


# ---------------------------------------------------------------------------
# Tier 0b: fresh reads (used for OCC version capture and post-trigger state)
# ---------------------------------------------------------------------------

def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def get_aircraft(aircraft_id: str) -> dict:
    return get_success_data(api_client.get_aircraft(aircraft_id, ADMIN))


def get_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, ADMIN))


def get_tow_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_tow_slot(slot_id, ADMIN))


def get_flight(flight_id: str) -> dict:
    return get_success_data(api_client.get_flight(flight_id, ADMIN))


def get_duty_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_duty_slot(slot_id, ADMIN))


def get_progress(progress_id: str) -> dict:
    return get_success_data(api_client.get_progress(progress_id, ADMIN))


def get_retrieve(retrieve_id: str) -> dict:
    return get_success_data(api_client.get_retrieve(retrieve_id, ADMIN))


def aircraft_version(aircraft_id: str) -> int:
    return get_aircraft(aircraft_id)["version"]


def tow_slot_version(slot_id: str) -> int:
    return get_tow_slot(slot_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: reservation / flight lifecycle steps
# ---------------------------------------------------------------------------

def book_reservation_raw(
    aircraft_id: str,
    member_id: str,
    start_at: str,
    end_at: str,
    expected_aircraft_version,
    instructor_id: str = None,
):
    """Raw reservation create (returns the Response) for error-path tests."""
    payload = reservation_payload(
        aircraft_id, member_id, start_at, end_at, expected_aircraft_version, instructor_id
    )
    return api_client.create_reservation(payload, make_member_headers(member_id))


def book_reservation(
    aircraft_id: str, member_id: str, start_at: str, end_at: str, instructor_id: str = None
) -> dict:
    """Book a glider as the piloting Member, re-reading the airframe's current
    version so the OCC token (PRD §2.10) is always fresh."""
    version = aircraft_version(aircraft_id)
    resp = book_reservation_raw(
        aircraft_id, member_id, start_at, end_at, version, instructor_id
    )
    return get_success_data(resp)


def checkout_reservation(reservation_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.checkout_reservation(reservation_id, make_member_headers(member_id))
    )


def cancel_reservation_as_member(reservation_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.cancel_reservation(reservation_id, make_member_headers(member_id))
    )


def post_flight_raw(
    reservation_id: str,
    tow_slot_id: str,
    release_altitude_ft: int,
    takeoff_at: str,
    expected_tow_slot_version,
    member_id: str,
):
    """Raw launch posting (returns the Response) for error-path tests."""
    payload = flight_payload(
        reservation_id, tow_slot_id, release_altitude_ft, takeoff_at, expected_tow_slot_version
    )
    return api_client.create_flight(payload, make_member_headers(member_id))


def post_flight(
    reservation_id: str,
    tow_slot_id: str,
    release_altitude_ft: int,
    takeoff_at: str,
    member_id: str,
) -> dict:
    """Post a launch as the piloting Member, re-reading the tow slot's current
    version so the OCC token (PRD §2.10) is always fresh."""
    version = tow_slot_version(tow_slot_id)
    resp = post_flight_raw(
        reservation_id, tow_slot_id, release_altitude_ft, takeoff_at, version, member_id
    )
    return get_success_data(resp)


def land_flight(flight_id: str, landed_at: str, member_id: str) -> dict:
    return get_success_data(
        api_client.land_flight(flight_id, land_payload(landed_at), make_member_headers(member_id))
    )


def reconcile_flight(flight_id: str, officer_id: str) -> dict:
    """Reconcile as a DutyOfficer (entity-backed: any real Member.id)."""
    return get_success_data(
        api_client.reconcile_flight(flight_id, make_duty_officer_headers(officer_id))
    )


def void_flight(flight_id: str, officer_id: str) -> dict:
    return get_success_data(api_client.void_flight(flight_id, make_duty_officer_headers(officer_id)))


def complete_flight(
    member_id: str,
    glider_id: str,
    tow_slot_id: str,
    res_start: str,
    res_end: str,
    takeoff_at: str,
    landed_at: str,
    release_altitude_ft: int = 1500,
    instructor_id: str = None,
    reconcile_officer_id: str = None,
) -> dict:
    """Book -> checkout -> post -> land (-> reconcile). The caller must have
    set the logical clock inside the reservation's checkout window first.
    Returns the final flight representation."""
    reservation = book_reservation(
        glider_id, member_id, res_start, res_end, instructor_id=instructor_id
    )
    checkout_reservation(reservation["id"], member_id)
    flight = post_flight(reservation["id"], tow_slot_id, release_altitude_ft, takeoff_at, member_id)
    landed = land_flight(flight["id"], landed_at, member_id)
    if reconcile_officer_id is not None:
        return reconcile_flight(flight["id"], reconcile_officer_id)
    return landed


# ---------------------------------------------------------------------------
# Tier 2: composite scenarios
# ---------------------------------------------------------------------------

def setup_ops(
    tier_overrides: dict = None,
    slot_start: str = "2026-08-10T08:00:00Z",
    slot_end: str = "2026-08-10T20:00:00Z",
    capacity: int = 4,
    pilot_name: str = "Pilot One",
) -> dict:
    """The common flying-day context: one tier, one pilot member, one tow
    pilot, one glider, one tow plane, and one SCHEDULED tow slot."""
    tier = create_tier(**(tier_overrides or {}))
    pilot = create_member(tier["id"], full_name=pilot_name)
    tow_pilot = create_member(tier["id"], full_name="Tow Pilot", is_tow_pilot=True)
    glider = create_aircraft("N100G", "GLIDER")
    tow_plane = create_aircraft("N200T", "TOW_PLANE")
    slot = create_tow_slot(tow_plane["id"], tow_pilot["id"], slot_start, slot_end, capacity)
    return {
        "tier": tier,
        "pilot": pilot,
        "tow_pilot": tow_pilot,
        "glider": glider,
        "tow_plane": tow_plane,
        "slot": slot,
    }


def setup_checked_out(
    tier_overrides: dict = None,
    slot_start: str = "2026-08-10T08:00:00Z",
    slot_end: str = "2026-08-10T20:00:00Z",
    capacity: int = 4,
    res_start: str = "2026-08-10T09:00:00Z",
    res_end: str = "2026-08-10T17:00:00Z",
    clock: str = "2026-08-10T09:10:00Z",
    instructor_id: str = None,
) -> dict:
    """setup_ops plus a BOOKED-then-CHECKED_OUT reservation for the pilot."""
    ctx = setup_ops(tier_overrides, slot_start, slot_end, capacity)
    set_clock(clock)
    reservation = book_reservation(
        ctx["glider"]["id"], ctx["pilot"]["id"], res_start, res_end, instructor_id=instructor_id
    )
    checkout_reservation(reservation["id"], ctx["pilot"]["id"])
    ctx["reservation"] = reservation
    return ctx


def setup_in_flight(
    tier_overrides: dict = None,
    slot_start: str = "2026-08-10T08:00:00Z",
    slot_end: str = "2026-08-10T20:00:00Z",
    capacity: int = 4,
    res_start: str = "2026-08-10T09:00:00Z",
    res_end: str = "2026-08-10T17:00:00Z",
    clock: str = "2026-08-10T09:10:00Z",
    release_altitude_ft: int = 1500,
    takeoff_at: str = "2026-08-10T10:05:00Z",
) -> dict:
    """setup_checked_out plus a posted IN_FLIGHT launch against the slot."""
    ctx = setup_checked_out(
        tier_overrides, slot_start, slot_end, capacity, res_start, res_end, clock
    )
    flight = post_flight(
        ctx["reservation"]["id"], ctx["slot"]["id"], release_altitude_ft, takeoff_at,
        ctx["pilot"]["id"],
    )
    ctx["flight"] = flight
    return ctx


def setup_reconciled_flight(
    tier_overrides: dict = None,
    slot_start: str = "2026-08-10T08:00:00Z",
    slot_end: str = "2026-08-10T20:00:00Z",
    capacity: int = 4,
    res_start: str = "2026-08-10T09:00:00Z",
    res_end: str = "2026-08-10T17:00:00Z",
    clock: str = "2026-08-10T09:10:00Z",
    release_altitude_ft: int = 1500,
    takeoff_at: str = "2026-08-10T10:05:00Z",
    landed_at: str = "2026-08-10T10:35:00Z",
) -> dict:
    """Full launch-pipeline walk: the flight lands and is reconciled by a
    DutyOfficer, closing the reservation (PRD §3.6)."""
    ctx = setup_in_flight(
        tier_overrides, slot_start, slot_end, capacity, res_start, res_end, clock,
        release_altitude_ft, takeoff_at,
    )
    land_flight(ctx["flight"]["id"], landed_at, ctx["pilot"]["id"])
    flight = reconcile_flight(ctx["flight"]["id"], ctx["tow_pilot"]["id"])
    ctx["flight"] = flight
    return ctx
