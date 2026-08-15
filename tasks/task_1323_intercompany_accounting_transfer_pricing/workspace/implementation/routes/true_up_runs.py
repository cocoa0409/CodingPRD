"""TrueUpRun lifecycle (PRD 3.5).

DRAFT -> COMPUTED -> (recompute -> DRAFT cyclic) -> APPROVED -> POSTED.
Posting fires the three-link cascade: adjustment transaction, immediate
auto-elimination, and cash-pool pending accrual.
"""
from flask import Blueprint, request

import errors
from db import store, new_resource, touch, public
from errors import ApiError
from middleware import (
    require_auth, get_body, get_path, require_fk, shape_str, list_page, ALL_ROLES,
)
from response import ok_object, ok_list
from services import calc

bp = Blueprint("true_up_runs", __name__)


def _tested_transactions(run):
    return [t for t in store.transactions.values()
            if t["agreement_id"] == run["agreement_id"]
            and t["fiscal_year_id"] == run["fiscal_year_id"]
            and t["elimination_status"] in ("MATCHED", "ELIMINATED")]


@bp.post("/tp/true_up_runs")
def create_true_up_run():
    uid, _ = require_auth(["TaxAnalyst"])
    body = get_body()
    agid = body.get("agreement_id")
    fyid = body.get("fiscal_year_id")
    require_fk(store.agreements, agid, "agreement_id")
    require_fk(store.fiscal_years, fyid, "fiscal_year_id")
    shape_str(body, "agreement_id")
    shape_str(body, "fiscal_year_id")
    r = new_resource()
    r.update({
        "agreement_id": agid,
        "fiscal_year_id": fyid,
        "status": "DRAFT",
        "actual_margin_bp": None,
        "true_up_amount_cents": None,
        "adjustment_transaction_id": None,
        "created_by_user_id": uid,
        "approved_by_user_id": None,
    })
    store.true_up_runs[r["id"]] = r
    return ok_object(public(r), 201)


@bp.get("/tp/true_up_runs/<trueUpRunId>")
def get_true_up_run(trueUpRunId):
    require_auth(ALL_ROLES)
    r = get_path(store.true_up_runs, trueUpRunId)
    return ok_object(public(r), 200)


@bp.get("/tp/true_up_runs")
def list_true_up_runs():
    require_auth(ALL_ROLES)
    filters = [
        ("agreement_id", request.args.get("agreement_id")),
        ("fiscal_year_id", request.args.get("fiscal_year_id")),
        ("adjustment_transaction_id", request.args.get("adjustment_transaction_id")),
        ("status", request.args.get("status")),
    ]
    page, limit, offset, total = list_page(list(store.true_up_runs.values()), filters)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/tp/true_up_runs/<trueUpRunId>/compute")
def compute_true_up_run(trueUpRunId):
    require_auth(["TaxAnalyst"])
    r = get_path(store.true_up_runs, trueUpRunId)
    if r["status"] != "DRAFT":
        raise ApiError(errors.INVALID_STATE, 409,
                       "compute requires the true-up run to be DRAFT")
    txs = _tested_transactions(r)
    if not txs:
        raise ApiError(errors.NO_ELIMINATED_TRANSACTIONS, 409,
                       "No MATCHED or ELIMINATED transactions for this agreement and year")
    agreement = store.agreements.get(r["agreement_id"])
    actual, amount = calc.true_up_calculation(agreement, txs)
    r["actual_margin_bp"] = actual
    r["true_up_amount_cents"] = amount
    r["status"] = "COMPUTED"
    touch(r)
    return ok_object(public(r), 200)


@bp.post("/tp/true_up_runs/<trueUpRunId>/recompute")
def recompute_true_up_run(trueUpRunId):
    require_auth(["TaxAnalyst"])
    r = get_path(store.true_up_runs, trueUpRunId)
    if r["status"] != "COMPUTED":
        raise ApiError(errors.INVALID_STATE, 409,
                       "recompute requires the true-up run to be COMPUTED")
    r["actual_margin_bp"] = None
    r["true_up_amount_cents"] = None
    r["status"] = "DRAFT"
    touch(r)
    return ok_object(public(r), 200)


@bp.post("/tp/true_up_runs/<trueUpRunId>/approve")
def approve_true_up_run(trueUpRunId):
    uid, _ = require_auth(["TaxManager"])
    r = get_path(store.true_up_runs, trueUpRunId)
    if r["status"] != "COMPUTED":
        raise ApiError(errors.INVALID_STATE, 409,
                       "approve requires the true-up run to be COMPUTED")
    # (5) segregation of duties vs creator.
    if uid == r["created_by_user_id"]:
        raise ApiError(errors.SEGREGATION, 409,
                       "Approver must differ from the run creator")
    # (9) fiscal-calendar obligation: the year must be CLOSING.
    fy = store.fiscal_years.get(r["fiscal_year_id"])
    if fy is None or fy["status"] != "CLOSING":
        raise ApiError(errors.YEAR_NOT_CLOSING, 409,
                       "True-up approval requires the fiscal year to be CLOSING")
    r["approved_by_user_id"] = uid
    r["status"] = "APPROVED"
    touch(r)
    return ok_object(public(r), 200)


@bp.post("/tp/true_up_runs/<trueUpRunId>/post")
def post_true_up_run(trueUpRunId):
    require_auth(["TaxManager"])
    r = get_path(store.true_up_runs, trueUpRunId)
    if r["status"] != "APPROVED":
        raise ApiError(errors.INVALID_STATE, 409,
                       "post requires the true-up run to be APPROVED")
    fy = store.fiscal_years.get(r["fiscal_year_id"])
    if fy is None or fy["status"] != "CLOSING":
        raise ApiError(errors.YEAR_NOT_CLOSING, 409,
                       "True-up posting requires the fiscal year to be CLOSING")
    amount = r["true_up_amount_cents"]
    if amount != 0:
        # Cascade link 1: create the adjustment transaction (MATCHED/UNSETTLED).
        adj = new_resource()
        adj.update({
            "agreement_id": r["agreement_id"],
            "fiscal_year_id": r["fiscal_year_id"],
            "cost_base_cents": 0,
            "provider_revenue_cents": amount,
            "recipient_cost_cents": amount,
            "origin_run_id": r["id"],
            "is_true_up_adjustment": True,
            "provisional_al_price_cents": 0,
            "margin_bp": 0,
            "elimination_status": "MATCHED",
            "settlement_status": "UNSETTLED",
            "matched_by_user_id": None,
            "_plug_cents": None,
        })
        store.transactions[adj["id"]] = adj
        r["adjustment_transaction_id"] = adj["id"]
        # Cascade link 2: the adjustment is immediately auto-eliminated (plug 0).
        adj["_plug_cents"] = adj["provider_revenue_cents"] - adj["recipient_cost_cents"]
        adj["elimination_status"] = "ELIMINATED"
        touch(adj)
        # Cascade link 3: accrue pending into an OPEN cash pool for the year.
        agreement = store.agreements.get(r["agreement_id"])
        pool = next((p for p in store.cash_pools.values()
                     if p["fiscal_year_id"] == r["fiscal_year_id"]
                     and p["status"] == "OPEN"), None)
        if pool is not None and agreement is not None:
            from routes.cash_pools import upsert_position
            prov_pos = upsert_position(pool, agreement["provider_entity_id"])
            prov_pos["pending_cents"] += amount
            rec_pos = upsert_position(pool, agreement["recipient_entity_id"])
            rec_pos["pending_cents"] -= amount
            touch(pool)
    r["status"] = "POSTED"
    touch(r)
    return ok_object(public(r), 200)
