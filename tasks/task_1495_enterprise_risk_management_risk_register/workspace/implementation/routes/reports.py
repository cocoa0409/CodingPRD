"""Board reports (PRD 3.8): provisional/final variants, draft supersede,
finalization overlap guard, frozen snapshots."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object
from services import new_entity, touch, serialize_report, aggregate_report
from util import json_body, req_dt, req_enum

bp = Blueprint("reports", __name__)


def get_report_or_404(rid):
    r = store["reports"].get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Report not found")
    return r


def _periods_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap; a shared boundary date counts as overlap."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/reports")
def create_report():
    authenticate(("BoardReporter",))
    data = json_body()
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    variant = req_enum(data, "variant", ("PROVISIONAL", "FINAL"))
    if period_end < period_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "period_end must not be earlier than period_start")
    rep = new_entity()
    rep.update({"period_start": period_start, "period_end": period_end,
                "variant": variant, "status": "DRAFT"})
    heat, breakdown, band_counts = aggregate_report(variant)
    rep["heat_score_total"] = heat
    rep["category_breakdown"] = breakdown
    rep["band_counts"] = band_counts
    store["reports"][rep["id"]] = rep
    # auto-supersede: any older DRAFT whose closed period overlaps is CANCELLED
    for other in store["reports"].values():
        if other["id"] == rep["id"] or other["status"] != "DRAFT":
            continue
        if _periods_overlap(period_start, period_end,
                            other["period_start"], other["period_end"]):
            other["status"] = "CANCELLED"
            touch(other)
    return ok_object(serialize_report(rep), 201)


@bp.get("/reports/<rid>")
def get_report(rid):
    authenticate(ALL_ROLES)
    return ok_object(serialize_report(get_report_or_404(rid)))


@bp.post("/reports/<rid>/finalize")
def finalize_report(rid):
    authenticate(("BoardReporter",))
    rep = get_report_or_404(rid)
    if rep["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT report can be finalized")
    for other in store["reports"].values():
        if other["id"] == rep["id"] or other["status"] != "FINALIZED":
            continue
        if _periods_overlap(rep["period_start"], rep["period_end"],
                            other["period_start"], other["period_end"]):
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 409,
                           "A FINALIZED report with an overlapping period exists")
    # authoritative recompute, then frozen
    heat, breakdown, band_counts = aggregate_report(rep["variant"])
    rep["heat_score_total"] = heat
    rep["category_breakdown"] = breakdown
    rep["band_counts"] = band_counts
    rep["status"] = "FINALIZED"
    touch(rep)
    return ok_object(serialize_report(rep))
