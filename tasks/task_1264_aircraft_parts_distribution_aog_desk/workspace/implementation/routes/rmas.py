"""ReturnAuthorization endpoints: create (auto-approved), receive."""

from flask import Blueprint, request

from auth import require_roles, forbid_unless_owner, ALL_BUSINESS
from calc import restock_fee, DAY_S
from db import store, clock
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CUSTOMER_NOT_FOUND, ERR_ORDER_LINE_NOT_FOUND,
                    ERR_RMA_NOT_FOUND, ERR_RETURN_WINDOW_CLOSED)
from helpers import (new_record, touch, get_or_404, bump_unit_status,
                     post_ledger, ser_rma, sort_asc)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_enum)

bp = Blueprint("rmas", __name__)


@bp.post("/aog/return-authorizations")
def create_rma():
    uid, role = require_roles("CustomerContact")
    body = get_body()
    customer_id = as_str(req_present(body, "customer_id"), "customer_id")
    line_id = as_str(req_present(body, "order_line_id"), "order_line_id")
    reason = as_str(req_present(body, "reason"), "reason")
    forbid_unless_owner(role, uid, customer_id)
    get_or_404("customers", customer_id, ERR_CUSTOMER_NOT_FOUND, "Customer")
    line = get_or_404("order_lines", line_id, ERR_ORDER_LINE_NOT_FOUND,
                      "OrderLine")
    order = store["orders"].get(line["order_id"])
    if order is None or order["customer_id"] != customer_id:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "order_line_id does not belong to this customer")
    if line["sale_type"] != "OUTRIGHT":
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Only OUTRIGHT lines may be returned")
    if line.get("_delivered_dt") is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Order line has not been delivered")
    days = int((clock.current - line["_delivered_dt"]).total_seconds()) \
        // DAY_S
    if days > 30:
        raise ApiError(ERR_RETURN_WINDOW_CLOSED, 422,
                       "Return requested more than 30 days after delivery")
    rec = new_record("rmas", {
        "customer_id": customer_id,
        "order_line_id": line["id"],
        "reason": reason,
        "days_since_delivery": days,
        "restock_fee_cents": 0,
        "credit_cents": 0,
        "condition_grade": None,
        "status": "APPROVED",
    })
    return success(ser_rma(rec), 201)


@bp.get("/aog/return-authorizations")
def list_rmas():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["rmas"].values())
    if role == "CustomerContact":
        recs = [r for r in recs if r["customer_id"] == uid]
    q = request.args
    if q.get("customer_id") is not None:
        recs = [r for r in recs if r["customer_id"] == q.get("customer_id")]
    if q.get("order_line_id") is not None:
        recs = [r for r in recs if r["order_line_id"] == q.get("order_line_id")]
    if q.get("status") is not None:
        recs = [r for r in recs if r["status"] == q.get("status")]
    return paged([ser_rma(r) for r in sort_asc(recs)], limit, offset)


@bp.get("/aog/return-authorizations/<rid>")
def get_rma(rid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("rmas", rid, ERR_RMA_NOT_FOUND, "ReturnAuthorization")
    return success(ser_rma(rec))


@bp.post("/aog/return-authorizations/<rid>/receive")
def receive_rma(rid):
    require_roles("WarehouseOperator")
    rma = get_or_404("rmas", rid, ERR_RMA_NOT_FOUND, "ReturnAuthorization")
    body = get_body()
    grade = as_enum(req_present(body, "condition_grade"), "condition_grade",
                    {"RESALEABLE", "DAMAGED"})
    if rma["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an APPROVED return authorization can be "
                       "received")
    line = store["order_lines"].get(rma["order_line_id"])
    days = int((clock.current - line["_delivered_dt"]).total_seconds()) \
        // DAY_S
    rma["days_since_delivery"] = days
    rma["condition_grade"] = grade
    unit = store["units"].get(line["allocated_unit_id"])
    if grade == "RESALEABLE":
        fee = restock_fee(line["line_total_cents"], days)
        rma["restock_fee_cents"] = fee
        rma["credit_cents"] = line["line_total_cents"] - fee
        if unit is not None:
            bump_unit_status(unit, "UNDER_INSPECTION")
            bump_unit_status(unit, "AVAILABLE")
        rma["status"] = "RECEIVED"
        touch(rma)
        if rma["credit_cents"] > 0:
            post_ledger(rma["customer_id"], "RESTOCK_CREDIT",
                        rma["credit_cents"], "RETURN_AUTH", rma["id"])
    else:  # DAMAGED: no fee, no credit, no ledger entry
        rma["restock_fee_cents"] = 0
        rma["credit_cents"] = 0
        if unit is not None:
            bump_unit_status(unit, "UNDER_INSPECTION")
            bump_unit_status(unit, "QUARANTINED")
        rma["status"] = "RECEIVED"
        touch(rma)
    rma["status"] = "SETTLED"
    touch(rma)
    return success(ser_rma(rma))
