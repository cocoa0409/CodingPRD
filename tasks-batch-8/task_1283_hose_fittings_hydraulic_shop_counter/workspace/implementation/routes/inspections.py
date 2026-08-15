"""Inspection lifecycle: start and complete (PRD §3.7)."""

from flask import Blueprint

from db import store, now, touch, pub
from errors import ApiError, ERR_INVALID_STATE, ERR_ASSET_NOT_ACTIVE
from middleware import require_roles, body, get_or_404, get_enum
from response import success
from services import next_due_date, touch_customer

bp = Blueprint("inspections", __name__)


@bp.post("/api/inspections/<iid>/start")
def start_inspection(iid):
    require_roles("FieldTechnician")
    inspection = get_or_404(store.inspections, iid, "inspection")
    if inspection["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Inspection is not SCHEDULED")
    asset = store.assets[inspection["equipment_asset_id"]]
    if asset["status"] != "ACTIVE":
        raise ApiError(ERR_ASSET_NOT_ACTIVE, 422,
                       "Equipment asset is DECOMMISSIONED")
    inspection["status"] = "IN_PROGRESS"
    touch(inspection)
    return success(pub(inspection), status=200)


@bp.post("/api/inspections/<iid>/complete")
def complete_inspection(iid):
    require_roles("FieldTechnician")
    inspection = get_or_404(store.inspections, iid, "inspection")
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Inspection is not IN_PROGRESS")
    data = body()
    result = get_enum(data, "result", ("PASSED", "FAILED"))
    asset = store.assets[inspection["equipment_asset_id"]]
    performed = now()
    # was_overdue: strictly later than the due date; equal is on time; the
    # flag stays at its default of false when no due date exists
    nd = next_due_date(asset)
    inspection["performed_at"] = performed
    inspection["result"] = result
    inspection["was_overdue"] = bool(nd is not None and performed > nd)
    inspection["status"] = result
    touch(inspection)
    if result == "PASSED":
        # the pass becomes the new due-date base
        asset["last_passed_inspection_at"] = performed
    # FAILED leaves last_passed untouched; posture derives NON_COMPLIANT
    # until a later pass
    touch(asset)
    touch_customer(asset["customer_id"])
    return success(pub(inspection), status=200)
