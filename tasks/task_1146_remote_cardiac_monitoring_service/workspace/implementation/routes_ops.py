"""Return shipments, compliance events, logical clock, daily sweep."""
from datetime import datetime, timedelta, timezone

import db
from bp import bp
from clock import now, set_current
from db import base_record, touch
from domain import run_sweep
from errors import ApiError
from helpers import (READ_ROLES, auth, body, pagination, req_enum, req_str,
                     require, sorted_by_creation)
from response import serialize, success, success_list

RESOLUTION_ACTIONS = {"CONTACTED_PATIENT", "DEVICE_REPLACED", "PHYSICIAN_NOTIFIED"}


# ------------------------------------------------------------- return shipments
@bp.post("/v1/episodes/<episode_id>/return-shipments")
def create_return_shipment(episode_id):
    uid, role = auth()
    require(role, {"InventoryManager"})
    ep = db.episodes.get(episode_id)
    if ep is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND", 404, "Episode not found")
    if ep["clinical_status"] not in ("COMPLETED", "TERMINATED_EARLY"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Episode must be clinically terminal to open a return shipment")
    enr = db.enrollments.get(ep["enrollment_id"])
    device = db.devices.get(enr["device_id"]) if enr else None
    if device is None or device["status"] != "DEPLOYED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Episode device is not DEPLOYED; an open shipment may already exist")
    t = now()
    rec = base_record()
    rec.update({
        "episode_id": ep["id"],
        "device_id": device["id"],
        "label_created_at": t,
        "due_at": t + timedelta(days=10),
        "received_at": None,
        "status": "LABEL_CREATED",
    })
    db.shipments[rec["id"]] = rec
    device["status"] = "RETURN_IN_TRANSIT"
    touch(device)
    return success(serialize(rec), 201)


@bp.get("/v1/return-shipments")
def list_shipments():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    ep_f = request.args.get("episode_id")
    dev_f = request.args.get("device_id")
    status_f = request.args.get("status")
    items = list(db.shipments.values())
    if ep_f is not None:
        items = [x for x in items if x["episode_id"] == ep_f]
    if dev_f is not None:
        items = [x for x in items if x["device_id"] == dev_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    return success_list(sorted_by_creation(items), limit, offset)


def _get_shipment_or_404(shipment_id):
    rec = db.shipments.get(shipment_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Return shipment not found")
    return rec


@bp.get("/v1/return-shipments/<shipment_id>")
def get_shipment(shipment_id):
    uid, role = auth()
    require(role, READ_ROLES)
    return success(serialize(_get_shipment_or_404(shipment_id)))


@bp.post("/v1/return-shipments/<shipment_id>/mark-received")
def mark_received(shipment_id):
    uid, role = auth()
    require(role, {"InventoryManager"})
    rec = _get_shipment_or_404(shipment_id)
    if rec["status"] not in ("LABEL_CREATED", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only LABEL_CREATED or OVERDUE shipments can be received")
    t = now()
    rec["status"] = "RECEIVED"
    rec["received_at"] = t
    touch(rec)
    device = db.devices.get(rec["device_id"])
    if device is not None:
        device["status"] = "REFURBISHING"
        device["refurbishment_due_at"] = t + timedelta(hours=48)
        touch(device)
    return success(serialize(rec))


# ------------------------------------------------------------ compliance events
@bp.get("/v1/compliance-events")
def list_compliance_events():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    ep_f = request.args.get("episode_id")
    status_f = request.args.get("status")
    type_f = request.args.get("event_type")
    items = list(db.compliance_events.values())
    if ep_f is not None:
        items = [x for x in items if x["episode_id"] == ep_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    if type_f is not None:
        items = [x for x in items if x["event_type"] == type_f]
    return success_list(sorted_by_creation(items), limit, offset)


def _get_event_or_404(event_id):
    rec = db.compliance_events.get(event_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Compliance event not found")
    return rec


@bp.get("/v1/compliance-events/<event_id>")
def get_compliance_event(event_id):
    uid, role = auth()
    require(role, READ_ROLES)
    return success(serialize(_get_event_or_404(event_id)))


@bp.post("/v1/compliance-events/<event_id>/resolve")
def resolve_compliance_event(event_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    rec = _get_event_or_404(event_id)
    d = body()
    action = req_enum(d, "resolution_action", RESOLUTION_ACTIONS)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Only OPEN events can be resolved")
    rec["status"] = "RESOLVED"
    rec["resolution_action"] = action
    touch(rec)
    ep = db.episodes.get(rec["episode_id"])
    if ep is not None:
        patient = db.patients.get(ep["patient_id"])
        if patient is not None:
            patient["open_compliance_events"] = max(
                0, patient["open_compliance_events"] - 1)
            touch(patient)
    return success(serialize(rec))


# ------------------------------------------------------------------ clock/sweep
@bp.post("/v1/_clock/set_current_utc")
def set_clock_endpoint():
    uid, role = auth()
    require(role, {"PlatformAdmin"})
    d = body()
    raw = req_str(d, "to_iso8601")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    set_current(dt)
    return success({}, 200)


@bp.post("/v1/_ops/run-daily-sweep")
def run_daily_sweep():
    uid, role = auth()
    require(role, {"PlatformAdmin"})
    run_sweep()
    return success({}, 200)
