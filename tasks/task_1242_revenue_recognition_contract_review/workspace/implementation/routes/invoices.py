from flask import Blueprint

from db import STORE, make_rec, mark, sort_created
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE_TRANSITION, ERR_CONTRACT_NOT_ACTIVE,
                    ERR_INVALID_AMOUNT, ERR_BILLING_EXCEEDS_PRICE)
from response import ok_object, ok_list
import serializers as ser
import services as svc
from clock import CLOCK
from validate import require_roles, body, req_str, req_int, req_date

bp = Blueprint("invoices", __name__)

ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")


@bp.post("/revrec/contracts/<contract_id>/invoices")
def create_invoice(contract_id):
    require_roles("RevenueAccountant")
    c = STORE.contracts.get(contract_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "contract id does not identify an existing contract")
    data = body()
    invoice_ref = req_str(data, "invoice_ref")
    amount = req_int(data, "amount_cents")
    inv_date = req_date(data, "invoice_date")
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "invoices may be issued only against ACTIVE contracts")
    svc.require_open_period(inv_date)
    if amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "amount_cents must be > 0")
    for i in STORE.invoices.values():
        if i["invoice_ref"] == invoice_ref:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invoice_ref must be unique per invoice")
    tx_price = c["fixed_consideration_cents"] + c["vc_estimate_cents"]
    if svc.contract_billed(contract_id) + amount > tx_price:
        raise ApiError(ERR_BILLING_EXCEEDS_PRICE, 422,
                       "cumulative issued billings may not exceed transaction_price_cents")
    rec = make_rec(STORE.invoices, {
        "contract_id": contract_id,
        "invoice_ref": invoice_ref,
        "amount_cents": amount,
        "invoice_date": inv_date.isoformat(),
        "status": "ISSUED",
        "voided_by_user_id": None,
        "_voided_date": None,
    })
    mark(c)
    svc.evaluate_auto_completion(c)
    return ok_object(ser.invoice(rec), 201)


@bp.get("/revrec/contracts/<contract_id>/invoices")
def list_invoices(contract_id):
    require_roles(*ALL_READ)
    if contract_id not in STORE.contracts:
        raise ApiError(ERR_NOT_FOUND, 404, "contract id does not identify an existing contract")
    items = sort_created([i for i in STORE.invoices.values() if i["contract_id"] == contract_id])
    return ok_list([ser.invoice(i) for i in items], len(items) or 1, 0, len(items))


@bp.post("/revrec/invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    uid = require_roles("RevenueManager")
    inv = STORE.invoices.get(invoice_id)
    if inv is None:
        raise ApiError(ERR_NOT_FOUND, 404, "invoice_id does not identify an existing invoice")
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "void requires the invoice to be ISSUED")
    svc.require_open_period(CLOCK.today())
    inv["status"] = "VOIDED"
    inv["voided_by_user_id"] = uid
    inv["_voided_date"] = CLOCK.today()
    mark(inv)
    c = STORE.contracts.get(inv["contract_id"])
    if c is not None:
        mark(c)
        svc.evaluate_auto_completion(c)
    return ok_object(ser.invoice(inv))
