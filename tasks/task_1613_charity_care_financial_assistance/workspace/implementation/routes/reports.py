"""Community benefit reports: create, file, reopen, recompute (PRD 3.12)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_REPORT_NOT_FOUND, ERR_REPORT_YEAR_DUPLICATE,
    ERR_REPORT_NOT_FILEABLE, ERR_REPORT_NOT_FILED, ERR_REPORT_TOTALS_STALE,
)
from middleware import authorized
from response import success_object
from routes.helpers import require
from services.core import compute_report_totals, new_record, public, touch
from util import CLOCK
from validate import get_body, req_int

bp = Blueprint("reports", __name__)

REPORT_READ = ["FinancialCounselor", "AssistanceReviewer", "BillingAdministrator",
               "CollectionsAgent", "ComplianceOfficer"]


def _apply_totals(report, totals):
    report["total_write_offs_cents"] = totals["total_write_offs_cents"]
    report["total_standard_write_offs_cents"] = totals["total_standard_write_offs_cents"]
    report["total_presumptive_write_offs_cents"] = totals["total_presumptive_write_offs_cents"]
    report["total_refunds_cents"] = totals["total_refunds_cents"]
    report["accounts_assisted_count"] = totals["accounts_assisted_count"]


@bp.post("/charity-care/community-benefit-reports")
def create_report():
    authorized(["ComplianceOfficer"])
    body = get_body()
    year = req_int(body, "reporting_year")
    if any(r["reporting_year"] == year for r in db["reports"].values()):
        raise_error(ERR_REPORT_YEAR_DUPLICATE,
                    "a report for this reporting_year already exists")
    totals = compute_report_totals(year)
    rec = new_record("reports", {
        "reporting_year": year,
        **totals,
        "totals_stale": False,
        "filed_at": None,
        "status": "OPEN",
    })
    return success_object(public(rec), status=201)


@bp.get("/charity-care/community-benefit-reports/<rid>")
def get_report(rid):
    authorized(REPORT_READ)
    report = require("reports", rid, ERR_REPORT_NOT_FOUND)
    return success_object(public(report))


@bp.post("/charity-care/community-benefit-reports/<rid>/file")
def file_report(rid):
    authorized(["ComplianceOfficer"])
    report = require("reports", rid, ERR_REPORT_NOT_FOUND)
    if report["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_REPORT_NOT_FILEABLE, "file requires an OPEN or REOPENED report")
    if report["totals_stale"]:
        raise_error(ERR_REPORT_TOTALS_STALE,
                    "totals are stale; recompute before filing")
    report["status"] = "FILED"
    report["filed_at"] = CLOCK.now_iso()
    touch(report)
    return success_object(public(report))


@bp.post("/charity-care/community-benefit-reports/<rid>/reopen")
def reopen_report(rid):
    authorized(["ComplianceOfficer"])
    report = require("reports", rid, ERR_REPORT_NOT_FOUND)
    if report["status"] != "FILED":
        raise_error(ERR_REPORT_NOT_FILED, "reopen requires a FILED report")
    report["status"] = "REOPENED"
    report["totals_stale"] = True
    touch(report)
    return success_object(public(report))


@bp.post("/charity-care/community-benefit-reports/<rid>/recompute")
def recompute_report(rid):
    authorized(["ComplianceOfficer"])
    report = require("reports", rid, ERR_REPORT_NOT_FOUND)
    _apply_totals(report, compute_report_totals(report["reporting_year"]))
    report["totals_stale"] = False
    touch(report)
    return success_object(public(report))
