"""Vessels (PRD 3.1)."""

from flask import Blueprint, request

import db
import response
from errors import not_found
from middleware import require_roles, check_owner_vessel
from validation import get_body, req_str, req_number, req_enum, parse_pagination, page

bp = Blueprint("vessels", __name__)

HULL_TYPES = ("POWER", "SAIL")
ALL_ROLES = ("ServiceWriter", "YardManager", "Accountant", "EnvironmentalOfficer", "Owner")


def get_vessel_or_404(vessel_id):
    vessel = db.vessels.get(vessel_id)
    if vessel is None:
        raise not_found(f"Vessel '{vessel_id}' does not exist")
    return vessel


@bp.post("/yard/vessels")
@require_roles("ServiceWriter")
def create_vessel():
    body = get_body()
    name = req_str(body, "name")
    owner_name = req_str(body, "owner_name")
    owner_user_id = req_str(body, "owner_user_id")
    loa_ft = req_number(body, "loa_ft", gt=0)
    beam_ft = req_number(body, "beam_ft", gt=0)
    hull_type = req_enum(body, "hull_type", HULL_TYPES)
    displacement_tons = req_number(body, "displacement_tons", gt=0)

    now = db.now_iso()
    vessel = {
        "id": db.new_id(),
        "name": name,
        "owner_name": owner_name,
        "owner_user_id": owner_user_id,
        "loa_ft": loa_ft,
        "beam_ft": beam_ft,
        "hull_type": hull_type,
        "displacement_tons": displacement_tons,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.vessels[vessel["id"]] = vessel
    return response.success_object(db.pub(vessel), status=201)


@bp.get("/yard/vessels/<vesselId>")
@require_roles(*ALL_ROLES)
def get_vessel(vesselId):
    vessel = get_vessel_or_404(vesselId)
    check_owner_vessel(vessel)
    return response.success_object(db.pub(vessel))


@bp.get("/yard/vessels")
@require_roles(*ALL_ROLES)
def list_vessels():
    limit, offset = parse_pagination()
    owner_filter = request.args.get("owner_user_id")
    items = list(db.vessels.values())
    if owner_filter is not None:
        items = [v for v in items if v["owner_user_id"] == owner_filter]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)
