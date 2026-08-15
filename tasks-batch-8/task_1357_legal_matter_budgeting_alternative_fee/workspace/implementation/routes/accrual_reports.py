"""AccrualReport endpoints (PRD §3.8)."""
from flask import Blueprint

import db
import util
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MATTER_NOT_OPEN,
)
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("accrual_reports", __name__)

READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner",
              "ManagingPartner", "ClientContact")


def _compute_amounts(report):
    """accrued_fees_cents / unbilled_wip_cents per PRD §3.8 / accrual_report_amounts."""
    entries = derived.entries_of(report["matter_id"])
    period = report.get("period_index")
    accrued = sum(
        int(e.get("billable_amount_cents", 0))
        for e in entries
        if e.get("period_index") == period and e.get("status") in ("APPROVED", "BILLED")
    )
    wip = sum(
        int(e.get("billable_amount_cents", 0))
        for e in entries
        if e.get("period_index") is not None
        and e.get("period_index") <= period
        and e.get("status") in ("DRAFT", "SUBMITTED", "APPROVED")
    )
    return accrued, wip


def _snapshot(report):
    """Freeze the two snapshot fields from current matter state."""
    matter = db.matters.get(report["matter_id"])
    if matter is not None:
        derived.recompute_matter(matter, bump=False)
        report["forecast_at_complete_cents"] = matter.get("revised_forecast_cents")
        report["variance_at_submission_cents"] = matter.get("variance_cents")
    accrued, wip = _compute_amounts(report)
    report["accrued_fees_cents"] = accrued
    report["unbilled_wip_cents"] = wip


@bp.get("/firms/accrual_reports/<reportId>")
def get_report(reportId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    report = util.get_report_flat(reportId)
    return success_object(report, 200)


@bp.get("/firms/accrual_reports")
def list_reports():
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    filters = util.query_filters(["firm_id", "matter_id", "status", "period_index"])
    items = util.apply_filters(list(db.accrual_reports.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/matters/<matterId>/accrual_reports")
def list_reports_for_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    filters = util.query_filters(["status", "period_index"])
    items = [r for r in db.accrual_reports.values() if r.get("matter_id") == matter["id"]]
    items = util.apply_filters(items, filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/accrual_reports/<reportId>/submit")
def submit_report(firmId, reportId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    firm = util.get_firm(firmId)
    report = util.get_report_scoped(firmId, reportId)
    if report["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT accrual report can be submitted", 409)
    matter = db.matters.get(report["matter_id"])
    if matter is None:
        from errors import err_not_found
        raise err_not_found("Matter not found")
    if matter["status"] not in ("ACTIVE", "REOPENED", "SUSPENDED"):
        raise ApiError(ERR_MATTER_NOT_OPEN,
                       "Matter not in ACTIVE/REOPENED/SUSPENDED for accrual submission", 409)
    _snapshot(report)
    report["submitted_period_index"] = int(firm.get("current_period_index", 0))
    report["status"] = "SUBMITTED"
    util.touch(report)
    return success_object(report, 200)


@bp.post("/firms/<firmId>/accrual_reports/<reportId>/acknowledge")
def acknowledge_report(firmId, reportId):
    ctx = get_context()
    require_roles(ctx, "ClientContact")
    report = util.get_report_scoped(firmId, reportId)
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a SUBMITTED accrual report can be acknowledged", 409)
    report["status"] = "ACKNOWLEDGED"
    util.touch(report)
    return success_object(report, 200)


@bp.post("/firms/<firmId>/accrual_reports/<reportId>/dispute")
def dispute_report(firmId, reportId):
    ctx = get_context()
    require_roles(ctx, "ClientContact")
    report = util.get_report_scoped(firmId, reportId)
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a SUBMITTED accrual report can be disputed", 409)
    report["status"] = "DISPUTED"
    util.touch(report)
    return success_object(report, 200)


@bp.post("/firms/<firmId>/accrual_reports/<reportId>/resubmit")
def resubmit_report(firmId, reportId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    firm = util.get_firm(firmId)
    report = util.get_report_scoped(firmId, reportId)
    if report["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DISPUTED accrual report can be resubmitted", 409)
    _snapshot(report)
    report["submitted_period_index"] = int(firm.get("current_period_index", 0))
    report["status"] = "SUBMITTED"
    util.touch(report)
    return success_object(report, 200)
