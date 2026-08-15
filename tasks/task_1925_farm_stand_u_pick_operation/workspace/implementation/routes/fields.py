"""Field endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
import domain
from errors import (
    raise_err,
    ERR_FIELD_RESTING,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEASON_NOT_ACTIVE,
    ERR_STALE_VERSION,
)
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    opt_int,
    paginate,
    req_int,
    req_str,
    require,
)

bp = Blueprint("fields", __name__)

FM = ("FarmManager",)
READERS = ("FarmManager", "GateStaff", "FieldStaff")


@bp.post("/farm/fields")
def create_field():
    require(FM)
    body = get_body()
    check_no_undeclared(
        body,
        {"season_id", "name", "rotation_group", "rotation_order", "estimated_harvest_oz"},
    )
    season_id = req_str(body, "season_id")
    name = req_str(body, "name")
    rotation_group = req_str(body, "rotation_group")
    rotation_order = req_int(body, "rotation_order", min_value=0)
    estimated = req_int(body, "estimated_harvest_oz", min_value=1)
    if season_id not in db.seasons:
        raise_err(ERR_NOT_FOUND, "season_id does not resolve")
    field = domain.new_entity()
    field.update(
        {
            "season_id": season_id,
            "name": name,
            "rotation_group": rotation_group,
            "rotation_order": rotation_order,
            "estimated_harvest_oz": estimated,
            "status": "DORMANT",
            "rest_until": None,
            "rotation_successor_field_id": None,
        }
    )
    db.fields[field["id"]] = field
    return ok_object(domain.serialize_field(field), 201)


@bp.get("/farm/fields/<fid>")
def get_field(fid):
    require(READERS)
    field = db.fields.get(fid)
    if field is None:
        raise_err(ERR_NOT_FOUND, "Field not found")
    return ok_object(domain.serialize_field(field))


@bp.get("/farm/fields")
def list_fields():
    require(READERS)
    items = list(db.fields.values())
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [f for f in items if f["season_id"] == season_id]
    rotation_group = request.args.get("rotation_group")
    if rotation_group is not None:
        items = [f for f in items if f["rotation_group"] == rotation_group]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    successor = request.args.get("rotation_successor_field_id")
    if successor is not None:
        items = [f for f in items if f["rotation_successor_field_id"] == successor]
    return paginate(items, domain.serialize_field)


@bp.patch("/farm/fields/<fid>")
def patch_field(fid):
    require(FM)
    field = db.fields.get(fid)
    if field is None:
        raise_err(ERR_NOT_FOUND, "Field not found")
    body = get_body()
    check_no_undeclared(
        body, {"expected_field_version", "rotation_order", "estimated_harvest_oz"}
    )
    expected = req_int(body, "expected_field_version")
    rotation_order = opt_int(body, "rotation_order", min_value=0)
    estimated = opt_int(body, "estimated_harvest_oz", min_value=1)
    # OCC (PRD §2.6): expected_field_version must equal the current version.
    if expected != field["version"]:
        raise_err(ERR_STALE_VERSION, "expected_field_version is stale")
    if rotation_order is not None:
        field["rotation_order"] = rotation_order
    if estimated is not None:
        field["estimated_harvest_oz"] = estimated
    domain.touch(field)
    return ok_object(domain.serialize_field(field))


@bp.post("/farm/fields/<fid>/open")
def open_field(fid):
    require(FM)
    field = db.fields.get(fid)
    if field is None:
        raise_err(ERR_NOT_FOUND, "Field not found")
    if field["status"] in ("OPEN", "PICKED_OUT", "RETIRED"):
        raise_err(ERR_INVALID_STATE, "Field cannot be opened from its current state")
    season = domain.season_of_field(field)
    if season is None or season["status"] != "ACTIVE":
        raise_err(ERR_SEASON_NOT_ACTIVE, "Season of the field is not ACTIVE")
    if field["status"] == "ROTATION_REST":
        raise_err(ERR_FIELD_RESTING, "Field is in ROTATION_REST")
    if field["rest_until"] is not None and field["rest_until"] >= db.logical_date_str():
        raise_err(ERR_FIELD_RESTING, "Field is resting")
    field["status"] = "OPEN"
    domain.touch(field)
    return ok_object(domain.serialize_field(field))


@bp.post("/farm/fields/<fid>/retire")
def retire_field(fid):
    require(FM)
    field = db.fields.get(fid)
    if field is None:
        raise_err(ERR_NOT_FOUND, "Field not found")
    if field["status"] == "RETIRED":
        raise_err(ERR_INVALID_STATE, "Field is already RETIRED")
    for w in db.windows.values():
        if w["field_id"] == fid and w["status"] in ("SCHEDULED", "OPEN"):
            raise_err(
                ERR_INVALID_STATE,
                "Field has a window in SCHEDULED or OPEN",
            )
    field["status"] = "RETIRED"
    domain.touch(field)
    return ok_object(domain.serialize_field(field))
