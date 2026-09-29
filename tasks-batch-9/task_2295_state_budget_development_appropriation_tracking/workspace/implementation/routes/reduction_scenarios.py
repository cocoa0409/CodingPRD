"""Reduction scenarios: immutable waterfall snapshots over a cycle."""

from flask import Blueprint

import db
import auth
import response
from errors import fail
from services import calc
from services import core
from validators import body_json, peek_fk, read_id, read_number

bp = Blueprint("reduction_scenarios", __name__)


@bp.post("/fiscal/reduction-scenarios")
def create_scenario():
    auth.authenticate((auth.BUDGET_ANALYST,))
    body = body_json()

    cycle = peek_fk(body, "budget_cycle_id", core.get_cycle)

    read_id(body, "budget_cycle_id")
    target_pct = read_number(body, "target_reduction_pct")
    if target_pct <= 0 or target_pct > 0.5:
        fail(
            "ERR_INVALID_REQUEST",
            "target_reduction_pct must be greater than 0 and at most 0.5.",
        )

    core.require_not_closed(cycle)

    _, candidates = calc.reduction_candidates(cycle)
    if not candidates:
        fail(
            "ERR_NO_REDUCTION_CANDIDATES",
            "The cycle has no eligible PROPOSED REDUCTION package.",
        )

    result = calc.reduction_waterfall(cycle, target_pct)
    row = db.new_row(audited=False)
    row.update(
        {
            "budget_cycle_id": cycle["id"],
            "target_reduction_pct": target_pct,
            "target_reduction_cents": result["target_reduction_cents"],
            "selected_package_ids": result["selected_package_ids"],
            "achieved_reduction_cents": result["achieved_reduction_cents"],
            "overshoot_cents": result["overshoot_cents"],
            "feasibility": result["feasibility"],
        }
    )
    db.reduction_scenarios[row["id"]] = row
    return response.created(db.serialize(row))
