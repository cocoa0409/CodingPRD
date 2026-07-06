"""Validation violations and error-catalogue triggers: time windows, party-size
composition, accessibility seats, venue-type, pagination, rental conflict,
accommodation subject coherence, and conditional refund.

Queue B (Corner): sections validations, errors, and the conditional-refund endpoint.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_dome,
    create_open_show,
    create_classroom_program,
    create_registration,
    create_rental_hall,
    create_held_rental,
    create_confirmed_booking,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
PROGRAM = TEST_USERS["program_coordinator_headers"]
EVENTS = TEST_USERS["events_manager_headers"]
CLERK = TEST_USERS["membership_clerk_headers"]
ACCESS = TEST_USERS["accessibility_headers"]


def test_show_invalid_time_window_rejected(api):
    """PRD §3.3: "The end of the window must be strictly after the start, and a window
    where `ends_at` is not strictly after `starts_at` is rejected with
    `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/show_invalid_time_window_rejected
    """
    dome = create_dome(seated_capacity=30, name="Dome DD")
    resp = api.create_show(
        {"venue_id": dome["id"], "title": "BadWindow", "starts_at": "2026-05-15T10:00:00Z",
         "ends_at": "2026-05-15T10:00:00Z", "base_price_cents": 1000}, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value, expected_status=422)


def test_individual_party_size_composition_rejected(api):
    """PRD §3.2: "Tier governs the party composition: an `INDIVIDUAL` card must have a
    `party_size` of exactly 1, while a `FAMILY` or `PATRON` card may name from 1 to 6
    admissions inclusive. A request that violates this composition rule is rejected
    with `ERR_PARTY_SIZE_INVALID`."

    Design: Corner/validations/membership_party_size_invalid_for_individual
    """
    resp = api.create_membership(
        {"primary_member_name": "BadParty", "tier": "INDIVIDUAL", "home_zip": "90210",
         "party_size": 3}, CLERK)
    validate_error(resp, ApiErrorId.ERR_PARTY_SIZE_INVALID.value, expected_status=422)


def test_accessible_seats_request_exceeds_available(api):
    """PRD §3.4: "It is rejected with `ERR_ACCESSIBLE_SEATS_UNAVAILABLE` if the
    `accessible_seats_requested` exceeds the accessible seats still free on the show's
    venue."

    Venue has accessible_seats=1; a hold requesting 2 accessible seats is rejected.

    Design: Corner/validations/accessible_seats_exceed_available
    """
    show = create_open_show(seated_capacity=40, accessible_seats=1, base_price_cents=1000,
                            title="Acc")
    resp = api.create_show_booking(
        {"show_event_id": show["id"], "party_size": 2, "accessible_seats_requested": 2,
         "expected_show_version": show["version"]}, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_ACCESSIBLE_SEATS_UNAVAILABLE.value, expected_status=409)


def test_program_venue_type_mismatch_rejected(api):
    """PRD §3.1: "a program session requires a `CLASSROOM` venue ... A mismatch between
    the requested event and the venue's `venue_type` is rejected with
    `ERR_VENUE_TYPE_MISMATCH`."

    Design: Corner/validations/program_venue_type_mismatch
    """
    dome = create_dome(seated_capacity=30, name="Dome FF")
    resp = api.create_program(
        {"venue_id": dome["id"], "title": "WrongRoom", "program_kind": "CAMP", "min_age": 5,
         "max_age": 12, "starts_at": "2026-08-20T09:00:00Z", "capacity": 5, "tuition_cents": 5000},
        PROGRAM)
    validate_error(resp, ApiErrorId.ERR_VENUE_TYPE_MISMATCH.value, expected_status=422)


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a negative
    `offset`, is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/validations/pagination_limit_out_of_range
    """
    resp = api.list_venues(ADMIN, params={"limit": 500, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value, expected_status=400)


def test_rental_window_overlap_rejected(api):
    """PRD §2.10: "a rental may be held only if its bare window overlaps no other held
    or confirmed rental in the same hall, and an overlap is rejected with
    `ERR_RENTAL_TIME_CONFLICT`."

    A HELD rental 14:00-16:00 and a second rental 15:00-17:00 overlap.

    Design: Corner/errors/rental_time_conflict_overlap
    """
    hall = create_rental_hall(seated_capacity=80, name="Hall HH")
    create_held_rental(hall["id"], guest_count=10, base_rental_cents=30000, host_name="A",
                       starts_at="2026-05-20T14:00:00Z", ends_at="2026-05-20T16:00:00Z")
    r2 = validate_success(api.create_rental(
        {"venue_id": hall["id"], "host_name": "B", "starts_at": "2026-05-20T15:00:00Z",
         "ends_at": "2026-05-20T17:00:00Z", "guest_count": 10, "base_rental_cents": 30000}, EVENTS),
        expected_status=201)
    resp = api.hold_rental(r2["id"], EVENTS)
    validate_error(resp, ApiErrorId.ERR_RENTAL_TIME_CONFLICT.value, expected_status=409)


def test_accommodation_subject_mismatch_rejected(api):
    """PRD §3.9: "Exactly one of the three identifiers must be present and it must
    agree with `subject_type`; a mismatch, a missing identifier, or more than one
    identifier is rejected with `ERR_ACCOMMODATION_SUBJECT_MISMATCH`."

    subject_type SHOW_BOOKING but only a registration_id supplied.

    Design: Corner/errors/accommodation_subject_mismatch
    """
    program = create_classroom_program(capacity=5, tuition_cents=5000, min_age=5, max_age=99,
                                        title="MM")
    reg = create_registration(program["id"], participant_name="Mm", participant_age=10)
    resp = api.create_accommodation(
        {"subject_type": "SHOW_BOOKING", "accommodation_kind": "ASL_INTERPRETER",
         "registration_id": reg["id"]}, ACCESS)
    validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_SUBJECT_MISMATCH.value, expected_status=422)


def test_refund_after_completion_rejected(api):
    """PRD §3.4: "Refunding is the corresponding action for a booking that has already
    been confirmed: refund is permitted only while the booking is `CONFIRMED` and the
    logical clock is still before the linked show's `starts_at`."
    PRD §3.3: "On completion, every booking still merely `HELD` is released to
    `CANCELLED` as a no-show, while every `CONFIRMED` booking stays `CONFIRMED`".

    After the show is completed (clock past ends_at, hence past starts_at), refunding
    the still-CONFIRMED booking violates the clock precondition: ERR_INVALID_STATE.

    Design: Corner/endpoints/refund_action_conditional_before_start
    """
    show = create_open_show(seated_capacity=40, base_price_cents=1000, title="Done",
                            starts_at="2026-04-01T10:00:00Z", ends_at="2026-04-01T11:00:00Z")
    booking = create_confirmed_booking(show["id"], party_size=1)

    validate_success(api.set_clock("2026-04-01T12:00:00Z", ADMIN))
    validate_success(api.complete_show(show["id"], BOX_OFFICE))

    resp = api.refund_show_booking(booking["id"], BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
