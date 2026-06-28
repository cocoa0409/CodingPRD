from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_DUPLICATE_BAY_LABEL
from services.common import (
    stamp_create, get_json_body, require_fields, require_string, require_enum,
    require_pos_int, require_pos_number, parse_pagination, paginate,
)
from services.lookups import get_marina, get_rack
from services.serialize import rack_view

racks_bp = Blueprint("racks", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}
SIZE_CLASSES = {"SMALL", "MEDIUM", "LARGE"}


@racks_bp.route("/marina/racks", methods=["POST"])
def create_rack():
    require_role({"DockMaster"})
    body = get_json_body()
    require_fields(body, ["marina_id", "bay_label", "size_class", "max_loa_ft",
                          "max_beam_ft", "max_weight_lbs"])
    require_string(body["marina_id"], "marina_id")
    require_string(body["bay_label"], "bay_label")
    require_enum(body["size_class"], SIZE_CLASSES, "size_class")
    require_pos_number(body["max_loa_ft"], "max_loa_ft")
    require_pos_number(body["max_beam_ft"], "max_beam_ft")
    require_pos_int(body["max_weight_lbs"], "max_weight_lbs")
    with db.lock:
        # Existence (priority 4) before bay-label uniqueness (priority 16).
        get_marina(body["marina_id"])
        for r in db.racks.values():
            if r["marina_id"] == body["marina_id"] and r["bay_label"] == body["bay_label"]:
                raise err(ERR_DUPLICATE_BAY_LABEL, "bay_label already used in this marina.")
        rec = {
            "marina_id": body["marina_id"],
            "bay_label": body["bay_label"],
            "size_class": body["size_class"],
            "max_loa_ft": body["max_loa_ft"],
            "max_beam_ft": body["max_beam_ft"],
            "max_weight_lbs": body["max_weight_lbs"],
            "status": "AVAILABLE",
            "current_agreement_id": None,
        }
        stamp_create(rec)
        db.racks[rec["id"]] = rec
    return object_response(rack_view(rec), 201)


@racks_bp.route("/marina/racks/<rack_id>", methods=["GET"])
def fetch_rack(rack_id):
    require_role(READ_ROLES)
    rec = get_rack(rack_id)
    return object_response(rack_view(rec), 200)


@racks_bp.route("/marina/racks", methods=["GET"])
def list_racks():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.racks.values())
    marina_id = request.args.get("marina_id")
    size_class = request.args.get("size_class")
    status = request.args.get("status")
    current_agreement_id = request.args.get("current_agreement_id")
    if marina_id is not None:
        records = [r for r in records if r["marina_id"] == marina_id]
    if size_class is not None:
        records = [r for r in records if r["size_class"] == size_class]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if current_agreement_id is not None:
        records = [r for r in records if r["current_agreement_id"] == current_agreement_id]
    page, total = paginate(records, limit, offset)
    return array_response([rack_view(r) for r in page], limit, offset, total)
