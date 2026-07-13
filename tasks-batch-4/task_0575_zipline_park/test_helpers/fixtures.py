"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints,
using the lenient get_success_data() validator so setup failures surface clearly.
The test harness restarts the server (empty DB) before every individual test, so
nothing is carried over between tests.

All staffing / configuration steps run as Operator (opaque identity). Ownership-
gated Customer actions are threaded through make_customer_headers(participant_id)
by the individual tests that exercise them.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS
from .factories import (
    create_course_payload, create_time_slot_payload, create_guide_payload,
    create_guide_assignment_payload, create_participant_payload,
    create_waiver_payload, create_season_pass_payload, create_group_payload,
    create_booking_payload, create_gear_item_payload, create_gear_checkout_payload,
)
from .constants import WEEKDAY_SLOT_START

OP = TEST_USERS["operator_headers"]


def _data(resp):
    return get_success_data(resp)


# --- Logical clock -------------------------------------------------------
def set_clock(api, iso):
    return _data(api.set_clock(iso, OP))


# --- Single-entity creators ----------------------------------------------
def create_course(api, **overrides):
    return _data(api.create_course(create_course_payload(**overrides), OP))


def create_time_slot(api, course_id, start_at=WEEKDAY_SLOT_START, capacity=None):
    return _data(api.create_time_slot(
        create_time_slot_payload(course_id, start_at, capacity=capacity), OP))


def create_guide(api, name="G1", certification_level=3):
    return _data(api.create_guide(
        create_guide_payload(name=name, certification_level=certification_level), OP))


def assign_guide(api, guide_id, time_slot_id):
    return _data(api.create_guide_assignment(
        create_guide_assignment_payload(guide_id, time_slot_id), OP))


def create_participant(api, full_name="P A", weight_kg=70,
                       birthdate="2000-01-01T00:00:00Z"):
    return _data(api.create_participant(
        create_participant_payload(full_name=full_name, weight_kg=weight_kg,
                                   birthdate=birthdate), OP))


def get_participant(api, participant_id):
    return _data(api.get_participant(participant_id, OP))


def sign_waiver(api, participant_id, signature_name="P A"):
    return _data(api.sign_waiver(
        participant_id, create_waiver_payload(signature_name=signature_name), OP))


def create_season_pass(api, participant_id, total_uses=5, tier="STANDARD",
                       valid_from=None, valid_until="2026-12-31T23:59:59Z",
                       expected_version=None):
    """Issue a pass. Reads the participant's current version unless one is given."""
    if expected_version is None:
        expected_version = get_participant(api, participant_id)["version"]
    kwargs = dict(expected_participant_version=expected_version, tier=tier,
                  total_uses=total_uses, valid_until=valid_until)
    if valid_from is not None:
        kwargs["valid_from"] = valid_from
    return _data(api.create_season_pass(
        participant_id, create_season_pass_payload(**kwargs), OP))


def create_group(api, time_slot_id, expected_size=2, name="Team"):
    return _data(api.create_group(
        create_group_payload(time_slot_id, expected_size=expected_size, name=name), OP))


def create_booking(api, time_slot_id, participant_id, group_id=None,
                   use_season_pass=None):
    return _data(api.create_booking(
        create_booking_payload(time_slot_id, participant_id, group_id=group_id,
                               use_season_pass=use_season_pass), OP))


def create_gear_item(api, gear_type="HARNESS", size="M"):
    return _data(api.create_gear_item(
        create_gear_item_payload(gear_type=gear_type, size=size), OP))


def checkout_gear(api, gear_item_id, booking_id):
    return _data(api.create_gear_checkout(
        create_gear_checkout_payload(gear_item_id, booking_id), OP))


# --- Reads ---------------------------------------------------------------
def get_time_slot(api, ts_id):
    return _data(api.get_time_slot(ts_id, OP))


def get_booking(api, booking_id):
    return _data(api.get_booking(booking_id, OP))


def get_group(api, group_id):
    return _data(api.get_group(group_id, OP))


def get_gear_item(api, gi_id):
    return _data(api.get_gear_item(gi_id, OP))


def get_gear_checkout(api, co_id):
    return _data(api.get_gear_checkout(co_id, OP))


def list_season_passes(api, participant_id):
    return _data(api.list_season_passes(participant_id, OP))


# --- Composite setups ----------------------------------------------------
def setup_course_slot_guide(api, capacity=None, start_at=WEEKDAY_SLOT_START,
                            course_overrides=None):
    """Course + one TimeSlot + one certified Guide ASSIGNED to the slot.

    Returns (course, time_slot, guide). The slot is left SCHEDULED.
    """
    course = create_course(api, **(course_overrides or {}))
    ts = create_time_slot(api, course["id"], start_at=start_at, capacity=capacity)
    guide = create_guide(api)
    assign_guide(api, guide["id"], ts["id"])
    return course, ts, guide


def setup_open_slot(api, capacity=None, start_at=WEEKDAY_SLOT_START,
                    course_overrides=None):
    """Course + slot + assigned guide, with the slot advanced to OPEN.

    Returns (course, time_slot, guide).
    """
    course, ts, guide = setup_course_slot_guide(
        api, capacity=capacity, start_at=start_at, course_overrides=course_overrides)
    _data(api.open_time_slot(ts["id"], OP))
    ts = get_time_slot(api, ts["id"])
    return course, ts, guide


def setup_participant_with_waiver(api, full_name="P A", weight_kg=70,
                                  birthdate="2000-01-01T00:00:00Z"):
    """Register a participant and sign their waiver. Returns the signed participant."""
    p = create_participant(api, full_name=full_name, weight_kg=weight_kg,
                           birthdate=birthdate)
    return sign_waiver(api, p["id"], signature_name=full_name)


def setup_booking_completed(api):
    """Drive one booking all the way to COMPLETED on an OPEN slot.

    Course + slot(OPEN) + guide + participant(waiver signed) + booking, then
    check-in -> brief -> complete. Returns (course, time_slot, guide, participant,
    booking) where booking is the COMPLETED booking.
    """
    course, ts, guide = setup_open_slot(api)
    p = setup_participant_with_waiver(api)
    booking = create_booking(api, ts["id"], p["id"])
    _data(api.checkin_booking(booking["id"], OP))
    _data(api.brief_booking(booking["id"], OP))
    booking = _data(api.complete_booking(booking["id"], OP))
    return course, ts, guide, p, booking


def setup_rainchecked_booking(api, start_at=WEEKDAY_SLOT_START):
    """A booking taken to RAINCHECKED via weather close (full credit stamped).

    Course + slot + guide + participant + CONFIRMED booking, then weather-close the
    slot. Returns (course, time_slot, guide, participant, booking) with booking now
    RAINCHECKED.
    """
    course, ts, guide = setup_course_slot_guide(api, start_at=start_at)
    p = create_participant(api)
    booking = create_booking(api, ts["id"], p["id"])
    _data(api.close_time_slot(ts["id"], OP, reason="storm"))
    booking = get_booking(api, booking["id"])
    return course, ts, guide, p, booking
