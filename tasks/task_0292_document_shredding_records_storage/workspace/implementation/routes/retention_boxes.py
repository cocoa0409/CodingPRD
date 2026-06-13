"""RetentionBox endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, as_int, as_str,
    get_account_or_404, get_location_or_404, get_box_or_404, has_active_hold,
)

bp = Blueprint("retention_boxes", __name__)


@bp.post("/retention-boxes")
def ingest_box():
    _, role = get_auth()
    require_role(role, {"AccountManager", "PlantOperator"})
    data = body()
    require_present(data, "account_id", "location_id", "barcode")
    account_id = as_str(data["account_id"], "account_id")
    location_id = as_str(data["location_id"], "location_id")
    acct = get_account_or_404(account_id)
    get_location_or_404(location_id)
    barcode = as_str(data["barcode"], "barcode")

    free_periods = data.get("free_periods", 0)
    free_periods = as_int(free_periods, "free_periods")
    if free_periods < 0:
        raise err("ERR_INVALID_FIELD_VALUE", "free_periods must be >= 0")

    destroy_after_period = data.get("destroy_after_period")
    if destroy_after_period is not None:
        destroy_after_period = as_int(destroy_after_period, "destroy_after_period")

    # Barcode unique among the account's non-DESTROYED boxes.
    for b in db.retention_boxes.values():
        if (b["account_id"] == account_id
                and b["status"] != "DESTROYED"
                and b["barcode"] == barcode):
            raise err("ERR_DUPLICATE_BARCODE", "Barcode already in use on the account")

    box = {
        "account_id": account_id,
        "location_id": location_id,
        "barcode": barcode,
        "stored_at_period": acct["current_period_index"],
        "free_periods": free_periods,
        "destroy_after_period": destroy_after_period,
        "status": "INGESTED",
    }
    stamp_create(box)
    db.retention_boxes[box["id"]] = box
    return object_response(serialize(box), 201)


@bp.get("/retention-boxes/<box_id>")
def get_box(box_id):
    _, role = get_auth()
    require_role(role, {"AccountManager", "PlantOperator", "ComplianceOfficer"})
    b = get_box_or_404(box_id)
    return object_response(serialize(b), 200)


@bp.get("/retention-boxes")
def list_boxes():
    _, role = get_auth()
    require_role(role, {"AccountManager", "PlantOperator", "ComplianceOfficer"})
    items = list(db.retention_boxes.values())
    account_id = request.args.get("account_id")
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [b for b in items if b["account_id"] == account_id]
    if location_id is not None:
        items = [b for b in items if b["location_id"] == location_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(b) for b in page], limit, offset, total, 200)


@bp.post("/retention-boxes/<box_id>/shelve")
def shelve_box(box_id):
    _, role = get_auth()
    require_role(role, {"PlantOperator"})
    b = get_box_or_404(box_id)
    if b["status"] != "INGESTED":
        raise err("ERR_BOX_NOT_INGESTED", "Box is not in INGESTED")
    b["status"] = "STORED"
    touch(b)
    return object_response(serialize(b), 200)


@bp.post("/retention-boxes/<box_id>/purge")
def purge_box(box_id):
    _, role = get_auth()
    require_role(role, {"AccountManager"})
    b = get_box_or_404(box_id)
    if b["status"] != "STORED":
        raise err("ERR_BOX_NOT_STORED", "Box is not in STORED")
    # Hold check before the retention schedule.
    if has_active_hold("RETENTION_BOX", b["id"]):
        raise err("ERR_SUBJECT_ON_HOLD", "Box is under an active compliance hold")
    if b.get("destroy_after_period") is not None:
        acct = db.accounts[b["account_id"]]
        if acct["current_period_index"] < b["destroy_after_period"]:
            raise err("ERR_RETENTION_NOT_ELAPSED", "Retention schedule has not elapsed")
    b["status"] = "DESTROYED"
    touch(b)
    return object_response(serialize(b), 200)
