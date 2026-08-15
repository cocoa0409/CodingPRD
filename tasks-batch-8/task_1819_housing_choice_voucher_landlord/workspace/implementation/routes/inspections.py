"""Inspection endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    parse_pagination, get_or_404, sorted_page,
    landlord_of_inspection, assert_landlord_owns,
)

bp = Blueprint("inspections", __name__)


def serialize_inspection(i):
    return {
        "id": i["id"],
        "contract_id": i["contract_id"],
        "inspection_type": i["inspection_type"],
        "scheduled_date": i["scheduled_date"],
        "status": i["status"],
        "result_recorded_date": i.get("result_recorded_date"),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


@bp.route("/hcv/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    require_roles("HousingAuthorityAdmin", "Landlord", "Inspector")
    insp = get_or_404(db.inspections, iid, "Inspection")
    return success_object(serialize_inspection(insp))


@bp.route("/hcv/inspections/<iid>/record-result", methods=["POST"])
def record_result(iid):
    require_roles("Inspector")
    insp = get_or_404(db.inspections, iid, "Inspection")
    body = request.get_json(force=True, silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise errors.invalid_amount("outcome must be PASS or FAIL")
    if insp["status"] != "SCHEDULED":
        raise errors.invalid_state("Inspection must be SCHEDULED to record result")

    # For FAIL: at least one RepairItem must exist (priority 14)
    if outcome == "FAIL":
        items = [ri for ri in db.repair_items.values() if ri["inspection_id"] == iid]
        if not items:
            raise errors.fail_requires_items()

    today = db.current_logical_date().isoformat()
    insp["result_recorded_date"] = today

    if outcome == "PASS":
        insp["status"] = "PASSED"
        db.touch(insp)
        # If INITIAL and contract PENDING_INSPECTION -> APPROVED
        if insp["inspection_type"] == "INITIAL":
            contract = db.hap_contracts.get(insp["contract_id"])
            if contract and contract["status"] == "PENDING_INSPECTION":
                contract["status"] = "APPROVED"
                db.touch(contract)
    else:  # FAIL
        insp["status"] = "FAILED"
        db.touch(insp)

    return success_object(serialize_inspection(insp))


@bp.route("/hcv/inspections/<iid>/request-reinspection", methods=["POST"])
def request_reinspection(iid):
    role, user_id = require_roles("Landlord")
    insp = get_or_404(db.inspections, iid, "Inspection")
    if insp["status"] != "FAILED":
        raise errors.invalid_state("Inspection must be FAILED to request reinspection")
    owner = landlord_of_inspection(insp)
    assert_landlord_owns(user_id, owner)
    # All RepairItems must be REPAIRED
    items = [ri for ri in db.repair_items.values() if ri["inspection_id"] == iid]
    for ri in items:
        if ri["status"] != "REPAIRED":
            raise errors.open_repair_items()
    insp["status"] = "REPAIR_VERIFICATION"
    db.touch(insp)
    return success_object(serialize_inspection(insp))


@bp.route("/hcv/inspections/<iid>/repair-items", methods=["GET"])
def list_repair_items(iid):
    require_roles("HousingAuthorityAdmin", "Landlord", "Inspector")
    get_or_404(db.inspections, iid, "Inspection")
    limit, offset = parse_pagination()
    rows = [ri for ri in db.repair_items.values() if ri["inspection_id"] == iid]
    page, total = sorted_page(rows, limit, offset)
    from routes.repair_items import serialize_repair_item
    return success_list([serialize_repair_item(ri) for ri in page], total, limit, offset)


@bp.route("/hcv/inspections/<iid>/repair-items", methods=["POST"])
def create_repair_item(iid):
    require_roles("Inspector")
    get_or_404(db.inspections, iid, "Inspection")
    body = request.get_json(force=True, silent=True) or {}
    rec = db.make_record({
        "inspection_id": iid,
        "description": body.get("description"),
        "is_life_threatening": bool(body.get("is_life_threatening", False)),
        "status": "OPEN",
    })
    db.repair_items[rec["id"]] = rec
    from routes.repair_items import serialize_repair_item
    return success_object(serialize_repair_item(rec), 201)
