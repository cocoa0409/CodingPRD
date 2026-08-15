"""RestockRequest endpoints (requests are opened by the reorder trigger)."""
from flask import Blueprint, request

from db import store, touch
from errors import err_not_found, err_invalid_state
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import wall_now
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("restock", __name__)

ROLES = ["OpsAdmin", "Technician"]


def _get_request(request_id):
    r = store.restock_requests.get(request_id)
    if r is None:
        raise err_not_found("RestockRequest not found")
    return r


@bp.route("/roadside/restock-requests/<restockRequestId>", methods=["GET"])
def get_request(restockRequestId):
    auth(ROLES)
    return success(serialize("restock", _get_request(restockRequestId)))


@bp.route("/roadside/restock-requests", methods=["GET"])
def list_requests():
    auth(ROLES)
    limit, offset = parse_pagination(request.args)
    item_f = request.args.get("van_stock_item_id")
    tech_f = request.args.get("technician_id")
    status_f = request.args.get("status")
    items = sorted(store.restock_requests.values(), key=lambda r: r["_seq"])
    if item_f is not None:
        items = [r for r in items if r["van_stock_item_id"] == item_f]
    if tech_f is not None:
        items = [r for r in items if r["technician_id"] == tech_f]
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("restock", r) for r in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/restock-requests/<restockRequestId>/approve",
          methods=["POST"])
def approve(restockRequestId):
    auth(["OpsAdmin"])
    rec = _get_request(restockRequestId)
    validate_body(request.get_json(silent=True), [])
    if rec["status"] != "PENDING":
        raise err_invalid_state("Approve requires status PENDING")
    rec["status"] = "APPROVED"
    touch(rec, wall_now())
    return success(serialize("restock", rec))


@bp.route("/roadside/restock-requests/<restockRequestId>/fulfill",
          methods=["POST"])
def fulfill(restockRequestId):
    auth(["OpsAdmin"])
    rec = _get_request(restockRequestId)
    vals = validate_body(request.get_json(silent=True), [
        Field("fulfilled_qty", "int", required=True, min_val=1),
    ])
    if rec["status"] != "APPROVED":
        raise err_invalid_state("Fulfill requires status APPROVED")
    rec["status"] = "FULFILLED"
    rec["fulfilled_qty"] = vals["fulfilled_qty"]
    touch(rec, wall_now())
    item = store.van_stock.get(rec["van_stock_item_id"])
    if item is not None:
        item["qty_on_hand"] += vals["fulfilled_qty"]
        touch(item, wall_now())
    return success(serialize("restock", rec))


@bp.route("/roadside/restock-requests/<restockRequestId>/reject",
          methods=["POST"])
def reject(restockRequestId):
    auth(["OpsAdmin"])
    rec = _get_request(restockRequestId)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string", required=True),
    ])
    if rec["status"] != "PENDING":
        raise err_invalid_state("Reject requires status PENDING")
    rec["status"] = "REJECTED"
    rec["reject_reason"] = vals["reason"]
    touch(rec, wall_now())
    return success(serialize("restock", rec))
