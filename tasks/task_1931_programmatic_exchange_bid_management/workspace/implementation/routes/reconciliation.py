"""Reconciliation report endpoints (PRD §3.7): DSP-vs-SSP discrepancy
reporting and the acknowledge / dispute / resolve workflow."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, invalid_state, ApiError, ERR_INVALID_TIME_RANGE,
    ERR_REPORT_ALREADY_TERMINAL, ERR_RECONCILIATION_INPUT_MISMATCH,
)
from middleware import (
    require_roles, ALL_ROLES, ROLE_EXCHANGE_ADMIN, ROLE_FINANCE_OFFICER,
)
from response import success_object, success_list, paginate
from util import get_body, req_str, req_enum, req_date, opt_int, has_field
from services.core import (
    RESOLUTION_TYPES, DISCREPANCY_THRESHOLD_PCT,
    base_record, touch, serialize_report, round_pct_3dp,
    recompute_publisher_accruals, _sorted,
)

bp = Blueprint("reconciliation", __name__)

_REPORT_ROLES = [ROLE_EXCHANGE_ADMIN, ROLE_FINANCE_OFFICER]


def _get_report_or_404(report_id):
    rep = store.reports.get(report_id)
    if rep is None:
        raise not_found("ReconciliationReport not found")
    return rep


@bp.route("/reconciliation-reports", methods=["POST"])
def create_report():
    require_roles(_REPORT_ROLES)
    body = get_body()
    deal_id = req_str(body, "deal_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    deal = store.deals.get(deal_id)
    if deal is None:
        raise not_found("Deal not found")
    if not period_start < period_end:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422,
                       "period_start must be strictly before period_end")
    # impression_discrepancy calculation: the SSP set is sliced on record
    # creation date, the DSP set on confirmation date — deliberately different
    # populations
    ssp = [r for r in store.records.values()
           if r["deal_id"] == deal_id and not r["voided"]
           and period_start <= r["_created_dt"].date() < period_end]
    dsp = [r for r in store.records.values()
           if r["deal_id"] == deal_id and not r["voided"]
           and r["_confirmed_dt"] is not None
           and period_start <= r["_confirmed_dt"].date() < period_end]
    ssp_impressions = sum(r["impressions"] for r in ssp)
    ssp_spend = sum(r["gross_micros"] for r in ssp)
    dsp_impressions = sum(r["impressions"] for r in dsp)
    dsp_billed = sum(r["dsp_billed_micros"] for r in dsp)
    discrepancy = round_pct_3dp(abs(ssp_impressions - dsp_impressions),
                                max(ssp_impressions, 1))
    auto_flagged = discrepancy > DISCREPANCY_THRESHOLD_PCT  # strictly greater
    rep = base_record()
    rep.update({
        "deal_id": deal_id,
        "period_start": period_start,
        "period_end": period_end,
        "ssp_impressions": ssp_impressions,
        "ssp_spend_micros": ssp_spend,
        "dsp_impressions": dsp_impressions,
        "dsp_billed_micros": dsp_billed,
        "discrepancy_pct": discrepancy,
        "auto_flagged": auto_flagged,
        "status": "DISPUTED" if auto_flagged else "OPEN",
        "resolution_type": None,
        "adjustment_micros": None,
        "_resolved_dt": None,
    })
    store.reports[rep["id"]] = rep
    return success_object(serialize_report(rep), 201)


@bp.route("/reconciliation-reports", methods=["GET"])
def list_reports():
    require_roles(ALL_ROLES)
    deal_id = request.args.get("deal_id")
    status = request.args.get("status")
    items = list(store.reports.values())
    if deal_id is not None:
        items = [r for r in items if r["deal_id"] == deal_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_report(r) for r in page], limit, offset, total)


@bp.route("/reconciliation-reports/<reportId>", methods=["GET"])
def get_report(reportId):
    require_roles(ALL_ROLES)
    return success_object(serialize_report(_get_report_or_404(reportId)))


@bp.route("/reconciliation-reports/<reportId>/acknowledge", methods=["POST"])
def acknowledge_report(reportId):
    require_roles(_REPORT_ROLES)
    rep = _get_report_or_404(reportId)
    if rep["status"] == "RESOLVED":
        raise ApiError(ERR_REPORT_ALREADY_TERMINAL, 409, "Report is already RESOLVED")
    if rep["status"] != "OPEN":
        raise invalid_state("Report is not OPEN")
    rep["status"] = "ACKNOWLEDGED"
    touch(rep)
    return success_object(serialize_report(rep))


@bp.route("/reconciliation-reports/<reportId>/dispute", methods=["POST"])
def dispute_report(reportId):
    require_roles(_REPORT_ROLES)
    rep = _get_report_or_404(reportId)
    if rep["status"] == "RESOLVED":
        raise ApiError(ERR_REPORT_ALREADY_TERMINAL, 409, "Report is already RESOLVED")
    if rep["status"] != "ACKNOWLEDGED":
        raise invalid_state("Report is not ACKNOWLEDGED")
    rep["status"] = "DISPUTED"
    touch(rep)
    return success_object(serialize_report(rep))


@bp.route("/reconciliation-reports/<reportId>/resolve", methods=["POST"])
def resolve_report(reportId):
    require_roles(_REPORT_ROLES)
    body = get_body()
    resolution_type = req_enum(body, "resolution_type", RESOLUTION_TYPES)
    adjustment = opt_int(body, "adjustment_micros")
    rep = _get_report_or_404(reportId)
    if rep["status"] == "RESOLVED":
        raise ApiError(ERR_REPORT_ALREADY_TERMINAL, 409, "Report is already RESOLVED")
    # resolution input consistency (stage 18)
    if resolution_type == "MAKE_GOOD":
        if adjustment is None or adjustment <= 0:
            raise ApiError(ERR_RECONCILIATION_INPUT_MISMATCH, 422,
                           "MAKE_GOOD requires adjustment_micros > 0")
    else:
        if adjustment is not None:
            raise ApiError(ERR_RECONCILIATION_INPUT_MISMATCH, 422,
                           "ACCEPT_SSP / ACCEPT_DSP forbid adjustment_micros")
    rep["status"] = "RESOLVED"
    rep["resolution_type"] = resolution_type
    rep["adjustment_micros"] = adjustment if resolution_type == "MAKE_GOOD" else None
    rep["_resolved_dt"] = store.now()
    touch(rep)
    if resolution_type == "MAKE_GOOD":
        # the make-good credit lands on the publisher's open accrual and flows
        # into the next overlapping payout line (§3.7, §3.8)
        deal = store.deals.get(rep["deal_id"])
        if deal is not None:
            pub = store.publishers.get(deal["publisher_id"])
            if pub is not None:
                recompute_publisher_accruals(pub)
    return success_object(serialize_report(rep))
