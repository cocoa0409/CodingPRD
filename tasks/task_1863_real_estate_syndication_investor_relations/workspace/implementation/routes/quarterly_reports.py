"""Quarterly reports: create, publish (distributable cash), amend (PRD 3.5)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_quarterly_report
from services.calculations import quarterly_distributable_cash_cents
from services.domain import (
    stamp_new, touch, sorted_items, check_not_future_period,
)
from util import CLOCK, fmt_dt
from validate import (
    get_body, req_int, req_number, pagination, apply_filters,
)

bp = Blueprint("quarterly_reports", __name__)
RS = {"strict_slashes": False}

PUBLISHABLE_OFFERING_STATES = ("OPEN", "CLOSED_TO_NEW_SUBSCRIPTIONS", "FINAL_CLOSE")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/quarterly-reports",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_report(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    body = get_body()
    year = req_int(body, "report_year")
    quarter = req_int(body, "report_quarter", minimum=1, maximum=4)
    noi = req_int(body, "noi_cents")
    occupancy = req_number(body, "occupancy_pct", minimum=0, maximum=1)
    check_not_future_period(year, quarter)
    r = {
        "offering_id": offeringId,
        "report_year": year,
        "report_quarter": quarter,
        "noi_cents": noi,
        "occupancy_pct": occupancy,
        "distributable_cash_cents": None,
        "status": "DRAFT",
        "published_at": None,
    }
    stamp_new(r)
    db["quarterly_reports"][r["id"]] = r
    return success_object(ser_quarterly_report(r), 201)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/quarterly-reports",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_reports(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    limit, offset = pagination()
    items = [r for r in db["quarterly_reports"].values() if r["offering_id"] == offeringId]
    items = apply_filters(sorted_items(items), {
        "status": "status", "report_year": "report_year", "report_quarter": "report_quarter",
    })
    page = items[offset:offset + limit]
    return success_list([ser_quarterly_report(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/quarterly-reports/<quarterlyReportId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_report(caller, syndicationId, offeringId, quarterlyReportId):
    return success_object(ser_quarterly_report(
        resolve.quarterly_report(syndicationId, offeringId, quarterlyReportId)))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/quarterly-reports/<quarterlyReportId>/publish",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def publish_report(caller, syndicationId, offeringId, quarterlyReportId):
    off = resolve.offering(syndicationId, offeringId)
    rep = resolve.quarterly_report(syndicationId, offeringId, quarterlyReportId)
    if rep["status"] not in ("DRAFT", "AMENDED"):
        raise_error("ERR_INVALID_STATE",
                    f"cannot publish a report in status {rep['status']}")
    if off["status"] not in PUBLISHABLE_OFFERING_STATES:
        raise_error("ERR_OFFERING_NOT_PUBLISHABLE",
                    f"offering in status {off['status']} cannot publish reports")
    if any(r["offering_id"] == offeringId and r["id"] != rep["id"]
           and r["report_year"] == rep["report_year"]
           and r["report_quarter"] == rep["report_quarter"]
           and r["status"] == "PUBLISHED"
           for r in db["quarterly_reports"].values()):
        raise_error("ERR_DUPLICATE_QUARTERLY_REPORT",
                    "another PUBLISHED report exists for this year/quarter")
    check_not_future_period(rep["report_year"], rep["report_quarter"])
    rep["distributable_cash_cents"] = quarterly_distributable_cash_cents(rep["noi_cents"])
    rep["published_at"] = fmt_dt(CLOCK.now())
    rep["status"] = "PUBLISHED"
    touch(rep)
    return success_object(ser_quarterly_report(rep))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/quarterly-reports/<quarterlyReportId>/amend",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def amend_report(caller, syndicationId, offeringId, quarterlyReportId):
    rep = resolve.quarterly_report(syndicationId, offeringId, quarterlyReportId)
    if rep["status"] != "PUBLISHED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot amend a report in status {rep['status']}")
    if any(d["offering_id"] == offeringId
           and d.get("quarterly_report_id") == rep["id"]
           and d["status"] in ("APPROVED", "PAID")
           for d in db["distributions"].values()):
        raise_error("ERR_REPORT_LOCKED_BY_DISTRIBUTION",
                    "a distribution referencing this report is APPROVED or PAID")
    rep["status"] = "AMENDED"
    rep["distributable_cash_cents"] = quarterly_distributable_cash_cents(rep["noi_cents"])
    touch(rep)  # published_at deliberately unchanged
    return success_object(ser_quarterly_report(rep))
