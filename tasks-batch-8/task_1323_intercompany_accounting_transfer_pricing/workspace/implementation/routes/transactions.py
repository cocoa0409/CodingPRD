"""ICTransaction resource (PRD 3.4).

Two independent parallel state dimensions:
  elimination: UNMATCHED -> MATCHED -> ELIMINATED
  settlement:  UNSETTLED -> NETTED -> SETTLED (system-driven via cash pool)
"""
from flask import Blueprint, request

import errors
from db import store, new_resource, touch, public
from errors import ApiError
from middleware import (
    require_auth, get_body, get_path, require_fk, is_int,
    shape_str, shape_int, list_page, ALL_ROLES,
)
from response import ok_object, ok_list
from services import calc

bp = Blueprint("transactions", __name__)

MATCH_TOLERANCE_CENTS = 100


@bp.post("/tp/transactions")
def create_transaction():
    require_auth(["TaxAnalyst"])
    body = get_body()
    agid = body.get("agreement_id")
    fyid = body.get("fiscal_year_id")
    # (3) existence of body FKs in declared order.
    require_fk(store.agreements, agid, "agreement_id")
    require_fk(store.fiscal_years, fyid, "fiscal_year_id")
    ag = store.agreements.get(agid) if isinstance(agid, str) else None
    fy = store.fiscal_years.get(fyid) if isinstance(fyid, str) else None
    # (8) booking only against an ACTIVE agreement.
    if ag is not None and ag["status"] != "ACTIVE":
        raise ApiError(errors.AGREEMENT_NOT_ACTIVE, 409,
                       "Transactions may only be booked against an ACTIVE agreement")
    # (9) never against a CLOSED fiscal year.
    if fy is not None and fy["status"] == "CLOSED":
        raise ApiError(errors.BOOKS_CLOSED, 409,
                       "The fiscal year is CLOSED")
    # (10) shape.
    shape_str(body, "agreement_id")
    shape_str(body, "fiscal_year_id")
    cost = shape_int(body, "cost_base_cents", min_v=1)
    revenue = shape_int(body, "provider_revenue_cents", min_v=0)
    recipient_cost = shape_int(body, "recipient_cost_cents", min_v=0)
    markup = ag["markup_bp"] if is_int(ag.get("markup_bp")) else 0
    t = new_resource()
    t.update({
        "agreement_id": agid,
        "fiscal_year_id": fyid,
        "cost_base_cents": cost,
        "provider_revenue_cents": revenue,
        "recipient_cost_cents": recipient_cost,
        "origin_run_id": None,
        "is_true_up_adjustment": False,
        "provisional_al_price_cents": calc.provisional_price_cents(cost, markup),
        "margin_bp": calc.margin_bp_of(revenue, cost),
        "elimination_status": "UNMATCHED",
        "settlement_status": "UNSETTLED",
        "matched_by_user_id": None,
        "_plug_cents": None,
    })
    store.transactions[t["id"]] = t
    return ok_object(public(t), 201)


@bp.get("/tp/transactions/<transactionId>")
def get_transaction(transactionId):
    require_auth(ALL_ROLES)
    t = get_path(store.transactions, transactionId)
    return ok_object(public(t), 200)


@bp.get("/tp/transactions")
def list_transactions():
    require_auth(ALL_ROLES)
    filters = [
        ("agreement_id", request.args.get("agreement_id")),
        ("fiscal_year_id", request.args.get("fiscal_year_id")),
        ("origin_run_id", request.args.get("origin_run_id")),
        ("elimination_status", request.args.get("elimination_status")),
        ("settlement_status", request.args.get("settlement_status")),
    ]
    page, limit, offset, total = list_page(list(store.transactions.values()), filters)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/tp/transactions/<transactionId>/match")
def match_transaction(transactionId):
    uid, _ = require_auth(["TaxAnalyst"])
    t = get_path(store.transactions, transactionId)
    if t["elimination_status"] != "UNMATCHED":
        raise ApiError(errors.INVALID_STATE, 409,
                       "match requires elimination_status UNMATCHED")
    if abs(t["provider_revenue_cents"] - t["recipient_cost_cents"]) > MATCH_TOLERANCE_CENTS:
        raise ApiError(errors.ELIMINATION_MISMATCH, 409,
                       "Booked amounts differ by more than 100 cents")
    t["elimination_status"] = "MATCHED"
    t["matched_by_user_id"] = uid
    touch(t)
    return ok_object(public(t), 200)
