"""Return authorization endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_RMA_NOT_REQUESTED, ERR_RMA_NOT_APPROVED, ERR_RMA_NOT_RECEIVED,
    ERR_RMA_ORDER_NOT_COMPLETED, ERR_RETURN_EXPIRED_CHEMICAL,
    ERR_RMA_LOT_EXPIRED_SINCE_REQUEST,
)
from middleware import check_account_ownership, get_caller, require_roles
from response import success_object
from routes.helpers import get_one, list_response, public
from services import new_record, rma_credit, touch
from util import CLOCK, parse_date
from validate import (
    get_body, req_enum, req_int, req_str, require_path_resource, require_ref,
)

bp = Blueprint("rmas", __name__)

RMA_READ_ROLES = ["BranchManager", "WarehouseLead", "Account"]
RMA_REASONS = {"DEFECTIVE", "WRONG_ITEM", "OVERSTOCK", "EXPIRED"}


def _require_rma(rid):
    return require_path_resource("return_authorizations", rid)


@bp.post("/pool-supply/return-authorizations")
def create_rma():
    caller = get_caller()
    require_roles(caller, ["Account", "BranchManager"])
    body = get_body()
    account_id = req_str(body, "account_id")
    order_id = req_str(body, "order_id")
    product_id = req_str(body, "product_id")
    lot_id = req_str(body, "lot_id")
    qty = req_int(body, "qty", minimum=1)
    reason = req_enum(body, "reason", RMA_REASONS)
    # ownership (priority 3)
    check_account_ownership(caller, account_id)
    # existence (priority 4)
    require_ref("accounts", account_id, "account_id")
    require_ref("orders", order_id, "order_id")
    product = require_ref("products", product_id, "product_id")
    lot = require_ref("stock_lots", lot_id, "lot_id")
    # priority 15: expired chemicals are hazmat waste — refused at request time
    if (
        reason == "EXPIRED"
        and product["product_family"] == "CHEMICAL"
        and lot["expiry_date"] is not None
        and parse_date(lot["expiry_date"]) <= CLOCK.today()
    ):
        raise_error(ERR_RETURN_EXPIRED_CHEMICAL, "expired chemicals cannot be returned through RMA")
    rec = new_record("return_authorizations", {
        "account_id": account_id,
        "order_id": order_id,
        "product_id": product_id,
        "lot_id": lot_id,
        "qty": qty,
        "reason": reason,
        "restocking_fee_pct": None,
        "credit_cents": None,
        "status": "REQUESTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/pool-supply/return-authorizations")
def list_rmas():
    filters = {
        "account_id": request.args.get("account_id"),
        "order_id": request.args.get("order_id"),
        "status": request.args.get("status"),
        "product_id": request.args.get("product_id"),
        "lot_id": request.args.get("lot_id"),
    }
    return list_response("return_authorizations", RMA_READ_ROLES, filters)


@bp.get("/pool-supply/return-authorizations/<rid>")
def get_rma(rid):
    return get_one("return_authorizations", rid, RMA_READ_ROLES)


@bp.post("/pool-supply/return-authorizations/<rid>/approve")
def approve_rma(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    rma = _require_rma(rid)
    if rma["status"] != "REQUESTED":
        raise_error(ERR_RMA_NOT_REQUESTED, "approve requires REQUESTED")
    order = db["orders"][rma["order_id"]]
    if order["fulfillment_status"] != "COMPLETED":
        raise_error(ERR_RMA_ORDER_NOT_COMPLETED, "original order must be COMPLETED")
    product = db["products"][rma["product_id"]]
    lot = db["stock_lots"][rma["lot_id"]]
    # re-run the expiry guard for EXPIRED-reason chemical returns
    if (
        rma["reason"] == "EXPIRED"
        and product["product_family"] == "CHEMICAL"
        and lot["expiry_date"] is not None
        and parse_date(lot["expiry_date"]) <= CLOCK.today()
    ):
        raise_error(ERR_RMA_LOT_EXPIRED_SINCE_REQUEST, "chemical lot expired since the request")
    credit, fee = rma_credit(rma["order_id"], rma["product_id"], rma["qty"], rma["reason"])
    rma["restocking_fee_pct"] = float(fee) if fee != 0 else 0
    rma["credit_cents"] = credit
    rma["status"] = "APPROVED"
    touch(rma)
    return success_object(public(rma))


@bp.post("/pool-supply/return-authorizations/<rid>/deny")
def deny_rma(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    rma = _require_rma(rid)
    if rma["status"] != "REQUESTED":
        raise_error(ERR_RMA_NOT_REQUESTED, "deny requires REQUESTED")
    rma["status"] = "DENIED"
    touch(rma)
    return success_object(public(rma))


@bp.post("/pool-supply/return-authorizations/<rid>/receive")
def receive_rma(rid):
    caller = get_caller()
    require_roles(caller, ["WarehouseLead"])
    rma = _require_rma(rid)
    if rma["status"] != "APPROVED":
        raise_error(ERR_RMA_NOT_APPROVED, "receive requires APPROVED")
    product = db["products"][rma["product_id"]]
    lot = db["stock_lots"][rma["lot_id"]]
    if (
        product["product_family"] == "CHEMICAL"
        and lot["expiry_date"] is not None
        and parse_date(lot["expiry_date"]) <= CLOCK.today()
    ):
        raise_error(ERR_RMA_LOT_EXPIRED_SINCE_REQUEST, "chemical lot expired before receipt")
    # chemicals are NEVER restocked; EXPIRED goods never restock
    if rma["reason"] != "EXPIRED" and product["product_family"] != "CHEMICAL":
        lot["qty_on_hand"] += rma["qty"]
        touch(lot)
    rma["status"] = "RECEIVED"
    touch(rma)
    return success_object(public(rma))


@bp.post("/pool-supply/return-authorizations/<rid>/credit")
def credit_rma(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    rma = _require_rma(rid)
    if rma["status"] != "RECEIVED":
        raise_error(ERR_RMA_NOT_RECEIVED, "credit requires RECEIVED")
    rma["status"] = "CREDITED"  # returns never move ytd_volume_cents
    touch(rma)
    return success_object(public(rma))
