"""PBGCFiling and DisclosureReport endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination, list_page
from errors import (
    invalid_state, plan_terminated, validation, not_found, ApiError,
    ERR_PLAN_YEAR_MISMATCH, ERR_VALUATION_RUN_NOT_CERTIFIED,
    ERR_FILING_DEADLINE_PASSED, ERR_NO_AMENDMENT_DELTA,
)
from validate import body_of, req_str
from services.core import (
    base_record, touch, public, get_plan, get_run, get_filing, get_report,
    compute_premium_fields, compute_pbo, certified_run_for_plan,
    filing_deadline_for, r2d, r2,
)

bp = Blueprint("filings", __name__)

READ_ROLES = ["PlanAdmin", "Actuary", "SeniorActuary", "Auditor"]


def _plan_active_gate(plan):
    if plan["status"] != "ACTIVE":
        raise plan_terminated()


# ---------------------------------------------------------------------------
# PBGCFiling
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/pbgc-filings", methods=["POST"])
def create_pbgc_filing(plan_id):
    require_roles(["PlanAdmin"])
    plan = get_plan(plan_id)
    _plan_active_gate(plan)
    body = body_of(request)

    # body-referenced run must exist (existence stage)
    run_id = body.get("valuation_run_id")
    run = None
    if isinstance(run_id, str):
        run = get_run(run_id)

    # priority 11: same plan and matching plan_year
    if run is not None and (run["plan_id"] != plan["id"] or run["plan_year"] != plan["plan_year"]):
        raise ApiError(ERR_PLAN_YEAR_MISMATCH, 422, "valuation_run does not belong to this plan and plan_year")

    # priority 22: body well-formedness. Creation snapshots the premium from
    # the referenced run; the CERTIFIED gate applies at file time.
    run_id = req_str(body, "valuation_run_id")
    if run is None:
        run = get_run(run_id)
    premium_method = body.get("premium_method", "STANDARD")
    if not isinstance(premium_method, str) or premium_method not in ("STANDARD", "ALTERNATIVE"):
        raise validation("premium_method must be STANDARD or ALTERNATIVE")

    fields = compute_premium_fields(run, premium_method)
    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "valuation_run_id": run["id"],
        "plan_year": run["plan_year"],
        "premium_method": premium_method,
        "status": "DRAFT",
        "filed_at": None,
    })
    rec.update(fields)
    store.pbgc_filings[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/pbgc-filings", methods=["GET"])
def list_pbgc_filings(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [f for f in store.pbgc_filings.values() if f["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(f) for f in page], limit, offset, total)


@bp.route("/v1/pbgc-filings/<filing_id>", methods=["GET"])
def fetch_pbgc_filing(filing_id):
    require_roles(READ_ROLES)
    rec = get_filing(filing_id)
    return success_object(public(rec))


@bp.route("/v1/valuation-runs/<run_id>/pbgc-filings", methods=["GET"])
def list_filings_by_run(run_id):
    require_roles(READ_ROLES)
    run = get_run(run_id)
    limit, offset = parse_pagination(request.args)
    items = [f for f in store.pbgc_filings.values() if f["valuation_run_id"] == run["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(f) for f in page], limit, offset, total)


@bp.route("/v1/pbgc-filings/<filing_id>/file", methods=["POST"])
def file_pbgc_filing(filing_id):
    require_roles(["PlanAdmin"])
    filing = get_filing(filing_id)
    if filing["status"] not in ("DRAFT", "AMENDED"):
        raise invalid_state("PBGCFiling is not DRAFT or AMENDED")
    plan = store.plans.get(filing["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    # priority 8: filing deadline plan_year-10-15T00:00:00Z
    if store.now() > filing_deadline_for(filing["plan_year"]):
        raise ApiError(ERR_FILING_DEADLINE_PASSED, 422, "Filing deadline has passed")
    # priority 14: referenced run must be CERTIFIED
    run = store.valuation_runs.get(filing["valuation_run_id"])
    if run is None or run["status"] != "CERTIFIED":
        raise ApiError(ERR_VALUATION_RUN_NOT_CERTIFIED, 422, "Referenced valuation run is not CERTIFIED")
    filing["status"] = "FILED"
    filing["filed_at"] = store.now_str()
    touch(filing)
    return success_object(public(filing))


@bp.route("/v1/pbgc-filings/<filing_id>/amend", methods=["POST"])
def amend_pbgc_filing(filing_id):
    require_roles(["PlanAdmin"])
    filing = get_filing(filing_id)
    if filing["status"] != "FILED":
        raise invalid_state("PBGCFiling is not FILED")
    plan = store.plans.get(filing["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    # priority 19: a superseding certification must have occurred
    current = certified_run_for_plan(filing["plan_id"])
    if current is None or current["id"] == filing["valuation_run_id"]:
        raise ApiError(ERR_NO_AMENDMENT_DELTA, 422, "The plan's certified run has not changed since this filing")
    # re-point to the currently CERTIFIED run and recompute the premium snapshot
    filing["valuation_run_id"] = current["id"]
    filing["plan_year"] = current["plan_year"]
    fields = compute_premium_fields(current, filing["premium_method"])
    filing.update(fields)
    filing["status"] = "AMENDED"
    filing["filed_at"] = None
    touch(filing)
    return success_object(public(filing))


@bp.route("/v1/pbgc-filings/<filing_id>/void", methods=["POST"])
def void_pbgc_filing(filing_id):
    require_roles(["PlanAdmin"])
    filing = get_filing(filing_id)
    if filing["status"] != "DRAFT":
        raise invalid_state("PBGCFiling is not DRAFT")
    plan = store.plans.get(filing["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    filing["status"] = "VOID"
    touch(filing)
    return success_object(public(filing))


# ---------------------------------------------------------------------------
# DisclosureReport
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/disclosure-reports", methods=["POST"])
def create_disclosure_report(plan_id):
    require_roles(["PlanAdmin", "Actuary", "SeniorActuary"])
    plan = get_plan(plan_id)
    _plan_active_gate(plan)
    body = body_of(request)

    run_id = body.get("valuation_run_id")
    run = None
    if isinstance(run_id, str):
        run = get_run(run_id)
    if run is not None and (run["plan_id"] != plan["id"] or run["plan_year"] != plan["plan_year"]):
        raise ApiError(ERR_PLAN_YEAR_MISMATCH, 422, "valuation_run does not belong to this plan and plan_year")
    # priority 14: disclosure generation requires a CERTIFIED run
    if run is not None and run["status"] != "CERTIFIED":
        raise ApiError(ERR_VALUATION_RUN_NOT_CERTIFIED, 422, "Referenced valuation run is not CERTIFIED")

    run_id = req_str(body, "valuation_run_id")
    if run is None:
        run = get_run(run_id)

    pbo = compute_pbo(run)
    ava = store.asset_valuations.get(run["asset_valuation_id"])
    fair_value_assets = r2d(ava["market_value"]) if ava else r2d(0)
    funded_status = fair_value_assets - pbo

    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "valuation_run_id": run["id"],
        "pbo": float(pbo),
        "fair_value_assets": float(fair_value_assets),
        "funded_status": float(r2d(funded_status)),
        "status": "DRAFT",
        "acknowledged_by": None,
    })
    store.disclosure_reports[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/disclosure-reports", methods=["GET"])
def list_disclosure_reports(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.disclosure_reports.values() if r["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/v1/disclosure-reports/<report_id>", methods=["GET"])
def fetch_disclosure_report(report_id):
    require_roles(READ_ROLES)
    rec = get_report(report_id)
    return success_object(public(rec))


@bp.route("/v1/valuation-runs/<run_id>/disclosure-reports", methods=["GET"])
def list_reports_by_run(run_id):
    require_roles(READ_ROLES)
    run = get_run(run_id)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.disclosure_reports.values() if r["valuation_run_id"] == run["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/v1/disclosure-reports/<report_id>/acknowledge", methods=["POST"])
def acknowledge_disclosure_report(report_id):
    role, user_id = require_roles(["Auditor"])
    report = get_report(report_id)
    if report["status"] != "DRAFT":
        raise invalid_state("DisclosureReport is not DRAFT")
    report["status"] = "ACKNOWLEDGED"
    report["acknowledged_by"] = user_id
    touch(report)
    return success_object(public(report))
