"""Aircraft registry, grounding/retirement, and maintenance log endpoints."""

import uuid
from fractions import Fraction

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_AIRCRAFT_IN_USE,
    ERR_INVALID_STATE,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UNIQUE_CONSTRAINT,
)
from middleware import auth, require_role
from response import success
from services import (
    apply_annual,
    currency_ok,
    ground_aircraft,
    ser_aircraft,
    ser_maintenance,
    touch,
)
from util import get_body, need, need_dt, need_number, need_str, paginate, sort_items

bp = Blueprint("aircraft", __name__)

KINDS = ("GLIDER", "TOW_PLANE")
MAINT_KINDS = ("INSPECTION_100H", "ANNUAL", "REPAIR")


def _get_aircraft_or_404(aircraft_id):
    aircraft = db.STORE["aircraft"].get(aircraft_id)
    if aircraft is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Aircraft not found")
    return aircraft


@bp.post("/soaring/aircraft")
def create_aircraft():
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    body = get_body()
    registration = need_str(body, "registration")
    kind = need_str(body, "kind")
    annual_due_date = need_dt(body, "annual_due_date")
    if kind not in KINDS:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "kind must be GLIDER or TOW_PLANE",
        )
    for existing in db.STORE["aircraft"].values():
        if existing["registration"] == registration:
            raise ApiError(
                ERR_UNIQUE_CONSTRAINT, 409,
                "registration '%s' already exists" % registration,
            )
    record = {
        "id": str(uuid.uuid4()),
        "registration": registration,
        "kind": kind,
        "status": "AIRWORTHY",
        "total_time_hours": Fraction(0, 1),
        "hours_since_inspection": Fraction(0, 1),
        "annual_due_date": annual_due_date,
        "grounded_reason": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["aircraft"][record["id"]] = record
    return success(ser_aircraft(record), "object", 201)


@bp.get("/soaring/aircraft")
def list_aircraft():
    auth()
    items = list(db.STORE["aircraft"].values())
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind is not None:
        items = [a for a in items if a["kind"] == kind]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(sort_items(items))
    return success([ser_aircraft(a) for a in page], "array", 200, meta)


@bp.get("/soaring/aircraft/<aid>")
def get_aircraft(aid):
    auth()
    return success(ser_aircraft(_get_aircraft_or_404(aid)), "object", 200)


@bp.post("/soaring/aircraft/<aid>/ground")
def ground(aid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    aircraft = _get_aircraft_or_404(aid)
    if aircraft["status"] != "AIRWORTHY":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only an AIRWORTHY airframe can be grounded"
        )
    ground_aircraft(aircraft, "MANUAL")
    return success(ser_aircraft(aircraft), "object", 200)


@bp.post("/soaring/aircraft/<aid>/unground")
def unground(aid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    aircraft = _get_aircraft_or_404(aid)
    if aircraft["status"] != "GROUNDED" or aircraft["grounded_reason"] != "MANUAL":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a manually grounded airframe can be ungrounded directly",
        )
    aircraft["status"] = "AIRWORTHY"
    aircraft["grounded_reason"] = None
    touch(aircraft)
    return success(ser_aircraft(aircraft), "object", 200)


@bp.post("/soaring/aircraft/<aid>/retire")
def retire(aid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    aircraft = _get_aircraft_or_404(aid)
    if aircraft["status"] != "AIRWORTHY":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only an AIRWORTHY airframe can be retired"
        )
    for reservation in db.STORE["reservations"].values():
        if (
            reservation["aircraft_id"] == aid
            and reservation["status"] == "CHECKED_OUT"
        ):
            raise ApiError(
                ERR_AIRCRAFT_IN_USE, 409,
                "A reservation is CHECKED_OUT on this airframe",
            )
    aircraft["status"] = "RETIRED"
    touch(aircraft)
    # Retirement sweep: ALL BOOKED reservations and ALL SCHEDULED tow slots
    # on the airframe cancel, regardless of date.
    for reservation in db.STORE["reservations"].values():
        if reservation["aircraft_id"] == aid and reservation["status"] == "BOOKED":
            reservation["status"] = "CANCELLED"
            touch(reservation)
    for slot in db.STORE["tow_slots"].values():
        if slot["tow_plane_id"] == aid and slot["status"] == "SCHEDULED":
            slot["status"] = "CANCELLED"
            touch(slot)
    return success(ser_aircraft(aircraft), "object", 200)


@bp.post("/soaring/aircraft/<aid>/maintenance-records")
def create_maintenance_record(aid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    aircraft = _get_aircraft_or_404(aid)
    body = get_body()
    kind = need_str(body, "kind")
    if kind not in MAINT_KINDS:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "kind must be INSPECTION_100H, ANNUAL, or REPAIR",
        )
    performed_at = need_dt(body, "performed_at")
    hobbs = need_number(body, "hobbs_hours_at_service")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422, "notes must be a string")
    record = {
        "id": str(uuid.uuid4()),
        "aircraft_id": aid,
        "kind": kind,
        "performed_at": performed_at,
        "hobbs_hours_at_service": hobbs,
        "notes": notes,
        "created_at": db.now(),
        "_seq": db.next_seq(),
    }
    db.STORE["maintenance"][record["id"]] = record
    # Airframe side effects.
    if kind == "INSPECTION_100H":
        aircraft["hours_since_inspection"] = Fraction(0, 1)
    elif kind == "ANNUAL":
        apply_annual(aircraft, performed_at)
    # A logged record that restores currency returns a non-manually grounded
    # airframe to service; MANUAL groundings are not restored by paperwork.
    if kind in ("INSPECTION_100H", "ANNUAL"):
        if (
            aircraft["status"] == "GROUNDED"
            and aircraft["grounded_reason"] != "MANUAL"
            and currency_ok(aircraft, db.now())
        ):
            aircraft["status"] = "AIRWORTHY"
            aircraft["grounded_reason"] = None
        touch(aircraft)
    return success(ser_maintenance(record), "object", 201)


@bp.get("/soaring/aircraft/<aid>/maintenance-records")
def list_maintenance_records(aid):
    auth()
    _get_aircraft_or_404(aid)
    items = [r for r in db.STORE["maintenance"].values() if r["aircraft_id"] == aid]
    page, meta = paginate(sort_items(items))
    return success([ser_maintenance(r) for r in page], "array", 200, meta)
