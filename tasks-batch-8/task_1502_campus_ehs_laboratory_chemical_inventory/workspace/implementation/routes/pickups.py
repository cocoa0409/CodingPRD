"""Waste pickup request routes (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import get_actor, require_role
from response import success_object, success_list
from services import pickup as pickup_service
from services.common import (get_body, serialize_pickup, parse_pagination, paginate,
                             get_or_404, require_fields, require_string,
                             require_datetime)

bp = Blueprint("pickups", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/waste-pickup-requests")
def create_pickup():
    user_id, role = get_actor()
    body = get_body()
    require_role(role, ("PrincipalInvestigator",))
    require_fields(body, ["lab_id"])
    lab = db.labs.get(body["lab_id"])
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {body['lab_id']}", 404)
    rec = pickup_service.create_request(lab, user_id)
    return success_object(serialize_pickup(rec), 201)


@bp.get("/ehs/waste-pickup-requests")
def list_pickups():
    _, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.waste_pickup_requests.values())
    lab_id = request.args.get("lab_id")
    status = request.args.get("status")
    if lab_id is not None:
        records = [r for r in records if r["lab_id"] == lab_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_pickup(r) for r in page], limit, offset, total)


@bp.get("/ehs/waste-pickup-requests/<request_id>")
def get_pickup(request_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    return success_object(serialize_pickup(rec))


@bp.post("/ehs/waste-pickup-requests/<request_id>/add-item")
def add_item(request_id):
    _, role = get_actor()
    body = get_body()
    require_role(role, ("PrincipalInvestigator", "LabMember"))
    container_id = body.get("container_id")
    if container_id is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: container_id", 400)
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    container = db.containers.get(container_id)
    if container is None:
        raise ApiError(ERR_NOT_FOUND, f"Container not found: {container_id}", 404)
    rec = pickup_service.add_item(rec, container)
    return success_object(serialize_pickup(rec))


@bp.post("/ehs/waste-pickup-requests/<request_id>/remove-item")
def remove_item(request_id):
    _, role = get_actor()
    body = get_body()
    require_role(role, ("PrincipalInvestigator", "LabMember"))
    container_id = body.get("container_id")
    if container_id is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: container_id", 400)
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    container = db.containers.get(container_id)
    if container is None:
        raise ApiError(ERR_NOT_FOUND, f"Container not found: {container_id}", 404)
    rec = pickup_service.remove_item(rec, container)
    return success_object(serialize_pickup(rec))


@bp.post("/ehs/waste-pickup-requests/<request_id>/submit")
def submit_pickup(request_id):
    user_id, role = get_actor()
    get_body()
    require_role(role, ("PrincipalInvestigator",))
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    lab = db.labs[rec["lab_id"]]
    rec = pickup_service.submit(rec, lab, user_id)
    return success_object(serialize_pickup(rec))


@bp.post("/ehs/waste-pickup-requests/<request_id>/reject")
def reject_pickup(request_id):
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin",))
    reason = require_string(body, "reason")
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    rec = pickup_service.reject(rec, reason)
    return success_object(serialize_pickup(rec))


@bp.post("/ehs/waste-pickup-requests/<request_id>/schedule")
def schedule_pickup(request_id):
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin",))
    require_fields(body, ["dock_id", "window_start", "window_end"])
    dock_id = require_string(body, "dock_id")
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    rec = pickup_service.schedule(rec, dock_id, window_start, window_end)
    return success_object(serialize_pickup(rec))


@bp.post("/ehs/waste-pickup-requests/<request_id>/complete")
def complete_pickup(request_id):
    _, role = get_actor()
    get_body()
    require_role(role, ("EHSAdmin",))
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    lab = db.labs[rec["lab_id"]]
    rec = pickup_service.complete(rec, lab)
    return success_object(serialize_pickup(rec))


@bp.post("/ehs/waste-pickup-requests/<request_id>/cancel")
def cancel_pickup(request_id):
    _, role = get_actor()
    get_body()
    require_role(role, ("EHSAdmin",))
    rec = get_or_404(db.waste_pickup_requests, request_id, "WastePickupRequest")
    rec = pickup_service.cancel(rec)
    return success_object(serialize_pickup(rec))
