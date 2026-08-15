"""Dividend declaration and payment endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import get_body, req_str, req_int, req_dt, pagination_params, fmt_dt
from middleware import auth, require_role, shareholder_owns, officer_owns
from response import success_list, success_object
from services import (stamp_new, touch, audit, sorted_recs, declaration_view,
                      payment_view, reactivate_account, maybe_close_declaration,
                      now_iso)

bp = Blueprint("dividends", __name__)

DECLARATION_LIST_ROLES = {"AgentAdmin", "IssuerOfficer", "TransferSupervisor",
                          "ServiceAgent", "Shareholder"}
PAYMENT_READ_ROLES = {"AgentAdmin", "IssuerOfficer", "ServiceAgent", "Shareholder"}


def get_declaration_or_404(declaration_id):
    decl = STORE["declarations"].get(declaration_id)
    if decl is None:
        fail("ERR_DECLARATION_NOT_FOUND", "declaration %s does not exist" % declaration_id)
    return decl


def get_payment_or_404(payment_id):
    payment = STORE["payments"].get(payment_id)
    if payment is None:
        fail("ERR_PAYMENT_NOT_FOUND", "payment %s does not exist" % payment_id)
    return payment


@bp.post("/dividend-declarations")
def create_declaration():
    user_id, role = auth()
    require_role(role, {"IssuerOfficer"})
    body = get_body()
    if body.get("issuer_id") is not None:
        officer_owns(user_id, body.get("issuer_id"))
    issuer_id = req_str(body, "issuer_id")
    issuer = STORE["issuers"].get(issuer_id)
    if issuer is None:
        fail("ERR_ISSUER_NOT_FOUND", "issuer %s does not exist" % issuer_id)
    if issuer["status"] == "SUSPENDED":
        fail("ERR_ISSUER_SUSPENDED", "issuer is SUSPENDED")
    record_date = req_dt(body, "record_date")
    payable_date = req_dt(body, "payable_date")
    if payable_date <= record_date:
        fail("ERR_INVALID_DATE_RANGE", "payable_date must be strictly after record_date")
    amount = req_int(body, "amount_per_share_millicents")
    if amount < 0:
        fail("ERR_INVALID_REQUEST", "amount_per_share_millicents must be >= 0")
    decl = stamp_new({
        "issuer_id": issuer["id"],
        "record_date": fmt_dt(record_date),
        "payable_date": fmt_dt(payable_date),
        "amount_per_share_millicents": amount,
        "status": "DECLARED",
        "total_eligible_shares": 0,
        "total_accrued_cents": 0,
    })
    STORE["declarations"][decl["id"]] = decl
    audit("DividendDeclaration", decl["id"], role, user_id, "declaration.create",
          "", "DECLARED", "cash dividend declared")
    return success_object(declaration_view(decl), 201)


@bp.get("/dividend-declarations")
def list_declarations():
    user_id, role = auth()
    require_role(role, DECLARATION_LIST_ROLES)
    issuer_filter = request.args.get("issuer_id")
    status_filter = request.args.get("status")
    if role == "IssuerOfficer" and issuer_filter is not None:
        officer_owns(user_id, issuer_filter)
    items = sorted_recs("declarations")
    if issuer_filter is not None:
        items = [d for d in items if d["issuer_id"] == issuer_filter]
    if status_filter is not None:
        items = [d for d in items if d["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([declaration_view(d) for d in page], limit, offset, total)


@bp.get("/dividend-declarations/<declaration_id>")
def read_declaration(declaration_id):
    user_id, role = auth()
    require_role(role, DECLARATION_LIST_ROLES)
    decl = get_declaration_or_404(declaration_id)
    if role == "IssuerOfficer":
        officer_owns(user_id, decl["issuer_id"])
    return success_object(declaration_view(decl))


@bp.post("/dividend-declarations/<declaration_id>/void")
def void_declaration(declaration_id):
    user_id, role = auth()
    require_role(role, {"IssuerOfficer"})
    decl = get_declaration_or_404(declaration_id)
    officer_owns(user_id, decl["issuer_id"])
    if decl["status"] != "DECLARED":
        fail("ERR_INVALID_STATE", "only a DECLARED declaration can be voided")
    decl["status"] = "VOIDED"
    touch(decl)
    audit("DividendDeclaration", decl["id"], role, user_id, "declaration.void",
          "DECLARED", "VOIDED", "declaration voided before record lock")
    return success_object(declaration_view(decl))


@bp.get("/dividend-payments")
def list_payments():
    user_id, role = auth()
    require_role(role, PAYMENT_READ_ROLES)
    declaration_filter = request.args.get("declaration_id")
    account_filter = request.args.get("account_id")
    status_filter = request.args.get("status")
    if role == "Shareholder" and account_filter is not None:
        shareholder_owns(user_id, account_filter)
    items = sorted_recs("payments")
    if declaration_filter is not None:
        items = [p for p in items if p["declaration_id"] == declaration_filter]
    if account_filter is not None:
        items = [p for p in items if p["account_id"] == account_filter]
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([payment_view(p) for p in page], limit, offset, total)


@bp.get("/dividend-payments/<payment_id>")
def read_payment(payment_id):
    user_id, role = auth()
    require_role(role, PAYMENT_READ_ROLES)
    payment = get_payment_or_404(payment_id)
    if role == "Shareholder":
        shareholder_owns(user_id, payment["account_id"])
    return success_object(payment_view(payment))


@bp.post("/dividend-payments/<payment_id>/cash")
def cash_payment(payment_id):
    user_id, role = auth()
    require_role(role, {"Shareholder"})
    payment = get_payment_or_404(payment_id)
    shareholder_owns(user_id, payment["account_id"])
    if payment["status"] != "DISBURSED":
        fail("ERR_INVALID_STATE", "only a DISBURSED payment can be cashed")
    payment["status"] = "RECONCILED"
    touch(payment)
    account = STORE["accounts"].get(payment["account_id"])
    if account is not None:
        # cashing is a qualifying owner contact (may reactivate a DORMANT account)
        reactivate_account(account, role, user_id)
    audit("DividendPayment", payment["id"], role, user_id, "payment.cashed",
          "DISBURSED", "RECONCILED", "dividend cashed by payee")
    maybe_close_declaration(payment["declaration_id"], role, user_id)
    return success_object(payment_view(payment))


@bp.post("/dividend-payments/<payment_id>/mark-returned")
def mark_returned(payment_id):
    user_id, role = auth()
    require_role(role, {"ServiceAgent"})
    payment = get_payment_or_404(payment_id)
    if payment["status"] != "DISBURSED":
        fail("ERR_INVALID_STATE", "only a DISBURSED payment can be marked returned")
    payment["status"] = "RETURNED"
    payment["returned_at"] = now_iso()
    touch(payment)
    account = STORE["accounts"].get(payment["account_id"])
    if account is not None:
        account["address_verified"] = False
        touch(account)
    audit("DividendPayment", payment["id"], role, user_id, "payment.returned",
          "DISBURSED", "RETURNED", "disbursement returned undeliverable")
    return success_object(payment_view(payment))


@bp.post("/dividend-payments/<payment_id>/reissue")
def reissue_payment(payment_id):
    user_id, role = auth()
    require_role(role, {"ServiceAgent"})
    payment = get_payment_or_404(payment_id)
    if payment["status"] != "RETURNED":
        fail("ERR_INVALID_STATE", "only a RETURNED payment can be reissued")
    account = STORE["accounts"].get(payment["account_id"])
    if account is not None and not account["address_verified"]:
        fail("ERR_ADDRESS_UNVERIFIED",
             "account address is not verified; reissue refused")
    payment["status"] = "DISBURSED"
    payment["disbursed_at"] = now_iso()
    touch(payment)
    audit("DividendPayment", payment["id"], role, user_id, "payment.reissued",
          "RETURNED", "DISBURSED", "payment reissued to verified address")
    return success_object(payment_view(payment))
