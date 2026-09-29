"""CounterfeitReport endpoints and the brand-protection cascade (PRD §3.9)."""

from flask import Blueprint

import calculations as calc
import services as svc
from errors import ApiError
from envelope import ok, ok_list
from routes.helpers import listing
from serialize import report_out
from store import base_row, store, touch, with_common
from validate import (auth, filter_arg, get_body, lookup, req_enum, req_int, req_str,
                     require_present, resolve_ref)

brand_bp = Blueprint("brand", __name__)

FILERS = ["BrandProtectionAnalyst", "ChannelManager", "PlatformAdmin"]
ANALYST = ["BrandProtectionAnalyst", "PlatformAdmin"]


@brand_bp.post("/toolworks/counterfeit-reports")
def create_report():
    auth(*FILERS)
    body = get_body()

    sku = resolve_ref(body, "sku_id", store.skus, "ERR_TOOL_SKU_NOT_FOUND")
    require_present(sku, "sku_id")
    channel_name = req_str(body, "channel_name")
    seller_handle = req_str(body, "seller_handle")
    evidence_grade = req_enum(body, "evidence_grade", calc.EVIDENCE_GRADES)
    unit_estimate = req_int(body, "unit_estimate", 0)

    row = with_common(base_row(
        sku_id=sku["id"],
        channel_name=channel_name,
        seller_handle=seller_handle,
        evidence_grade=evidence_grade,
        unit_estimate=unit_estimate,
        risk_points=calc.report_risk_points(evidence_grade, unit_estimate, sku["channel"]),
        status="OPEN",
        confirmation_note=None,
        dismissal_note=None,
    ))
    store.reports[row["id"]] = row
    return ok(report_out(row), 201)


@brand_bp.get("/toolworks/counterfeit-reports")
def list_reports():
    auth(*FILERS)
    filters = {"status": filter_arg("status"), "evidence_grade": filter_arg("evidence_grade")}
    items, limit, offset, total = listing(list(store.reports.values()), report_out, filters)
    return ok_list(items, limit, offset, total)


@brand_bp.get("/toolworks/counterfeit-reports/<id>")
def get_report(id):
    auth(*FILERS)
    row = lookup(store.reports, id, "ERR_REPORT_NOT_FOUND")
    return ok(report_out(row))


@brand_bp.post("/toolworks/counterfeit-reports/<id>/confirm")
def confirm_report(id):
    auth(*ANALYST)
    row = lookup(store.reports, id, "ERR_REPORT_NOT_FOUND")
    body = get_body()
    confirmation_note = req_str(body, "confirmation_note")

    if row["status"] != "OPEN":
        raise ApiError("ERR_REPORT_STATE_INVALID")

    row["status"] = "CONFIRMED"
    row["confirmation_note"] = confirmation_note
    touch(row)

    svc.cascade_counterfeit_confirmed(row)
    return ok(report_out(row))


@brand_bp.post("/toolworks/counterfeit-reports/<id>/dismiss")
def dismiss_report(id):
    auth(*ANALYST)
    row = lookup(store.reports, id, "ERR_REPORT_NOT_FOUND")
    body = get_body()
    dismissal_note = req_str(body, "dismissal_note")

    if row["status"] != "OPEN":
        raise ApiError("ERR_REPORT_STATE_INVALID")

    row["status"] = "DISMISSED"
    row["dismissal_note"] = dismissal_note
    touch(row)
    return ok(report_out(row))
