from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok
from serializers import ser_pole
from validators import (body, req_field, opt_field, as_str, as_int, as_num,
                        as_bool, as_enum, as_date_str)

bp = Blueprint("poles", __name__)

SPECIES = ["SOUTHERN_PINE", "DOUGLAS_FIR", "WESTERN_RED_CEDAR", "LARCH"]
POLE_CLASSES = ["H1", "1", "2", "3", "4", "5"]


@bp.post("/pole-program/poles")
@locked
def create_pole():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    pole_number = as_str(req_field(d, "pole_number"), "pole_number", non_empty=True)
    species = as_enum(req_field(d, "species"), "species", SPECIES)
    original_class = as_enum(req_field(d, "original_class"), "original_class",
                             POLE_CLASSES)
    install_date = as_date_str(req_field(d, "install_date"), "install_date")
    gis_lat = as_num(req_field(d, "gis_lat"), "gis_lat")
    gis_lon = as_num(req_field(d, "gis_lon"), "gis_lon")
    gis_tag = as_str(req_field(d, "gis_tag"), "gis_tag")
    height_ft = as_num(req_field(d, "height_ft"), "height_ft", 0,
                       min_exclusive=True)
    joint_use = opt_field(d, "joint_use", False)
    as_bool(joint_use, "joint_use")
    attachment_count_declared = opt_field(d, "attachment_count_declared", 0)
    as_int(attachment_count_declared, "attachment_count_declared", 0)
    if any(p["pole_number"] == pole_number for p in db.poles.values()):
        raise ApiError("ERR_DUPLICATE_POLE_NUMBER", 409,
                       "pole_number already registered")
    rec = db.new_record()
    rec.update(
        pole_number=pole_number, species=species, original_class=original_class,
        install_date=install_date, gis_lat=gis_lat, gis_lon=gis_lon,
        gis_tag=gis_tag, height_ft=height_ft, joint_use=joint_use,
        attachment_count_declared=attachment_count_declared,
        status="IN_SERVICE", last_inspection_date=None,
        last_treatment_date=None, current_remaining_strength_pct=None,
        current_classification="NONE", open_treatment_count=0,
    )
    db.poles[rec["id"]] = rec
    return ok(ser_pole(rec), 201)


@bp.get("/pole-program/poles/<pid>")
def get_pole(pid):
    authenticate()
    rec = db.poles.get(pid)
    if rec is None:
        raise ApiError("ERR_POLE_NOT_FOUND", 404, "pole_id does not resolve")
    return ok(ser_pole(rec), 200)


@bp.patch("/pole-program/poles/<pid>/gis-attributes")
@locked
def patch_gis(pid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    gis_lat = as_num(req_field(d, "gis_lat"), "gis_lat")
    gis_lon = as_num(req_field(d, "gis_lon"), "gis_lon")
    gis_tag = as_str(req_field(d, "gis_tag"), "gis_tag")
    expected = as_int(req_field(d, "expected_pole_version"),
                      "expected_pole_version")
    rec = db.poles.get(pid)
    if rec is None:
        raise ApiError("ERR_POLE_NOT_FOUND", 404, "pole_id does not resolve")
    if expected != rec["version"]:
        raise ApiError("ERR_STALE_POLE_VERSION", 412,
                       "expected_pole_version != Pole.version")
    rec["gis_lat"] = gis_lat
    rec["gis_lon"] = gis_lon
    rec["gis_tag"] = gis_tag
    db.touch(rec)
    return ok(ser_pole(rec), 200)
