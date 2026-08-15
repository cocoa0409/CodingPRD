"""WarrantyClaim endpoints: file, review, approve, reject (segregated)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, forbid_unless_owner, ALL_BUSINESS
from calc import warranty_coverage, MONTH_S, rhu
from db import store, clock
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CUSTOMER_NOT_FOUND, ERR_ORDER_LINE_NOT_FOUND,
                    ERR_CLAIM_NOT_FOUND, ERR_WARRANTY_PERIOD_ELAPSED,
                    ERR_SEGREGATION_OF_DUTIES, ERR_REOPEN_LIMIT_REACHED)
from helpers import (new_record, touch, get_or_404, post_ledger, ser_claim,
                     sort_asc)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_enum, bad)

bp = Blueprint("warranty", __name__)

FAULT_CATEGORIES = {"DOA", "PREMATURE_FAILURE", "COSMETIC"}


@bp.post("/aog/warranty-claims")
def create_claim():
    uid, role = require_roles("CustomerContact")
    body = get_body()
    customer_id = as_str(req_present(body, "customer_id"), "customer_id")
    line_id = as_str(req_present(body, "order_line_id"), "order_line_id")
    fault = as_enum(req_present(body, "fault_category"), "fault_category",
                    FAULT_CATEGORIES)
    description = as_str(req_present(body, "description"), "description")
    forbid_unless_owner(role, uid, customer_id)
    get_or_404("customers", customer_id, ERR_CUSTOMER_NOT_FOUND, "Customer")
    line = get_or_404("order_lines", line_id, ERR_ORDER_LINE_NOT_FOUND,
                      "OrderLine")
    order = store["orders"].get(line["order_id"])
    if order is None or order["customer_id"] != customer_id:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "order_line_id does not belong to this customer")
    if line.get("_delivered_dt") is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Order line has not been delivered")
    part = store["parts"].get(line["part_id"])
    horizon = line["_delivered_dt"] + timedelta(
        seconds=part["warranty_months"] * MONTH_S)
    if clock.current >= horizon:
        raise ApiError(ERR_WARRANTY_PERIOD_ELAPSED, 422,
                       "Warranty period has elapsed")
    months = int((clock.current - line["_delivered_dt"]).total_seconds()) \
        // MONTH_S
    rec = new_record("claims", {
        "customer_id": customer_id,
        "order_line_id": line["id"],
        "fault_category": fault,
        "description": description,
        "months_in_service": months,
        "coverage_pct": 0,
        "credit_cents": 0,
        "reviewed_by": None,
        "reopen_count": 0,
        "fraud_flag": False,
        "status": "FILED",
    })
    return success(ser_claim(rec), 201)


@bp.get("/aog/warranty-claims")
def list_claims():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["claims"].values())
    if role == "CustomerContact":
        recs = [c for c in recs if c["customer_id"] == uid]
    q = request.args
    if q.get("customer_id") is not None:
        recs = [c for c in recs if c["customer_id"] == q.get("customer_id")]
    if q.get("order_line_id") is not None:
        recs = [c for c in recs if c["order_line_id"] == q.get("order_line_id")]
    if q.get("status") is not None:
        recs = [c for c in recs if c["status"] == q.get("status")]
    return paged([ser_claim(c) for c in sort_asc(recs)], limit, offset)


@bp.get("/aog/warranty-claims/<cid>")
def get_claim(cid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("claims", cid, ERR_CLAIM_NOT_FOUND, "WarrantyClaim")
    return success(ser_claim(rec))


@bp.post("/aog/warranty-claims/<cid>/review")
def review_claim(cid):
    uid, _ = require_roles("WarrantyAdjuster")
    claim = get_or_404("claims", cid, ERR_CLAIM_NOT_FOUND, "WarrantyClaim")
    if claim["status"] == "REJECTED":
        if claim["reopen_count"] >= 1:
            raise ApiError(ERR_REOPEN_LIMIT_REACHED, 409,
                           "Claim has already been reopened once")
        claim["reopen_count"] += 1
    elif claim["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a FILED or REJECTED claim can be reviewed")
    claim["reviewed_by"] = uid
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success(ser_claim(claim))


def _decide_claim(cid, approve):
    uid, _ = require_roles("WarrantyApprover")
    claim = get_or_404("claims", cid, ERR_CLAIM_NOT_FOUND, "WarrantyClaim")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an UNDER_REVIEW claim can be decided")
    if uid == claim["reviewed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Approver must differ from the reviewer")
    return claim, uid


@bp.post("/aog/warranty-claims/<cid>/approve")
def approve_claim(cid):
    claim, _ = _decide_claim(cid, True)
    line = store["order_lines"].get(claim["order_line_id"])
    months = int((clock.current - line["_delivered_dt"]).total_seconds()) \
        // MONTH_S
    coverage = warranty_coverage(months)
    credit = rhu(line["line_total_cents"] * coverage)
    claim["months_in_service"] = months
    claim["coverage_pct"] = float(coverage)
    claim["credit_cents"] = credit
    claim["status"] = "APPROVED"
    touch(claim)
    if credit > 0:
        post_ledger(claim["customer_id"], "WARRANTY_CREDIT", credit,
                    "WARRANTY_CLAIM", claim["id"])
    claim["status"] = "CREDIT_ISSUED"
    touch(claim)
    return success(ser_claim(claim))


@bp.post("/aog/warranty-claims/<cid>/reject")
def reject_claim(cid):
    claim, _ = _decide_claim(cid, False)
    body = get_body()
    fraud = body.get("fraud_flag", False)
    if not isinstance(fraud, bool):
        bad("fraud_flag must be a boolean")
    claim["fraud_flag"] = fraud
    claim["status"] = "REJECTED"
    touch(claim)
    if fraud:
        customer = store["customers"].get(claim["customer_id"])
        if customer is not None:
            customer["warranty_fraud_flags"] += 1
            touch(customer)
    return success(ser_claim(claim))
