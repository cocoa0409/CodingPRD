"""Trade-ins (PRD 3.5)."""

import re

from flask import Blueprint, request

import errors
from common import get_body, stamp_new, serialize, touch, paginate, as_int, as_str, as_enum
from db import db
from lookups import get_trade, get_customer
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("trade_ins", __name__)

CATEGORIES = {"MOTORCYCLE", "ATV", "UTV", "PWC", "SNOWMOBILE"}
VIN_RE = re.compile(r"^.{17}$")


@bp.route("/trade-ins", methods=["POST"])
def create_trade():
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    body = get_body()
    customer_id = as_str(body, "customer_id")
    # existence first (customer FK)
    get_customer(customer_id)
    vin = as_str(body, "vin")
    category = as_enum(body, "category", CATEGORIES)
    appraised = as_int(body, "appraised_value_cents", minimum=0)
    est_payoff = as_int(body, "estimated_payoff_cents", required=False, default=0, minimum=0)

    if len(vin) != 17:
        errors.err(errors.ERR_INVALID_REQUEST, "Trade VIN must be 17 characters")

    rec = stamp_new({
        "customer_id": customer_id,
        "vin": vin,
        "category": category,
        "appraised_value_cents": appraised,
        "estimated_payoff_cents": est_payoff,
        "status": "APPRAISED",
        "resulting_unit_id": None,
    })
    db.trade_ins[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/trade-ins", methods=["GET"])
def list_trades():
    _, role = get_user_context()
    require_role(role, {"SalesManager", "FinanceManager", "DealerPrincipal"})
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    resulting_unit_id = request.args.get("resulting_unit_id")
    records = []
    for t in db.trade_ins.values():
        if customer_id is not None and t["customer_id"] != customer_id:
            continue
        if status is not None and t["status"] != status:
            continue
        if resulting_unit_id is not None and t.get("resulting_unit_id") != resulting_unit_id:
            continue
        records.append(t)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/trade-ins/<tid>", methods=["GET"])
def get_trade_route(tid):
    _, role = get_user_context()
    require_role(role, {"SalesManager", "FinanceManager", "DealerPrincipal"})
    rec = get_trade(tid)
    return ok(serialize(rec), 200)


@bp.route("/trade-ins/<tid>/reject", methods=["POST"])
def reject_trade(tid):
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    trade = get_trade(tid)
    if trade["status"] != "APPRAISED":
        errors.err(errors.ERR_INVALID_STATE, "Trade is not APPRAISED")
    trade["status"] = "REJECTED"
    touch(trade)
    return ok(serialize(trade), 200)
