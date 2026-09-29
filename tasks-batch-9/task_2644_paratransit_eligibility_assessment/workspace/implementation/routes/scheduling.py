"""PRD 3.4-3.5 — slot publication, assessment booking, the provided ride,
attendance, scoring and independent sign-off."""

from datetime import timedelta

from flask import Blueprint

import lookups
import mirrors
import serializers
import shapes
from auth import actor_id, require
from envelope import created, ok
from errors import ApiError
from store import base_record, db, elapsed_days, now, touch

bp = Blueprint("scheduling", __name__)

EVALUATOR_BUFFER = timedelta(minutes=15)
DISTANCE_FLOOR_M = 400
DISTANCE_CEILING_M = 800


# ---------------------------------------------------------------------------
# POST /assessment-slots
# ---------------------------------------------------------------------------

@bp.post("/assessment-slots")
@require(("AccessibilityOfficeAdmin",))
def publish_slot():
    payload = shapes.body()
    site_name = shapes.req_str(payload, "site_name")
    evaluator_user_id = shapes.req_str(payload, "evaluator_user_id")
    starts_at = shapes.req_instant(payload, "starts_at")
    ends_at = shapes.req_instant(payload, "ends_at")
    capacity = shapes.req_int(payload, "capacity", minimum=1)
    accessible = shapes.opt_bool(payload, "site_is_wheelchair_accessible", True)
    if not starts_at < ends_at:
        shapes.bad("starts_at must be strictly earlier than ends_at.")

    # PRD 3.4: the past-start refusal is stated before the turnaround buffer.
    if not starts_at > now():
        raise ApiError("ERR_SLOT_IN_PAST")

    for other in db.slots.values():
        if other["evaluator_user_id"] != evaluator_user_id:
            continue
        if starts_at < other["ends_at"] + EVALUATOR_BUFFER and other["starts_at"] < ends_at + EVALUATOR_BUFFER:
            raise ApiError("ERR_EVALUATOR_SLOT_CONFLICT")

    rec = base_record()
    rec.update(
        {
            "site_name": site_name,
            "site_is_wheelchair_accessible": accessible,
            "evaluator_user_id": evaluator_user_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "capacity": capacity,
            "booked_count": 0,
            "status": "OPEN",
        }
    )
    db.slots[rec["id"]] = rec
    return created(serializers.slot(rec))


# ---------------------------------------------------------------------------
# POST /vehicles
# ---------------------------------------------------------------------------

@bp.post("/vehicles")
@require(("AccessibilityOfficeAdmin",))
def register_vehicle():
    payload = shapes.body()
    vehicle_number = shapes.req_str(payload, "vehicle_number")
    wheelchair_positions = shapes.opt_int(payload, "wheelchair_positions", 0, minimum=0)
    ambulatory_seats = shapes.opt_int(payload, "ambulatory_seats", 0, minimum=0)
    status = shapes.opt_enum(payload, "status", shapes.VEHICLE_STATUSES, "IN_SERVICE")

    rec = base_record()
    rec.update(
        {
            "vehicle_number": vehicle_number,
            "wheelchair_positions": wheelchair_positions,
            "ambulatory_seats": ambulatory_seats,
            "open_wheelchair_reservations": 0,
            "open_ambulatory_reservations": 0,
            "status": status,
        }
    )
    db.vehicles[rec["id"]] = rec
    return created(serializers.vehicle(rec))


# ---------------------------------------------------------------------------
# POST /applications/{id}/assessments
# ---------------------------------------------------------------------------

@bp.post("/applications/<application_id>/assessments")
@require(("IntakeClerk",))
def book_assessment(application_id):
    app_rec = lookups.application(application_id)
    payload = shapes.body()

    slot = None
    if payload.get("slot_id") is not None:
        slot = lookups.slot(payload["slot_id"])
    prior = None
    if payload.get("rescheduled_from_assessment_id") is not None:
        prior = lookups.assessment(payload["rescheduled_from_assessment_id"])

    if slot is None:
        shapes.req_str(payload, "slot_id")
    requires_wheelchair = shapes.opt_bool(payload, "requires_wheelchair_position", False)

    if app_rec["status"] != "ASSESSMENT_REQUIRED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    if slot["booked_count"] >= slot["capacity"]:
        raise ApiError("ERR_SLOT_FULL")
    if not slot["starts_at"] > now():
        raise ApiError("ERR_SLOT_IN_PAST")
    if requires_wheelchair and not slot["site_is_wheelchair_accessible"]:
        raise ApiError("ERR_SITE_NOT_ACCESSIBLE")

    rec = base_record()
    rec.update(
        {
            "application_id": app_rec["id"],
            "slot_id": slot["id"],
            "rescheduled_from_assessment_id": prior["id"] if prior is not None else None,
            "requires_wheelchair_position": requires_wheelchair,
            "attendance_status": "SCHEDULED",
            "scoring_status": "NOT_STARTED",
            "board_alight_score": None,
            "wayfinding_score": None,
            "distance_meters_walked": None,
            "heat_sensitivity_flag": None,
            "evaluator_notes": None,
            "recommended_category": None,
            "recommended_term_days": None,
            "scored_by_user_id": None,
            "signed_off_by_user_id": None,
            "attendance_recorded_at": None,
        }
    )
    db.assessments[rec["id"]] = rec
    mirrors.recompute_slot(slot)

    # PRD 3.2/3.5: a rider's own no-show is charged when the replacement is
    # booked; agency fault is never charged to the rider.
    if prior is not None and prior["attendance_status"] == "NO_SHOW":
        prior_slot = db.slots.get(prior["slot_id"])
        if prior_slot is not None:
            app_rec["applicant_delay_days"] += elapsed_days(
                prior_slot["starts_at"], slot["starts_at"]
            )

    app_rec["status"] = "ASSESSMENT_SCHEDULED"
    touch(app_rec)
    return created(serializers.assessment(rec))


# ---------------------------------------------------------------------------
# POST /transportation-bookings
# ---------------------------------------------------------------------------

def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open intervals: adjacency is never an overlap."""
    return a_start < b_end and b_start < a_end


@bp.post("/transportation-bookings")
@require(("IntakeClerk", "AccessibilityOfficeAdmin"))
def reserve_ride():
    payload = shapes.body()

    assessment = None
    if payload.get("assessment_id") is not None:
        assessment = lookups.assessment(payload["assessment_id"])
    vehicle = None
    if payload.get("vehicle_id") is not None:
        vehicle = lookups.vehicle(payload["vehicle_id"])

    if assessment is None:
        shapes.req_str(payload, "assessment_id")
    if vehicle is None:
        shapes.req_str(payload, "vehicle_id")
    window_start = shapes.req_instant(payload, "pickup_window_start")
    window_end = shapes.req_instant(payload, "pickup_window_end")
    requires_wheelchair = shapes.opt_bool(payload, "requires_wheelchair_position", False)
    if not window_start < window_end:
        shapes.bad("pickup_window_start must be strictly earlier than pickup_window_end.")

    if vehicle["status"] != "IN_SERVICE":
        raise ApiError("ERR_VEHICLE_OUT_OF_SERVICE")
    if requires_wheelchair and vehicle["wheelchair_positions"] < 1:
        raise ApiError("ERR_VEHICLE_NOT_ACCESSIBLE")

    capacity = (
        vehicle["wheelchair_positions"] if requires_wheelchair else vehicle["ambulatory_seats"]
    )
    concurrent = 0
    for other in db.bookings.values():
        if other["vehicle_id"] != vehicle["id"] or other["status"] != "RESERVED":
            continue
        if other["requires_wheelchair_position"] != requires_wheelchair:
            continue
        if _overlaps(
            window_start, window_end, other["pickup_window_start"], other["pickup_window_end"]
        ):
            concurrent += 1
    if concurrent + 1 > capacity:
        raise ApiError("ERR_VEHICLE_WINDOW_CONFLICT")

    slot = db.slots.get(assessment["slot_id"])
    if slot is not None and window_end > slot["starts_at"]:
        raise ApiError("ERR_PICKUP_WINDOW_LATE")

    rec = base_record()
    rec.update(
        {
            "assessment_id": assessment["id"],
            "vehicle_id": vehicle["id"],
            "pickup_window_start": window_start,
            "pickup_window_end": window_end,
            "requires_wheelchair_position": requires_wheelchair,
            "status": "RESERVED",
            "cancelled_reason": None,
        }
    )
    db.bookings[rec["id"]] = rec
    mirrors.recompute_vehicle(vehicle)
    return created(serializers.booking(rec))


# ---------------------------------------------------------------------------
# POST /transportation-bookings/{id}/cancel
# ---------------------------------------------------------------------------

@bp.post("/transportation-bookings/<booking_id>/cancel")
@require(("IntakeClerk", "AccessibilityOfficeAdmin"))
def cancel_booking(booking_id):
    rec = lookups.booking(booking_id)
    payload = shapes.body()
    reason = shapes.req_str(payload, "cancelled_reason")

    if rec["status"] != "RESERVED":
        raise ApiError("ERR_BOOKING_NOT_CANCELLABLE")

    rec["status"] = "CANCELLED"
    rec["cancelled_reason"] = reason
    touch(rec)
    vehicle = db.vehicles.get(rec["vehicle_id"])
    if vehicle is not None:
        mirrors.recompute_vehicle(vehicle)
    return ok(serializers.booking(rec))


# ---------------------------------------------------------------------------
# POST /assessments/{id}/attendance
# ---------------------------------------------------------------------------

def _close_bookings(assessment, new_status):
    """Every booking on this assessment still in RESERVED moves on, each
    releasing exactly the one vehicle counter it consumed."""
    touched_vehicles = set()
    for booking in lookups.bookings_of_assessment(assessment["id"]):
        if booking["status"] != "RESERVED":
            continue
        booking["status"] = new_status
        touch(booking)
        touched_vehicles.add(booking["vehicle_id"])
    for vehicle_id in touched_vehicles:
        vehicle = db.vehicles.get(vehicle_id)
        if vehicle is not None:
            mirrors.recompute_vehicle(vehicle)


@bp.post("/assessments/<assessment_id>/attendance")
@require(("Evaluator", "AccessibilityOfficeAdmin"))
def record_attendance(assessment_id):
    rec = lookups.assessment(assessment_id)
    payload = shapes.body()
    branch = shapes.req_enum(payload, "attendance_status", shapes.ATTENDANCE_BRANCHES)

    if rec["attendance_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")

    slot = db.slots.get(rec["slot_id"])
    if branch in ("ATTENDED", "NO_SHOW"):
        # PRD 3.5: permitted only when the current instant is at or after the
        # slot's starts_at.
        if slot is not None and now() < slot["starts_at"]:
            raise ApiError("ERR_INVALID_ASSESSMENT_STATE")

    rec["attendance_status"] = branch
    rec["attendance_recorded_at"] = now()
    touch(rec)

    if branch == "ATTENDED":
        _close_bookings(rec, "COMPLETED")
    elif branch == "NO_SHOW":
        _close_bookings(rec, "NO_SHOW_CLOSED")
    else:
        _close_bookings(rec, "CANCELLED")

    if slot is not None:
        mirrors.recompute_slot(slot)

    app_rec = db.applications.get(rec["application_id"])
    if app_rec is not None:
        if branch in ("NO_SHOW", "CANCELLED_BY_AGENCY") and app_rec["status"] == "ASSESSMENT_SCHEDULED":
            app_rec["status"] = "ASSESSMENT_REQUIRED"
        touch(app_rec)
    return ok(serializers.assessment(rec))


# ---------------------------------------------------------------------------
# POST /assessments/{id}/scores
# ---------------------------------------------------------------------------

def recommend(board, wayfinding, distance, heat, attests_permanent):
    """PRD 3.5: the first matching rule decides; later rules are not consulted."""
    if attests_permanent is False:
        category = "TEMPORARY"
    elif min(board, wayfinding) <= 1:
        category = "UNCONDITIONAL"
    elif distance < DISTANCE_FLOOR_M and max(board, wayfinding) >= 3:
        category = "CONDITIONAL"
    elif board + wayfinding <= 4:
        category = "UNCONDITIONAL"
    elif distance >= DISTANCE_CEILING_M and heat is False:
        category = "INELIGIBLE"
    else:
        category = "CONDITIONAL"
    return category, mirrors.term_days_for(category)


@bp.post("/assessments/<assessment_id>/scores")
@require(("Evaluator",))
def record_scores(assessment_id):
    rec = lookups.assessment(assessment_id)
    payload = shapes.body()
    board = shapes.req_int(payload, "board_alight_score", minimum=0, maximum=4)
    wayfinding = shapes.req_int(payload, "wayfinding_score", minimum=0, maximum=4)
    distance = shapes.req_int(payload, "distance_meters_walked", minimum=0)
    heat = shapes.req_bool(payload, "heat_sensitivity_flag")
    notes = shapes.opt_str(payload, "evaluator_notes", None)

    if rec["attendance_status"] != "ATTENDED":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")
    if rec["scoring_status"] not in ("NOT_STARTED", "SCORED"):
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")

    app_rec = db.applications.get(rec["application_id"])
    attests_permanent = None if app_rec is None else app_rec["attests_permanent"]
    category, term_days = recommend(board, wayfinding, distance, heat, attests_permanent)

    rec["board_alight_score"] = board
    rec["wayfinding_score"] = wayfinding
    rec["distance_meters_walked"] = distance
    rec["heat_sensitivity_flag"] = heat
    rec["evaluator_notes"] = notes
    rec["recommended_category"] = category
    rec["recommended_term_days"] = term_days
    rec["scoring_status"] = "SCORED"
    rec["scored_by_user_id"] = actor_id()
    touch(rec)
    return ok(serializers.assessment(rec))


# ---------------------------------------------------------------------------
# POST /assessments/{id}/sign-off
# ---------------------------------------------------------------------------

@bp.post("/assessments/<assessment_id>/sign-off")
@require(("EligibilitySpecialist",), identity_required=True)
def sign_off(assessment_id):
    rec = lookups.assessment(assessment_id)
    shapes.body()

    if rec["scoring_status"] != "SCORED":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")
    if actor_id() == rec["scored_by_user_id"]:
        raise ApiError("ERR_SIGNOFF_NOT_INDEPENDENT")

    rec["signed_off_by_user_id"] = actor_id()
    rec["scoring_status"] = "SIGNED_OFF"
    touch(rec)

    app_rec = db.applications.get(rec["application_id"])
    if (
        app_rec is not None
        and app_rec["status"] == "ASSESSMENT_SCHEDULED"
        and rec["attendance_status"] == "ATTENDED"
    ):
        app_rec["status"] = "ASSESSMENT_COMPLETE"
        touch(app_rec)
    return ok(serializers.assessment(rec))
