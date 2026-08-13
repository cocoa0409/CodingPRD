"""Invoice routes: list, read, issue, void, payments, refunds, adjustments (PRD 3.8)."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core
from util import REFUND_AUTO_APPROVE_MAX_CENTS

bp = Blueprint("invoices", __name__)

PAYMENT_METHODS = ("CHECK", "CARD", "CASH", "CREDIT")


@bp.get("/invoices")
def list_invoices():
    require_roles(*ANY_ROLE)
    items = list(store.invoices.values())
    for param in ("organization_id", "permit_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [i for i in items if i.get(param) == val]
    return util.paginate(items)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_invoice(iid))


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    require_roles("FinanceClerk")
    inv = core.get_invoice(iid)
    if inv["status"] != "DRAFT":
        raise errors.ApiError(errors.ERR_INVALID_INVOICE_STATE,
                              "Invoice must be DRAFT to issue", 409)
    inv["status"] = "ISSUED"
    util.touch(inv)
    return success_object(inv)


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    require_roles("FinanceClerk")
    inv = core.get_invoice(iid)
    if inv["status"] not in ("DRAFT", "ISSUED", "PARTIALLY_PAID"):
        raise errors.ApiError(errors.ERR_INVALID_INVOICE_STATE,
                              "Invoice cannot be voided from its current state", 409)
    if inv["paid_cents"] > 0:
        raise errors.ApiError(errors.ERR_INVOICE_HAS_PAYMENTS,
                              "Invoice has cleared payments and cannot be voided", 422)
    inv["status"] = "VOID"
    util.touch(inv)
    return success_object(inv)


@bp.post("/invoices/<iid>/payments")
def record_payment(iid):
    user_id, _ = require_roles("FinanceClerk")
    body = util.get_json_body()
    amount = util.require_int(body, "amount_cents", min_v=1)
    method = util.require_enum(body, "method", PAYMENT_METHODS)
    inv = core.get_invoice(iid)
    if inv["status"] in ("DRAFT", "VOID", "REFUNDED", "PAID"):
        raise errors.ApiError(errors.ERR_INVALID_INVOICE_STATE,
                              "Invoice cannot accept payments in its current state", 409)
    if amount > inv["balance_due_cents"]:
        raise errors.ApiError(errors.ERR_PAYMENT_EXCEEDS_BALANCE,
                              "amount_cents exceeds balance_due_cents", 422)

    payment = util.new_entity({
        "invoice_id": inv["id"],
        "organization_id": inv["organization_id"],
        "kind": "PAYMENT",
        "amount_cents": amount,
        "method": method,
        "status": "CLEARED",
        "initiated_by": user_id,
        "approved_by": None,
    })
    store.payments[payment["id"]] = payment

    inv["paid_cents"] += amount
    core.recompute_invoice_totals(inv)
    core.apply_payment_status(inv)
    util.touch(inv)
    return success_object(payment, 201)


@bp.post("/invoices/<iid>/refunds")
def record_refund(iid):
    user_id, _ = require_roles("FinanceClerk")
    body = util.get_json_body()
    amount = util.require_int(body, "amount_cents", min_v=1)
    util.require_str(body, "reason")
    inv = core.get_invoice(iid)
    if inv["status"] in ("DRAFT", "VOID", "REFUNDED"):
        raise errors.ApiError(errors.ERR_INVALID_INVOICE_STATE,
                              "Invoice cannot be refunded in its current state", 409)
    if amount > inv["paid_cents"] - inv["refunded_cents"]:
        raise errors.ApiError(errors.ERR_REFUND_EXCEEDS_PAID,
                              "amount_cents exceeds net paid amount", 422)

    status = "CLEARED" if amount <= REFUND_AUTO_APPROVE_MAX_CENTS else "PENDING_APPROVAL"
    payment = util.new_entity({
        "invoice_id": inv["id"],
        "organization_id": inv["organization_id"],
        "kind": "REFUND",
        "amount_cents": amount,
        "method": None,
        "status": status,
        "initiated_by": user_id,
        "approved_by": None,
    })
    store.payments[payment["id"]] = payment

    if status == "CLEARED":
        inv["refunded_cents"] += amount
        core.recompute_invoice_totals(inv)
        core.maybe_settle_refunded(inv)
        util.touch(inv)
    return success_object(payment, 201)


@bp.post("/invoices/<iid>/adjustments")
def post_adjustment(iid):
    require_roles("FinanceClerk")
    body = util.get_json_body()
    delta = util.require_int(body, "delta_cents")
    util.require_str(body, "note")
    expected = util.require_int(body, "expected_invoice_version")
    inv = core.get_invoice(iid)
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise errors.ApiError(errors.ERR_INVALID_INVOICE_STATE,
                              "Adjustments require an ISSUED or PARTIALLY_PAID invoice", 409)
    if expected != inv["version"]:
        raise errors.stale_version(
            "expected_invoice_version does not match the invoice's current version")
    inv["adjustment_cents"] += delta
    inv["total_cents"] += delta
    core.recompute_invoice_totals(inv)
    util.touch(inv)
    return success_object(inv)
