"""The credit ledger (PRD 3.7 "The credit ledger")."""

from flask import Blueprint

import constants as C
import serialize
import services
import shapes
import store
from auth import api, get_credit
from envelope import ok, created, paginate
from errors import ApiError
from routes.children import body_fk
from store import db, now, touch

bp = Blueprint("credits", __name__)

READ_ROLES = ["AccountHolder", "SupportAgent", "OpsAdmin"]


@api(bp, "POST", "/credits", ["SupportAgent"])
def issue_credit():
    data = shapes.body()
    body_fk(data, "account_id", db.accounts, "Account")
    parsed = shapes.validate(data, [
        shapes.field("account_id", required=True, kind="string"),
        shapes.field("issued_cents", required=True, kind="int", lo=1),
        # credit_type is NOT one of the closed ERR_INVALID_ENUM fields; an
        # undeclared member therefore routes to ERR_VALUE_OUT_OF_RANGE.
        shapes.field("credit_type", kind="enum", members=C.CREDIT_TYPES,
                     default="GOODWILL", enum_error="ERR_VALUE_OUT_OF_RANGE"),
    ])
    row = services.issue_credit(
        parsed["account_id"], parsed["credit_type"] or "GOODWILL",
        parsed["issued_cents"], True,
        store.plus_days(now(), C.CREDIT_EXPIRY_DAYS))
    services.recompute_account_estimate(parsed["account_id"])
    return created(serialize.credit(row))


@api(bp, "GET", "/credits/<id>", READ_ROLES)
def read_credit(id):
    return ok(serialize.credit(get_credit(id)))


@api(bp, "GET", "/credits", READ_ROLES)
def list_credits():
    rows = [r for r in db.credits.values()
            if shapes.match(r, "account_id", shapes.qs("account_id"))
            and shapes.match(r, "source_gift_order_id",
                             shapes.qs("source_gift_order_id"))
            and shapes.match(r, "source_referral_id",
                             shapes.qs("source_referral_id"))
            and shapes.match(r, "credit_type", shapes.qs("credit_type"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.credit)


@api(bp, "POST", "/credits/<id>/revoke", ["SupportAgent"])
def revoke_credit(id):
    credit = get_credit(id)
    if credit["status"] not in ("AVAILABLE", "PARTIALLY_CONSUMED"):
        raise ApiError("ERR_CREDIT_NOT_AVAILABLE")
    if credit["status"] == "PARTIALLY_CONSUMED":
        services.reverse_credit_consumption_on_planned_cycles(credit)
    services.forfeit_credit(credit, "REVOKED")
    services.recompute_account_estimate(credit["account_id"])
    return ok(serialize.credit(credit))


@api(bp, "POST", "/credits/<id>/expire", ["OpsAdmin"])
def expire_credit(id):
    credit = get_credit(id)
    if credit["status"] not in ("AVAILABLE", "PARTIALLY_CONSUMED"):
        raise ApiError("ERR_CREDIT_NOT_AVAILABLE")
    if credit["expires_at"] > now():
        raise ApiError("ERR_CREDIT_NOT_YET_EXPIRED")
    services.forfeit_credit(credit, "EXPIRED")
    services.recompute_account_estimate(credit["account_id"])
    return ok(serialize.credit(credit))
