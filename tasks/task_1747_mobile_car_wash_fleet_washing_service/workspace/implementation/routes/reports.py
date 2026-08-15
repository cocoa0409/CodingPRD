"""InspectionReport endpoints."""

from flask import Blueprint, request

from db import store
from serialize import ser_report, customer_of_report
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    stamp_new, touch, ApiError,
)
from errors import ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE

bp = Blueprint("reports", __name__)

AREAS = {"EXTERIOR_BODY", "GLASS", "WHEELS", "INTERIOR", "TRIM"}
SUBMITTABLE_ORDER_STATES = ("SCHEDULED", "ASSIGNED", "IN_PROGRESS", "COMPLETED",
                            "REWASH_PENDING")


@bp.post("/fleet-wash/inspection-reports")
def create_report():
    uid, role = caller()
    require_role(role, {"Technician"})
    body = get_body()
    wash_order_id = req_str(body, "wash_order_id")
    if wash_order_id not in store.orders:
        raise ApiError(ERR_NOT_FOUND, "WashOrder %s not found" % wash_order_id)
    areas = body.get("areas")
    if not isinstance(areas, list) or len(areas) == 0:
        raise ApiError(ERR_VALIDATION, "areas must be a non-empty list")
    seen = set()
    normalized = []
    for entry in areas:
        if not isinstance(entry, dict):
            raise ApiError(ERR_VALIDATION, "each area entry must be an object")
        area = entry.get("area")
        if not isinstance(area, str) or area not in AREAS:
            raise ApiError(ERR_VALIDATION, "area must be one of %s" % sorted(AREAS))
        if area in seen:
            raise ApiError(ERR_VALIDATION, "each area may appear at most once")
        seen.add(area)
        flag = entry.get("pre_existing_damage")
        if not isinstance(flag, bool):
            raise ApiError(ERR_VALIDATION, "pre_existing_damage must be a boolean")
        notes = entry.get("notes", "")
        if not isinstance(notes, str):
            raise ApiError(ERR_VALIDATION, "notes must be a string")
        normalized.append({"area": area, "pre_existing_damage": flag, "notes": notes})
    rec = {
        "wash_order_id": wash_order_id,
        "technician_id": uid,
        "areas": normalized,
        "status": "DRAFT",
    }
    stamp_new(rec)
    store.reports[rec["id"]] = rec
    return respond(ser_report(rec), 201)


@bp.get("/fleet-wash/inspection-reports/<rid>")
def get_report(rid):
    uid, role = caller()
    rec = store.reports.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "InspectionReport %s not found" % rid)
    if role == "Customer" and customer_of_report(rec) != uid:
        forbid("Customers may only access reports for their own orders")
    return respond(ser_report(rec), 200)


@bp.get("/fleet-wash/inspection-reports")
def list_reports():
    uid, role = caller()
    wash_order_id = request.args.get("wash_order_id")
    technician_id = request.args.get("technician_id")
    status = request.args.get("status")
    recs = list(store.reports.values())
    if role == "Customer":
        recs = [r for r in recs if customer_of_report(r) == uid]
    if wash_order_id is not None:
        recs = [r for r in recs if r["wash_order_id"] == wash_order_id]
    if technician_id is not None:
        recs = [r for r in recs if r["technician_id"] == technician_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_report)


@bp.post("/fleet-wash/inspection-reports/<rid>/events")
def report_event(rid):
    uid, role = caller()
    require_role(role, {"Technician"})
    rec = store.reports.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "InspectionReport %s not found" % rid)
    body = get_body()
    event = req_str(body, "event_type")
    if event != "SUBMIT":
        raise ApiError(ERR_VALIDATION, "event_type must be SUBMIT")
    if rec["technician_id"] != uid:
        forbid("Only the filing technician may submit this report")
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "InspectionReport is not DRAFT")
    order = store.orders.get(rec["wash_order_id"])
    if order is None or order["status"] not in SUBMITTABLE_ORDER_STATES:
        raise ApiError(ERR_INVALID_STATE,
                       "WashOrder state does not allow report submission")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return respond(ser_report(rec), 200)
