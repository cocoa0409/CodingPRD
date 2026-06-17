"""CostCenter endpoints + nested budget-adjustments (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize
from services.common import (
    get_body, require_string, require_int, validate_nonneg_fte,
    base_common_fields, base_immutable_fields, fetch, paginate, bump,
)

bp = Blueprint("cost_centers", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


@bp.post("/cost-centers")
def create_cost_center():
    require_auth(["FinanceController"])
    body = get_body()
    name = require_string(body, "name")
    code = require_string(body, "code")
    budget = require_int(body, "annual_budget_cents", min_value=0)
    if body.get("fte_cap") is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: fte_cap")
    fte_cap = validate_nonneg_fte(body.get("fte_cap"))

    for cc in db.cost_centers.values():
        if cc["code"] == code:
            raise err("ERR_INVALID_REQUEST", "code must be unique among cost centers")

    rec = base_common_fields()
    rec.update({
        "name": name,
        "code": code,
        "annual_budget_cents": budget,
        "fte_cap": fte_cap,
    })
    db.cost_centers[rec["id"]] = rec
    return success(serialize.cost_center_out(rec), status=201)


@bp.get("/cost-centers/<cost_center_id>")
def get_cost_center(cost_center_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.cost_centers, cost_center_id)
    return success(serialize.cost_center_out(rec))


@bp.get("/cost-centers")
def list_cost_centers():
    require_auth(ALL_ROLES)
    page, limit, offset, total = paginate(list(db.cost_centers.values()))
    return list_success([serialize.cost_center_out(r) for r in page], limit, offset, total)


# --- Budget adjustments (append-only) ---------------------------------------
@bp.post("/cost-centers/<cost_center_id>/budget-adjustments")
def create_budget_adjustment(cost_center_id):
    require_auth(["FinanceController"])
    cc = fetch(db.cost_centers, cost_center_id)
    body = get_body()
    memo = require_string(body, "memo")
    if body.get("amount_cents") is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: amount_cents")
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise err("ERR_INVALID_REQUEST", "amount_cents must be an integer")
    if amount == 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be non-zero")

    rec = base_immutable_fields()
    rec.update({
        "cost_center_id": cost_center_id,
        "amount_cents": amount,
        "memo": memo,
        "status": "APPLIED",
    })
    db.budget_adjustments[rec["id"]] = rec
    # Applying an adjustment increments the cost center's version by 1 (PRD §3.1).
    bump(cc)
    return success(serialize.budget_adjustment_out(rec), status=201)


@bp.get("/cost-centers/<cost_center_id>/budget-adjustments")
def list_cc_budget_adjustments(cost_center_id):
    require_auth(ALL_ROLES)
    fetch(db.cost_centers, cost_center_id)
    records = [b for b in db.budget_adjustments.values()
               if b["cost_center_id"] == cost_center_id]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.budget_adjustment_out(r) for r in page], limit, offset, total)


@bp.get("/budget-adjustments/<budget_adjustment_id>")
def get_budget_adjustment(budget_adjustment_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.budget_adjustments, budget_adjustment_id)
    return success(serialize.budget_adjustment_out(rec))


@bp.get("/budget-adjustments")
def list_budget_adjustments():
    require_auth(ALL_ROLES)
    cost_center_id = request.args.get("cost_center_id")
    records = list(db.budget_adjustments.values())
    if cost_center_id is not None:
        records = [r for r in records if r["cost_center_id"] == cost_center_id]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.budget_adjustment_out(r) for r in page], limit, offset, total)
