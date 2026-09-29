"""Records transfer items and their delivery review cycle."""
from flask import Blueprint

import auth
import cascades
import clock
import constants
import response
import util
import validation as v
from db import db, new_record, serialize, touch
from errors import ApiError
from routes import common

bp = Blueprint("records_items", __name__)


@bp.post("/hoa/records-items")
def create_records_item():
    auth.require_roles(constants.ROLE_DECLARANT)
    body = v.body()

    case = common.body_turnover_case_or_404(v.get_fk(body, "turnover_case_id"))
    if case is None:
        raise ApiError("ERR_INVALID_REQUEST", "turnover_case_id is required.")

    category = v.get_enum(body, "category", constants.RECORDS_CATEGORIES)
    required = v.get_bool(body, "required", required=False, default=True)

    item = new_record({
        "turnover_case_id": case["id"],
        "category": category,
        "required": required,
        "status": "OUTSTANDING",
        "delivered_at": None,
        "rejection_reason": None,
    })
    db.records_items[item["id"]] = item

    cascades.recompute_records_completeness(case)
    return response.object_response(serialize(item), 201)


@bp.post("/hoa/records-items/<item_id>/transitions")
def transition_records_item(item_id):
    auth.require_roles(constants.ROLE_DECLARANT, constants.ROLE_TRANSITION_COMMITTEE)
    body = v.body()
    auth.require_discriminator_role(body.get("action"), constants.RECORDS_ACTION_ROLES)

    item = common.records_item_or_404(item_id, scoped=True)
    action = v.get_enum(body, "action", constants.RECORDS_ACTIONS)
    rejection_reason = None
    if action == "REJECT":
        rejection_reason = v.get_str(body, "rejection_reason", min_len=1, max_len=400)

    if action == "DELIVER":
        if item["status"] not in ("OUTSTANDING", "REJECTED"):
            raise ApiError("ERR_RECORDS_ITEM_STATE_INVALID")
        item["status"] = "DELIVERED"
        item["delivered_at"] = util.fmt_dt(clock.now())
        item["rejection_reason"] = None
        touch(item)
        return response.object_response(serialize(item))

    if item["status"] != "DELIVERED":
        raise ApiError("ERR_RECORDS_ITEM_STATE_INVALID")

    if action == "ACCEPT":
        item["status"] = "ACCEPTED"
    else:
        item["status"] = "REJECTED"
        item["rejection_reason"] = rejection_reason
    touch(item)

    case = db.turnover_cases.get(item["turnover_case_id"])
    cascades.recompute_records_completeness(case)
    return response.object_response(serialize(item))
