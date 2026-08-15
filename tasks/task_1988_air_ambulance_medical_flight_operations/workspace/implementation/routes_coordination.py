"""Bed-to-bed coordination: ground transport legs and bed reservations."""

from flask import Blueprint

import services
from core import (
    ERR_INVALID_STATE, db, fail, get_body, list_response, must_exist,
    ok_object, require_roles, stamp_new, touch, v_dt, v_enum, v_num, v_str,
)
from serialize import ser_bed_reservation, ser_ground_leg

bp = Blueprint("coordination", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

LEG_TYPES = {"ORIGIN", "DESTINATION"}
LEG_STATUSES = {"SCHEDULED", "ENROUTE", "AT_BEDSIDE", "COMPLETED", "CANCELLED"}
BED_TYPES = {"ICU", "CCU", "MED_SURGE", "NICU"}
BED_STATUSES = {"HELD", "CONFIRMED", "RELEASED", "CONSUMED"}
MISSION_TERMINAL = {"COMPLETED", "ABORTED", "CANCELLED"}


@bp.route("/air-ambulance/ground-legs", methods=["POST"])
def create_ground_leg():
    require_roles("Dispatcher")
    body = get_body()
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    if body.get("bed_reservation_id") is not None:
        must_exist(db.bed_reservations, body["bed_reservation_id"], "BedReservation")
    mission_id = v_str(body, "mission_id")
    leg_type = v_enum(body, "leg_type", LEG_TYPES)
    provider = v_str(body, "provider_name")
    pickup_raw, _ = v_dt(body, "scheduled_pickup_iso")
    est_miles = v_num(body, "estimated_ground_miles", required=False,
                      minimum=0, exclusive_min=True)
    bed_id = body.get("bed_reservation_id")
    if bed_id is not None and not isinstance(bed_id, str):
        fail("ERR_VALIDATION", 400, "bed_reservation_id must be a string")
    mission = db.missions[mission_id]
    if mission["status"] in MISSION_TERMINAL:
        fail(ERR_INVALID_STATE, 409,
             "Owning mission %s is terminal" % mission["status"])
    rec = stamp_new({
        "mission_id": mission_id,
        "leg_type": leg_type,
        "provider_name": provider,
        "scheduled_pickup_iso": pickup_raw,
        "estimated_ground_miles": est_miles,
        "bed_reservation_id": bed_id,
        "status": "SCHEDULED",
    })
    db.ground_legs[rec["id"]] = rec
    services.recompute_ground_coordination(mission)
    return ok_object(ser_ground_leg(rec), 201)


@bp.route("/air-ambulance/ground-legs/<rid>", methods=["GET"])
def get_ground_leg(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.ground_legs, rid, "GroundTransportLeg")
    return ok_object(ser_ground_leg(rec))


@bp.route("/air-ambulance/ground-legs", methods=["GET"])
def list_ground_legs():
    require_roles(*ALL_ROLES)
    return list_response(
        db.ground_legs.values(), ser_ground_leg,
        {"mission_id": "mission_id", "bed_reservation_id": "bed_reservation_id",
         "status": "status"},
    )


@bp.route("/air-ambulance/ground-legs/<rid>", methods=["PUT"])
def update_ground_leg(rid):
    require_roles("Dispatcher")
    rec = must_exist(db.ground_legs, rid, "GroundTransportLeg")
    body = get_body()
    target = v_enum(body, "status", LEG_STATUSES)
    current = rec["status"]
    mission = db.missions.get(rec["mission_id"])
    valid = (
        (current == "SCHEDULED" and target == "ENROUTE")
        or (current == "ENROUTE" and target == "AT_BEDSIDE")
        or (current == "AT_BEDSIDE" and target == "COMPLETED")
        or (current in {"SCHEDULED", "ENROUTE"} and target == "CANCELLED")
    )
    if not valid:
        fail(ERR_INVALID_STATE, 409,
             "GroundTransportLeg status %s cannot transition to %s" % (current, target))
    if current == "SCHEDULED" and target == "ENROUTE":
        if mission is None or mission["status"] in MISSION_TERMINAL:
            fail(ERR_INVALID_STATE, 409, "Owning mission is terminal")
    if target == "CANCELLED":
        # shared helper: cancels the leg and releases a linked HELD/CONFIRMED
        # bed on DESTINATION legs (cascade hop 2)
        services.cancel_ground_leg(rec)
    else:
        rec["status"] = target
        touch(rec)
    if mission is not None:
        services.recompute_ground_coordination(mission)
    return ok_object(ser_ground_leg(rec))


@bp.route("/air-ambulance/bed-reservations", methods=["POST"])
def create_bed_reservation():
    require_roles("Dispatcher")
    body = get_body()
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    mission_id = v_str(body, "mission_id")
    facility = v_str(body, "facility_name")
    bed_type = v_enum(body, "bed_type", BED_TYPES)
    hold_raw, _ = v_dt(body, "hold_until_iso")
    mission = db.missions[mission_id]
    if mission["status"] in MISSION_TERMINAL:
        fail(ERR_INVALID_STATE, 409,
             "Owning mission %s is terminal" % mission["status"])
    rec = stamp_new({
        "mission_id": mission_id,
        "facility_name": facility,
        "bed_type": bed_type,
        "hold_until_iso": hold_raw,
        "status": "HELD",
    })
    db.bed_reservations[rec["id"]] = rec
    return ok_object(ser_bed_reservation(rec), 201)


@bp.route("/air-ambulance/bed-reservations/<rid>", methods=["GET"])
def get_bed_reservation(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.bed_reservations, rid, "BedReservation")
    return ok_object(ser_bed_reservation(rec))


@bp.route("/air-ambulance/bed-reservations", methods=["GET"])
def list_bed_reservations():
    require_roles(*ALL_ROLES)
    return list_response(
        db.bed_reservations.values(), ser_bed_reservation,
        {"mission_id": "mission_id", "status": "status"},
    )


@bp.route("/air-ambulance/bed-reservations/<rid>", methods=["PUT"])
def update_bed_reservation(rid):
    require_roles("Dispatcher")
    rec = must_exist(db.bed_reservations, rid, "BedReservation")
    body = get_body()
    target = v_enum(body, "status", BED_STATUSES)
    current = rec["status"]
    valid = (
        (current == "HELD" and target == "CONFIRMED")
        or (current in {"HELD", "CONFIRMED"} and target == "RELEASED")
    )
    if not valid:
        fail(ERR_INVALID_STATE, 409,
             "BedReservation status %s cannot transition to %s" % (current, target))
    rec["status"] = target
    touch(rec)
    return ok_object(ser_bed_reservation(rec))
