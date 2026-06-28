from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from services.common import parse_pagination, paginate
from services.lookups import get_slot
from services.serialize import slot_view

slots_bp = Blueprint("slots", __name__)

READ_ROLES = {"DockMaster", "BillingClerk"}


@slots_bp.route("/marina/forklift-slots/<slot_id>", methods=["GET"])
def fetch_slot(slot_id):
    require_role(READ_ROLES)
    rec = get_slot(slot_id)
    return object_response(slot_view(rec), 200)


@slots_bp.route("/marina/forklift-slots", methods=["GET"])
def list_slots():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.slots.values())
    forklift_id = request.args.get("forklift_id")
    launch_request_id = request.args.get("launch_request_id")
    status = request.args.get("status")
    if forklift_id is not None:
        records = [r for r in records if r["forklift_id"] == forklift_id]
    if launch_request_id is not None:
        records = [r for r in records if r["launch_request_id"] == launch_request_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([slot_view(r) for r in page], limit, offset, total)
