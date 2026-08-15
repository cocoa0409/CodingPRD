"""Outcome report retrieval and finalization."""
from flask import Blueprint

from auth import endpoint
from db import store, now, touch
from envelope import ok
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_REPORT_PERIOD_OPEN
import calc
import serialize
import timeutil

bp = Blueprint("reports", __name__)

PC_QR = ["ProgramCoordinator", "QualityReviewer"]


def get_report_or_404(rid):
    r = store.reports.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, "Outcome report not found")
    return r


@bp.route("/api/outcome-reports/<rid>", methods=["GET"])
@endpoint(PC_QR)
def get_report(rid, uid, role):
    return ok(serialize.outcome_report(get_report_or_404(rid)))


@bp.route("/api/outcome-reports/<rid>/finalize", methods=["POST"])
@endpoint(["QualityReviewer"])
def finalize_report(rid, uid, role):
    r = get_report_or_404(rid)
    if r["status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE, "Outcome report is not PROVISIONAL")
    y, m = timeutil.parse_month(r["period_month"])
    _, _, _, end = timeutil.month_bounds(y, m)
    if not (now() >= end):
        raise_err(ERR_REPORT_PERIOD_OPEN, "The report period is still open")
    g = store.programs.get(r["program_id"])
    r.update(calc.compute_report_metrics(g, r["period_month"], "final"))
    r["status"] = "FINALIZED"
    touch(r)
    return ok(serialize.outcome_report(r))
