"""SalesReport routes."""

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, require_list, paginate,
                     sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list
from services import calc

bp = Blueprint("sales", __name__)


def report_view(r):
    return {k: r[k] for k in (
        "id", "application_id", "exhibitor_id", "lines", "status",
        "tax_settlement_cents", "created_at", "updated_at", "version")}


@bp.route("/sales-reports", methods=["POST"])
def create_sales_report():
    user_id, _ = require_roles("Exhibitor")
    body = get_json_body()
    application_id = require_str(body, "application_id")
    lines = require_list(body, "lines")
    for line in lines:
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "lines entries must be objects")
        if not isinstance(line.get("sale_date"), str):
            fail("ERR_INVALID_REQUEST", "line.sale_date must be a string")
        gross = line.get("gross_cents")
        if not isinstance(gross, int) or isinstance(gross, bool) or gross < 0:
            fail("ERR_INVALID_REQUEST", "line.gross_cents must be a non-negative integer")
    a = db.applications.get(application_id)
    if a is None:
        fail("ERR_NOT_FOUND", "application_id does not exist")
    if a["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own applications only")
    if a["status"] != "PLACED":
        fail("ERR_APPLICATION_NOT_PLACED", "Application must be PLACED")
    if len(lines) == 0:
        fail("ERR_SALES_REPORT_EMPTY", "lines array must be non-empty")
    r = {
        "id": db.new_id(),
        "application_id": application_id,
        "exhibitor_id": a["exhibitor_id"],
        "lines": [{"sale_date": l["sale_date"], "gross_cents": l["gross_cents"]} for l in lines],
        "status": "DRAFT",
        "tax_settlement_cents": None,
    }
    db.stamp_created(r)
    db.sales_reports[r["id"]] = r
    return success_object(report_view(r), 201)


@bp.route("/sales-reports", methods=["GET"])
def list_sales_reports():
    user_id, role = require_roles("ShowDirector", "Exhibitor")
    items = list(db.sales_reports.values())
    if role == "Exhibitor":
        items = [r for r in items if r["exhibitor_id"] == user_id]
    for f in ("application_id", "exhibitor_id", "status"):
        v = request.args.get(f)
        if v is not None:
            if role == "Exhibitor" and f == "exhibitor_id":
                continue
            items = [r for r in items if r[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([report_view(r) for r in page], limit, offset, total)


@bp.route("/sales-reports/<salesReportId>", methods=["GET"])
def get_sales_report(salesReportId):
    user_id, role = require_roles("ShowDirector", "Exhibitor")
    r = get_or_404(db.sales_reports, salesReportId)
    if role == "Exhibitor" and r["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own reports only")
    return success_object(report_view(r), 200)


@bp.route("/sales-reports/<salesReportId>/submit", methods=["POST"])
def submit_sales_report(salesReportId):
    user_id, _ = require_roles("Exhibitor")
    r = get_or_404(db.sales_reports, salesReportId)
    if r["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own reports only")
    if r["status"] != "DRAFT":
        fail("ERR_INVALID_TRANSITION", "submit requires DRAFT")
    a = db.applications[r["application_id"]]
    conv = db.conventions[a["convention_id"]]
    if conv["phase"] not in ("LIVE", "LOAD_OUT", "CLOSED"):
        fail("ERR_PHASE_PRECONDITION",
             "Sales report submission requires phase LIVE, LOAD_OUT, or CLOSED")
    if len(r["lines"]) == 0:
        fail("ERR_SALES_REPORT_EMPTY", "lines array must be non-empty")
    r["tax_settlement_cents"] = calc.sales_tax_settlement(r["lines"], conv)
    r["status"] = "SUBMITTED"
    db.touch(r)
    return success_object(report_view(r), 200)
