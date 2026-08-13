"""ReissueRequest endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    REISSUE_REASONS,
    emit_audit,
    get_order,
    get_reissue_request,
    lines_of_order,
    ser_reissue_request,
    sorted_created,
    stamp,
    touch,
)
from util import as_bool, as_enum, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("reissues", __name__)

READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]
REVIEWER = ["RegistrarReviewer"]


@bp.post("/registrar/orders/<oid>/reissue-requests")
def open_reissue(oid):
    user_id, role = auth(["Student"])
    original = get_order(oid)
    data = body()
    reject_unknown_fields(data, {"reason", "fee_waived"})
    reason = as_enum(required(data, "reason"), "reason", REISSUE_REASONS)
    fee_waived = data.get("fee_waived", False)
    if not isinstance(fee_waived, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "fee_waived must be a boolean")

    if original["fulfillment_status"] != "DELIVERED":
        raise ApiError(
            "ERR_REISSUE_SOURCE_INVALID",
            422,
            "Reissue source order is not DELIVERED",
        )

    rec = {
        "id": new_id(),
        "original_order_id": original["id"],
        "reason": reason,
        "status": "REQUESTED",
        "replacement_order_id": None,
        "reviewed_by": None,
        "fee_waived": fee_waived,
    }
    stamp(rec)
    DB["reissue_requests"][rec["id"]] = rec
    original["fulfillment_status"] = "REISSUE_PENDING"
    touch(original)
    return ok(ser_reissue_request(rec), status=201)


@bp.get("/registrar/reissue-requests")
def list_reissues():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["reissue_requests"].values())
    ooid = request.args.get("original_order_id")
    if ooid is not None:
        items = [r for r in items if r["original_order_id"] == ooid]
    roid = request.args.get("replacement_order_id")
    if roid is not None:
        items = [r for r in items if r.get("replacement_order_id") == roid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_reissue_request(r) for r in page], total, limit, offset)


@bp.get("/registrar/reissue-requests/<rid>")
def get_one_reissue(rid):
    auth(READ_ROLES)
    return ok(ser_reissue_request(get_reissue_request(rid)))


def _segregation_check(rr, original, user_id):
    if user_id == original["student_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Reviewer may not act on a reissue for their own order",
        )


@bp.post("/registrar/reissue-requests/<rid>/approve")
def approve_reissue(rid):
    user_id, role = auth(REVIEWER)
    rr = get_reissue_request(rid)
    original = get_order(rr["original_order_id"])
    _segregation_check(rr, original, user_id)
    if rr["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "ReissueRequest is not REQUESTED")
    if original["fulfillment_status"] != "REISSUE_PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Original order is not REISSUE_PENDING"
        )

    rr["status"] = "APPROVED"
    rr["reviewed_by"] = user_id
    touch(rr)

    # Create the replacement order + copied line items.
    replacement = {
        "id": new_id(),
        "student_id": original["student_id"],
        "order_kind": original["order_kind"],
        "fulfillment_status": "READY_TO_FULFILL",
        "payment_status": "WAIVED" if rr["fee_waived"] else "UNPAID",
        "rush_requested": original["rush_requested"],
        "rush_qualified": False,
        "quoted_fee_cents": 0,
        "final_fee_cents": 0,
        "submitted_at": original["submitted_at"],
        "cancelled_reason": None,
        "reissue_of_order_id": original["id"],
    }
    stamp(replacement)
    DB["orders"][replacement["id"]] = replacement

    for line in lines_of_order(original["id"]):
        copy = {
            "id": new_id(),
            "order_id": replacement["id"],
            "recipient_id": line["recipient_id"],
            "delivery_kind": line["delivery_kind"],
            "quantity": line["quantity"],
            "unit_price_cents": line["unit_price_cents"],
            "line_status": "QUEUED",
            "tracking_ref": None,
            "archived_retrieval_id": line.get("archived_retrieval_id"),
        }
        stamp(copy)
        DB["order_line_items"][copy["id"]] = copy

    rr["replacement_order_id"] = replacement["id"]
    original["fulfillment_status"] = "IN_TRANSIT"
    touch(original)
    touch(replacement)
    emit_audit("ReissueRequest", rr["id"], role, user_id, "REISSUE_APPROVED")
    return ok(ser_reissue_request(rr))


@bp.post("/registrar/reissue-requests/<rid>/reject")
def reject_reissue(rid):
    user_id, role = auth(REVIEWER)
    rr = get_reissue_request(rid)
    original = get_order(rr["original_order_id"])
    _segregation_check(rr, original, user_id)
    if rr["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "ReissueRequest is not REQUESTED")
    rr["status"] = "REJECTED"
    rr["reviewed_by"] = user_id
    touch(rr)
    original["fulfillment_status"] = "DELIVERED"
    touch(original)
    return ok(ser_reissue_request(rr))
