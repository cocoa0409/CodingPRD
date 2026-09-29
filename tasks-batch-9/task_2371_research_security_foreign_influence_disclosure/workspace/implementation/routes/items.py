"""Disclosure item reads and the officer/investigator item state machine."""

from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import CRO, INVESTIGATOR, RSO, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("items", __name__)

ITEM_TRANSITIONS = {
    ("DECLARED", "VERIFIED"): (RSO, CRO),
    ("DECLARED", "DISPUTED"): (RSO, CRO),
    ("DECLARED", "WITHDRAWN"): (INVESTIGATOR,),
    ("DISPUTED", "VERIFIED"): (CRO,),
    ("DISPUTED", "WITHDRAWN"): (CRO,),
}


@bp.get("/disclosure-items/<item_id>")
def read_item(item_id):
    require_any()
    record = must_exist("item", item_id)
    return response.object_response(present.item(record))


@bp.get("/disclosure-items")
def list_items():
    require_any()
    disclosure_id = validate.filter_value("disclosure_id")
    organization_id = validate.filter_value("foreign_organization_id")
    status = validate.filter_enum("status", E.ITEM_STATUSES)

    rows = []
    for record in db.ordered(db.items.values()):
        if disclosure_id and record["disclosure_id"] != disclosure_id:
            continue
        if organization_id and \
                record["foreign_organization_id"] != organization_id:
            continue
        if status and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, present.item)


@bp.post("/disclosure-items/<item_id>/status")
def set_item_status(item_id):
    user_id, role = require(RSO, CRO, INVESTIGATOR)
    data = validate.body()
    record = must_exist("item", item_id)
    disclosure = db.disclosures.get(record["disclosure_id"])

    # step 3 — ownership for Investigator-role callers
    if role == INVESTIGATOR and disclosure is not None and \
            disclosure["investigator_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting investigator does not own this item.")

    to_status = validate.req_enum(data, "to_status", E.ITEM_STATUSES)
    current = record["status"]
    key = (current, to_status)
    if key not in ITEM_TRANSITIONS:
        raise ApiError("ERR_INVALID_ITEM_TRANSITION",
                       "Item status cannot move %s -> %s." % (current, to_status))
    if role not in ITEM_TRANSITIONS[key]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not move an item %s -> %s."
                       % (role, current, to_status))

    review_status = disclosure["review_status"] if disclosure else None
    investigator = db.investigators.get(disclosure["investigator_id"]) \
        if disclosure else None

    if current == "DECLARED" and to_status in ("VERIFIED", "DISPUTED"):
        if review_status not in ("SUBMITTED", "UNDER_REVIEW"):
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "The parent disclosure must be SUBMITTED or "
                           "UNDER_REVIEW.")
    if current == "DECLARED" and to_status == "WITHDRAWN":
        if review_status not in ("DRAFT", "RETURNED_FOR_REVISION"):
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "The parent disclosure must be DRAFT or "
                           "RETURNED_FOR_REVISION.")

    record["status"] = to_status
    derive.compute_item(record)
    db.touch(record)

    if to_status == "VERIFIED":
        cascade.recompute_investigator(investigator)
    elif to_status == "WITHDRAWN":
        cascade.recompute_disclosure(disclosure)
        cascade.recompute_investigator(investigator)

    return response.object_response(present.item(record))
