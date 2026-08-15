"""Requisition routes."""
from flask import Blueprint, request

import db
from db import stamp_new, touch
from errors import (err_vessel_call_not_found, err_requisition_not_found,
                    err_catalog_item_not_found, err_invalid_request,
                    err_insufficient_permissions,
                    err_requisition_not_submittable,
                    err_requisition_not_recallable,
                    err_requisition_has_live_quotation)
from middleware import require_roles, require_any_authenticated
from response import success_object, success_list, parse_pagination
from services.validate import (get_body, req_string, req_lines_array,
                               qty_at_least_one, req_bool)

bp = Blueprint("requisition", __name__)


def _validate_requisition_lines(lines):
    """Validate shape of requisition lines and FK existence (priority 3/4/13)."""
    validated = []
    for line in lines:
        catalog_item_id = line.get("catalog_item_id")
        if not isinstance(catalog_item_id, str) or catalog_item_id.strip() == "":
            raise err_invalid_request("missing or invalid field: catalog_item_id")
        if catalog_item_id not in db.catalog_items:
            raise err_catalog_item_not_found()
        requested_qty = line.get("requested_qty")
        if isinstance(requested_qty, bool) or not isinstance(requested_qty, int):
            raise err_invalid_request("requested_qty must be an integer")
        qty_at_least_one(requested_qty)
        allows_substitution = line.get("allows_substitution")
        if not isinstance(allows_substitution, bool):
            raise err_invalid_request("allows_substitution must be a boolean")
        notes = line.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise err_invalid_request("notes must be a string")
        validated.append({
            "catalog_item_id": catalog_item_id,
            "requested_qty": requested_qty,
            "allows_substitution": allows_substitution,
            "notes": notes,
        })
    return validated


@bp.route("/chandlery/vessel-calls/<vc_id>/requisitions", methods=["POST"])
@require_roles("VesselCateringOfficer")
def create_requisition(user_id, role, vc_id):
    vc = db.vessel_calls.get(vc_id)
    if vc is None:
        raise err_vessel_call_not_found()
    # entity-backed ownership: officer's X-User-ID must equal the call's id
    if user_id != vc_id:
        raise err_insufficient_permissions()
    body = get_body()
    lines = _validate_requisition_lines(req_lines_array(body, "lines", min_len=1))
    req_record = {
        "vessel_call_id": vc_id,
        "title": req_string(body, "title"),
        "lines": lines,
        "status": "DRAFT",
        "submitted_at": None,
    }
    stamp_new(req_record)
    db.requisitions[req_record["id"]] = req_record
    return success_object(req_record, status=201)


@bp.route("/chandlery/vessel-calls/<vc_id>/requisitions", methods=["GET"])
@require_any_authenticated
def list_requisitions(user_id, role, vc_id):
    if vc_id not in db.vessel_calls:
        raise err_vessel_call_not_found()
    items = [r for r in db.requisitions.values() if r["vessel_call_id"] == vc_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


@bp.route("/chandlery/requisitions/<req_id>", methods=["GET"])
@require_any_authenticated
def get_requisition(user_id, role, req_id):
    r = db.requisitions.get(req_id)
    if r is None:
        raise err_requisition_not_found()
    return success_object(r)


@bp.route("/chandlery/requisitions/<req_id>/submit", methods=["POST"])
@require_roles("VesselCateringOfficer")
def submit_requisition(user_id, role, req_id):
    r = db.requisitions.get(req_id)
    if r is None:
        raise err_requisition_not_found()
    # ownership: acting officer must own the call
    if user_id != r["vessel_call_id"]:
        raise err_insufficient_permissions()
    if r["status"] != "DRAFT":
        raise err_requisition_not_submittable()
    r["status"] = "SUBMITTED"
    r["submitted_at"] = db.now_iso()
    touch(r)
    return success_object(r)


@bp.route("/chandlery/requisitions/<req_id>/recall", methods=["POST"])
@require_roles("VesselCateringOfficer")
def recall_requisition(user_id, role, req_id):
    r = db.requisitions.get(req_id)
    if r is None:
        raise err_requisition_not_found()
    if user_id != r["vessel_call_id"]:
        raise err_insufficient_permissions()
    # PRD §3.3: recall is blocked while any quotation on the requisition sits
    # in SENT (ERR_REQUISITION_HAS_LIVE_QUOTATION); recalling from any state
    # other than SUBMITTED is ERR_REQUISITION_NOT_RECALLABLE. The live-
    # quotation block is the reachable failure when a SENT quotation exists
    # (the requisition is then QUOTED), so it is checked first.
    for q in db.quotations.values():
        if q["requisition_id"] == req_id and q["status"] == "SENT":
            raise err_requisition_has_live_quotation()
    if r["status"] != "SUBMITTED":
        raise err_requisition_not_recallable()
    r["status"] = "DRAFT"
    touch(r)
    return success_object(r)
