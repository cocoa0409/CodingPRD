"""TrueUpRun endpoints (PRD 3.7)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_TRUEUP_GUARD
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public
from services.ledger import compute_trueup_adjustments
from validate import get_body, req_period, require_path_resource

bp = Blueprint("trueups", __name__)

TRUEUP_READ_ROLES = ["CompAnalyst", "CompCommittee"]


@bp.post("/comp-plans/<rid>/true-up-runs")
def create_trueup_run(rid):
    authorized(["CompAnalyst"])
    plan = require_path_resource("comp_plans", rid)
    body = get_body()
    as_of_period = req_period(body, "as_of_period")
    # Priority 23: blocked while any agreement of the plan has an UNDER_REVIEW
    # statement, or another run for the plan is still COMPUTED
    for a in db["physician_agreements"].values():
        if a["plan_id"] != plan["id"]:
            continue
        for s in db["comp_statements"].values():
            if s["agreement_id"] == a["id"] and s["status"] == "UNDER_REVIEW":
                raise_error(ERR_TRUEUP_GUARD,
                            "an agreement of the plan has an UNDER_REVIEW statement")
    for r in db["true_up_runs"].values():
        if r["plan_id"] == plan["id"] and r["status"] == "COMPUTED":
            raise_error(ERR_TRUEUP_GUARD, "another true-up run is still COMPUTED")
    adjustments = compute_trueup_adjustments(plan, as_of_period)
    rec = new_record("true_up_runs", {
        "plan_id": plan["id"],
        "as_of_period": as_of_period,
        "adjustments": adjustments,
        "status": "COMPUTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/comp-plans/<rid>/true-up-runs")
def list_trueup_runs(rid):
    authorized(TRUEUP_READ_ROLES)
    require_path_resource("comp_plans", rid)
    return list_response("true_up_runs", {"plan_id": rid})


@bp.post("/true-up-runs/<rid>/post")
def post_trueup_run(rid):
    authorized(["CompCommittee"])
    run = require_path_resource("true_up_runs", rid)
    if run["status"] != "COMPUTED":
        raise_error(ERR_INVALID_STATE, "only a COMPUTED true-up run can be posted")
    for adj in run["adjustments"]:
        agr = db["physician_agreements"].get(adj["agreement_id"])
        if agr is not None:
            # Overwrite semantics, not accumulation
            agr["pending_trueup_adjustment_cents"] = adj["variance_cents"]
            touch("physician_agreements", agr)
    run["status"] = "POSTED"
    touch("true_up_runs", run)
    return success_object(public(run))


@bp.post("/true-up-runs/<rid>/void")
def void_trueup_run(rid):
    authorized(["CompAnalyst"])
    run = require_path_resource("true_up_runs", rid)
    if run["status"] != "COMPUTED":
        raise_error(ERR_INVALID_STATE, "only a COMPUTED true-up run can be voided")
    run["status"] = "VOIDED"
    touch("true_up_runs", run)
    return success_object(public(run))
