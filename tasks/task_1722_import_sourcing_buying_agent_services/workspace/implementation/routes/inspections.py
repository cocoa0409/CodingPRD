"""Inspections: book (AQL sample size), list, get, record-result, cancel."""

from datetime import timedelta

from flask import Blueprint, request

from db import new_id, parse_date, public, stamp_new, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    paginate,
    req_enum,
    req_int,
    require_roles,
    sorted_created,
)
from response import success_list, success_object
from services.domain import aql_result, aql_sample_size

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("DUPRO", "PSI")


def _get_inspection(inspectionId):
    return get_or_404(
        store.inspections, inspectionId, "ERR_INSPECTION_NOT_FOUND", "Inspection"
    )


def _window_overlaps(inspector_id, start_date, duration_days, exclude_id=None):
    new_start = start_date
    new_end = start_date + timedelta(days=duration_days)
    for existing in store.inspections.values():
        if existing["inspector_id"] != inspector_id:
            continue
        if existing["id"] == exclude_id:
            continue
        if existing["status"] != "BOOKED":
            continue
        ex_start = existing["_scheduled_date"]
        ex_end = ex_start + timedelta(days=existing["duration_days"])
        if new_start < ex_end and ex_start < new_end:
            return True
    return False


@bp.route("/sourcing/purchase-orders/<poId>/inspections", methods=["POST"])
def book_inspection(poId):
    uid, _ = require_roles("SourcingAgent")
    po = get_or_404(
        store.purchase_orders, poId, "ERR_PURCHASE_ORDER_NOT_FOUND", "PurchaseOrder"
    )
    data = body_json()
    inspector_id = data.get("inspector_id")
    if not isinstance(inspector_id, str) or not inspector_id:
        raise ApiError(
            "ERR_VALIDATION", "Missing or invalid required field: inspector_id", 400
        )
    inspection_type = req_enum(data, "inspection_type", INSPECTION_TYPES)
    scheduled_date_raw = data.get("scheduled_date")
    scheduled_date = parse_date(scheduled_date_raw)
    if scheduled_date is None:
        raise ApiError(
            "ERR_VALIDATION", "scheduled_date must be an ISO 8601 date", 400
        )
    duration_days = req_int(data, "duration_days", lo=1, hi=5)
    lot_size = req_int(data, "lot_size", lo=1)
    if po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if po["status"] != "ACTIVE":
        raise ApiError("ERR_PO_NOT_ACTIVE", "PurchaseOrder is not ACTIVE", 409)
    factory = store.factories.get(po["factory_id"])
    if factory is not None and factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_SUSPENDED", "Factory is SUSPENDED", 409)
    if po["ship_blocked"]:
        raise ApiError(
            "ERR_FACTORY_NOT_COMPLIANT",
            "Factory compliance posture blocks this purchase order",
            409,
        )
    # PRD §2.12: inspection-type readiness (priority 8) precedes the structural
    # inspector-window overlap check (priority 9).
    if inspection_type == "DUPRO" and po["production_status"] != "IN_PRODUCTION":
        raise ApiError(
            "ERR_PO_NOT_READY_FOR_DUPRO",
            "DUPRO booking requires production_status IN_PRODUCTION",
            409,
        )
    if inspection_type == "PSI" and po["production_status"] != "PRODUCTION_COMPLETE":
        raise ApiError(
            "ERR_PO_NOT_READY_FOR_PSI",
            "PSI booking requires production_status PRODUCTION_COMPLETE",
            409,
        )
    if _window_overlaps(inspector_id, scheduled_date, duration_days):
        raise ApiError(
            "ERR_INSPECTION_WINDOW_CONFLICT",
            "Inspector already has a live inspection overlapping the window",
            409,
        )
    inspection = stamp_new(
        {
            "id": new_id(),
            "po_id": po["id"],
            "inspector_id": inspector_id,
            "inspection_type": inspection_type,
            "scheduled_date": scheduled_date_raw,
            "duration_days": duration_days,
            "lot_size": lot_size,
            "sample_size": aql_sample_size(lot_size),
            "defects_critical": None,
            "defects_major": None,
            "defects_minor": None,
            "result": "NONE",
            "status": "BOOKED",
            "_scheduled_date": scheduled_date,
        }
    )
    store.inspections[inspection["id"]] = inspection
    return success_object(public(inspection), 201)


@bp.route("/sourcing/inspections", methods=["GET"])
def list_inspections():
    require_roles(*ALL_ROLES)
    items = list(store.inspections.values())
    po_id = request.args.get("po_id")
    inspector_id = request.args.get("inspector_id")
    status = request.args.get("status")
    if po_id is not None:
        items = [i for i in items if i["po_id"] == po_id]
    if inspector_id is not None:
        items = [i for i in items if i["inspector_id"] == inspector_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(i) for i in page], limit, offset, total)


@bp.route("/sourcing/inspections/<inspectionId>", methods=["GET"])
def get_inspection(inspectionId):
    require_roles(*ALL_ROLES)
    return success_object(public(_get_inspection(inspectionId)))


@bp.route("/sourcing/inspections/<inspectionId>/record-result", methods=["POST"])
def record_result(inspectionId):
    uid, _ = require_roles("Inspector")
    inspection = _get_inspection(inspectionId)
    data = body_json()
    defects_critical = req_int(data, "defects_critical", lo=0)
    defects_major = req_int(data, "defects_major", lo=0)
    defects_minor = req_int(data, "defects_minor", lo=0)
    if inspection["inspector_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned inspector for this inspection",
            403,
        )
    if inspection["status"] != "BOOKED":
        raise ApiError(
            "ERR_INSPECTION_NOT_RECORDABLE", "Inspection is not BOOKED", 409
        )
    if (
        defects_critical + defects_major + defects_minor
        > inspection["sample_size"]
    ):
        raise ApiError(
            "ERR_AQL_SAMPLE_MISMATCH",
            "Total defect counts exceed the AQL sample size",
            422,
        )
    inspection["defects_critical"] = defects_critical
    inspection["defects_major"] = defects_major
    inspection["defects_minor"] = defects_minor
    inspection["result"] = aql_result(
        inspection["sample_size"], defects_critical, defects_major, defects_minor
    )
    inspection["status"] = "RESULT_RECORDED"
    touch(inspection)
    if inspection["inspection_type"] == "PSI":
        po = store.purchase_orders.get(inspection["po_id"])
        if po is not None:
            po["latest_psi_result"] = inspection["result"]
            touch(po)
    return success_object(public(inspection))


@bp.route("/sourcing/inspections/<inspectionId>/cancel", methods=["POST"])
def cancel_inspection(inspectionId):
    uid, _ = require_roles("SourcingAgent")
    inspection = _get_inspection(inspectionId)
    po = store.purchase_orders.get(inspection["po_id"])
    if po is None or po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if inspection["status"] != "BOOKED":
        raise ApiError(
            "ERR_INSPECTION_NOT_CANCELLABLE", "Inspection is not BOOKED", 409
        )
    inspection["status"] = "CANCELLED"
    touch(inspection)
    return success_object(public(inspection))
