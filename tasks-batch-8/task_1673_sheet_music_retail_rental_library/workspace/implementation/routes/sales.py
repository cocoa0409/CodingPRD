"""Retail sales and sale settlement (PRD 3.8)."""
from flask import Blueprint, request

import calc
from db import db
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PERUSAL_REQUEST_NOT_FOUND,
    ERR_SALE_RECORD_NOT_FOUND,
    ERR_WORK_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_sale
from services import get_or_404, maybe_restore_standing
from util import is_int, new_record, touch
from routes.helpers import body, paginate, require_fields

bp = Blueprint("sales", __name__)

READ_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "Customer")


@bp.post("/library/sale-records")
def create_sale():
    require_auth("LibraryClerk", "BillingManager")
    data = body()
    require_fields(data, ["account_id", "work_id", "quantity"])
    account = db["customer_accounts"].get(data["account_id"])
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 404, "CustomerAccount not found")
    work = db["works"].get(data["work_id"])
    if work is None:
        raise ApiError(ERR_WORK_NOT_FOUND, 404, "Work not found")
    if not is_int(data["quantity"]) or data["quantity"] < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "quantity must be an integer >= 1")
    perusal_id = data.get("perusal_request_id")
    if perusal_id is not None and perusal_id not in db["perusal_requests"]:
        raise ApiError(ERR_PERUSAL_REQUEST_NOT_FOUND, 404, "PerusalRequest not found")
    # Conversion discount applies only when perusal_request_id is present.
    unit = calc.conversion_unit_price(work["sale_price_cents"], discounted=perusal_id is not None)
    total = unit * data["quantity"]
    rec = new_record()
    rec.update(
        {
            "account_id": account["id"],
            "work_id": work["id"],
            "quantity": data["quantity"],
            "unit_price_cents": unit,
            "total_cents": total,
            "balance_due_cents": total,
            "perusal_request_id": perusal_id,
            "status": "INVOICED",
        }
    )
    db["sale_records"][rec["id"]] = rec
    touch(account)  # exposure recompute at creation
    return success_object(ser_sale(rec), status=201)


@bp.get("/library/sale-records")
def list_sales():
    require_auth(*READ_ROLES)
    rows = list(db["sale_records"].values())
    for param in ("account_id", "work_id", "perusal_request_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [s for s in rows if s.get(param) == v]
    return paginate(rows, ser_sale)


@bp.get("/library/sale-records/<sid>")
def get_sale(sid):
    require_auth(*READ_ROLES)
    rec = get_or_404("sale_records", sid, ERR_SALE_RECORD_NOT_FOUND)
    return success_object(ser_sale(rec))


@bp.post("/library/sale-records/<sid>/record-payment")
def pay_sale(sid):
    require_auth("BillingManager")
    rec = get_or_404("sale_records", sid, ERR_SALE_RECORD_NOT_FOUND)
    if rec["status"] != "INVOICED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an INVOICED sale may be paid")
    rec["status"] = "PAID"
    rec["balance_due_cents"] = 0
    touch(rec)
    account = db["customer_accounts"].get(rec["account_id"])
    if account is not None:
        touch(account)  # exposure recompute
        maybe_restore_standing(account)
    return success_object(ser_sale(rec))


@bp.post("/library/sale-records/<sid>/write-off")
def write_off_sale(sid):
    require_auth("BillingManager")
    rec = get_or_404("sale_records", sid, ERR_SALE_RECORD_NOT_FOUND)
    if rec["status"] != "INVOICED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an INVOICED sale may be written off")
    rec["status"] = "WRITTEN_OFF"
    rec["balance_due_cents"] = 0
    touch(rec)
    account = db["customer_accounts"].get(rec["account_id"])
    if account is not None:
        touch(account)  # exposure recompute
        maybe_restore_standing(account)
    return success_object(ser_sale(rec))
