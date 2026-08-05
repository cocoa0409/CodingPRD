"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API process before every individual test, so the
database (and the logical clock, which resets to 2026-05-01T00:00:00Z) starts
empty for each test. Every helper rebuilds its preconditions from scratch using
only PRD-declared endpoints and ``get_success_data()`` (lenient 2xx validator),
so setup failures surface as clear "Setup failed" errors.

Identity threading (PRD Section 2.1): the Resident role is entity-backed, so any
resident-owned action (appeal / withdraw-appeal / pay, or resident-authored
create) is issued with ``make_resident_headers(resident_id)``.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    set_clock_payload,
    create_community_payload,
    create_resident_payload,
    create_vehicle_payload,
    create_decal_payload,
    create_pass_payload,
    create_gate_event_payload,
    create_amenity_payload,
    create_reservation_payload,
    create_patrol_payload,
    create_incident_payload,
    create_violation_payload,
)
from .test_users import (
    TEST_USERS,
    make_officer_headers,
    make_resident_headers,
)

ADMIN = TEST_USERS["community_admin_headers"]
OFFICER = TEST_USERS["security_officer_headers"]  # X-User-ID == "off-1"

# The opaque officer id recorded as issued_by_user_id on issued violations.
DEFAULT_ISSUER_ID = "off-1"


# --- Clock primitive (PRD Section 2.4) -----------------------------------

def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# --- Primitive entity builders -------------------------------------------

def create_community(**overrides) -> dict:
    return get_success_data(
        api_client.create_community(create_community_payload(**overrides), ADMIN)
    )


def create_resident(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_resident(
            create_resident_payload(community_id, **overrides), ADMIN
        )
    )


def create_vehicle(resident_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(
            create_vehicle_payload(resident_id, **overrides), ADMIN
        )
    )


def issue_decal(vehicle_id: str, expected_vehicle_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_decal(
            create_decal_payload(vehicle_id, expected_vehicle_version, **overrides), ADMIN
        )
    )


def create_pass(sponsor_resident_id: str, headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_pass(
            create_pass_payload(sponsor_resident_id, **overrides), headers
        )
    )


def authorize_pass(pass_id: str, decision: str = "APPROVED") -> dict:
    return get_success_data(
        api_client.authorize_pass(pass_id, {"decision": decision}, OFFICER)
    )


def record_gate_event(community_id: str, plate_read: str, direction: str = "ENTRY", **overrides) -> dict:
    return get_success_data(
        api_client.create_gate_event(
            create_gate_event_payload(community_id, plate_read, direction, **overrides), OFFICER
        )
    )


def create_amenity(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_amenity(
            create_amenity_payload(community_id, **overrides), ADMIN
        )
    )


def book_reservation(amenity_id: str, resident_id: str, headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(amenity_id, resident_id, **overrides), headers
        )
    )


def transition_reservation(reservation_id: str, to_status: str, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.transition_reservation(reservation_id, {"to_status": to_status}, headers)
    )


def create_patrol(community_id: str, officer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_patrol(
            create_patrol_payload(community_id, officer_id, **overrides), OFFICER
        )
    )


def create_incident(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_incident(
            create_incident_payload(community_id, **overrides), OFFICER
        )
    )


def issue_violation(community_id: str, resident_id: str, issuer_id: str = DEFAULT_ISSUER_ID, **overrides) -> dict:
    """Issue a violation as a SecurityOfficer whose X-User-ID is ``issuer_id``
    (recorded as issued_by_user_id, the segregation-of-duties anchor)."""
    return get_success_data(
        api_client.create_violation(
            create_violation_payload(community_id, resident_id, **overrides),
            make_officer_headers(issuer_id),
        )
    )


def appeal_violation(violation_id: str, resident_id: str, reason: str = None) -> dict:
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(
        api_client.appeal_violation(violation_id, payload, make_resident_headers(resident_id))
    )


def transition_resident(resident_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.transition_resident(resident_id, {"to_status": to_status}, ADMIN)
    )


# --- Composite scenarios --------------------------------------------------

def setup_community_and_resident(resident_overrides=None):
    """Active community + one ACTIVE/GOOD resident. Returns (community, resident)."""
    community = create_community()
    resident = create_resident(community["id"], **(resident_overrides or {}))
    return community, resident


def setup_approved_vendor_pass_onsite(clock_iso="2026-06-01T08:00:00Z",
                                      valid_from="2026-06-01T09:00:00Z",
                                      valid_until="2026-06-01T13:00:00Z",
                                      entry_iso="2026-06-01T10:00:00Z",
                                      visitor_plate="VEND01"):
    """Community + resident + APPROVED VENDOR pass driven ONSITE by an ENTRY read.
    Returns (community, resident, pass_obj)."""
    set_clock(clock_iso)
    community, resident = setup_community_and_resident()
    pass_obj = create_pass(
        resident["id"], pass_type="VENDOR", visitor_name="Ace Plumbing",
        visitor_plate=visitor_plate, valid_from=valid_from, valid_until=valid_until,
        vendor_company="Ace",
    )
    authorize_pass(pass_obj["id"], "APPROVED")
    set_clock(entry_iso)
    record_gate_event(community["id"], visitor_plate, "ENTRY")
    return community, resident, pass_obj


def setup_reservation_checked_in(clock_iso="2026-06-02T08:00:00Z",
                                 amenity_overrides=None,
                                 start_at="2026-06-02T10:00:00Z",
                                 end_at="2026-06-02T12:00:00Z",
                                 party_size=2,
                                 checkin_iso="2026-06-02T10:00:00Z"):
    """Community + resident + amenity + a CHECKED_IN reservation.
    Returns (community, resident, amenity, reservation)."""
    set_clock(clock_iso)
    community, resident = setup_community_and_resident()
    amenity = create_amenity(community["id"], **(amenity_overrides or {}))
    reservation = book_reservation(
        amenity["id"], resident["id"], start_at=start_at, end_at=end_at, party_size=party_size,
    )
    set_clock(checkin_iso)
    reservation = transition_reservation(reservation["id"], "CHECKED_IN")
    return community, resident, amenity, reservation
