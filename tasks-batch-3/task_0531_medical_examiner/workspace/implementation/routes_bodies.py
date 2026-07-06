"""Body intake, storage, release, list/get."""
from flask import Blueprint, request

import errors
import lookup
import validate
from db import db
from middleware import require, json_body, paginate
from records import make_record, touch, public
from response import object_response, array_response
import services

bp = Blueprint("bodies", __name__)


def _body_view(rec):
    return public(rec)


@bp.post("/cases/<case_id>/bodies")
def intake_body(case_id):
    require({"Investigator"})
    case = lookup.case(case_id)
    body = json_body()
    tag_no = validate.req_str(body, "tag_no")

    # A declined case is a dead end (priority 22, ERR_CASE_DECLINED).
    if case["status"] == "DECLINED":
        raise errors.err(errors.ERR_CASE_DECLINED, "Case is declined")
    # state: first body intake requires ACCEPTED
    if case["status"] != "ACCEPTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Body intake requires case ACCEPTED")

    # duplicate tag_no (priority 61)
    for b in db.bodies.values():
        if b["tag_no"] == tag_no:
            raise errors.err(errors.ERR_DUPLICATE, "tag_no already in use")

    rec = make_record({
        "case_id": case_id,
        "tag_no": tag_no,
        "cooler_unit_id": None,
        "storage_status": "INTAKE",
        "intake_at": None,
        "released_at": None,
        "release_blocked": False,
    })
    db.bodies[rec["id"]] = rec

    # cascade Case ACCEPTED -> INVESTIGATING (first body intake)
    case["status"] = "INVESTIGATING"
    touch(case)

    return object_response(_body_view(rec), 201)


@bp.get("/cases/<case_id>/bodies")
def list_case_bodies(case_id):
    require({"Admin", "Investigator", "MedicalExaminer"})
    lookup.case(case_id)
    rows = services.case_bodies(case_id)
    page, limit, offset, total = paginate(rows)
    return array_response([_body_view(b) for b in page], limit, offset, total)


@bp.get("/bodies/<id_>")
def get_body(id_):
    require({"Admin", "Investigator", "MedicalExaminer"})
    rec = lookup.body(id_)
    return object_response(_body_view(rec), 200)


@bp.get("/bodies")
def list_bodies():
    require({"Admin", "Investigator"})
    rows = list(db.bodies.values())
    cooler = request.args.get("cooler_unit_id")
    if cooler is not None:
        rows = [b for b in rows if b.get("cooler_unit_id") == cooler]
    page, limit, offset, total = paginate(rows)
    return array_response([_body_view(b) for b in page], limit, offset, total)


@bp.post("/bodies/<id_>/store")
def store_body(id_):
    require({"Investigator"})
    rec = lookup.body(id_)
    body = json_body()
    cooler_unit_id = validate.req_str(body, "cooler_unit_id")
    if "expected_cooler_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing expected_cooler_version")
    expected_cooler_version = validate.req_int(body, "expected_cooler_version")

    # existence of the referenced cooler (priority 20)
    cooler = lookup.cooler_unit(cooler_unit_id)

    # state legality (priority 21)
    if rec["storage_status"] != "INTAKE":
        raise errors.err(errors.ERR_INVALID_STATE, "Body store only allowed from INTAKE")

    # out-of-service (priority 31)
    if cooler["out_of_service"]:
        raise errors.err(errors.ERR_COOLER_OUT_OF_SERVICE, "Cooler is out of service")

    # capacity (priority 30)
    occupied = services.cooler_occupied_slots(cooler["id"])
    if occupied >= cooler["slot_capacity"]:
        raise errors.err(errors.ERR_COOLER_FULL, "Cooler has no free slot")

    # OCC on cooler (priority 50) — evaluated last among business rules
    if expected_cooler_version != cooler["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale cooler version")

    rec["cooler_unit_id"] = cooler["id"]
    rec["storage_status"] = "STORED"
    rec["intake_at"] = db.clock.now_iso()
    rec["release_blocked"] = True
    touch(rec)

    # recompute cooler occupied_slots and bump its version
    cooler["occupied_slots"] = services.cooler_occupied_slots(cooler["id"])
    touch(cooler)

    return object_response(_body_view(rec), 200)


@bp.post("/bodies/<id_>/release")
def release_body(id_):
    require({"Investigator"})
    rec = lookup.body(id_)

    if rec["storage_status"] != "STORED":
        raise errors.err(errors.ERR_INVALID_STATE, "Body release only allowed from STORED")
    if rec["release_blocked"]:
        raise errors.err(errors.ERR_RELEASE_BLOCKED, "Body release is blocked")

    former_cooler_id = rec.get("cooler_unit_id")
    rec["storage_status"] = "RELEASED"
    rec["released_at"] = db.clock.now_iso()
    rec["cooler_unit_id"] = None
    touch(rec)

    if former_cooler_id and former_cooler_id in db.cooler_units:
        cooler = db.cooler_units[former_cooler_id]
        cooler["occupied_slots"] = services.cooler_occupied_slots(cooler["id"])
        touch(cooler)

    return object_response(_body_view(rec), 200)
