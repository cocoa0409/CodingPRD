"""Firm endpoints: create/get, advance_period, close_books (PRD §3.1, §2.6)."""
from flask import Blueprint

import db
import util
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import get_context, require_roles
from response import success_object
from services import derived

bp = Blueprint("firms", __name__)


@bp.post("/firms")
def create_firm():
    ctx = get_context()
    require_roles(ctx, "FirmAdmin")
    data = util.body()
    util.require_fields(data, ["name", "fiscal_year_start_month"])
    name = util.check_string(data, "name")
    start_month = util.check_int(data, "fiscal_year_start_month", minimum=1, maximum=12)

    firm = util.new_resource()
    firm.update({
        "name": name,
        "fiscal_year_start_month": start_month,
        "current_period_index": 0,
        "closed_through_period_index": -1,
    })
    db.firms[firm["id"]] = firm
    return success_object(firm, 201)


@bp.get("/firms/<firmId>")
def get_firm(firmId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "PricingAnalyst", "BillingPartner",
                  "ManagingPartner", "Timekeeper", "ClientContact")
    firm = util.get_firm(firmId)
    return success_object(firm, 200)


@bp.post("/firms/<firmId>/advance_period")
def advance_period(firmId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin")
    firm = util.get_firm(firmId)

    firm["current_period_index"] = int(firm.get("current_period_index", 0)) + 1
    util.touch(firm)
    new_period = firm["current_period_index"]

    # Regenerate a fresh DRAFT accrual report covering the new period on every
    # matter whose client mandates accrual reporting (one report per period).
    for matter in list(db.matters.values()):
        if matter.get("firm_id") != firmId:
            continue
        client = db.clients.get(matter.get("client_id"))
        if client is None or not client.get("accrual_reporting_required"):
            continue
        exists = any(
            r.get("period_index") == new_period
            for r in derived.reports_of(matter["id"])
        )
        if exists:
            continue
        report = util.new_resource()
        report.update({
            "matter_id": matter["id"],
            "firm_id": firmId,
            "period_index": new_period,
            "accrued_fees_cents": 0,
            "unbilled_wip_cents": 0,
            "forecast_at_complete_cents": None,
            "variance_at_submission_cents": None,
            "submitted_period_index": None,
            "status": "DRAFT",
        })
        # Computed amounts reflect the matter's entries at generation time.
        entries = derived.entries_of(matter["id"])
        report["accrued_fees_cents"] = sum(
            int(e.get("billable_amount_cents", 0))
            for e in entries
            if e.get("period_index") == new_period and e.get("status") in ("APPROVED", "BILLED")
        )
        report["unbilled_wip_cents"] = sum(
            int(e.get("billable_amount_cents", 0))
            for e in entries
            if e.get("period_index") is not None
            and e.get("period_index") <= new_period
            and e.get("status") in ("DRAFT", "SUBMITTED", "APPROVED")
        )
        db.accrual_reports[report["id"]] = report

    # Refresh computed amounts on every DRAFT accrual report (they are not
    # frozen until submission; see PRD §3.8 and accrual_report_amounts).
    for report in list(db.accrual_reports.values()):
        if report.get("firm_id") != firmId or report.get("status") != "DRAFT":
            continue
        entries = derived.entries_of(report["matter_id"])
        period = report.get("period_index")
        report["accrued_fees_cents"] = sum(
            int(e.get("billable_amount_cents", 0))
            for e in entries
            if e.get("period_index") == period and e.get("status") in ("APPROVED", "BILLED")
        )
        report["unbilled_wip_cents"] = sum(
            int(e.get("billable_amount_cents", 0))
            for e in entries
            if e.get("period_index") is not None
            and e.get("period_index") <= period
            and e.get("status") in ("DRAFT", "SUBMITTED", "APPROVED")
        )
        util.touch(report)

    return success_object(firm, 200)


@bp.post("/firms/<firmId>/close_books")
def close_books(firmId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "ManagingPartner")
    firm = util.get_firm(firmId)

    target = int(firm.get("current_period_index", 0)) - 1
    if int(firm.get("closed_through_period_index", -1)) == target:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Books are already closed through the current period",
            409,
        )
    firm["closed_through_period_index"] = target
    util.touch(firm)
    return success_object(firm, 200)
