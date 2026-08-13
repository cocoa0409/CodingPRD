"""Device Master Record endpoints (PRD section 3.1)."""
from flask import Blueprint, request

from auth import QUALITY_ENGINEER, QUALITY_MANAGER, context, require_role
from domain import (invalidate_in_progress_studies, list_data, serialize,
                    supersede_family_on_approve)
from envelope import pagination_params, success
from errors import ApiError, err_sod, err_stale_version, err_state
from store import DB, bump, new_entity, now
from validate import get_body, get_or_404, req_bool, req_int, req_str

bp = Blueprint("dmrs", __name__)

_PROTOCOL_IN_FLIGHT = (
    "DRAFT", "IQ_EXECUTION", "IQ_REVIEW", "OQ_EXECUTION", "OQ_REVIEW",
    "PQ_EXECUTION", "PQ_REVIEW",
)


def _dup_revision(device_code, revision_code):
    return any(
        d["device_code"] == device_code and d["revision_code"] == revision_code
        for d in DB["dmrs"].values()
    )


@bp.post("/api/device-master-records")
def create_dmr():
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    data = get_body()
    device_code = req_str(data, "device_code")
    revision_code = req_str(data, "revision_code")
    sterile = req_bool(data, "sterile")
    claim = req_int(data, "shelf_life_claim_months", min_value=1)
    # step 12: (device_code, revision_code) unique
    if _dup_revision(device_code, revision_code):
        raise ApiError("ERR_DUPLICATE_DMR_REVISION", 409,
                       "A revision with this device_code and revision_code already exists")
    dmr = new_entity({
        "device_code": device_code,
        "revision_code": revision_code,
        "revision_seq": 1,
        "parent_dmr_id": None,
        "sterile": sterile,
        "shelf_life_claim_months": claim,
        "confirmed_shelf_life_months": None,
        "complaint_rate_per_100k": 0,
        "field_action_review_required": False,
        "author_user_id": uid,
        "approver_user_id": None,
        "approved_at": None,
        "status": "DRAFT",
    })
    DB["dmrs"][dmr["id"]] = dmr
    return success(serialize(dmr), 201)


@bp.get("/api/device-master-records")
def list_dmrs():
    context()
    filters = [
        ("device_code", request.args.get("device_code")),
        ("status", request.args.get("status")),
        ("parent_dmr_id", request.args.get("parent_dmr_id")),
    ]
    items = list_data("dmrs", filters)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return success([serialize(o) for o in page], 200, pagination={
        "limit": limit, "offset": offset, "total_count": len(items),
        "has_more": offset + len(page) < len(items),
    })


@bp.get("/api/device-master-records/<id>")
def get_dmr(id):
    context()
    return success(serialize(get_or_404("dmrs", id)), 200)


@bp.post("/api/device-master-records/<id>/approve")
def approve_dmr(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    dmr = get_or_404("dmrs", id)
    # step 6: segregation of duties (before state-shape per the pipeline)
    if uid == dmr["author_user_id"]:
        raise err_sod()
    # step 7
    if dmr["status"] != "DRAFT":
        raise err_state()
    dmr["status"] = "APPROVED"
    dmr["approver_user_id"] = uid
    dmr["approved_at"] = now()
    bump(dmr)
    supersede_family_on_approve(dmr)
    return success(serialize(dmr), 200)


@bp.post("/api/device-master-records/<id>/obsolete")
def obsolete_dmr(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    dmr = get_or_404("dmrs", id)
    if dmr["status"] not in ("APPROVED", "SUPERSEDED"):
        raise err_state()
    if any(l["dmr_id"] == id and l["disposition_status"] in ("IN_PRODUCTION", "COMPLETED")
           for l in DB["lots"].values()):
        raise ApiError("ERR_LOTS_IN_FLIGHT", 409,
                       "Lots in IN_PRODUCTION or COMPLETED reference this revision")
    if any(p["dmr_id"] == id and p["status"] in _PROTOCOL_IN_FLIGHT
           for p in DB["protocols"].values()):
        raise ApiError("ERR_PROTOCOLS_IN_FLIGHT", 409,
                       "Validation protocols in flight reference this revision")
    dmr["status"] = "OBSOLETE"
    bump(dmr)
    invalidate_in_progress_studies(id)
    return success(serialize(dmr), 200)


@bp.post("/api/device-master-records/<id>/revisions")
def create_revision(id):
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    data = get_body()
    revision_code = req_str(data, "revision_code")
    claim = req_int(data, "shelf_life_claim_months", min_value=1)
    sterile = req_bool(data, "sterile")
    expected = req_int(data, "expected_dmr_version")
    parent = get_or_404("dmrs", id)
    # step 5: optimistic concurrency
    if expected != parent["version"]:
        raise err_stale_version()
    # parent revision must be APPROVED
    if parent["status"] != "APPROVED":
        raise ApiError("ERR_DMR_NOT_APPROVED", 409,
                       "Revision creation requires the parent revision in APPROVED")
    # step 12
    if _dup_revision(parent["device_code"], revision_code):
        raise ApiError("ERR_DUPLICATE_DMR_REVISION", 409,
                       "A revision with this device_code and revision_code already exists")
    dmr = new_entity({
        "device_code": parent["device_code"],
        "revision_code": revision_code,
        "revision_seq": parent["revision_seq"] + 1,
        "parent_dmr_id": parent["id"],
        "sterile": sterile,
        "shelf_life_claim_months": claim,
        "confirmed_shelf_life_months": None,
        "complaint_rate_per_100k": 0,
        "field_action_review_required": False,
        "author_user_id": uid,
        "approver_user_id": None,
        "approved_at": None,
        "status": "DRAFT",
    })
    DB["dmrs"][dmr["id"]] = dmr
    # OCC side effect: the parent revision's version advances by one
    bump(parent)
    return success(serialize(dmr), 201)
