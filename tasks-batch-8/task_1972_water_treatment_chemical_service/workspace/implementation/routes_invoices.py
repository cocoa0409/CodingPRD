"""Invoice endpoints: create/issue/pay/void with the dual-variant
per-line-then-sum pricing and open-balance debit/credit."""

from flask import Blueprint, g

import errors
from calc import invoice_pricing
from db import db, create_entity, touch
from helpers import list_response, account_of_invoice, query_filter
from response import success_object
from serializers import invoice as ser
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership)

bp = Blueprint("invoices", __name__)


@bp.route("/wt/invoices", methods=["POST"])
def create_invoice():
    body = get_body()
    account = resolve_body_fk(body, "account_id", "accounts")
    vals = validate_shape(body, [
        ("account_id", "str", True),
        ("period_start", "iso", True),
        ("period_end", "iso", True),
    ])
    if not vals["period_end"] > vals["period_start"]:
        raise errors.field_constraint("period_end must be strictly after period_start")
    ent = create_entity("invoices", {
        "account_id": account["id"],
        "period_start": vals["period_start"],
        "period_end": vals["period_end"],
        "pricing_variant": None,
        "product_charges_cents": None,
        "service_fee_cents": None,
        "invoice_total_cents": None,
        "status": "DRAFT",
    })
    return success_object(ser(ent), 201)


@bp.route("/wt/invoices", methods=["GET"])
def list_invoices():
    user = (g.role, g.user_id)
    items = list(db["invoices"].values())
    account_id = query_filter("account_id")
    if account_id is not None:
        items = [i for i in items if i["account_id"] == account_id]
    status = query_filter("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items, ser, account_of_invoice, user)


@bp.route("/wt/invoices/<invoiceId>", methods=["GET"])
def get_invoice(invoiceId):
    ent = db["invoices"].get(invoiceId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, ent["account_id"])
    ent = resolve("invoices", invoiceId)
    return success_object(ser(ent), 200)


@bp.route("/wt/invoices/<invoiceId>/issue", methods=["POST"])
def issue_invoice(invoiceId):
    ent = resolve("invoices", invoiceId)
    get_body()
    if ent["status"] != "DRAFT":
        raise errors.invalid_state("Invoice must be DRAFT to issue")
    account = db["accounts"][ent["account_id"]]
    variant, product_charges, service_fee, total = invoice_pricing(account, ent)
    ent["pricing_variant"] = variant
    ent["product_charges_cents"] = product_charges
    ent["service_fee_cents"] = service_fee
    ent["invoice_total_cents"] = total
    ent["status"] = "ISSUED"
    touch(ent)
    # Debit the account's open balance.
    if total != 0:
        account["open_balance_cents"] += total
        touch(account)
    return success_object(ser(ent), 200)


@bp.route("/wt/invoices/<invoiceId>/pay", methods=["POST"])
def pay_invoice(invoiceId):
    ent = db["invoices"].get(invoiceId)
    if ent is not None:
        # Tier 3: CustomerContact pays only its own account's invoices.
        check_cc_ownership(g.user_id, g.role, ent["account_id"])
    ent = resolve("invoices", invoiceId)
    get_body()
    if ent["status"] not in ("ISSUED", "OVERDUE"):
        raise errors.invalid_state("Invoice must be ISSUED or OVERDUE to pay")
    ent["status"] = "PAID"
    touch(ent)
    account = db["accounts"].get(ent["account_id"])
    if account is not None and ent["invoice_total_cents"]:
        account["open_balance_cents"] -= ent["invoice_total_cents"]
        touch(account)
    return success_object(ser(ent), 200)


@bp.route("/wt/invoices/<invoiceId>/void", methods=["POST"])
def void_invoice(invoiceId):
    ent = resolve("invoices", invoiceId)
    get_body()
    if ent["status"] != "DRAFT":
        raise errors.invalid_state("Invoice must be DRAFT to void")
    ent["status"] = "VOID"
    touch(ent)
    return success_object(ser(ent), 200)
