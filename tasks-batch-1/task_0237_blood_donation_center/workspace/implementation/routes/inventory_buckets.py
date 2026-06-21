"""Inventory buckets: create/initialize (recount), reads (live recount)."""
from flask import Blueprint, request

import db
import lookup
from common import get_json_body, paginate, require_enum, require_string
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_bucket

bp = Blueprint("inventory_buckets", __name__)


@bp.route("/blood-bank/inventory-buckets", methods=["POST"])
@require_roles("InventoryManager")
def create_bucket():
    body = get_json_body()
    with db.lock:
        center_id = require_string(body, "center_id")
        blood_type = require_enum(body, "blood_type", domain.BLOOD_TYPES)
        component = require_enum(body, "component", domain.COMPONENTS)

        lookup.center(center_id)

        bucket = {
            "center_id": center_id,
            "blood_type": blood_type,
            "component": component,
            "available_count": 0,
            "reserved_count": 0,
        }
        db.stamp_new(bucket)
        # initialize counts from a recount of existing units
        available, reserved = domain.recount_bucket(bucket)
        bucket["available_count"] = available
        bucket["reserved_count"] = reserved
        db.inventory_buckets[bucket["id"]] = bucket
        return success(serialize_bucket(bucket), status=201)


@bp.route("/blood-bank/inventory-buckets", methods=["GET"])
@require_roles("CenterAdmin", "InventoryManager", "LabTechnician")
def list_buckets():
    center_id = request.args.get("center_id")
    blood_type = request.args.get("blood_type")
    component = request.args.get("component")
    with db.lock:
        rows = list(db.inventory_buckets.values())
        if center_id is not None:
            rows = [b for b in rows if b["center_id"] == center_id]
        if blood_type is not None:
            rows = [b for b in rows if b["blood_type"] == blood_type]
        if component is not None:
            rows = [b for b in rows if b["component"] == component]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_bucket(b) for b in page], limit, offset, total)


@bp.route("/blood-bank/inventory-buckets/<bucket_id>", methods=["GET"])
@require_roles("CenterAdmin", "InventoryManager", "LabTechnician")
def get_bucket(bucket_id):
    with db.lock:
        bucket = lookup.bucket(bucket_id)
        return success(serialize_bucket(bucket))
