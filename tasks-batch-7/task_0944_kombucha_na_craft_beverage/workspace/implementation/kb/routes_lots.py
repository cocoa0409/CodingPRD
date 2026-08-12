"""Custody of finished goods: hold, release, quarantine, clearance, recall."""

from flask import Blueprint, g

from . import constants as C
from . import lookup
from .auth import authorize
from .cascades import (
    lot_reallocation_cascade,
    quarantine_finished_lot,
    recall_finished_lot,
)
from .envelope import list_response, object_response
from .errors import ApiError
from .store import collection_sorted, db, touch
from .util import add_hours
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
    query_string,
)

bp = Blueprint("lots", __name__)

READ_ROLES = (
    "ProductionOperator",
    "QaManager",
    "ComplianceOfficer",
    "SalesRep",
    "TaproomStaff",
    "PlatformAdmin",
)
TRACE_ROLES = ("SalesRep", "ComplianceOfficer", "QaManager", "PlatformAdmin")
LOT_STATUSES = ("HELD", "RELEASED", "QUARANTINED", "RECALLED", "DEPLETED")
LINE_STATUSES = ("ACTIVE", "RECALLED", "CANCELLED")
ALLOCATION_STATUSES = ("ALLOCATED", "SHIPPED", "REVERSED")
NOTICE_STATUSES = ("PENDING", "ACKNOWLEDGED", "OVERDUE")


@bp.post("/finished-lots/<id>/release")
def release_lot(id):
    authorize("QaManager", "PlatformAdmin")
    lot = lookup.finished_lot(id)
    body_dict()
    if lot["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", "Only a HELD lot may be released.")
    if db.clock < add_hours(lot["packaged_at"], C.LOT_RELEASE_MIN_HOLD_HOURS):
        raise ApiError(
            "ERR_LOT_HOLD_PERIOD",
            "The %d-hour minimum hold has not elapsed." % C.LOT_RELEASE_MIN_HOLD_HOURS,
        )
    run = db.packaging_runs.get(lot["packaging_run_id"])
    if run is not None and g.user_id == run["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The releaser may not be the operator who opened the packaging run.",
        )

    lot["status"] = "RELEASED"
    lot["released_by_user_id"] = g.user_id
    lot["released_at"] = db.clock
    touch(lot)
    return object_response(lot)


@bp.post("/finished-lots/<id>/quarantine")
def quarantine_lot(id):
    authorize("ComplianceOfficer", "QaManager", "PlatformAdmin")
    lot = lookup.finished_lot(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if lot["status"] not in ("HELD", "RELEASED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a HELD or RELEASED lot may be quarantined."
        )
    quarantine_finished_lot(lot, "LOT_QUARANTINE")
    return object_response(lot)


@bp.post("/finished-lots/<id>/clear-quarantine")
def clear_lot_quarantine(id):
    authorize("ComplianceOfficer", "PlatformAdmin")
    lot = lookup.finished_lot(id)
    body_dict()
    if lot["status"] != "QUARANTINED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a QUARANTINED lot may be cleared."
        )
    if int(lot["quarantine_clearance_count"]) >= C.LOT_QUARANTINE_CLEARANCE_CAP:
        raise ApiError(
            "ERR_QUARANTINE_CLEARANCE_CAP",
            "This lot has already used its single clearance.",
        )

    lot["status"] = lot["pre_quarantine_status"] or "HELD"
    lot["quarantine_clearance_count"] = int(lot["quarantine_clearance_count"]) + 1
    lot_reallocation_cascade(lot)
    touch(lot)
    return object_response(lot)


@bp.post("/finished-lots/<id>/recall")
def recall_lot(id):
    authorize("ComplianceOfficer", "PlatformAdmin")
    lot = lookup.finished_lot(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUARANTINED lot may be recalled.")
    recall_finished_lot(lot)
    return object_response(lot)


@bp.get("/finished-lots/<id>")
def read_lot(id):
    authorize(*READ_ROLES)
    return object_response(lookup.finished_lot(id))


@bp.get("/finished-lots")
def list_lots():
    authorize(*READ_ROLES)
    packaging_run_id = query_string("packaging_run_id")
    recipe_id = query_string("recipe_id")
    status = query_enum("status", LOT_STATUSES)
    limit, offset = pagination()

    def keep(lot):
        if packaging_run_id is not None and lot["packaging_run_id"] != packaging_run_id:
            return False
        if recipe_id is not None and lot["recipe_id"] != recipe_id:
            return False
        if status is not None and lot["status"] != status:
            return False
        return True

    rows = collection_sorted(db.finished_lots, keep)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/finished-lots/<id>/shipment-lines")
def list_lot_shipment_lines(id):
    authorize(*TRACE_ROLES)
    lot = lookup.finished_lot(id)
    line_status = query_enum("line_status", LINE_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.shipment_lines,
        lambda l: l["finished_lot_id"] == lot["id"]
        and (line_status is None or l["line_status"] == line_status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/finished-lots/<id>/allocations")
def list_lot_allocations(id):
    authorize(*TRACE_ROLES)
    lot = lookup.finished_lot(id)
    status = query_enum("status", ALLOCATION_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.subscription_allocations,
        lambda a: a["finished_lot_id"] == lot["id"]
        and (status is None or a["status"] == status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/finished-lots/<id>/recall-notices")
def list_lot_recall_notices(id):
    authorize(*TRACE_ROLES)
    lot = lookup.finished_lot(id)
    status = query_enum("status", NOTICE_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.recall_notices,
        lambda n: n["finished_lot_id"] == lot["id"]
        and (status is None or n["status"] == status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
