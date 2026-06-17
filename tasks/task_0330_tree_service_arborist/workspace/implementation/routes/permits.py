"""Permit routes (nested under work order) + submit/request-changes/decide."""
from flask import Blueprint

import db
import errors
import lookups
import response
from errors import ApiError
from helpers import as_bool, as_string, get_json_body, parse_pagination
from middleware import ALL_ROLES, require_roles

bp = Blueprint("permits", __name__)


@bp.post("/work-orders/<wid>/permits")
@require_roles("Arborist")
def create_permit(wid):
    wo = lookups.get_work_order(wid)
    if wo["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(errors.ERR_WORK_ORDER_TERMINAL, 409, "Work order is terminal.")
    body = get_json_body()
    authority_ref = as_string(body, "authority_ref")
    covers_heritage = as_bool(body, "covers_heritage", default=False)
    obj = db.stamp_new({
        "work_order_id": wid,
        "authority_ref": authority_ref,
        "covers_heritage": covers_heritage,
        "revision_count": 0,
        "status": "DRAFT",
    })
    db.permits[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/work-orders/<wid>/permits")
@require_roles(*ALL_ROLES)
def list_permits(wid):
    lookups.get_work_order(wid)
    limit, offset = parse_pagination()
    items = db.sort_by_created([p for p in db.permits.values() if p["work_order_id"] == wid])
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/work-orders/<wid>/permits/<pid>")
@require_roles(*ALL_ROLES)
def get_permit(wid, pid):
    lookups.get_work_order(wid)
    obj = lookups.get_permit_on_wo(wid, pid)
    return response.success(db.public(obj), 200)


@bp.post("/work-orders/<wid>/permits/<pid>/submit")
@require_roles("Arborist")
def submit_permit(wid, pid):
    wo = lookups.get_work_order(wid)
    permit = lookups.get_permit_on_wo(wid, pid)
    if permit["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Submit only allowed from DRAFT or CHANGES_REQUESTED.")
    if not wo["requires_permit"]:
        raise ApiError(errors.ERR_PERMIT_NOT_REQUIRED, 409,
                       "Work order does not require a permit.")
    permit["status"] = "UNDER_REVIEW"
    db.touch(permit)
    return response.success(db.public(permit), 200)


@bp.post("/work-orders/<wid>/permits/<pid>/request-changes")
@require_roles("Dispatcher")
def request_changes(wid, pid):
    lookups.get_work_order(wid)
    permit = lookups.get_permit_on_wo(wid, pid)
    if permit["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Request-changes only allowed from UNDER_REVIEW.")
    permit["status"] = "CHANGES_REQUESTED"
    permit["revision_count"] += 1
    db.touch(permit)
    return response.success(db.public(permit), 200)


@bp.post("/work-orders/<wid>/permits/<pid>/decide")
@require_roles("Dispatcher")
def decide_permit(wid, pid):
    lookups.get_work_order(wid)
    permit = lookups.get_permit_on_wo(wid, pid)
    body = get_json_body()
    if "decision" not in body or body["decision"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Missing required field: decision.")
    decision = body["decision"]
    if decision not in ("APPROVE", "DENY"):
        raise ApiError(errors.ERR_INVALID_ENUM, 400, f"Illegal decision: {decision!r}.")
    if permit["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Decide only allowed from UNDER_REVIEW.")
    permit["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    db.touch(permit)
    return response.success(db.public(permit), 200)
