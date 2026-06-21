"""Sales deal lifecycle (PRD 3.3, 3.4) with cross-aggregate cascades."""

from flask import Blueprint, request

import errors
import calculations as calc
from common import get_body, stamp_new, serialize, touch, paginate, as_int, as_str
from db import db
from lookups import get_deal, get_customer, get_unit, get_trade
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("deals", __name__)


def _apply_pricing(deal, variant):
    trade = db.trade_ins.get(deal.get("trade_in_id")) if deal.get("trade_in_id") else None
    ta, otd, fin = calc.compute_deal_pricing(deal, trade, variant)
    deal["trade_allowance_cents"] = ta
    deal["out_the_door_cents"] = otd
    deal["amount_financed_cents"] = fin


@bp.route("/deals", methods=["POST"])
def create_deal():
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    body = get_body()
    # existence: customer_id, unit_id, then optional trade_in_id (declared order)
    customer_id = as_str(body, "customer_id")
    get_customer(customer_id)
    unit_id = as_str(body, "unit_id")
    get_unit(unit_id)
    trade_in_id = body.get("trade_in_id")
    if trade_in_id is not None:
        if not isinstance(trade_in_id, str):
            errors.err(errors.ERR_INVALID_REQUEST, "trade_in_id must be a string")
        get_trade(trade_in_id)

    # body validation
    sale_price = as_int(body, "sale_price_cents", minimum=0)
    freight = as_int(body, "freight_setup_cents", required=False, default=0, minimum=0)
    doc_fee = as_int(body, "doc_fee_cents", required=False, default=39900, minimum=0)
    tax_rate_bps = as_int(body, "tax_rate_bps", minimum=0)
    down = as_int(body, "down_payment_cents", required=False, default=0, minimum=0)
    approved_payoff = as_int(body, "approved_lender_payoff_cents", required=False, default=0, minimum=0)

    rec = stamp_new({
        "customer_id": customer_id,
        "unit_id": unit_id,
        "trade_in_id": trade_in_id,
        "sale_price_cents": sale_price,
        "freight_setup_cents": freight,
        "doc_fee_cents": doc_fee,
        "tax_rate_bps": tax_rate_bps,
        "down_payment_cents": down,
        "trade_allowance_cents": 0,
        "out_the_door_cents": 0,
        "amount_financed_cents": 0,
        "approved_lender_payoff_cents": approved_payoff,
        "status": "DRAFT",
    })
    db.deals[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/deals", methods=["GET"])
def list_deals():
    _, role = get_user_context()
    require_role(role, {"SalesManager", "FinanceManager", "DealerPrincipal"})
    customer_id = request.args.get("customer_id")
    unit_id = request.args.get("unit_id")
    trade_in_id = request.args.get("trade_in_id")
    status = request.args.get("status")
    records = []
    for d in db.deals.values():
        if customer_id is not None and d["customer_id"] != customer_id:
            continue
        if unit_id is not None and d["unit_id"] != unit_id:
            continue
        if trade_in_id is not None and d.get("trade_in_id") != trade_in_id:
            continue
        if status is not None and d["status"] != status:
            continue
        records.append(d)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/deals/<did>", methods=["GET"])
def get_deal_route(did):
    _, role = get_user_context()
    require_role(role, {"SalesManager", "FinanceManager", "DealerPrincipal"})
    rec = get_deal(did)
    return ok(serialize(rec), 200)


@bp.route("/deals/<did>/quote", methods=["POST"])
def quote_deal(did):
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    deal = get_deal(did)

    # from-state: DRAFT or DECLINED -> QUOTED
    if deal["status"] not in ("DRAFT", "DECLINED"):
        errors.err(errors.ERR_INVALID_STATE, "Deal must be DRAFT or DECLINED to quote")

    unit = db.units.get(deal["unit_id"])
    # cross-entity precondition: unit IN_STOCK
    if unit is None or unit["status"] != "IN_STOCK":
        errors.err(errors.ERR_UNIT_NOT_AVAILABLE, "Unit is not IN_STOCK")

    # trade must be APPRAISED when present
    if deal.get("trade_in_id"):
        trade = db.trade_ins.get(deal["trade_in_id"])
        if trade is None or trade["status"] != "APPRAISED":
            errors.err(errors.ERR_TRADE_NOT_APPRAISED, "Trade is not APPRAISED")

    # transition
    unit["status"] = "ON_HOLD"
    unit["held_by_deal_id"] = deal["id"]
    touch(unit)

    deal["status"] = "QUOTED"
    _apply_pricing(deal, "provisional")
    touch(deal)
    return ok(serialize(deal), 200)


@bp.route("/deals/<did>/submit-finance", methods=["POST"])
def submit_finance(did):
    _, role = get_user_context()
    require_role(role, {"FinanceManager"})
    deal = get_deal(did)
    if deal["status"] != "QUOTED":
        errors.err(errors.ERR_INVALID_STATE, "Deal must be QUOTED to submit finance")
    deal["status"] = "FINANCE_SUBMITTED"
    touch(deal)
    return ok(serialize(deal), 200)


@bp.route("/deals/<did>/approve", methods=["POST"])
def approve_deal(did):
    _, role = get_user_context()
    require_role(role, {"FinanceManager"})
    deal = get_deal(did)

    if deal["status"] != "FINANCE_SUBMITTED":
        errors.err(errors.ERR_INVALID_STATE, "Deal must be FINANCE_SUBMITTED to approve")

    # optional approved_lender_payoff_cents override in the request body
    body = get_body()
    if body.get("approved_lender_payoff_cents") is not None:
        deal["approved_lender_payoff_cents"] = as_int(body, "approved_lender_payoff_cents", minimum=0)

    unit = db.units.get(deal["unit_id"])
    # cross-entity precondition: unit ON_HOLD held by this deal
    if unit is None or unit["status"] != "ON_HOLD" or unit.get("held_by_deal_id") != deal["id"]:
        errors.err(errors.ERR_UNIT_NOT_AVAILABLE, "Unit is not ON_HOLD held by this deal")

    # final-variant recompute
    _apply_pricing(deal, "final")
    deal["status"] = "APPROVED"
    touch(deal)

    # unit ON_HOLD -> SOLD
    unit["status"] = "SOLD"
    touch(unit)

    # cascade hop 1: trade APPRAISED -> ACCEPTED
    if deal.get("trade_in_id"):
        trade = db.trade_ins.get(deal["trade_in_id"])
        if trade is not None:
            if trade["status"] != "APPRAISED":
                errors.err(errors.ERR_TRADE_NOT_APPRAISED, "Trade is not APPRAISED")
            trade["status"] = "ACCEPTED"
            touch(trade)

    return ok(serialize(deal), 200)


@bp.route("/deals/<did>/decline", methods=["POST"])
def decline_deal(did):
    _, role = get_user_context()
    require_role(role, {"FinanceManager"})
    deal = get_deal(did)
    if deal["status"] != "FINANCE_SUBMITTED":
        errors.err(errors.ERR_INVALID_STATE, "Deal must be FINANCE_SUBMITTED to decline")
    deal["status"] = "DECLINED"
    touch(deal)
    # unit ON_HOLD -> IN_STOCK, clear hold
    unit = db.units.get(deal["unit_id"])
    if unit is not None and unit.get("held_by_deal_id") == deal["id"]:
        unit["status"] = "IN_STOCK"
        unit["held_by_deal_id"] = None
        touch(unit)
    return ok(serialize(deal), 200)


@bp.route("/deals/<did>/deliver", methods=["POST"])
def deliver_deal(did):
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    deal = get_deal(did)

    if deal["status"] != "APPROVED":
        errors.err(errors.ERR_INVALID_STATE, "Deal must be APPROVED to deliver")

    unit = db.units.get(deal["unit_id"])
    if unit is None or unit["status"] != "SOLD":
        errors.err(errors.ERR_UNIT_NOT_AVAILABLE, "Unit is not SOLD")

    deal["status"] = "DELIVERED"
    touch(deal)

    # cascade hop 1: unit SOLD -> DELIVERED
    unit["status"] = "DELIVERED"
    touch(unit)

    # cascade hop 2->3: floor plan payoff
    loan_id = unit.get("floor_plan_loan_id")
    if loan_id:
        loan = db.floor_plan_loans.get(loan_id)
        if loan is not None and loan["status"] != "PAID_OFF":
            outstanding = loan["principal_outstanding_cents"]
            curt = stamp_new({
                "floor_plan_loan_id": loan_id,
                "principal_cents": outstanding,
                "reason": "SALE_PAYOFF",
                "status": "POSTED",
            }, common=False)
            db.curtailments[curt["id"]] = curt
            loan["principal_outstanding_cents"] = 0
            loan["cumulative_curtailment_cents"] = loan.get("cumulative_curtailment_cents", 0) + outstanding
            loan["status"] = "PAID_OFF"
            touch(loan)

    # cascade hop 2 (trade path): trade ACCEPTED -> TITLED, mint new Unit
    if deal.get("trade_in_id"):
        trade = db.trade_ins.get(deal["trade_in_id"])
        if trade is not None and trade["status"] == "ACCEPTED":
            new_unit = stamp_new({
                "vin": trade["vin"],
                "category": trade["category"],
                "model_year": 2000,
                "msrp_cents": 0,
                "dealer_cost_cents": trade["appraised_value_cents"],
                "acquisition_kind": "TRADE_IN",
                "status": "IN_STOCK",
                "floor_plan_loan_id": None,
                "held_by_deal_id": None,
            })
            db.units[new_unit["id"]] = new_unit
            trade["status"] = "TITLED"
            trade["resulting_unit_id"] = new_unit["id"]
            touch(trade)

    return ok(serialize(deal), 200)


@bp.route("/deals/<did>/cancel", methods=["POST"])
def cancel_deal(did):
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    deal = get_deal(did)
    if deal["status"] not in ("DRAFT", "QUOTED"):
        errors.err(errors.ERR_INVALID_STATE, "Deal must be DRAFT or QUOTED to cancel")
    deal["status"] = "CANCELLED"
    touch(deal)
    unit = db.units.get(deal["unit_id"])
    if unit is not None and unit.get("held_by_deal_id") == deal["id"]:
        unit["status"] = "IN_STOCK"
        unit["held_by_deal_id"] = None
        touch(unit)
    return ok(serialize(deal), 200)
