"""Composite setup helpers.

Each helper builds a multi-step precondition state from scratch using only
PRD-declared endpoints, returning the captured resources tests need. All setup
calls go through get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup failed" rather than an opaque assertion.

The test harness restarts the server (empty database) before every test, so
every helper here builds its world from nothing. Self-service writes in setup
(signups, reservations, transport requests) are performed as a Coordinator,
which the PRD authorizes to act on any participant's behalf, so no entity-backed
ownership identity is required for setup plumbing.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F


# Convenience header aliases (opaque roles use shared constants).
ADMIN = TEST_USERS["center_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + single-entity building blocks
# ---------------------------------------------------------------------------
def set_clock(iso="2026-03-01T00:00:00Z"):
    """Pin the logical clock (PRD 2.8). Tests that touch temporal windows or age
    should set it explicitly before creating time-bound resources."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


def create_participant(**overrides) -> dict:
    return get_success_data(
        api_client.create_participant(F.create_participant_payload(**overrides), ADMIN)
    )


def create_grant(**overrides) -> dict:
    """Create a grant award; it opens in DRAFT (PRD 3.2)."""
    return get_success_data(
        api_client.create_grant(F.create_grant_payload(**overrides), ADMIN)
    )


def activate_grant(grant_id) -> dict:
    return get_success_data(api_client.activate_grant(grant_id, ADMIN))


def suspend_grant(grant_id) -> dict:
    return get_success_data(api_client.suspend_grant(grant_id, ADMIN))


def create_active_grant(**overrides) -> dict:
    """Create and activate a grant; returns the ACTIVE grant (version advanced)."""
    grant = create_grant(**overrides)
    return activate_grant(grant["id"])


def create_donation(**overrides) -> dict:
    return get_success_data(
        api_client.create_donation(F.create_donation_payload(**overrides), ADMIN)
    )


def grant_version(grant_id) -> int:
    return get_success_data(api_client.get_grant(grant_id, ADMIN))["version"]


def fund_service(
    participant_id,
    grant_id,
    category="WELLNESS",
    quantity=1,
    donation_id=None,
    service_date="2026-03-02T00:00:00Z",
    expected_version=None,
) -> dict:
    """Record one APPLIED funded service, running the funding waterfall (PRD 3.3).
    Reads the grant's current version for the OCC field when not supplied."""
    if expected_version is None:
        expected_version = grant_version(grant_id)
    payload = F.create_funded_service_payload(
        participant_id=participant_id,
        category=category,
        quantity=quantity,
        grant_award_id=grant_id,
        service_date=service_date,
        expected_grant_award_version=expected_version,
    )
    if donation_id is not None:
        payload["donation_id"] = donation_id
    return get_success_data(api_client.create_funded_service(payload, COORD))


def reverse_service(fs_id) -> dict:
    return get_success_data(api_client.reverse_funded_service(fs_id, COORD))


def create_room(**overrides) -> dict:
    return get_success_data(
        api_client.create_room(F.create_room_payload(**overrides), ADMIN)
    )


def create_vehicle(**overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(F.create_vehicle_payload(**overrides), ADMIN)
    )


def create_session(room_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_session(
            F.create_session_payload(room_id=room_id, **overrides), COORD
        )
    )


def cancel_session(session_id) -> dict:
    return get_success_data(api_client.cancel_session(session_id, COORD))


def create_signup(session_id, participant_id, headers=COORD) -> dict:
    return get_success_data(
        api_client.create_signup(
            F.create_signup_payload(session_id=session_id, participant_id=participant_id),
            headers,
        )
    )


def create_transport(participant_id, vehicle_id, linked_session_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_transport(
            F.create_transport_payload(
                participant_id=participant_id,
                vehicle_id=vehicle_id,
                linked_session_id=linked_session_id,
                **overrides,
            ),
            COORD,
        )
    )


def approve_transport(transport_id) -> dict:
    return get_success_data(api_client.approve_transport(transport_id, COORD))


def complete_transport(transport_id) -> dict:
    return get_success_data(api_client.complete_transport(transport_id, COORD))


def create_meal_day(**overrides) -> dict:
    return get_success_data(
        api_client.create_meal_day(F.create_meal_day_payload(**overrides), ADMIN)
    )


def close_meal_day(day_id) -> dict:
    return get_success_data(api_client.close_meal_day(day_id, ADMIN))


def day_version(day_id) -> int:
    return get_success_data(api_client.get_meal_day(day_id, ADMIN))["version"]


def reserve_meal(
    day_id, participant_id, contribution_cents=None, expected_version=None, headers=COORD
) -> dict:
    """Reserve a congregate meal seat (PRD 3.6). Reads the day's current version
    for the OCC field when not supplied, so back-to-back reservations thread the
    version automatically."""
    if expected_version is None:
        expected_version = day_version(day_id)
    payload = F.create_reservation_payload(
        service_day_id=day_id,
        participant_id=participant_id,
        expected_service_day_version=expected_version,
    )
    if contribution_cents is not None:
        payload["suggested_contribution_cents"] = contribution_cents
    return get_success_data(api_client.create_reservation(payload, headers))


def cancel_reservation(reservation_id, headers=COORD) -> dict:
    return get_success_data(api_client.cancel_reservation(reservation_id, headers))


def check_in(reservation_id) -> dict:
    return get_success_data(api_client.check_in_reservation(reservation_id, COORD))


def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(F.create_program_payload(**overrides), COORD)
    )


def enroll(program_id, participant_id) -> dict:
    return get_success_data(
        api_client.create_enrollment(
            F.create_enrollment_payload(program_id=program_id, participant_id=participant_id),
            COORD,
        )
    )


def log_session(enrollment_id, attended) -> dict:
    return get_success_data(api_client.log_session(enrollment_id, attended, COORD))


def finalize(enrollment_id) -> dict:
    return get_success_data(api_client.finalize_enrollment(enrollment_id, COORD))


def create_volunteer_shift(**overrides) -> dict:
    return get_success_data(
        api_client.create_volunteer_shift(
            F.create_volunteer_shift_payload(**overrides), ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: composite scenarios shared across several tests
# ---------------------------------------------------------------------------
def setup_active_grant_with_funded_service(
    authorized_cents=2000,
    category="WELLNESS",
    quantity=1,
    donation_amount_cents=None,
    donation_category="WELLNESS",
    service_date="2026-03-02T00:00:00Z",
) -> dict:
    """Participant + ACTIVE grant + one APPLIED FundedService that draws on the
    grant (and optionally a donation). Returns dict with keys participant, grant,
    donation (or None), funded_service. Underpins the grant-suspend cascade,
    funds-conservation reverse, and already-reversed idempotency tests."""
    participant = create_participant()
    grant = create_active_grant(category=category, authorized_cents=authorized_cents)
    donation = None
    donation_id = None
    if donation_amount_cents is not None:
        donation = create_donation(
            category=donation_category, amount_cents=donation_amount_cents
        )
        donation_id = donation["id"]
    fs = fund_service(
        participant["id"],
        grant["id"],
        category=category,
        quantity=quantity,
        donation_id=donation_id,
        service_date=service_date,
    )
    return {
        "participant": participant,
        "grant": grant,
        "donation": donation,
        "funded_service": fs,
    }


def setup_meal_day_with_reservations(
    capacity=10, num_confirmed=1, num_checked_in=0
) -> dict:
    """OPEN meal service day with (num_confirmed + num_checked_in) reservations,
    each by a distinct participant; the first num_checked_in of them are moved to
    CHECKED_IN. Returns dict with keys day, participants, reservations. Underpins
    the provisional/final variant, seat-conservation, and deactivate-cascade
    tests. Version is threaded automatically by reserve_meal()."""
    day = create_meal_day(capacity=capacity)
    total = num_confirmed + num_checked_in
    participants = [create_participant() for _ in range(total)]
    reservations = [reserve_meal(day["id"], p["id"]) for p in participants]
    for res in reservations[:num_checked_in]:
        check_in(res["id"])
    return {"day": day, "participants": participants, "reservations": reservations}


def setup_scheduled_transport(
    session_starts="2026-03-18T13:00:00Z",
    session_ends="2026-03-18T15:00:00Z",
    trip_starts="2026-03-18T12:00:00Z",
    trip_ends="2026-03-18T12:45:00Z",
) -> dict:
    """Participant, room, vehicle, a SCHEDULED activity session, and a
    PENDING/SCHEDULED transportation request linked to it. Returns dict with keys
    participant, room, vehicle, session, transport."""
    participant = create_participant()
    room = create_room(capacity=20)
    vehicle = create_vehicle(seat_capacity=8)
    session = create_session(
        room["id"], starts_at=session_starts, ends_at=session_ends, capacity=20
    )
    transport = create_transport(
        participant["id"], vehicle["id"], session["id"],
        starts_at=trip_starts, ends_at=trip_ends,
    )
    return {
        "participant": participant,
        "room": room,
        "vehicle": vehicle,
        "session": session,
        "transport": transport,
    }


def setup_enrollment(total_sessions=6, fidelity_min_sessions=5, model="ENHANCE_FITNESS") -> dict:
    """Participant + wellness program + a fresh ACTIVE enrollment. Returns dict
    with keys participant, program, enrollment."""
    participant = create_participant()
    program = create_program(
        total_sessions=total_sessions,
        fidelity_min_sessions=fidelity_min_sessions,
        model=model,
    )
    enrollment = enroll(program["id"], participant["id"])
    return {"participant": participant, "program": program, "enrollment": enrollment}
