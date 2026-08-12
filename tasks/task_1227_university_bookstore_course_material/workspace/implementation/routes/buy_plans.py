"""Buy plans: draft edits, OCC-guarded commit with tiered landed cost and the
term budget cap, receipt into stock, cancellation (PRD §3.5)."""

from flask import Blueprint

from db import store, new_entity, touch, pub
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_NO_ACTIVE_AGREEMENT, ERR_ADOPTION_NOT_APPROVED,
    ERR_TERM_BUDGET_EXCEEDED,
)
from middleware import require_roles, body, get_int, get_or_404
from response import success
from services import (
    active_agreement, compute_landed_cost, committed_landed_total,
    plan_term_id,
)

bp = Blueprint("buy_plans", __name__)

PLAN_QTY_FIELDS = ("qty_new", "qty_used", "qty_rental", "qty_digital")


@bp.get("/bookstore/buy-plans/<pid>")
def get_buy_plan(pid):
    require_roles("BookstoreManager", "FinanceAdmin")
    return success(pub(get_or_404(store.buy_plans, pid, "buy plan")))


@bp.patch("/bookstore/buy-plans/<pid>")
def patch_buy_plan(pid):
    require_roles("BookstoreManager")
    plan = get_or_404(store.buy_plans, pid, "buy plan")
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "buy plan not in DRAFT")
    data = body()
    for f in PLAN_QTY_FIELDS:
        if f in data and data[f] is not None:
            plan[f] = get_int(data, f, min_val=0)
    touch(plan)
    return success(pub(plan))


@bp.post("/bookstore/buy-plans/<pid>/commit")
def commit_buy_plan(pid):
    uid, _ = require_roles("BookstoreManager")
    plan = get_or_404(store.buy_plans, pid, "buy plan")
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "buy plan not in DRAFT")
    data = body()
    # OCC (§2.7): after existence and from-state, before business rules
    expected = get_int(data, "expected_buy_plan_version")
    if expected != plan["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "stale buy plan version")
    adoption = store.adoptions[plan["adoption_id"]]
    if adoption["status"] != "APPROVED":
        raise ApiError(ERR_ADOPTION_NOT_APPROVED, 422,
                       "referenced adoption not APPROVED")
    title = store.titles[adoption["title_id"]]
    agreement = active_agreement(title["publisher_id"])
    if agreement is None:
        raise ApiError(ERR_NO_ACTIVE_AGREEMENT, 422,
                       "no active agreement covers the publisher")
    calc = compute_landed_cost(plan, agreement)
    term = store.terms[plan_term_id(plan)]
    spent = committed_landed_total(term["id"])
    if spent + calc["landed_cost_cents"] > term["buy_budget_cents"]:
        raise ApiError(ERR_TERM_BUDGET_EXCEEDED, 422,
                       "commit exceeds the term buy budget")
    plan["discount_pct_applied"] = calc["discount_pct_applied"]
    plan["tier_bonus_applied"] = calc["tier_bonus_applied"]
    plan["landed_cost_cents"] = calc["landed_cost_cents"]
    plan["committed_by_user_id"] = uid
    plan["status"] = "COMMITTED"
    touch(plan)
    return success(pub(plan))


@bp.post("/bookstore/buy-plans/<pid>/receive")
def receive_buy_plan(pid):
    require_roles("BookstoreManager")
    plan = get_or_404(store.buy_plans, pid, "buy plan")
    if plan["status"] != "COMMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "buy plan not in COMMITTED")
    data = body()
    rec_new = get_int(data, "received_new_qty", min_val=0)
    rec_used = get_int(data, "received_used_qty", min_val=0)
    rec_rental = get_int(data, "received_rental_qty", min_val=0)
    if (rec_new > plan["qty_new"] or rec_used > plan["qty_used"]
            or rec_rental > plan["qty_rental"]):
        raise ApiError(ERR_VALIDATION, 400,
                       "received quantity exceeds committed quantity")
    adoption = store.adoptions[plan["adoption_id"]]
    title = store.titles[adoption["title_id"]]
    title["new_stock_qty"] += rec_new
    title["used_stock_qty"] += rec_used
    title["rental_stock_qty"] += rec_rental
    touch(title)
    plan["status"] = "RECEIVED"
    touch(plan)
    return success(pub(plan))


@bp.post("/bookstore/buy-plans/<pid>/cancel")
def cancel_buy_plan(pid):
    require_roles("BookstoreManager")
    plan = get_or_404(store.buy_plans, pid, "buy plan")
    if plan["status"] not in ("DRAFT", "COMMITTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "buy plan not in DRAFT or COMMITTED")
    plan["status"] = "CANCELLED"
    touch(plan)
    return success(pub(plan))
