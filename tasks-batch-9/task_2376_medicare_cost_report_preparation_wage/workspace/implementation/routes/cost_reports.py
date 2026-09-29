"""Cost reports: opening, filing and the GME summary read (PRD 3.1 / 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import services.calc as calc
from common import (READ_ROLES, body, check_scope, endpoint, find, gme_refresh, ok_list_of,
                    pagination, public, reference)
from db import db, iso, new_row, ordered, touch, ucc_of
from response import ok
from validators import query_enum, query_string

bp = Blueprint("cost_reports", __name__)

APPORTIONMENT_METHODS = ("SINGLE_APPORTIONMENT", "DOUBLE_APPORTIONMENT")
REPORT_STATUSES = ("DRAFT", "FILED", "TENTATIVE_SETTLED", "FINAL_SETTLED", "REOPENED",
                   "AMENDED_FILED", "CLOSED")
WAGE_DATA_STATUSES = ("NOT_STARTED", "COLLECTED", "UNDER_REVIEW", "VERIFIED",
                      "REVISION_REQUESTED", "REJECTED")
ALLOCATION_STATUSES = ("NOT_RUN", "CURRENT", "STALE")
MAX_PERIOD_DAYS = 366


@bp.post("/cost-reports")
@endpoint(roles=["SystemAdmin", "ReimbursementManager"])
def create_cost_report():
    payload = body()
    provider_id = payload.string("provider_id")
    fiscal_year_begin = payload.date("fiscal_year_begin")
    fiscal_year_end = payload.date("fiscal_year_end")
    apportionment_method = payload.enum("apportionment_method", APPORTIONMENT_METHODS,
                                        required=False, default="SINGLE_APPORTIONMENT")
    utilization = payload.number("medicare_utilization_ratio", required=False,
                                 default=Decimal("0.4000"), places=4, minimum=0, maximum=1)
    interim_payments = payload.integer("interim_payments_received_cents", required=False,
                                       default=0, minimum=0)
    total_charges = payload.integer("total_charges_cents", required=False, default=0, minimum=0)
    discharges = payload.integer("medicare_discharges", required=False, default=0, minimum=0)

    provider = reference("Provider", provider_id)
    check_scope(provider["id"])

    span = (fiscal_year_end - fiscal_year_begin).days
    if span < 1 or span > MAX_PERIOD_DAYS:
        raise errors.business("ERR_FISCAL_PERIOD_INVALID",
                             "The cost reporting period must span 1 to 366 days.")

    report = new_row(
        provider_id=provider["id"],
        fiscal_year_begin=fiscal_year_begin.isoformat(),
        fiscal_year_end=fiscal_year_end.isoformat(),
        filing_deadline=calc.filing_deadline(fiscal_year_end).isoformat(),
        status="DRAFT",
        wage_data_status="NOT_STARTED",
        allocation_status="NOT_RUN",
        apportionment_method=apportionment_method,
        medicare_utilization_ratio=utilization,
        interim_payments_received_cents=interim_payments,
        total_charges_cents=total_charges,
        medicare_discharges=discharges,
        total_direct_cost_cents=0,
        unmapped_tb_total_cents=0,
        total_allowable_cost_cents=0,
        cost_to_charge_ratio=Decimal("0.000000"),
        unweighted_fte_days_total=Decimal("0.0000"),
        unweighted_fte_total=Decimal("0.00"),
        capped_unweighted_fte=Decimal("0.00"),
        weighted_fte_total=Decimal("0.00"),
        rolling_average_fte=Decimal("0.00"),
        allowable_cost_per_discharge_cents=0,
        filed_at=None,
        amendment_count=0,
    )
    db.cost_reports[report["id"]] = report
    return ok(public(report), 201)


@bp.get("/cost-reports/<report_id>")
@endpoint(roles=list(READ_ROLES))
def read_cost_report(report_id):
    report = find("CostReport", report_id)
    check_scope(report["provider_id"])
    return ok(public(report))


@bp.get("/cost-reports")
@endpoint(roles=list(READ_ROLES))
def list_cost_reports():
    limit, offset = pagination()
    provider_id = query_string(request.args, "provider_id")
    status = query_enum(request.args, "status", REPORT_STATUSES)
    wage_data_status = query_enum(request.args, "wage_data_status", WAGE_DATA_STATUSES)
    allocation_status = query_enum(request.args, "allocation_status", ALLOCATION_STATUSES)
    rows = ordered(list(db.cost_reports.values()))
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if wage_data_status is not None:
        rows = [r for r in rows if r["wage_data_status"] == wage_data_status]
    if allocation_status is not None:
        rows = [r for r in rows if r["allocation_status"] == allocation_status]
    return ok_list_of(rows, limit, offset)


@bp.post("/cost-reports/<report_id>/file")
@endpoint(roles=["ReimbursementManager"])
def file_cost_report(report_id):
    report = find("CostReport", report_id)
    check_scope(report["provider_id"])

    if report["status"] not in ("DRAFT", "REOPENED"):
        raise errors.invalid_state(
            "A report in %s may not be filed." % report["status"])
    amending = report["status"] == "REOPENED"

    if not amending and calc.clock_date() > calc.as_date(report["filing_deadline"]):
        raise errors.business("ERR_FILING_DEADLINE_PASSED",
                             "The filing deadline has passed.")
    if report["unmapped_tb_total_cents"] != 0:
        raise errors.business("ERR_UNMAPPED_TRIAL_BALANCE",
                             "Trial balance lines remain unmapped.")
    if report["allocation_status"] != "CURRENT":
        raise errors.business("ERR_ALLOCATION_NOT_CURRENT",
                             "The overhead allocation is not current.")
    if report["wage_data_status"] != "VERIFIED":
        raise errors.business("ERR_WAGE_SUBMISSION_NOT_ACCEPTED",
                             "The wage index submission has not been accepted.")
    if len(ucc_of(report["id"])) != 1:
        raise errors.business("ERR_UCC_DATA_MISSING",
                             "The uncompensated care data set is missing.")

    report["status"] = "AMENDED_FILED" if amending else "FILED"
    if report["filed_at"] is None:
        report["filed_at"] = iso(db.clock)
    else:
        report["amendment_count"] = report["amendment_count"] + 1
    calc.recompute_gme(report)
    touch(report)
    return ok(public(report))


@bp.get("/cost-reports/<report_id>/gme-summary")
@endpoint(roles=list(READ_ROLES))
def gme_summary(report_id):
    report = find("CostReport", report_id)
    period_days, prior_count = gme_refresh(report)
    return ok({
        "cost_report_id": report["id"],
        "period_days": period_days,
        "unweighted_fte_days_total": report["unweighted_fte_days_total"],
        "unweighted_fte_total": report["unweighted_fte_total"],
        "capped_unweighted_fte": report["capped_unweighted_fte"],
        "weighted_fte_total": report["weighted_fte_total"],
        "rolling_average_fte": report["rolling_average_fte"],
        "prior_period_count": prior_count,
    })
