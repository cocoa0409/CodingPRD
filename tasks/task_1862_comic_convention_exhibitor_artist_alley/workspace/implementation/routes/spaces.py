"""SpaceUnit routes."""

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, require_int, require_enum,
                     paginate, sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list

bp = Blueprint("spaces", __name__)

HALLS = ("MAIN", "ARTIST_ALLEY_HALL", "SMALL_PRESS")
KINDS = ("BOOTH_10X10", "BOOTH_10X20", "CORNER_BOOTH", "ENDCAP",
         "FEATURED_ISLAND", "ARTIST_TABLE", "NONPROFIT_TABLE")


def space_view(s):
    return {k: s[k] for k in (
        "id", "convention_id", "space_code", "block", "unit_number", "hall",
        "kind", "base_price_cents", "status", "current_application_id",
        "created_at", "updated_at", "version")}


@bp.route("/space-units", methods=["POST"])
def create_space_unit():
    require_roles("ShowDirector")
    body = get_json_body()
    convention_id = require_str(body, "convention_id")
    space_code = require_str(body, "space_code")
    block = require_str(body, "block")
    unit_number = require_int(body, "unit_number")
    hall = require_enum(body, "hall", HALLS)
    kind = require_enum(body, "kind", KINDS)
    base_price_cents = require_int(body, "base_price_cents", minimum=0)

    conv = db.conventions.get(convention_id)
    if conv is None:
        fail("ERR_NOT_FOUND", "convention_id does not exist")
    for su in db.space_units.values():
        if su["convention_id"] == convention_id and su["space_code"] == space_code:
            fail("ERR_DUPLICATE_SPACE_CODE", "space_code already exists within the convention")

    su = {
        "id": db.new_id(),
        "convention_id": convention_id,
        "space_code": space_code,
        "block": block,
        "unit_number": unit_number,
        "hall": hall,
        "kind": kind,
        "base_price_cents": base_price_cents,
        "status": "AVAILABLE",
        "current_application_id": None,
    }
    db.stamp_created(su)
    db.space_units[su["id"]] = su
    return success_object(space_view(su), 201)


@bp.route("/space-units", methods=["GET"])
def list_space_units():
    require_roles("ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor")
    items = list(db.space_units.values())
    for f in ("convention_id", "status", "kind", "hall"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([space_view(s) for s in page], limit, offset, total)


@bp.route("/space-units/<spaceUnitId>", methods=["GET"])
def get_space_unit(spaceUnitId):
    require_roles("ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor")
    su = get_or_404(db.space_units, spaceUnitId)
    return success_object(space_view(su), 200)
