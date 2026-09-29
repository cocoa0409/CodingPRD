"""Bookings: request, resource assignment, confirmation, rain diversion,
delivery, no-shows, cancellation and payments."""

from flask import Blueprint

import calc
import derive
import flows
import logical_clock
from envelope import array_response, object_response
from errors import ApiError
from schema import (body_json, find, lookup, opt_id, opt_int, opt_str,
                    pagination, paginate, query_enum, query_str, req_dt,
                    req_int, req_str)
from security import authorize, naturalist_scope, teacher_scope
from store import db, new_entity, public, set_dt, sorted_rows, touch

bp = Blueprint("bookings", __name__)

DELIVERY_STATUSES = ("REQUESTED", "CONFIRMED", "RAIN_DIVERTED", "DELIVERED", "NO_SHOW", "CANCELLED")
FUNDING_STATUSES = ("UNFUNDED", "AID_PENDING", "AID_APPROVED", "INVOICED", "SETTLED", "WRITTEN_OFF")


@bp.post("/bookings")
def create_booking():
    actor = authorize(("BookingCoordinator", "TeacherContact"))
    body = body_json()
    school_id = req_str(body, "school_id")
    offering_id = req_str(body, "offering_id")
    start_raw, start_utc = req_dt(body, "start_utc")
    end_raw, end_utc = req_dt(body, "end_utc")
    student_count = req_int(body, "student_count", 1, 500)
    chaperone_count = req_int(body, "chaperone_count", 0, 200)

    if end_utc <= start_utc:
        raise ApiError("ERR_INVALID_TIME_RANGE")

    school = lookup("school", school_id)
    offering = lookup("offering", offering_id)
    teacher_scope(actor, school["id"])

    if offering["status"] != "PUBLISHED":
        raise ApiError("ERR_OFFERING_NOT_PUBLISHED")
    if school["status"] == "SUSPENDED":
        raise ApiError("ERR_SCHOOL_SUSPENDED")
    if start_utc <= logical_clock.now():
        raise ApiError("ERR_BOOKING_START_IN_PAST")
    if student_count + chaperone_count > offering["max_group_size"]:
        raise ApiError("ERR_GROUP_SIZE_EXCEEDED")

    booking = new_entity()
    booking.update({
        "school_id": school["id"],
        "offering_id": offering["id"],
        "trail_segment_id": None,
        "lead_educator_id": None,
        "animal_id": None,
        "rain_diverted_to_offering_id": None,
        "student_count": student_count,
        "chaperone_count": chaperone_count,
        "required_chaperones": calc.required_chaperones(
            student_count, offering["min_chaperone_ratio_students_per_adult"]
        ),
        "actual_student_count": None,
        "actual_chaperone_count": None,
        "actual_contact_minutes": None,
        "delivery_status": "REQUESTED",
        "funding_status": "UNFUNDED",
        "provisional_gross_fee_cents": 0,
        "final_gross_fee_cents": 0,
        "aid_amount_cents": 0,
        "transport_subsidy_cents": 0,
        "net_due_cents": 0,
        "paid_cents": 0,
        "resource_release_reason": None,
    })
    set_dt(booking, "start_utc", start_raw, start_utc)
    set_dt(booking, "end_utc", end_raw, end_utc)
    db.bookings[booking["id"]] = booking

    gross = calc.booking_fee(student_count, offering, school, False, False)
    booking["provisional_gross_fee_cents"] = gross
    booking["net_due_cents"] = gross
    derive.sync()
    return object_response(public(booking), 201)


@bp.get("/bookings")
def list_bookings():
    authorize(("BookingCoordinator", "EducationDirector", "GrantsOfficer"))
    limit, offset = pagination()
    filters = {
        "school_id": query_str("school_id"),
        "offering_id": query_str("offering_id"),
        "trail_segment_id": query_str("trail_segment_id"),
        "lead_educator_id": query_str("lead_educator_id"),
        "animal_id": query_str("animal_id"),
        "rain_diverted_to_offering_id": query_str("rain_diverted_to_offering_id"),
        "delivery_status": query_enum("delivery_status", DELIVERY_STATUSES),
        "funding_status": query_enum("funding_status", FUNDING_STATUSES),
    }
    rows = sorted_rows(db.bookings.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    actor = authorize(("BookingCoordinator", "EducationDirector", "TeacherContact", "Naturalist"))
    booking = lookup("booking", booking_id)
    teacher_scope(actor, booking["school_id"])
    naturalist_scope(actor, booking.get("lead_educator_id"))
    return object_response(public(booking))


@bp.post("/bookings/<booking_id>/assign-resources")
def assign_resources(booking_id):
    authorize(("BookingCoordinator",))
    body = body_json()
    expected_version = req_int(body, "expected_booking_version")
    trail_id = opt_id(body, "trail_segment_id")
    educator_id = opt_id(body, "lead_educator_id")
    animal_id = opt_id(body, "animal_id")
    booking = lookup("booking", booking_id)

    trail = lookup("trail", trail_id) if trail_id is not None else None
    educator = lookup("educator", educator_id) if educator_id is not None else None
    animal = lookup("animal", animal_id) if animal_id is not None else None

    if booking["delivery_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    if expected_version != booking["version"]:
        raise ApiError("ERR_STALE_BOOKING_VERSION")

    offering = derive.offering_of(booking)
    merged_trail = trail if trail is not None else find("trail", booking.get("trail_segment_id"))
    merged_educator = educator if educator is not None else find("educator", booking.get("lead_educator_id"))
    merged_animal = animal if animal is not None else find("animal", booking.get("animal_id"))

    # the lazy training-expiry sweep runs before any credential check
    flows.lazy_expire_training(merged_educator)

    party = derive.persons(booking)
    flows.resource_battery(offering, merged_educator, merged_animal, merged_trail, party)
    flows.check_season(booking, merged_educator)
    flows.check_educator_conflict(booking, merged_educator)
    flows.check_animal_conflict(booking, merged_animal)
    flows.check_weekly_load(booking, merged_educator, offering)

    if trail is not None:
        booking["trail_segment_id"] = trail["id"]
    if educator is not None:
        booking["lead_educator_id"] = educator["id"]
    if animal is not None:
        booking["animal_id"] = animal["id"]
    touch(booking)
    derive.sync()
    return object_response(public(booking))


@bp.post("/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    authorize(("BookingCoordinator",))
    booking = lookup("booking", booking_id)

    if booking["delivery_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    offering = derive.offering_of(booking)
    school = db.schools.get(booking["school_id"])
    if offering["status"] != "PUBLISHED":
        raise ApiError("ERR_OFFERING_NOT_PUBLISHED")
    if school is not None and school["status"] == "SUSPENDED":
        raise ApiError("ERR_SCHOOL_SUSPENDED")

    trail = find("trail", booking.get("trail_segment_id"))
    educator = find("educator", booking.get("lead_educator_id"))
    animal = find("animal", booking.get("animal_id"))
    party = derive.persons(booking)

    flows.resource_battery(offering, educator, animal, trail, party)
    if booking["chaperone_count"] < calc.required_chaperones(
            booking["student_count"], offering["min_chaperone_ratio_students_per_adult"]):
        raise ApiError("ERR_CHAPERONE_RATIO_UNMET")
    flows.check_welfare_gate(animal, offering)
    flows.check_public_contact(animal, offering)

    if educator is None:
        raise ApiError("ERR_REQUIRED_RESOURCE_MISSING")
    if offering["requires_trail_segment"] and trail is None:
        raise ApiError("ERR_REQUIRED_RESOURCE_MISSING")
    if offering["requires_live_animal"] and animal is None:
        raise ApiError("ERR_REQUIRED_RESOURCE_MISSING")

    if party > offering["max_group_size"]:
        raise ApiError("ERR_GROUP_SIZE_EXCEEDED")
    flows.check_trail_capacity(booking, trail)
    flows.check_trail_weekly_budget(booking, trail)

    booking["delivery_status"] = "CONFIRMED"
    touch(booking)
    derive.sync()
    return object_response(public(booking))


@bp.post("/bookings/<booking_id>/rain-divert")
def rain_divert(booking_id):
    authorize(("BookingCoordinator",))
    body = body_json()
    alternate_id = opt_id(body, "alternate_offering_id")
    opt_str(body, "reason")
    booking = lookup("booking", booking_id)

    if booking["delivery_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    offering = derive.offering_of(booking)
    pool = flows.rain_candidates(booking, offering)
    if alternate_id is not None:
        chosen = None
        for candidate in pool:
            if candidate["id"] == alternate_id:
                chosen = candidate
                break
        if chosen is None:
            raise ApiError("ERR_RAIN_ALTERNATE_NOT_ELIGIBLE")
    else:
        if not pool:
            raise ApiError("ERR_NO_RAIN_ALTERNATE")
        chosen = pool[0]

    booking["delivery_status"] = "RAIN_DIVERTED"
    booking["rain_diverted_to_offering_id"] = chosen["id"]
    booking["trail_segment_id"] = None
    booking["provisional_gross_fee_cents"] = derive.provisional_fee(booking)
    touch(booking)
    derive.sync()
    return object_response(public(booking))


@bp.post("/bookings/<booking_id>/deliver")
def deliver_booking(booking_id):
    actor = authorize(("BookingCoordinator", "Naturalist"))
    body = body_json()
    actual_students = req_int(body, "actual_student_count", 0)
    actual_chaperones = req_int(body, "actual_chaperone_count", 0)
    actual_contact = opt_int(body, "actual_contact_minutes", 0)
    booking = lookup("booking", booking_id)
    naturalist_scope(actor, booking.get("lead_educator_id"))

    if booking["delivery_status"] not in ("CONFIRMED", "RAIN_DIVERTED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    offering = derive.offering_of(booking)
    needed = calc.required_chaperones(
        actual_students, offering["min_chaperone_ratio_students_per_adult"]
    )
    if actual_chaperones < needed:
        raise ApiError("ERR_CHAPERONE_RATIO_UNMET")

    booking["actual_student_count"] = actual_students
    booking["actual_chaperone_count"] = actual_chaperones
    booking["actual_contact_minutes"] = actual_contact if actual_contact is not None else 0
    booking["delivery_status"] = "DELIVERED"
    booking["final_gross_fee_cents"] = derive.final_fee(booking)
    booking["funding_status"] = "INVOICED"
    touch(booking)

    for application in derive.aid_for_booking(booking["id"]):
        if application["status"] in derive.AWARDED:
            application["status"] = "DISBURSED"
            touch(application)

    derive.sync()
    return object_response(public(booking))


@bp.post("/bookings/<booking_id>/no-show")
def no_show(booking_id):
    authorize(("BookingCoordinator",))
    body = body_json()
    opt_str(body, "note")
    booking = lookup("booking", booking_id)

    if booking["delivery_status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    booking["delivery_status"] = "NO_SHOW"
    booking["final_gross_fee_cents"] = calc.NO_SHOW_FEE_CENTS
    booking["net_due_cents"] = calc.NO_SHOW_FEE_CENTS
    booking["funding_status"] = "WRITTEN_OFF"
    booking["resource_release_reason"] = "NO_SHOW"
    flows.revoke_awarded_aid(booking)
    touch(booking)

    derive.sync()
    school = db.schools.get(booking["school_id"])
    if school is not None:
        flows.cascade_school_suspension(school, origin_booking_id=booking["id"])
        derive.sync()
    return object_response(public(booking))


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    actor = authorize(("BookingCoordinator", "TeacherContact"))
    body = body_json()
    opt_str(body, "reason")
    booking = lookup("booking", booking_id)
    teacher_scope(actor, booking["school_id"])

    if booking["delivery_status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    booking["delivery_status"] = "CANCELLED"
    booking["resource_release_reason"] = "CANCELLED_BY_SCHOOL"
    flows.revoke_awarded_aid(booking)
    if booking["funding_status"] == "AID_APPROVED":
        booking["funding_status"] = "UNFUNDED"
    touch(booking)
    derive.sync()
    return object_response(public(booking))


@bp.post("/bookings/<booking_id>/record-payment")
def record_payment(booking_id):
    authorize(("BookingCoordinator",))
    body = body_json()
    amount = req_int(body, "amount_cents", 0)
    booking = lookup("booking", booking_id)

    if booking["funding_status"] != "INVOICED":
        raise ApiError("ERR_INVALID_FUNDING_STATE")
    if amount > booking["net_due_cents"] - booking["paid_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    booking["paid_cents"] = booking["paid_cents"] + amount
    if booking["paid_cents"] >= booking["net_due_cents"]:
        booking["funding_status"] = "SETTLED"
    touch(booking)
    derive.sync()
    return object_response(public(booking))
