"""Student endpoints (PRD §3.2)."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_REFERENCE, ERR_DUPLICATE, ERR_FORBIDDEN,
)
from services import validate as v
from services.common import (
    stamp_create, parse_pagination, sorted_by_creation, paginate,
)
from services.calc import home_distance_miles
from services.domain import student_public
from services.lookup import get_student

bp = Blueprint("students", __name__)


@bp.post("/students")
def create_student():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    body = v.get_body()

    district_id = v.require_str(body, "district_id")
    parent_id = v.require_str(body, "parent_id")
    full_name = v.require_str(body, "full_name")
    grade = v.require_int(body, "grade")
    if grade < 0 or grade > 12:
        raise err(ERR_INVALID_REQUEST, "grade must be between 0 and 12")
    home_lat = v.require_number(body, "home_lat")
    home_lng = v.require_number(body, "home_lng")
    rfid_uid = v.require_str(body, "rfid_uid")
    hazard_zone = v.optional_bool(body, "hazard_zone", False)
    special_needs = v.optional_bool(body, "special_needs", False)

    # Parent ownership: a Parent may only register their own student.
    if p.role == "Parent" and parent_id != p.user_id:
        raise err(ERR_FORBIDDEN, "Parent may only register their own student")

    # Body FK resolution — priority 5.
    district = DB.districts.get(district_id)
    if district is None:
        raise err(ERR_INVALID_REFERENCE, "district_id does not resolve")

    # rfid_uid unique within the District — priority 6.
    for s in DB.students.values():
        if s["district_id"] == district_id and s["rfid_uid"] == rfid_uid:
            raise err(ERR_DUPLICATE, "rfid_uid already used in this District")

    home_dist = home_distance_miles(
        home_lat, home_lng, district["school_lat"], district["school_lng"])

    rec = {
        "district_id": district_id,
        "parent_id": parent_id,
        "full_name": full_name,
        "grade": grade,
        "home_lat": home_lat,
        "home_lng": home_lng,
        "hazard_zone": hazard_zone,
        "special_needs": special_needs,
        "rfid_uid": rfid_uid,
        "home_distance_miles": home_dist,
    }
    stamp_create(rec)
    DB.students[rec["id"]] = rec
    return ok(student_public(rec), 201)


@bp.get("/students/<student_id>")
def get_student_ep(student_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    rec = get_student(student_id)
    if p.role == "Parent" and rec["parent_id"] != p.user_id:
        raise err(ERR_FORBIDDEN, "Parent may only read their own student")
    return ok(student_public(rec), 200)


@bp.get("/students")
def list_students():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    limit, offset = parse_pagination(request.args)

    district_id = request.args.get("district_id")
    parent_id = request.args.get("parent_id")

    records = list(DB.students.values())
    if district_id is not None:
        records = [s for s in records if s["district_id"] == district_id]
    if parent_id is not None:
        records = [s for s in records if s["parent_id"] == parent_id]
    if p.role == "Parent":
        records = [s for s in records if s["parent_id"] == p.user_id]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([student_public(s) for s in page], limit, offset, total)
