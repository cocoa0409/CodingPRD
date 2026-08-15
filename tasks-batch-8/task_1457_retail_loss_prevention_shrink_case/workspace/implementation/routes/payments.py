"""Restitution payment endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import body, req_string, req_int, req_enum, get_or_404
from services.entities import make_restitution_payment, pub, touch
from services.calculations import (
    waterfall_allocate, demand_outstanding, recompute_case_restitution_status,
    NSF_FEE_CENTS,
)
from errors import (
    err409,
    ERR_INVALID_STATE_TRANSITION, ERR_DEMAND_NOT_PAYABLE,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
)

bp = Blueprint("payments", __name__)

METHODS = ["CASH", "CARD", "MONEY_ORDER", "PAYROLL_DEDUCT"]


@bp.route("/restitution-payments", methods=["POST"])
def create_payment():
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    demand_id = req_string(data, "demand_id")
    amount_cents = req_int(data, "amount_cents", minimum=1)
    method = req_enum(data, "method", METHODS)
    get_or_404(db.civil_demands, demand_id, "civil demand")
    payment = make_restitution_payment(demand_id, amount_cents, method)
    db.restitution_payments[payment["id"]] = payment
    return success_object(pub(payment), status=201)


@bp.route("/restitution-payments", methods=["GET"])
def list_payments():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    demand_id = _q("demand_id")
    status = _q("status")
    method = _q("method")
    items = sorted(db.restitution_payments.values(),
                   key=lambda p: (p["created_at"], p["id"]))
    if demand_id is not None:
        items = [p for p in items if p["demand_id"] == demand_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if method is not None:
        items = [p for p in items if p["method"] == method]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(p) for p in page], limit, offset, total)


@bp.route("/restitution-payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    payment = get_or_404(db.restitution_payments, payment_id, "restitution payment")
    return success_object(pub(payment))


def _recompute_demand_status_after_post(demand):
    """Status flips per outstanding after a post."""
    outstanding = demand["outstanding_cents"]
    due_plus_fees = demand["amount_due_cents"] + demand["fees_incurred_cents"]
    if outstanding == 0:
        demand["status"] = "PAID_IN_FULL"
    elif 0 < demand["paid_to_date_cents"] < due_plus_fees:
        demand["status"] = "PARTIALLY_PAID"
    elif demand["paid_to_date_cents"] == 0:
        demand["status"] = "ISSUED"


@bp.route("/restitution-payments/<payment_id>/post", methods=["POST"])
def post_payment(payment_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    payment = get_or_404(db.restitution_payments, payment_id, "restitution payment")
    if payment["status"] != "RECEIVED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Payment must be RECEIVED to post")
    demand = db.civil_demands.get(payment["demand_id"])
    if demand is None or demand["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise err409(ERR_DEMAND_NOT_PAYABLE,
                     "Demand must be ISSUED or PARTIALLY_PAID to accept a posting")
    if payment["amount_cents"] > demand["outstanding_cents"]:
        raise err409(ERR_PAYMENT_EXCEEDS_OUTSTANDING,
                     "Payment amount exceeds the demand's outstanding balance")

    applied_fees, applied_penalty, applied_merch = waterfall_allocate(
        demand, payment["amount_cents"])
    payment["applied_fees_cents"] = applied_fees
    payment["applied_penalty_cents"] = applied_penalty
    payment["applied_merch_cents"] = applied_merch
    payment["status"] = "POSTED"
    touch(payment)

    demand["_fees_paid_cents"] += applied_fees
    demand["_penalty_paid_cents"] += applied_penalty
    demand["_merch_paid_cents"] += applied_merch
    demand["paid_to_date_cents"] += payment["amount_cents"]
    demand["outstanding_cents"] = demand_outstanding(demand)
    _recompute_demand_status_after_post(demand)
    touch(demand)

    case = db.cases.get(demand["case_id"])
    if case is not None:
        recompute_case_restitution_status(case)
        touch(case)
    if case is not None:
        store = db.stores.get(case["store_id"])
        if store is not None:
            store["restitution_collected_cents"] += payment["amount_cents"]
            touch(store)
    return success_object(pub(payment))


@bp.route("/restitution-payments/<payment_id>/return", methods=["POST"])
def return_payment(payment_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    payment = get_or_404(db.restitution_payments, payment_id, "restitution payment")
    if payment["status"] != "POSTED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Payment must be POSTED to return")
    demand = db.civil_demands.get(payment["demand_id"])

    payment["status"] = "RETURNED"
    touch(payment)

    demand["fees_incurred_cents"] += NSF_FEE_CENTS
    demand["_fees_paid_cents"] -= payment["applied_fees_cents"]
    demand["_penalty_paid_cents"] -= payment["applied_penalty_cents"]
    demand["_merch_paid_cents"] -= payment["applied_merch_cents"]
    demand["paid_to_date_cents"] -= payment["amount_cents"]
    demand["outstanding_cents"] = demand_outstanding(demand)
    # status unwind
    if demand["status"] == "PAID_IN_FULL":
        demand["status"] = "PARTIALLY_PAID"
    if demand["status"] == "PARTIALLY_PAID" and demand["paid_to_date_cents"] == 0:
        demand["status"] = "ISSUED"
    touch(demand)

    case = db.cases.get(demand["case_id"]) if demand else None
    if case is not None:
        recompute_case_restitution_status(case)
        touch(case)
        store = db.stores.get(case["store_id"])
        if store is not None:
            store["restitution_collected_cents"] -= payment["amount_cents"]
            touch(store)
    return success_object(pub(payment))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
