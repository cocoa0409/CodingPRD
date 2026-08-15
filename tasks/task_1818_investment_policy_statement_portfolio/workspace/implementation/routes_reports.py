from flask import Blueprint, request

import store as db
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import new_common, touch, get_or_404, resolve
from logic2 import compute_return_bps
from serialize import report_out
from validate import (body, no_unknown, req_str, req_int, req_enum, req_date,
                      pagination)

bp = Blueprint("reports", __name__)

METHODS = {"TIME_WEIGHTED", "MONEY_WEIGHTED"}


def _owns(uid, r):
    return db.portfolios[r["portfolio_id"]]["client_id"] == uid


@bp.post("/advisory/performance-reports")
def create_report():
    authorize("Advisor")
    b = body()
    no_unknown(b, {"portfolio_id", "benchmark_id", "period_start", "period_end",
                   "calculation_method", "beginning_value_cents",
                   "ending_value_cents", "benchmark_return_bps"})
    portfolio_id = req_str(b, "portfolio_id")
    benchmark_id = req_str(b, "benchmark_id")
    pstart = req_date(b, "period_start")
    pend = req_date(b, "period_end")
    method = req_enum(b, "calculation_method", METHODS)
    beginning = req_int(b, "beginning_value_cents", lo=0)
    ending = req_int(b, "ending_value_cents", lo=0)
    bench_bps = req_int(b, "benchmark_return_bps")
    resolve(db.portfolios, portfolio_id, "portfolio_id")
    resolve(db.benchmarks, benchmark_id, "benchmark_id")
    if pstart > pend:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "period_start must be on or before period_end")
    r = new_common()
    r.update({
        "portfolio_id": portfolio_id, "benchmark_id": benchmark_id,
        "period_start_d": pstart, "period_end_d": pend,
        "calculation_method": method,
        "beginning_value_cents": beginning, "ending_value_cents": ending,
        "benchmark_return_bps": bench_bps,
        "portfolio_return_bps": None, "excess_return_bps": None,
        "status": "DRAFT",
    })
    db.reports[r["id"]] = r
    return obj(report_out(r), 201)


@bp.get("/advisory/performance-reports")
def list_reports():
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    limit, offset = pagination()
    rows = sorted(db.reports.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    if role == "Client":
        rows = [r for r in rows if _owns(uid, r)]
    pf_id = request.args.get("portfolio_id")
    if pf_id is not None:
        rows = [r for r in rows if r["portfolio_id"] == pf_id]
    bm_id = request.args.get("benchmark_id")
    if bm_id is not None:
        rows = [r for r in rows if r["benchmark_id"] == bm_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return page([report_out(r) for r in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/performance-reports/<rid>")
def get_report(rid):
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    r = get_or_404(db.reports, rid)
    if role == "Client" and not _owns(uid, r):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Clients may read only their own reports")
    return obj(report_out(r))


@bp.post("/advisory/performance-reports/<rid>/finalize")
def finalize_report(rid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    r = get_or_404(db.reports, rid)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_INVALID_STATE", 409,
                       "Finalize requires DRAFT")
    if db.benchmarks[r["benchmark_id"]]["status"] != "ACTIVE":
        raise ApiError("ERR_BENCHMARK_NOT_ACTIVE", 422,
                       "Referenced benchmark is not ACTIVE")
    for other in db.reports.values():
        if (other["id"] != rid and other["portfolio_id"] == r["portfolio_id"]
                and other["status"] == "FINALIZED"
                and not (r["period_end_d"] < other["period_start_d"]
                         or r["period_start_d"] > other["period_end_d"])):
            # Closed-interval semantics: a shared boundary date counts as overlap.
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 422,
                           "Period overlaps an existing FINALIZED report")
    r["portfolio_return_bps"] = compute_return_bps(r)
    r["excess_return_bps"] = r["portfolio_return_bps"] - r["benchmark_return_bps"]
    r["status"] = "FINALIZED"
    touch(r)
    return obj(report_out(r))
