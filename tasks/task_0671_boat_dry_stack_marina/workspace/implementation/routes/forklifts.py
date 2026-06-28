from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from services.common import (
    stamp_create, get_json_body, require_fields, require_string, require_pos_int,
    parse_pagination, paginate,
)
from services.lookups import get_marina, get_forklift
from services.serialize import forklift_view

forklifts_bp = Blueprint("forklifts", __name__)

READ_ROLES = {"DockMaster", "BillingClerk"}


@forklifts_bp.route("/marina/forklifts", methods=["POST"])
def create_forklift():
    require_role({"DockMaster"})
    body = get_json_body()
    require_fields(body, ["marina_id", "label", "max_lift_weight_lbs"])
    require_string(body["marina_id"], "marina_id")
    require_string(body["label"], "label")
    require_pos_int(body["max_lift_weight_lbs"], "max_lift_weight_lbs")
    with db.lock:
        get_marina(body["marina_id"])
        rec = {
            "marina_id": body["marina_id"],
            "label": body["label"],
            "max_lift_weight_lbs": body["max_lift_weight_lbs"],
            "status": "AVAILABLE",
        }
        stamp_create(rec)
        db.forklifts[rec["id"]] = rec
    return object_response(forklift_view(rec), 201)


@forklifts_bp.route("/marina/forklifts/<forklift_id>", methods=["GET"])
def fetch_forklift(forklift_id):
    require_role(READ_ROLES)
    rec = get_forklift(forklift_id)
    return object_response(forklift_view(rec), 200)


@forklifts_bp.route("/marina/forklifts", methods=["GET"])
def list_forklifts():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.forklifts.values())
    marina_id = request.args.get("marina_id")
    if marina_id is not None:
        records = [r for r in records if r["marina_id"] == marina_id]
    page, total = paginate(records, limit, offset)
    return array_response([forklift_view(r) for r in page], limit, offset, total)
