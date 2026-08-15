"""CostPremiumAnalysis endpoints (PRD 3.7)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok
from services import (
    compute_analysis_fields,
    get_analysis,
    get_project,
    ser_analysis,
    stamp,
    touch,
)
from util import as_int, as_str, body, required

bp = Blueprint("analyses", __name__)


@bp.post("/cost-premium-analyses")
def create_analysis():
    _user_id, role = auth_headers()
    data = body()
    project_id = as_str(required(data, "project_id"), "project_id")
    incremental = as_int(
        required(data, "incremental_construction_cost_cents"),
        "incremental_construction_cost_cents",
    )
    if incremental <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "incremental_construction_cost_cents must be > 0"
        )
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    for a in DB["cost_premium_analyses"].values():
        if a["project_id"] == project["id"]:
            raise ApiError(
                "ERR_ANALYSIS_EXISTS",
                409,
                "A cost premium analysis already exists for the project",
            )
    rec = stamp(
        {
            "project_id": project["id"],
            "incremental_construction_cost_cents": incremental,
            "annual_energy_savings_cents": 0,
            "incentive_total_cents": 0,
            "net_cost_premium_cents": 0,
            "simple_payback_years": None,
            "analysis_version": 1,
        }
    )
    # Pinned evaluation order; raises ERR_PROPOSED_MODEL_NOT_LOCKED when the
    # LOCKED baseline/proposed pair is missing.
    compute_analysis_fields(rec)
    DB["cost_premium_analyses"][rec["id"]] = rec
    return ok(ser_analysis(rec), status=201)


@bp.get("/cost-premium-analyses/<analysis_id>")
def get_one_analysis(analysis_id):
    auth_headers()
    return ok(ser_analysis(get_analysis(analysis_id)))


@bp.post("/cost-premium-analyses/<analysis_id>/recalculate")
def recalculate_analysis(analysis_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"ProjectAdministrator"})
    rec = get_analysis(analysis_id)
    compute_analysis_fields(rec)
    rec["analysis_version"] += 1
    touch(rec)
    return ok(ser_analysis(rec))
