"""Capitalization budget lines (PRD 3.2)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (GENERAL_MANAGER, MANAGEMENT_ROLES, ctx, endpoint,
                        find_production, lookup)
from services import ledger

bp = Blueprint("budget_lines", __name__)

COMPONENTS = ("PRODUCTION", "REHEARSAL", "ADVERTISING", "RESERVE",
              "BONDS_AND_DEPOSITS")
COMMITMENT_STATUSES = ("PLANNED", "COMMITTED", "SPENT")


@bp.post("/budget-lines")
@endpoint((GENERAL_MANAGER,))
def create_budget_line():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    component = v.req_enum(data, "component", COMPONENTS)
    description = v.req_str(data, "description", 1, 200)
    amount_cents = v.req_int(data, "amount_cents", 1)
    expected_version = v.req_int(data, "expected_production_version")

    production = find_production(production_id)

    # Global validation step 10 (PRD 2.7).
    if expected_version != production["version"]:
        fail(errors.ERR_STALE_PRODUCTION_VERSION,
             "The production has been written since the client last read it.")

    # Fiscal ceiling 14b (PRD 2.11).
    if production["budget_total_cents"] + amount_cents > production[
            "capitalization_target_cents"]:
        fail(errors.ERR_BUDGET_EXCEEDS_CAPITALIZATION,
             "The line would push budget_total_cents above the capitalization target.")

    row = db.insert("budget_lines", {
        "production_id": production_id,
        "component": component,
        "description": description,
        "amount_cents": amount_cents,
        "commitment_status": "PLANNED",
    })
    ctx().created(row)
    ctx().force(production)
    ledger.capitalization_budget_rollup(ctx(), production)
    return response.obj(row, 201)


@bp.post("/budget-lines/<line_id>/commit")
@endpoint((GENERAL_MANAGER,))
def commit_budget_line(line_id):
    line = lookup("budget_lines", line_id, errors.ERR_BUDGET_LINE_NOT_FOUND)
    production = db.get("productions", line["production_id"])
    if line["commitment_status"] != "PLANNED":
        fail(errors.ERR_INVALID_BUDGET_LINE_STATE,
             "Only a PLANNED line may be committed.")
    if production["budget_status"] != "APPROVED":
        fail(errors.ERR_INVALID_BUDGET_LINE_STATE,
             "The capitalization budget must be APPROVED before a line is committed.")

    ctx().force(production)
    ctx().watch(line)
    line["commitment_status"] = "COMMITTED"
    ledger.capitalization_budget_rollup(ctx(), production)
    return response.obj(line)


@bp.get("/budget-lines/<line_id>")
@endpoint(MANAGEMENT_ROLES)
def read_budget_line(line_id):
    return response.obj(lookup("budget_lines", line_id,
                               errors.ERR_BUDGET_LINE_NOT_FOUND))


@bp.get("/budget-lines")
@endpoint(MANAGEMENT_ROLES)
def list_budget_lines():
    production_id = v.q_str("production_id")
    component = v.q_enum("component", COMPONENTS)
    commitment_status = v.q_enum("commitment_status", COMMITMENT_STATUSES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("budget_lines")
            if (production_id is None or r["production_id"] == production_id)
            and (component is None or r["component"] == component)
            and (commitment_status is None
                 or r["commitment_status"] == commitment_status)]
    return response.listing(rows, limit, offset)
