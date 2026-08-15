"""Payment endpoints (PRD §3.5)."""

from flask import Blueprint

import db
from errors import not_found
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import payment as ser_payment
from services.common import touch_account
from services.waterfall import post_payment
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("payments", __name__)

TENDER_TYPES = {"CASH", "CARD", "CHECK", "MONEY_ORDER"}
GET_ROLES = ["Customer", "CustomerServiceRep", "ProgramAdmin"]
LIST_ROLES = ["CustomerServiceRep", "ProgramAdmin"]


@bp.route("/assistance/payments", methods=["POST"])
def create_payment():
    actor = authenticate(["Customer", "CustomerServiceRep"])
    raw = get_body(allow_empty=False)
    if actor.is_customer and isinstance(raw.get("account_id"), str):
        check_ownership(actor, raw.get("account_id"))
    body = validate_shape(raw, [
        ("account_id", "string", True, None),
        ("amount_cents", "int", True, (1, None)),
        ("tender_type", "enum", True, TENDER_TYPES),
    ])
    if actor.is_customer:
        check_ownership(actor, body["account_id"])
    account = db.accounts.get(body["account_id"])
    if account is None:
        raise not_found("Account not found")
    payment = post_payment(account, body["amount_cents"], body["tender_type"])
    touch_account(account)
    return success_object(ser_payment(payment), status=201)


@bp.route("/assistance/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    actor = authenticate(GET_ROLES)
    p = db.payments.get(payment_id)
    if p is not None:
        check_ownership(actor, p["account_id"])
    if p is None:
        raise not_found("Payment not found")
    return success_object(ser_payment(p))


@bp.route("/assistance/payments", methods=["GET"])
def list_payments():
    authenticate(LIST_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"account_id": "str", "dpa_id": "str"})
    items = sort_by_creation(db.payments.values())
    if "account_id" in filters:
        items = [x for x in items if x["account_id"] == filters["account_id"]]
    if "dpa_id" in filters:
        items = [x for x in items if x["dpa_id"] == filters["dpa_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_payment(x) for x in page], limit, offset, total)
