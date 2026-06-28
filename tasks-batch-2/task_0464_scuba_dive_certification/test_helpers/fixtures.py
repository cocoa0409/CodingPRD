"""Composite setup helpers.

Each test runs against a fresh, empty database (the runner restarts the server
before every test). These helpers build the multi-step preconditions the design
instances require, using only PRD-declared endpoints. They use get_success_data()
(lenient) internally so setup failures surface clearly.

Identity threading: Instructor and Diver are entity-backed. Any ownership-gated
call (session complete, booking attend) uses make_instructor_headers(instructor_id)
so X-User-ID equals the real instructor's id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_shop_admin_headers, make_instructor_headers,
)
from . import factories as f

ADMIN = make_shop_admin_headers()


# --- Clock ----------------------------------------------------------------

def set_clock(iso: str):
    """Set the logical clock; returns nothing meaningful."""
    return api_client.set_clock(iso, ADMIN)


# --- Primitive creators (return the entity dict) --------------------------

def create_diver(full_name="Test Diver", email=None, **overrides):
    payload = f.create_diver_payload(full_name=full_name, **overrides)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_diver(payload, ADMIN))


def create_instructor(full_name="Test Instructor", rating="INSTRUCTOR"):
    return get_success_data(
        api_client.create_instructor(
            f.create_instructor_payload(full_name=full_name, rating=rating), ADMIN
        )
    )


def create_course(**overrides):
    return get_success_data(
        api_client.create_course(f.create_course_payload(**overrides), ADMIN)
    )


def create_boat(**overrides):
    return get_success_data(
        api_client.create_boat(f.create_boat_payload(**overrides), ADMIN)
    )


def sign_waiver(diver_id, medical_flagged=False):
    return get_success_data(
        api_client.create_waiver(
            f.create_waiver_payload(diver_id, medical_flagged=medical_flagged), ADMIN
        )
    )


def create_enrollment(diver_id, course_id):
    return get_success_data(
        api_client.create_enrollment(
            f.create_enrollment_payload(diver_id, course_id), ADMIN
        )
    )


def create_session(course_id, instructor_id, **overrides):
    return get_success_data(
        api_client.create_session(
            f.create_session_payload(course_id, instructor_id, **overrides), ADMIN
        )
    )


def create_dive_trip(boat_id, **overrides):
    return get_success_data(
        api_client.create_dive_trip(f.create_dive_trip_payload(boat_id, **overrides), ADMIN)
    )


def create_rental(diver_id, **overrides):
    return get_success_data(
        api_client.create_rental_agreement(
            f.create_rental_agreement_payload(diver_id, **overrides), ADMIN
        )
    )


# --- Tier 1: State progression -------------------------------------------

def create_waiver_cleared_diver(full_name="Cleared Diver", email=None):
    """Register a diver and sign a clean (medical_flagged=false) waiver so the
    diver has medical_status CLEAR. Returns the diver dict."""
    diver = create_diver(full_name=full_name, email=email)
    sign_waiver(diver["id"])
    return diver


def book_seat(session_id, enrollment_id, expected_session_version, headers=None):
    """Create a session booking. Returns the booking dict."""
    return get_success_data(
        api_client.create_session_booking(
            f.create_session_booking_payload(
                session_id, enrollment_id, expected_session_version
            ),
            headers or ADMIN,
        )
    )


def attend_booking(booking_id, instructor_id):
    """Record attendance as the owning instructor (ownership-gated)."""
    return get_success_data(
        api_client.attend_session_booking(
            booking_id, make_instructor_headers(instructor_id)
        )
    )


# --- Tier 3 / Tier 2: full certification lifecycle ------------------------

def attend_one_ow_session(diver_id, course_id, instructor_id,
                          session_starts_at="2026-06-04T08:00:00Z",
                          session_ends_at="2026-06-04T10:00:00Z",
                          attend_clock="2026-06-04T09:00:00Z"):
    """Enroll an already-waivered diver in `course_id`, set e-learning to 100,
    book and attend one OPEN_WATER session led by `instructor_id`.

    Returns (enrollment, session, booking). The caller controls the clock before
    this call (it is left at attend_clock at the end). Does NOT issue a card.
    """
    session = create_session(
        course_id, instructor_id,
        session_type="OPEN_WATER",
        starts_at=session_starts_at, ends_at=session_ends_at,
    )
    enrollment = create_enrollment(diver_id, course_id)
    get_success_data(
        api_client.set_elearning_progress(enrollment["id"], {"elearning_pct": 100}, ADMIN)
    )
    booking = book_seat(session["id"], enrollment["id"], session["version"])
    set_clock(attend_clock)
    attend_booking(booking["id"], instructor_id)
    return enrollment, session, booking


def certify_diver_open_water(diver_full_name="Cert Diver", grants_specialty="NONE",
                             base_clock="2026-06-01T00:00:00Z"):
    """Drive a brand-new diver all the way to a COMPLETED OPEN_WATER enrollment
    with an issued CertificationCard. After this the diver has cert_level
    OPEN_WATER (and nitrox_certified true iff grants_specialty == ENRICHED_AIR).

    Sequence: set clock -> course -> diver -> waiver -> instructor -> session ->
    enroll -> e-learning 100 -> book -> (clock to session day) attend ->
    recompute-eligibility -> issue-certification.

    Returns (diver, course, enrollment, card). Clock is left at the attend day.
    """
    set_clock(base_clock)
    course = create_course(
        title="OW Cert", course_type="OPEN_WATER",
        required_pool_sessions=0, required_open_water_sessions=1,
        price_cents=50000, grants_specialty=grants_specialty,
    )
    diver = create_diver(full_name=diver_full_name)
    sign_waiver(diver["id"])
    instructor = create_instructor(full_name="Cert Instructor")
    enrollment, session, booking = attend_one_ow_session(
        diver["id"], course["id"], instructor["id"]
    )
    enr = get_success_data(api_client.recompute_eligibility(enrollment["id"], ADMIN))
    enr = get_success_data(
        api_client.issue_certification(
            enrollment["id"], {"expected_enrollment_version": enr["version"]}, ADMIN
        )
    )
    cards = get_success_data(
        api_client.list_certification_cards(ADMIN, params={"enrollment_id": enrollment["id"]})
    )
    card = cards[0] if isinstance(cards, list) and cards else None
    return diver, course, enrollment, card


def setup_nitrox_certified_diver(base_clock="2026-06-01T00:00:00Z"):
    """A diver certified OPEN_WATER via a course that grants ENRICHED_AIR, so
    nitrox_certified is true. Returns the diver dict (re-fetched)."""
    diver, _course, _enr, _card = certify_diver_open_water(
        diver_full_name="Nitrox Diver", grants_specialty="ENRICHED_AIR",
        base_clock=base_clock,
    )
    return get_success_data(api_client.get_diver(diver["id"], ADMIN))


# --- Tier 1: enrollment reaching ELIGIBLE (without issuing) ---------------

def setup_eligible_enrollment(course_overrides=None, base_clock="2026-06-01T00:00:00Z"):
    """Build an ELIGIBLE enrollment (all prerequisites met, no card issued yet).

    Default course: ADVANCED, required_pool 0, required_ow 1. Returns
    (diver, course, instructor, enrollment, session, booking). Clock left at the
    attend day (2026-06-04T09:00:00Z).
    """
    set_clock(base_clock)
    overrides = {
        "title": "Adv Cert", "course_type": "ADVANCED",
        "required_pool_sessions": 0, "required_open_water_sessions": 1,
        "price_cents": 60000,
    }
    if course_overrides:
        overrides.update(course_overrides)
    course = create_course(**overrides)
    diver = create_diver(full_name="Eligible Diver")
    sign_waiver(diver["id"])
    instructor = create_instructor(full_name="Eligible Instructor")
    enrollment, session, booking = attend_one_ow_session(
        diver["id"], course["id"], instructor["id"]
    )
    enr = get_success_data(api_client.recompute_eligibility(enrollment["id"], ADMIN))
    return diver, course, instructor, enr, session, booking


# --- Tier 2: trip charter scenario ----------------------------------------

def setup_trip_with_certified_diver(trip_overrides=None,
                                    base_clock="2026-06-01T00:00:00Z",
                                    diver_full_name="Trip Diver"):
    """An OPEN trip on a boat plus one OPEN_WATER-certified, waiver-cleared diver
    ready to book. Returns (boat, trip, diver). Clock left at the cert attend day.
    """
    diver, _course, _enr, _card = certify_diver_open_water(
        diver_full_name=diver_full_name, base_clock=base_clock
    )
    boat = create_boat(name="Charter Boat", capacity=10)
    overrides = {
        "starts_at": "2026-06-20T08:00:00Z", "ends_at": "2026-06-20T12:00:00Z",
        "min_cert_level": "OPEN_WATER", "base_fare_cents": 12000, "fill_addon_cents": 1500,
    }
    if trip_overrides:
        overrides.update(trip_overrides)
    trip = create_dive_trip(boat["id"], **overrides)
    diver = get_success_data(api_client.get_diver(diver["id"], ADMIN))
    return boat, trip, diver
