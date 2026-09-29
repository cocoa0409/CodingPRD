"""Rebate accruals, settlements and returns on job-quoted material."""
from flask import Blueprint, request

import clock
import db
import response
import validate as v
from errors import ApiError
from middleware import auth, check_scope, scope_list
from services import credit as credit_svc
from services import rebate as rebate_svc
from services import returns_calc
from services import tier as tier_svc

bp = Blueprint("finance", __name__)

RETURN_REASONS = ("OVER_ORDERED", "DAMAGED", "JOB_CANCELLED", "WRONG_ITEM")
ACCRUAL_READ_ROLES = ("CreditManager", "ContractorAdmin")
RETURN_READ_ROLES = ("ContractorAdmin", "ProDeskAssociate", "CreditManager")


def _order_owner(rec):
    order = db.get("pro_orders", rec["pro_order_id"])
    return order["pro_account_id"] if order else None


# ------------------------------------------------------------ rebate accruals
@bp.get("/pro/rebate-accruals/<rebate_accrual_id>")
def get_accrual(rebate_accrual_id):
    user_id, role = auth(*ACCRUAL_READ_ROLES)
    accrual = db.require("rebate_accruals", rebate_accrual_id)
    check_scope(role, user_id, accrual["pro_account_id"])
    return response.obj(db.public(accrual))


@bp.get("/pro/rebate-accruals")
def list_accruals():
    user_id, role = auth(*ACCRUAL_READ_ROLES)
    records = db.all_of("rebate_accruals")
    for key in ("pro_account_id", "payout_status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, lambda r: r["pro_account_id"])
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


@bp.post("/pro/rebate-accruals/<rebate_accrual_id>/close")
def close_accrual(rebate_accrual_id):
    auth("CreditManager")
    accrual = db.require("rebate_accruals", rebate_accrual_id)
    if accrual["payout_status"] != "ACCRUING":
        raise ApiError("ERR_INVALID_STATE", 409)
    accrual["closed_at"] = clock.now_iso()
    accrual["payout_status"] = "PAYABLE" if accrual["payable_cents"] > 0 else "VOIDED"
    db.touch(accrual)
    if accrual["payout_status"] == "VOIDED":
        account = db.get("pro_accounts", accrual["pro_account_id"])
        if account is not None:
            rebate_svc.recompute_account_total(account)
    return response.obj(db.public(accrual))


@bp.post("/pro/rebate-accruals/<rebate_accrual_id>/pay-out")
def pay_out_accrual(rebate_accrual_id):
    auth("CreditManager")
    accrual = db.require("rebate_accruals", rebate_accrual_id)
    data = v.body()
    payout_reference = v.req_str(data, "payout_reference")
    if accrual["payout_status"] != "PAYABLE":
        raise ApiError("ERR_INVALID_STATE", 409)
    if accrual["payable_cents"] <= 0:
        raise ApiError("ERR_NO_REBATE_PAYABLE", 422)
    accrual["paid_amount_cents"] = accrual["payable_cents"]
    accrual["payout_reference"] = payout_reference
    accrual["payout_status"] = "PAID"
    db.touch(accrual)
    account = db.get("pro_accounts", accrual["pro_account_id"])
    if account is not None:
        rebate_svc.recompute_account_total(account)
    return response.obj(db.public(accrual))


# ------------------------------------------------------------- return requests
@bp.post("/pro/return-requests")
def create_return_request():
    user_id, role = auth("ContractorAdmin")
    data = v.body()
    order = v.resolve_fk(data, "pro_order_id", "pro_orders", "ERR_PRO_ORDER_NOT_FOUND")
    if order is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'pro_order_id' is required.")
    reason_code = v.req_enum(data, "reason_code", RETURN_REASONS)
    entries = v.req_array(data, "lines")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Each lines entry must be an object.")
    resolved = []
    for entry in entries:
        line_id = entry.get("order_line_id")
        line = db.get("order_lines", line_id) if isinstance(line_id, str) else None
        if line is None or line["pro_order_id"] != order["id"]:
            raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404)
        qty = entry.get("qty_units")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Each lines entry needs an integer qty_units >= 1.")
        resolved.append((line, qty))
    check_scope(role, user_id, order["pro_account_id"])
    if order["fulfillment_status"] != "FULFILLED":
        raise ApiError("ERR_ORDER_NOT_FULFILLED", 409)
    for line, qty in resolved:
        remaining = (line["fulfilled_units"] or 0) - (line["returned_units"] or 0)
        if qty > remaining:
            raise ApiError("ERR_RETURN_QTY_EXCEEDS_FULFILLED", 422)

    rec = db.new_record("return_requests", {
        "pro_order_id": order["id"],
        "reason_code": reason_code,
        "lines": [{"order_line_id": line["id"], "qty_units": qty} for line, qty in resolved],
        "valuation_mode": None,
        "gross_refund_cents": None,
        "restocking_fee_pct": None,
        "restocking_fee_cents": None,
        "tax_refund_cents": None,
        "refund_total_cents": None,
        "status": "REQUESTED",
        "approved_by_user_id": None,
        "denied_reason_code": None,
        "credited_at": None,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/return-requests/<return_request_id>")
def get_return_request(return_request_id):
    user_id, role = auth(*RETURN_READ_ROLES)
    req = db.require("return_requests", return_request_id)
    check_scope(role, user_id, _order_owner(req))
    return response.obj(db.public(req))


@bp.get("/pro/return-requests")
def list_return_requests():
    user_id, role = auth(*RETURN_READ_ROLES)
    records = db.all_of("return_requests")
    for key in ("pro_order_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, _order_owner)
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


@bp.post("/pro/return-requests/<return_request_id>/approve")
def approve_return(return_request_id):
    user_id, _role = auth("ProDeskAssociate")
    req = db.require("return_requests", return_request_id)
    order = db.require("pro_orders", req["pro_order_id"])
    if req["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    returns_calc.value(req, order)
    req["approved_by_user_id"] = user_id
    req["status"] = "APPROVED"
    db.touch(req)
    return response.obj(db.public(req))


@bp.post("/pro/return-requests/<return_request_id>/deny")
def deny_return(return_request_id):
    auth("ProDeskAssociate")
    req = db.require("return_requests", return_request_id)
    data = v.body()
    reason_code = v.req_str(data, "reason_code")
    if req["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    req["denied_reason_code"] = reason_code
    req["status"] = "DENIED"
    db.touch(req)
    return response.obj(db.public(req))


@bp.post("/pro/return-requests/<return_request_id>/credit")
def credit_return(return_request_id):
    auth("CreditManager")
    req = db.require("return_requests", return_request_id)
    order = db.require("pro_orders", req["pro_order_id"])
    if req["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if order["credit_status"] not in ("AUTHORIZED", "INVOICED", "PAID"):
        raise ApiError("ERR_INVALID_STATE", 409)

    account = db.require("pro_accounts", order["pro_account_id"])
    req["credited_at"] = clock.now_iso()
    req["status"] = "CREDITED"
    db.touch(req)
    for entry in req["lines"]:
        line = db.get("order_lines", entry["order_line_id"])
        if line is not None:
            line["returned_units"] = (line["returned_units"] or 0) + entry["qty_units"]
            db.touch(line)

    # hop 1
    returns_calc.recompute_order_refunds(order)
    # hop 2
    credit_svc.recompute_exposure(credit_svc.credit_line_of(account["id"]))
    # hop 3
    tier_svc.tier_review(account)
    # hop 4
    rebate_svc.book_clawback(account, req)
    return response.obj(db.public(req))
