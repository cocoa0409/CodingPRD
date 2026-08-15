"""Commission invoice administration (PRD §3.7): issue/pay/dispute with the
installment ordering rule and the dispute loop.
"""
from flask import Blueprint

from db import store, public, touch
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_INSTALLMENT_NOT_DUE,
)
from middleware import authenticate, body, require_fields, get_path, ALL_ROLES
from response import success_object
from routes import list_response

bp = Blueprint("invoices", __name__)


@bp.get("/api/commission-invoices")
def list_invoices():
    authenticate(ALL_ROLES)
    return list_response(store.invoices.values(), [
        ("loi_id", lambda e: e["loi_id"]),
        ("broker_side", lambda e: e["broker_side"]),
        ("status", lambda e: e["status"]),
    ])


@bp.get("/api/commission-invoices/<iid>")
def get_invoice(iid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.invoices, iid, "commission invoice")))


@bp.post("/api/commission-invoices/<iid>/issue")
def issue_invoice(iid):
    authenticate(["LeasingManager"])
    inv = get_path(store.invoices, iid, "commission invoice")
    if inv["status"] not in ("ACCRUED", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot issue an invoice in status {inv['status']}", 409)
    if inv["status"] == "DISPUTED":
        # Re-issue after dispute: reason cleared, every amount unchanged.
        inv["dispute_reason"] = None
    inv["status"] = "INVOICED"
    touch(inv)
    return success_object(public(inv))


@bp.post("/api/commission-invoices/<iid>/pay")
def pay_invoice(iid):
    authenticate(["LeasingManager"])
    inv = get_path(store.invoices, iid, "commission invoice")
    b = body()
    require_fields(b, [("installment_number", "int", True)])
    n = b["installment_number"]
    if n == 1:
        if inv["status"] != "INVOICED":
            raise ApiError(ERR_INVALID_STATE,
                           f"Cannot pay installment 1 on an invoice in status {inv['status']}", 409)
        inv["installment_1_paid"] = True
        inv["status"] = "PARTIALLY_PAID"
    elif n == 2:
        # Out-of-order pay (installment 2 before 1) fails the state check.
        if inv["status"] != "PARTIALLY_PAID":
            raise ApiError(ERR_INVALID_STATE,
                           f"Cannot pay installment 2 on an invoice in status {inv['status']}", 409)
        if not inv["installment_2_due"]:
            raise ApiError(ERR_INSTALLMENT_NOT_DUE,
                           "Installment 2 is not due until rent commencement (site LEASED)", 409)
        inv["installment_2_paid"] = True
        inv["status"] = "PAID"
    else:
        raise ApiError(ERR_INVALID_STATE,
                       f"No declared payment transition for installment_number {n}", 409)
    touch(inv)
    return success_object(public(inv))


@bp.post("/api/commission-invoices/<iid>/dispute")
def dispute_invoice(iid):
    authenticate(["LeasingManager"])
    inv = get_path(store.invoices, iid, "commission invoice")
    b = body()
    require_fields(b, [("reason", "string", True)])
    if inv["status"] != "INVOICED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot dispute an invoice in status {inv['status']}", 409)
    inv["status"] = "DISPUTED"
    inv["dispute_reason"] = b["reason"]
    touch(inv)
    return success_object(public(inv))
