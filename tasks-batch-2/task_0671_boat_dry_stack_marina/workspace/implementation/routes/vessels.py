from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_NOT_RESOURCE_OWNER
from services.common import (
    stamp_create, get_json_body, require_fields, require_string,
    require_pos_int, require_pos_number, parse_pagination, paginate,
)
from services.lookups import get_marina, get_owner, get_vessel
from services.serialize import vessel_view

vessels_bp = Blueprint("vessels", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}


@vessels_bp.route("/marina/vessels", methods=["POST"])
def create_vessel():
    user_id, role = require_role({"DockMaster", "BoatOwner"})
    body = get_json_body()
    require_fields(body, ["marina_id", "owner_id", "name", "loa_ft", "beam_ft", "dry_weight_lbs"])
    require_string(body["marina_id"], "marina_id")
    require_string(body["owner_id"], "owner_id")
    require_string(body["name"], "name")
    require_pos_number(body["loa_ft"], "loa_ft")
    require_pos_number(body["beam_ft"], "beam_ft")
    require_pos_int(body["dry_weight_lbs"], "dry_weight_lbs")
    with db.lock:
        get_marina(body["marina_id"])
        get_owner(body["owner_id"])
        # BoatOwner may only register vessels under their own account (§2.1 ownership).
        if role == "BoatOwner" and body["owner_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "BoatOwner may only register vessels they own.")
        rec = {
            "marina_id": body["marina_id"],
            "owner_id": body["owner_id"],
            "name": body["name"],
            "loa_ft": body["loa_ft"],
            "beam_ft": body["beam_ft"],
            "dry_weight_lbs": body["dry_weight_lbs"],
            "location_status": "OFF_SITE",
            "billing_status": "UNBILLED",
            "active_policy_id": None,
        }
        stamp_create(rec)
        db.vessels[rec["id"]] = rec
    return object_response(vessel_view(rec), 201)


@vessels_bp.route("/marina/vessels/<vessel_id>", methods=["GET"])
def fetch_vessel(vessel_id):
    require_role(READ_ROLES)
    rec = get_vessel(vessel_id)
    return object_response(vessel_view(rec), 200)


@vessels_bp.route("/marina/vessels", methods=["GET"])
def list_vessels():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.vessels.values())
    marina_id = request.args.get("marina_id")
    owner_id = request.args.get("owner_id")
    location_status = request.args.get("location_status")
    billing_status = request.args.get("billing_status")
    active_policy_id = request.args.get("active_policy_id")
    if marina_id is not None:
        records = [r for r in records if r["marina_id"] == marina_id]
    if owner_id is not None:
        records = [r for r in records if r["owner_id"] == owner_id]
    if location_status is not None:
        records = [r for r in records if r["location_status"] == location_status]
    if billing_status is not None:
        records = [r for r in records if r["billing_status"] == billing_status]
    if active_policy_id is not None:
        records = [r for r in records if r["active_policy_id"] == active_policy_id]
    page, total = paginate(records, limit, offset)
    return array_response([vessel_view(r) for r in page], limit, offset, total)
