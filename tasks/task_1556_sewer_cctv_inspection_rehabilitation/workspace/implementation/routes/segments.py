"""PipeSegment + Lateral endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, technician_capability_check
from response import success_object, success_list
from errors import err_invalid_request, err_not_found
from services.common import (
    body, require_string, require_number, require_int, require_enum,
    parse_pagination, paginate, get_segment, get_lateral_in_segment,
    get_segment_in_district, get_district, sweep_notice_expiry,
)

bp = Blueprint("segments", __name__)

ALL_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead", "CustomerServiceRep"]
MATERIALS = {"VCP", "RCP", "PVC", "HDPE", "CI", "BRICK"}
CONN_TYPES = {"DIRECT", "WYE", "SADDLE"}


def segment_view(s):
    return {
        "id": s["id"],
        "district_id": s["district_id"],
        "segment_ref": s["segment_ref"],
        "diameter_mm": s["diameter_mm"],
        "material": s["material"],
        "length_m": s["length_m"],
        "install_year": s["install_year"],
        "structural_grade": s["structural_grade"],
        "om_grade": s["om_grade"],
        "quick_rating": s["quick_rating"],
        "structural_index": s["structural_index"],
        "rehab_status": s["rehab_status"],
        "last_rehab_completed_at": s["last_rehab_completed_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def lateral_view(l):
    return {
        "id": l["id"],
        "segment_id": l["segment_id"],
        "address": l["address"],
        "connection_type": l["connection_type"],
        "active": l["active"],
        "reinstated": l["reinstated"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------

@bp.post("/sewer/districts/<id>/segments")
def create_segment(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    district = get_district(id)
    payload = body()
    segment_ref = require_string(payload, "segment_ref")
    diameter = require_int(payload, "diameter_mm")
    if diameter <= 0:
        raise err_invalid_request("diameter_mm must be > 0")
    material = require_enum(payload, "material", MATERIALS)
    length = require_number(payload, "length_m")
    if length <= 0:
        raise err_invalid_request("length_m must be > 0")
    install_year = require_int(payload, "install_year")
    for s in db.segments.values():
        if s["district_id"] == district["id"] and s["segment_ref"] == segment_ref:
            raise err_invalid_request("segment_ref must be unique within district")
    ent = {
        "id": db.new_id(),
        "district_id": district["id"],
        "segment_ref": segment_ref,
        "diameter_mm": diameter,
        "material": material,
        "length_m": length,
        "install_year": install_year,
        "structural_grade": 0,
        "om_grade": 0,
        "quick_rating": None,
        "structural_index": None,
        "rehab_status": "NONE",
        "last_rehab_completed_at": None,
    }
    db.stamp_new(ent)
    db.segments[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(segment_view(ent), status=201)


@bp.get("/sewer/segments/<id>")
def get_segment_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    s = get_segment(id)
    return success_object(segment_view(s))


@bp.get("/sewer/districts/<id>/segments")
def list_segments(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    district = get_district(id)
    limit, offset = parse_pagination()
    items = [s for s in db.segments.values() if s["district_id"] == district["id"]]
    rs = request.args.get("rehab_status")
    if rs:
        items = [s for s in items if s["rehab_status"] == rs]
    msg = request.args.get("min_structural_grade")
    if msg is not None and msg != "":
        try:
            thr = int(msg)
        except ValueError:
            raise err_invalid_request("min_structural_grade must be an integer")
        items = [s for s in items if s["structural_grade"] >= thr]
    page, total = paginate(items, limit, offset)
    return success_list([segment_view(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Laterals
# ---------------------------------------------------------------------------

@bp.post("/sewer/segments/<id>/laterals")
def create_lateral(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    segment = get_segment(id)
    payload = body()
    address = require_string(payload, "address")
    ctype = require_enum(payload, "connection_type", CONN_TYPES)
    active = payload.get("active", True)
    if not isinstance(active, bool):
        raise err_invalid_request("active must be a boolean")
    for l in db.laterals.values():
        if l["segment_id"] == segment["id"] and l["address"] == address:
            raise err_invalid_request("address must be unique within segment")
    ent = {
        "id": db.new_id(),
        "segment_id": segment["id"],
        "address": address,
        "connection_type": ctype,
        "active": active,
        "reinstated": False,
    }
    db.stamp_new(ent)
    db.laterals[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(lateral_view(ent), status=201)


@bp.get("/sewer/segments/<id>/laterals")
def list_laterals(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    segment = get_segment(id)
    limit, offset = parse_pagination()
    items = [l for l in db.laterals.values() if l["segment_id"] == segment["id"]]
    act = request.args.get("active")
    if act is not None and act != "":
        if act.lower() in ("true", "1"):
            items = [l for l in items if l["active"] is True]
        elif act.lower() in ("false", "0"):
            items = [l for l in items if l["active"] is False]
        else:
            raise err_invalid_request("active must be true/false")
    rei = request.args.get("reinstated")
    if rei is not None and rei != "":
        if rei.lower() in ("true", "1"):
            items = [l for l in items if l["reinstated"] is True]
        elif rei.lower() in ("false", "0"):
            items = [l for l in items if l["reinstated"] is False]
        else:
            raise err_invalid_request("reinstated must be true/false")
    page, total = paginate(items, limit, offset)
    return success_list([lateral_view(l) for l in page], limit, offset, total)


@bp.post("/sewer/segments/<id>/laterals/<lateralId>/reinstate")
def reinstate_lateral(id, lateralId):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    technician_capability_check(actor, "CREW_LEAD")
    segment = get_segment(id)
    lateral = get_lateral_in_segment(id, lateralId)
    lateral["reinstated"] = True
    db.touch(lateral)
    sweep_notice_expiry()
    return success_object(lateral_view(lateral))
