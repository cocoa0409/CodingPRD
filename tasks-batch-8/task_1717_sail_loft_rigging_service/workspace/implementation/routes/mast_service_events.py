"""MastServiceEvent endpoints."""

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles
from response import success_object, success_list
from services import domain

bp = Blueprint("mast_service_events", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
SERVICE_KINDS = ("UNSTEP", "STEP", "TUNE")


@bp.post("/lofts/boats/<boatId>/mast-service-events")
def create_event(boatId):
    require_roles("Rigger")
    boat = domain.get_boat_or_404(boatId)
    body = util.get_body()
    service_kind = util.as_enum(util.require_field(body, "service_kind"), "service_kind", SERVICE_KINDS)
    start_raw = util.as_string(util.require_field(body, "slot_start_utc"), "slot_start_utc")
    end_raw = util.as_string(util.require_field(body, "slot_end_utc"), "slot_end_utc")
    slot_start = util.parse_iso_datetime(start_raw, "slot_start_utc")
    slot_end = util.parse_iso_datetime(end_raw, "slot_end_utc")
    if domain.mast_slot_conflict_exists(boat["id"], slot_start, slot_end):
        raise errors.mast_slot_overlap()
    ev = util.stamp_new({
        "boat_id": boat["id"],
        "service_kind": service_kind,
        "slot_start_utc": start_raw,
        "slot_end_utc": end_raw,
        "event_status": "BOOKED",
    })
    db.mast_service_events[ev["id"]] = ev
    if service_kind == "UNSTEP":
        boat["mast_status"] = "UNSTEPPING_SCHEDULED"
        util.touch(boat)
    return success_object(domain.serialize(ev), 201)


@bp.get("/lofts/boats/<boatId>/mast-service-events")
def list_boat_events(boatId):
    require_roles(*READ_ROLES)
    domain.get_boat_or_404(boatId)
    limit, offset = util.pagination_params()
    items = [e for e in db.mast_service_events.values() if e["boat_id"] == boatId]
    items = util.filter_exact(items, "event_status", request.args.get("event_status"))
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(e) for e in page], limit, offset, total)


@bp.get("/lofts/mast-service-events")
def list_events():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.mast_service_events.values()))
    items = util.filter_exact(items, "boat_id", request.args.get("boat_id"))
    items = util.filter_exact(items, "event_status", request.args.get("event_status"))
    items = util.filter_exact(items, "service_kind", request.args.get("service_kind"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(e) for e in page], limit, offset, total)


@bp.get("/lofts/mast-service-events/<eventId>")
def get_event(eventId):
    require_roles(*READ_ROLES)
    ev = domain.get_mast_event_or_404(eventId)
    return success_object(domain.serialize(ev))


@bp.post("/lofts/boats/<boatId>/mast-service-events/<eventId>/start")
def start_event(boatId, eventId):
    require_roles("Rigger")
    boat = domain.get_boat_or_404(boatId)
    ev = domain.get_mast_event_or_404(eventId)
    domain.check_child_of(ev, "boat_id", boat["id"])
    if ev["event_status"] != "BOOKED":
        raise errors.invalid_state(f"Event must be BOOKED to start (is {ev['event_status']})")
    open_fail = any(
        i for i in db.rigging_inspections.values()
        if i["boat_id"] == boat["id"]
        and i["inspection_status"] == "REPORTED"
        and i["verdict"] == "FAIL"
    )
    if open_fail or boat["status"] == "OUT_OF_SERVICE":
        raise errors.unresolved_rigging_fail()
    ev["event_status"] = "IN_PROGRESS"
    util.touch(ev)
    if ev["service_kind"] == "UNSTEP":
        boat["mast_status"] = "UNSTEPPED"
    elif ev["service_kind"] == "STEP":
        boat["mast_status"] = "STEPPED"
    elif ev["service_kind"] == "TUNE":
        boat["mast_status"] = "TUNING_IN_PROGRESS"
    util.touch(boat)
    return success_object(domain.serialize(ev))


@bp.post("/lofts/boats/<boatId>/mast-service-events/<eventId>/complete")
def complete_event(boatId, eventId):
    require_roles("Rigger")
    boat = domain.get_boat_or_404(boatId)
    ev = domain.get_mast_event_or_404(eventId)
    domain.check_child_of(ev, "boat_id", boat["id"])
    if ev["event_status"] != "IN_PROGRESS":
        raise errors.invalid_state(f"Event must be IN_PROGRESS to complete (is {ev['event_status']})")
    ev["event_status"] = "COMPLETED"
    util.touch(ev)
    if ev["service_kind"] == "STEP":
        boat["mast_status"] = "STEPPED"
    elif ev["service_kind"] == "UNSTEP":
        boat["mast_status"] = "UNSTEPPED"
    elif ev["service_kind"] == "TUNE":
        boat["mast_status"] = "STEPPED"
    util.touch(boat)
    return success_object(domain.serialize(ev))


@bp.post("/lofts/boats/<boatId>/mast-service-events/<eventId>/cancel")
def cancel_event(boatId, eventId):
    require_roles("Rigger")
    boat = domain.get_boat_or_404(boatId)
    ev = domain.get_mast_event_or_404(eventId)
    domain.check_child_of(ev, "boat_id", boat["id"])
    if ev["event_status"] != "BOOKED":
        raise errors.invalid_state(f"Event must be BOOKED to cancel (is {ev['event_status']})")
    ev["event_status"] = "CANCELLED"
    util.touch(ev)
    if ev["service_kind"] == "UNSTEP" and boat["mast_status"] == "UNSTEPPING_SCHEDULED":
        boat["mast_status"] = "STEPPED"
        util.touch(boat)
    return success_object(domain.serialize(ev))
