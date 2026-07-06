"""Config / actor registration, cooler units, and the logical clock."""
from flask import Blueprint

import errors
import lookup
import validate
from clock import parse_iso
from db import db
from middleware import require, json_body
from records import make_record, touch, public
from response import object_response
from services import cooler_occupied_slots

bp = Blueprint("config", __name__)


# ---- Investigators ----
@bp.post("/investigators")
def create_investigator():
    require({"Admin"})
    body = json_body()
    full_name = validate.req_str(body, "full_name")
    badge_no = validate.req_str(body, "badge_no")
    active = validate.opt_bool(body, "active", default=True)

    for rec in db.investigators.values():
        if rec["badge_no"] == badge_no:
            raise errors.err(errors.ERR_DUPLICATE, "badge_no already in use")

    rec = make_record({"full_name": full_name, "badge_no": badge_no, "active": active})
    db.investigators[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/investigators/<id_>")
def get_investigator(id_):
    require({"Admin", "Investigator", "MedicalExaminer"})
    rec = lookup.investigator(id_)
    return object_response(public(rec), 200)


# ---- Pathologists ----
@bp.post("/pathologists")
def create_pathologist():
    require({"Admin"})
    body = json_body()
    full_name = validate.req_str(body, "full_name")
    license_no = validate.req_str(body, "license_no")
    is_me = validate.opt_bool(body, "is_medical_examiner", default=False)

    for rec in db.pathologists.values():
        if rec["license_no"] == license_no:
            raise errors.err(errors.ERR_DUPLICATE, "license_no already in use")

    rec = make_record({"full_name": full_name, "license_no": license_no, "is_medical_examiner": is_me})
    db.pathologists[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/pathologists/<id_>")
def get_pathologist(id_):
    require({"Admin", "Pathologist", "MedicalExaminer", "Investigator"})
    rec = lookup.pathologist(id_)
    return object_response(public(rec), 200)


# ---- Cooler units ----
@bp.post("/cooler-units")
def create_cooler():
    require({"Admin"})
    body = json_body()
    label = validate.req_str(body, "label")
    slot_capacity = validate.req_int(body, "slot_capacity", minimum=1)
    temperature_c = validate.opt_number(body, "temperature_c", default=4)
    out_of_service = validate.opt_bool(body, "out_of_service", default=False)

    for rec in db.cooler_units.values():
        if rec["label"] == label:
            raise errors.err(errors.ERR_DUPLICATE, "label already in use")

    rec = make_record({
        "label": label,
        "slot_capacity": slot_capacity,
        "temperature_c": temperature_c,
        "out_of_service": out_of_service,
        "occupied_slots": 0,
    })
    db.cooler_units[rec["id"]] = rec
    return object_response(_cooler_view(rec), 201)


@bp.get("/cooler-units/<id_>")
def get_cooler(id_):
    require({"Admin", "Investigator"})
    rec = lookup.cooler_unit(id_)
    return object_response(_cooler_view(rec), 200)


@bp.patch("/cooler-units/<id_>")
def patch_cooler(id_):
    require({"Admin"})
    rec = lookup.cooler_unit(id_)
    body = json_body()
    changed = False
    if "out_of_service" in body and body["out_of_service"] is not None:
        rec["out_of_service"] = validate.opt_bool(body, "out_of_service")
        changed = True
    if "temperature_c" in body and body["temperature_c"] is not None:
        rec["temperature_c"] = validate.opt_number(body, "temperature_c")
        changed = True
    if changed:
        touch(rec)
    return object_response(_cooler_view(rec), 200)


@bp.get("/cooler-units/<id_>/occupancy-report")
def occupancy_report(id_):
    require({"Admin", "Investigator"})
    rec = lookup.cooler_unit(id_)
    from services import cooler_occupancy_report
    occupied, total_days = cooler_occupancy_report(rec)
    return object_response({"occupied_slots": occupied, "total_body_days": total_days}, 200)


def _cooler_view(rec):
    view = public(rec)
    view["occupied_slots"] = cooler_occupied_slots(rec["id"])
    return view


# ---- Logical clock ----
@bp.post("/_clock/set_current_utc")
def set_clock():
    require({"Admin"})
    body = json_body()
    to_iso = validate.req_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    db.clock.set(dt)
    from clock import fmt_iso
    return object_response({"current_utc": fmt_iso(dt)}, 200)
