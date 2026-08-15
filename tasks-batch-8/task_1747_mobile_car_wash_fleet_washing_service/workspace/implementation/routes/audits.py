"""QualityAudit endpoints."""

import uuid

from flask import Blueprint, request

from db import store
from serialize import ser_audit, customer_of_audit
from services import create_rewash_order, has_open_rewash
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_int, touch, ApiError,
)
from errors import ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE

bp = Blueprint("audits", __name__)

SCORE_FIELDS = ("exterior_score", "wheels_score", "glass_score", "trim_score",
                "water_spotting_score")


@bp.post("/fleet-wash/quality-audits")
def create_audit():
    uid, role = caller()
    require_role(role, {"QualityAuditor"})
    body = get_body()
    wash_order_id = req_str(body, "wash_order_id")
    order = store.orders.get(wash_order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, "WashOrder %s not found" % wash_order_id)
    scores = {}
    for f in SCORE_FIELDS:
        v = req_int(body, f)
        if v < 0 or v > 20:
            raise ApiError(ERR_VALIDATION, "%s must be between 0 and 20" % f)
        scores[f] = v
    if order["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, "WashOrder is not COMPLETED")
    total = sum(scores.values())
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": store.clock,
        "wash_order_id": wash_order_id,
        "auditor_id": uid,
        "exterior_score": scores["exterior_score"],
        "wheels_score": scores["wheels_score"],
        "glass_score": scores["glass_score"],
        "trim_score": scores["trim_score"],
        "water_spotting_score": scores["water_spotting_score"],
        "total_score": total,
        "result": "PASS" if total >= 80 else "FAIL",
        "_seq": store.next_seq(),
        "created_at_sort": store.clock,
    }
    store.audits[rec["id"]] = rec
    if rec["result"] == "FAIL" and not has_open_rewash(order["id"]):
        create_rewash_order(order)
        order["status"] = "REWASH_PENDING"
        touch(order)
    return respond(ser_audit(rec), 201)


@bp.get("/fleet-wash/quality-audits/<aid>")
def get_audit(aid):
    uid, role = caller()
    rec = store.audits.get(aid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "QualityAudit %s not found" % aid)
    if role == "Customer" and customer_of_audit(rec) != uid:
        forbid("Customers may only access audits of their own orders")
    return respond(ser_audit(rec), 200)


@bp.get("/fleet-wash/quality-audits")
def list_audits():
    uid, role = caller()
    wash_order_id = request.args.get("wash_order_id")
    recs = list(store.audits.values())
    if role == "Customer":
        recs = [a for a in recs if customer_of_audit(a) == uid]
    if wash_order_id is not None:
        recs = [a for a in recs if a["wash_order_id"] == wash_order_id]
    return paginate(recs, ser_audit)
