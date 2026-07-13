"""Congregate meal service days and reservations (OCC, capacity, dual counts)."""
from flask import Blueprint, request

from store import db, base_common, touch
from core import (
    require_actor, authorize, check_ownership, get_body, ok_object, ok_array,
    paginate, req_str, req_int, opt_int, err, parse_dt,
)
from lookups import get_service_day, get_participant, get_reservation
from serializers import ser_service_day, ser_reservation

bp = Blueprint("meals", __name__)


# ----------------------------- MealServiceDay ------------------------------
@bp.post("/meal-service-days")
def create_service_day():
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    body = get_body()
    service_raw = req_str(body, "service_date")
    parse_dt(service_raw, "service_date")
    site_name = req_str(body, "site_name")
    capacity = req_int(body, "capacity", minimum=1)
    rec = base_common()
    rec.update({
        "service_date": service_raw,
        "site_name": site_name,
        "capacity": capacity,
        "reserved_count": 0,
        "served_count": 0,
        "status": "OPEN",
    })
    db.service_days[rec["id"]] = rec
    return ok_object(ser_service_day(rec), 201)


@bp.get("/meal-service-days/<did>")
def get_service_day_route(did):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    return ok_object(ser_service_day(get_service_day(did)))


@bp.post("/meal-service-days/<did>/close")
def close_service_day(did):
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    rec = get_service_day(did)
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an OPEN service day can be closed")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok_object(ser_service_day(rec))


# ----------------------------- MealReservation -----------------------------
@bp.post("/meal-reservations")
def create_reservation():
    actor = require_actor()
    authorize(actor, {"Participant", "Coordinator"})
    body = get_body()
    service_day_id = req_str(body, "service_day_id")
    participant_id = req_str(body, "participant_id")
    contribution = opt_int(body, "suggested_contribution_cents", 0, minimum=0)
    expected_version = req_int(body, "expected_service_day_version")
    check_ownership(actor, participant_id)

    day = get_service_day(service_day_id)
    participant = get_participant(participant_id)

    if expected_version != day["version"]:
        raise err("ERR_STALE_VERSION", "Stale service day version")
    if day["status"] != "OPEN":
        raise err("ERR_SERVICE_DAY_CLOSED", "Service day is not OPEN")
    if participant["status"] != "ACTIVE":
        raise err("ERR_PARTICIPANT_INACTIVE", "Participant is not ACTIVE")
    if day["reserved_count"] >= day["capacity"]:
        raise err("ERR_MEAL_CAPACITY_EXCEEDED", "No seats available")
    for r in db.reservations.values():
        if (r["service_day_id"] == service_day_id
                and r["participant_id"] == participant_id
                and r["status"] in ("CONFIRMED", "CHECKED_IN")):
            raise err("ERR_DUPLICATE_RESERVATION", "Participant already reserved this day")

    rec = base_common()
    rec.update({
        "service_day_id": service_day_id,
        "participant_id": participant_id,
        "suggested_contribution_cents": contribution,
        "status": "CONFIRMED",
    })
    day["reserved_count"] += 1
    touch(day)
    db.reservations[rec["id"]] = rec
    return ok_object(ser_reservation(rec), 201)


@bp.get("/meal-reservations/<rid>")
def get_reservation_route(rid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    return ok_object(ser_reservation(get_reservation(rid)))


@bp.get("/meal-reservations")
def list_reservations():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    rows = list(db.reservations.values())
    args = request.args
    for key in ("service_day_id", "participant_id"):
        if key in args:
            rows = [r for r in rows if r.get(key) == args.get(key)]
    window, page = paginate(rows)
    return ok_array([ser_reservation(r) for r in window], page)


@bp.post("/meal-reservations/<rid>/cancel")
def cancel_reservation(rid):
    actor = require_actor()
    authorize(actor, {"Participant", "Coordinator"})
    rec = get_reservation(rid)
    check_ownership(actor, rec["participant_id"])
    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED reservation can be cancelled")
    rec["status"] = "CANCELLED"
    day = db.service_days.get(rec["service_day_id"])
    if day is not None:
        day["reserved_count"] -= 1
        touch(day)
    touch(rec)
    return ok_object(ser_reservation(rec))


@bp.post("/meal-reservations/<rid>/check-in")
def check_in_reservation(rid):
    actor = require_actor()
    authorize(actor, {"Coordinator"})
    rec = get_reservation(rid)
    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED reservation can be checked in")
    day = db.service_days.get(rec["service_day_id"])
    if day is not None and day["status"] not in ("OPEN", "CLOSED"):
        raise err("ERR_INVALID_STATE", "Service day does not permit check-in")
    rec["status"] = "CHECKED_IN"
    if day is not None:
        day["served_count"] += 1
        touch(day)
    touch(rec)
    return ok_object(ser_reservation(rec))
