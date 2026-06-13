"""Appraisals and the insurance document (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.calc import replacement_value_cents
from services.common import (
    get_body, require_str, require_int, require_datetime, optional_number,
    resolve_fk, resolve_path, require_own_version, require_item_version,
    appraisal_slot_conflict, parse_dt,
)

bp = Blueprint("appraisals", __name__)


def recompute_item_appraised_value(item_id):
    """latest_appraised_value_cents = replacement_value of the most recent FINALIZED
    appraisal (created_at DESC), else null (PRD §3.2)."""
    item = db.inventory_items.get(item_id)
    if item is None:
        return
    finalized = [a for a in db.appraisals.values()
                 if a["inventory_item_id"] == item_id and a["status"] == "FINALIZED"]
    if not finalized:
        item["latest_appraised_value_cents"] = None
        return
    finalized.sort(key=lambda a: (a["created_at"], a["_seq"]), reverse=True)
    item["latest_appraised_value_cents"] = finalized[0]["replacement_value_cents"]


@bp.route("/appraisals", methods=["POST"])
def create_appraisal():
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    body = get_body()
    item_id = require_str(body, "inventory_item_id")
    item = resolve_fk(db.inventory_items, item_id)
    appraiser_name = require_str(body, "appraiser_name")
    start = require_datetime(body, "appointment_start")
    end = require_datetime(body, "appointment_end")
    if not (parse_dt(end) > parse_dt(start)):
        raise ApiError("ERR_INVALID_REQUEST", "appointment_end must be after appointment_start")
    market_value = require_int(body, "market_value_cents", gt=0)
    replacement_factor = optional_number(body, "replacement_factor", default=1.30,
                                         minimum=1.00, maximum=2.00)
    # Appraiser-slot overlap check (closed interval + 30-min buffer) — PRD §2.10.
    if appraisal_slot_conflict(appraiser_name, start, end):
        raise ApiError("ERR_APPRAISAL_SLOT_CONFLICT", "Appraiser slot conflicts with an existing appointment")
    rec = db.new_record()
    rec.update({
        "inventory_item_id": item_id, "appraiser_name": appraiser_name,
        "appointment_start": start, "appointment_end": end,
        "market_value_cents": market_value, "replacement_factor": replacement_factor,
        "replacement_value_cents": replacement_value_cents(market_value, replacement_factor),
        "document_number": None, "status": "DRAFT",
    })
    db.appraisals[rec["id"]] = rec
    return success(serialize.appraisal(rec), status=201)


@bp.route("/appraisals", methods=["GET"])
def list_appraisals():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    item_id = request.args.get("inventory_item_id")
    records = [a for a in db.appraisals.values()
               if item_id is None or a["inventory_item_id"] == item_id]
    page, meta = paginate(records, limit, offset)
    return success([serialize.appraisal(r) for r in page], status=200, pagination=meta)


@bp.route("/appraisals/<aid>", methods=["GET"])
def get_appraisal(aid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = resolve_path(db.appraisals, aid)
    return success(serialize.appraisal(rec), status=200)


@bp.route("/appraisals/<aid>/finalize", methods=["POST"])
def finalize_appraisal(aid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.appraisals, aid)
    body = get_body()
    # State legality first (PRD §2.8 ordering).
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Appraisal is not DRAFT")
    item = db.inventory_items.get(rec["inventory_item_id"])
    # Cross-entity guard: item not SOLD.
    if item is not None and item["status"] == "SOLD":
        raise ApiError("ERR_ITEM_SOLD", "Referenced inventory item is SOLD")
    # OCC on the referenced item.
    require_item_version(item, body)
    rec["status"] = "FINALIZED"
    rec["document_number"] = db.next_appraisal_doc_number()
    db.touch(rec)
    recompute_item_appraised_value(item["id"])
    db.touch(item)
    return success(serialize.appraisal(rec), status=200)


@bp.route("/appraisals/<aid>/void", methods=["POST"])
def void_appraisal(aid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.appraisals, aid)
    body = get_body()
    if rec["status"] not in ("DRAFT", "FINALIZED"):
        raise ApiError("ERR_INVALID_STATE", "Appraisal cannot be voided from its current state")
    require_own_version(rec, body)
    was_finalized = rec["status"] == "FINALIZED"
    rec["status"] = "VOID"
    db.touch(rec)
    # If this was the item's latest finalized appraisal, recompute (next most recent or null).
    if was_finalized:
        recompute_item_appraised_value(rec["inventory_item_id"])
    return success(serialize.appraisal(rec), status=200)
