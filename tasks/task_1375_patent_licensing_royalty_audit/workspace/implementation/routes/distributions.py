"""Distribution run endpoints."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response
from services import calc

bp = Blueprint("distributions", __name__)


@bp.post("/licensing/distribution-runs")
def create_run():
    user_id, _ = middleware.require_role("FinanceOfficer")
    body = common.get_body()
    common.validate_body(body, [
        ("agreement_id", "string", True),
        ("period_start", "datetime", True),
        ("period_end", "datetime", True),
        ("pool_cents", "int", True),
    ])
    # Tier 3: body FK existence
    agr = db.agreements.get(body["agreement_id"])
    if agr is None:
        raise errors.err_agreement_not_found()
    ps = common.parse_dt(body["period_start"])
    pe = common.parse_dt(body["period_end"])
    if pe <= ps:
        raise errors.err_validation("period_end must be after period_start")
    if body["pool_cents"] <= 0:
        raise errors.err_validation("pool_cents must be > 0")
    # Tier 7: agreement must not be DRAFT
    if agr["status"] == "DRAFT":
        raise errors.err_agreement_not_active(
            "Distribution runs may not target a DRAFT agreement")
    # Tier 11: period closed
    if pe > common.logical_now():
        raise errors.err_period_not_closed()
    # Tier 13: pool guard at creation
    if body["pool_cents"] > agr["undistributed_pool_cents"]:
        raise errors.err_pool_exceeds_undistributed()

    run = common.new_resource({
        "agreement_id": body["agreement_id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "pool_cents": body["pool_cents"],
        "lines": [],
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "DRAFT",
    })
    db.distribution_runs[run["id"]] = run
    return response.success_object(run, 201)


@bp.get("/licensing/distribution-runs")
def list_runs():
    middleware.require_role("FinanceOfficer", "LicensingAnalyst")
    args = common.request.args
    agreement_id = args.get("agreement_id")
    status = args.get("status")
    items = list(db.distribution_runs.values())
    if agreement_id is not None:
        items = [r for r in items if r["agreement_id"] == agreement_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/distribution-runs/<rid>")
def get_run(rid):
    middleware.require_role("FinanceOfficer", "LicensingAnalyst")
    run = db.distribution_runs.get(rid)
    if run is None:
        raise errors.err_run_not_found()
    return response.success_object(run)


@bp.post("/licensing/distribution-runs/<rid>/approve")
def approve_run(rid):
    user_id, _ = middleware.require_role("FinanceOfficer")
    run = db.distribution_runs.get(rid)
    if run is None:
        raise errors.err_run_not_found()
    body = common.get_body()
    if body:
        raise errors.err_validation("Undeclared fields in request body")
    # Tier 8
    if run["status"] != "DRAFT":
        raise errors.err_run_invalid_state(
            "Only a DRAFT distribution run can be approved")
    # Tier 9: SoD -- approver != creator
    if user_id == run["created_by_user_id"]:
        raise errors.err_sod_conflict(
            "The approver must differ from the run's creator")
    agr = db.agreements[run["agreement_id"]]
    # Tier 13: pool re-check at approval
    if run["pool_cents"] > agr["undistributed_pool_cents"]:
        raise errors.err_pool_exceeds_undistributed()

    run["lines"] = calc.inventor_share_distribution(agr, run["pool_cents"])
    run["approved_by_user_id"] = user_id
    agr["undistributed_pool_cents"] -= run["pool_cents"]
    common.touch(agr)
    run["status"] = "POSTED"
    common.touch(run)
    return response.success_object(run)


@bp.post("/licensing/distribution-runs/<rid>/void")
def void_run(rid):
    user_id, _ = middleware.require_role("FinanceOfficer")
    run = db.distribution_runs.get(rid)
    if run is None:
        raise errors.err_run_not_found()
    body = common.get_body()
    common.validate_body(body, [("reason", "string", True)])
    # Tier 8
    if run["status"] != "POSTED":
        raise errors.err_run_invalid_state(
            "Only a POSTED distribution run can be voided")
    agr = db.agreements[run["agreement_id"]]
    agr["undistributed_pool_cents"] += run["pool_cents"]
    common.touch(agr)
    run["status"] = "VOIDED"
    common.touch(run)
    return response.success_object(run)
