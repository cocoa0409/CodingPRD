"""Weekly operating budgets (PRD 3.5)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (COMPTROLLER, GENERAL_MANAGER, MANAGEMENT_ROLES, ctx,
                        endpoint, find_production, lookup)
from services import queries as q

bp = Blueprint("operating_budgets", __name__)

BUDGET_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")


@bp.post("/operating-budgets")
@endpoint((GENERAL_MANAGER,))
def create_operating_budget():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    running_cost = v.req_int(data, "weekly_fixed_running_cost_cents", 1)
    variable_cost_pct = v.req_pct(data, "variable_cost_pct")
    performances = v.opt_int(data, "performances_per_week", 8, 1, 16)

    find_production(production_id)
    row = db.insert("operating_budgets", {
        "production_id": production_id,
        "weekly_fixed_running_cost_cents": running_cost,
        "variable_cost_pct": variable_cost_pct,
        "performances_per_week": performances,
        "status": "DRAFT",
    })
    return response.obj(row, 201)


@bp.post("/operating-budgets/<budget_id>/activate")
@endpoint((COMPTROLLER,))
def activate_operating_budget(budget_id):
    budget = lookup("operating_budgets", budget_id,
                    errors.ERR_OPERATING_BUDGET_NOT_FOUND)
    if budget["status"] != "DRAFT":
        fail(errors.ERR_INVALID_OPERATING_BUDGET_STATE,
             "Only a DRAFT operating budget may be activated.")

    # Activation supersedes the incumbent; the version bump on the superseded
    # row is what invalidates every wrap that pinned it (PRD 3.5).
    for other in q.active_operating_budgets(budget["production_id"]):
        if other["id"] == budget["id"]:
            continue
        ctx().watch(other)
        other["status"] = "SUPERSEDED"

    ctx().watch(budget)
    budget["status"] = "ACTIVE"
    return response.obj(budget)


@bp.get("/operating-budgets/<budget_id>")
@endpoint(MANAGEMENT_ROLES)
def read_operating_budget(budget_id):
    return response.obj(lookup("operating_budgets", budget_id,
                               errors.ERR_OPERATING_BUDGET_NOT_FOUND))


@bp.get("/operating-budgets")
@endpoint(MANAGEMENT_ROLES)
def list_operating_budgets():
    production_id = v.q_str("production_id")
    status = v.q_enum("status", BUDGET_STATUSES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("operating_budgets")
            if (production_id is None or r["production_id"] == production_id)
            and (status is None or r["status"] == status)]
    return response.listing(rows, limit, offset)
