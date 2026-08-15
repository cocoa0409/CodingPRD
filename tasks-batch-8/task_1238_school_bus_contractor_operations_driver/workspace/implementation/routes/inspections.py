"""Inspection endpoints."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INSPECTION_DAY_CONFLICT,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_RANGE,
    raise_err,
)
from middleware import authenticate, get_or_404, require_roles
from services.coverage import ground_bus, return_bus_after_inspection_pass
from validation import (
    get_body,
    paginate,
    pagination_params,
    req_date,
    req_enum,
    req_str,
)

bp = Blueprint("inspections", __name__)

ROLES = {"SystemAdmin", "ContractorOps", "FleetManager"}


@bp.route("/busops/inspections", methods=["POST"])
def create_inspection():
    body = get_body()
    bus_id = req_str(body, "bus_id")
    scheduled_date = req_date(body, "scheduled_date")
    inspector_ref = req_str(body, "inspector_ref")
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    bus = get_or_404("buses", bus_id, "Bus")
    if bus["status"] == "DECOMMISSIONED":
        raise_err(ERR_ALREADY_TERMINAL, "Bus is DECOMMISSIONED (terminal)")
    # Whole-day occupation: a CONFIRMED assignment on the proposed date blocks.
    for a in db.all_of("assignments"):
        if a.get("bus_id") != bus_id or a["status"] != "CONFIRMED":
            continue
        day = db.day_of_assignment(a)
        if day is not None and day["service_date"] == scheduled_date:
            raise_err(
                ERR_INSPECTION_DAY_CONFLICT,
                "Bus has a CONFIRMED assignment on the proposed inspection date",
            )

    rec = {
        "id": db.new_id(),
        "bus_id": bus_id,
        "scheduled_date": scheduled_date,
        "inspector_ref": inspector_ref,
        "status": "SCHEDULED",
        "result": None,
        "completed_on": None,
    }
    db.stamp_new(rec)
    db.STORES["inspections"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/inspections", methods=["GET"])
def list_inspections():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, ROLES)
    items = list(db.all_of("inspections"))
    bus_id = request.args.get("bus_id")
    status = request.args.get("status")
    if bus_id is not None:
        items = [i for i in items if i["bus_id"] == bus_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/inspections/<rid>", methods=["GET"])
def get_inspection(rid):
    actor = authenticate()
    require_roles(actor, ROLES)
    rec = get_or_404("inspections", rid, "Inspection")
    return success_object(db.public(rec))


@bp.route("/busops/inspections/<rid>/record-result", methods=["POST"])
def record_result(rid):
    body = get_body()
    result = req_enum(body, "result", ("PASS", "FAIL"))
    next_due = body.get("next_inspection_due")
    if next_due is not None:
        req_date(body, "next_inspection_due")
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    rec = get_or_404("inspections", rid, "Inspection")
    if rec["status"] == "CANCELLED":
        raise_err(ERR_ALREADY_TERMINAL, "Inspection is CANCELLED (terminal)")
    if rec["status"] not in ("SCHEDULED", "OVERDUE"):
        raise_err(
            ERR_INVALID_STATE,
            "Result can be recorded only for SCHEDULED or OVERDUE inspections",
        )
    bus = get_or_404("buses", rec["bus_id"], "Bus")
    rec["result"] = result
    rec["completed_on"] = db.clock_date().isoformat()
    if result == "PASS":
        rec["status"] = "PASSED"
        db.touch(rec)
        if next_due is not None:
            bus["next_inspection_due"] = next_due
            db.touch(bus)
        return_bus_after_inspection_pass(bus)
    else:
        rec["status"] = "FAILED"
        db.touch(rec)
        ground_bus(bus)
    return success_object(db.public(rec))


@bp.route("/busops/inspections/<rid>/reschedule", methods=["POST"])
def reschedule_inspection(rid):
    body = get_body()
    scheduled_date = req_date(body, "scheduled_date")
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    rec = get_or_404("inspections", rid, "Inspection")
    if rec["status"] == "CANCELLED":
        raise_err(ERR_ALREADY_TERMINAL, "Inspection is CANCELLED (terminal)")
    if rec["status"] != "FAILED":
        raise_err(
            ERR_INVALID_STATE,
            "Only FAILED inspections can be rescheduled",
        )
    if scheduled_date < db.clock_date().isoformat():
        raise_err(
            ERR_INVALID_TIME_RANGE,
            "Rescheduled inspection date must be on or after the clock date",
        )
    rec["status"] = "SCHEDULED"
    rec["scheduled_date"] = scheduled_date
    rec["result"] = None
    rec["completed_on"] = None
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/inspections/<rid>/cancel", methods=["POST"])
def cancel_inspection(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    rec = get_or_404("inspections", rid, "Inspection")
    if rec["status"] == "CANCELLED":
        raise_err(ERR_ALREADY_TERMINAL, "Inspection is CANCELLED (terminal)")
    if rec["status"] != "SCHEDULED":
        raise_err(
            ERR_INVALID_STATE,
            "Only SCHEDULED inspections can be cancelled",
        )
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success_object(db.public(rec))
