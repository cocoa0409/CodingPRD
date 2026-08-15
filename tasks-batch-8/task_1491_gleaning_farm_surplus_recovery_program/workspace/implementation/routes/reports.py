"""Grant reports and impact metrics snapshot."""
from decimal import Decimal
from flask import request

import errors as E
import services as svc
from db import store, stamp_new, touch
from errors import ApiError
from middleware import require_roles
from response import ok_obj, ok_list
from util import serialize, floor_int

PC = "ProgramCoordinator"
GR = "GrantReviewer"

MEALS_PER_LB = Decimal("1.2")
TERMINAL_REPORT = ("ACCEPTED",)


def compute_metrics(report):
    """calculations.impact_metrics — snapshot at submit time.

    Scope: glean events whose offer's farm county matches, whose offer is
    CLOSED, and whose offer close timestamp (updated_at at the CLOSED
    transition) falls in the half-open period [period_start, period_end).
    """
    county = report["county_code"]
    start = report["period_start"]
    end = report["period_end"]
    in_scope = []
    for ev in store.events.values():
        offer = store.offers.get(ev["surplus_offer_id"])
        if offer is None or offer["status"] != "CLOSED":
            continue
        closed_at = offer.get("_closed_at") or offer["updated_at"]
        if not (start <= closed_at < end):
            continue
        farm = store.farms.get(offer["farm_id"])
        if farm is None or farm["county_code"] != county:
            continue
        in_scope.append(ev)
    total = svc.dsum(ev["total_harvested_lbs"] for ev in in_scope)
    condemned = Decimal("0.0")
    for ev in in_scope:
        for i in svc.incidents_of_event(ev["id"]):
            if i["disposition"].startswith("RESOLVED_"):
                condemned += i["condemned_lbs"]
    total_gleaned = (total - condemned).quantize(Decimal("0.1"))
    meals = floor_int(total_gleaned * MEALS_PER_LB)
    agencies = set()
    for ev in in_scope:
        for d in svc.distributions_of_event(ev["id"]):
            if d["status"] == "DELIVERED":
                agencies.add(d["agency_id"])
    return total_gleaned, meals, len(agencies)


def register(app):

    @app.route("/glean/reports", methods=["POST"])
    def create_report():
        require_roles(PC)
        fs = svc.FieldSet()
        county_code = fs.req_str("county_code")
        period_start = fs.req_dt("period_start")
        period_end = fs.req_dt("period_end")
        if period_start is not None and period_end is not None and period_end <= period_start:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "county_code": county_code,
            "period_start": period_start,
            "period_end": period_end,
            "status": "DRAFT",
            "total_gleaned_lbs": None,
            "meals_equivalent": None,
            "agency_count": None,
        }
        stamp_new(rec)
        store.reports[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/reports", methods=["GET"])
    def list_reports():
        require_roles(PC, GR)
        page, limit, offset, total = svc.paginate(
            store.reports.values(),
            {"county_code": request.args.get("county_code"),
             "status": request.args.get("status")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/reports/<rid>", methods=["GET"])
    def get_report(rid):
        require_roles(PC, GR)
        rep = svc.get_or_404(store.reports, rid, "GrantReport")
        return ok_obj(serialize(rep))

    @app.route("/glean/reports/<rid>/submit", methods=["POST"])
    def submit_report(rid):
        require_roles(PC)
        rep = svc.get_or_404(store.reports, rid, "GrantReport")
        status = rep["status"]
        if status in TERMINAL_REPORT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Report is in terminal state %s" % status)
        if status not in ("DRAFT", "RETURNED"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a DRAFT or RETURNED report can be submitted")
        total_gleaned, meals, agency_count = compute_metrics(rep)
        rep["total_gleaned_lbs"] = total_gleaned
        rep["meals_equivalent"] = meals
        rep["agency_count"] = agency_count
        rep["status"] = "SUBMITTED"
        touch(rep)
        return ok_obj(serialize(rep))

    @app.route("/glean/reports/<rid>/accept", methods=["POST"])
    def accept_report(rid):
        require_roles(GR)
        rep = svc.get_or_404(store.reports, rid, "GrantReport")
        status = rep["status"]
        if status in TERMINAL_REPORT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Report is in terminal state %s" % status)
        if status != "SUBMITTED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a SUBMITTED report can be accepted")
        rep["status"] = "ACCEPTED"
        touch(rep)
        return ok_obj(serialize(rep))

    @app.route("/glean/reports/<rid>/return", methods=["POST"])
    def return_report(rid):
        require_roles(GR)
        rep = svc.get_or_404(store.reports, rid, "GrantReport")
        status = rep["status"]
        if status in TERMINAL_REPORT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Report is in terminal state %s" % status)
        if status != "SUBMITTED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a SUBMITTED report can be returned")
        rep["status"] = "RETURNED"
        touch(rep)
        return ok_obj(serialize(rep))
