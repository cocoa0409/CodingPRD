"""Escalation routes."""

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body, req_enum
from response import success_object, success_list, parse_pagination
from services import core

bp = Blueprint("escalations", __name__)

ESC_TYPES = {"MISSING_TRAY", "INCOMPLETE_COUNT", "DOCUMENTATION", "STERILIZATION_DELAY", "LATE_DELIVERY"}
TRAY_SCOPED_TYPES = {"MISSING_TRAY", "INCOMPLETE_COUNT", "DOCUMENTATION", "STERILIZATION_DELAY"}
RESOLUTION_TYPES = {"BACKFILL_DELIVERY", "SUBSTITUTE_APPROVED", "CASE_RESCHEDULED", "CASE_CANCELLED", "WAIVED"}
# Tray states in which a MISSING_TRAY escalation may be resolved with
# BACKFILL_DELIVERY (the tray has actually materialized).
BACKFILL_OK_STATES = {
    "DELIVERY_PENDING", "CHECKED_IN", "PROCESSING", "STERILE_READY", "STAGED",
    "IN_USE", "USED", "AWAITING_PICKUP", "PICKED_UP", "RECONCILED",
}


def _get_escalation_or_404(esc_id):
    e = db.escalations.get(esc_id)
    if e is None:
        raise_err("ERR_ESCALATION_NOT_FOUND", "Escalation not found")
    return e


@bp.post("/requests/<id>/escalations")
def create_escalation(id):
    _, role = get_auth()
    body = get_body(required=True)

    esc_type = req_enum(body, "type", ESC_TYPES)
    linked_tray_id = body.get("linked_tray_id")
    if linked_tray_id is not None and not isinstance(linked_tray_id, str):
        raise_err("ERR_VALIDATION", "linked_tray_id must be a string")

    require_role(role, ["VendorCoordinator"])

    request = db.requests.get(id)
    if request is None:
        raise_err("ERR_REQUEST_NOT_FOUND", "Loaner request not found")

    if esc_type in TRAY_SCOPED_TYPES and linked_tray_id is None:
        raise_err("ERR_VALIDATION", f"linked_tray_id is required for type {esc_type}")
    if linked_tray_id is not None:
        tray = db.trays.get(linked_tray_id)
        if tray is None:
            raise_err("ERR_TRAY_NOT_FOUND", "Tray not found")
        if tray["request_id"] != id:
            raise_err("ERR_TRAY_NOT_IN_REQUEST", "linked tray belongs to a different request")

    esc = core.create_escalation(id, esc_type, linked_tray_id=linked_tray_id)
    return success_object(core.serialize(esc), status=201)


@bp.get("/escalations")
def list_escalations():
    get_auth()
    request_id = flask_request.args.get("request_id")
    status = flask_request.args.get("status")
    esc_type = flask_request.args.get("type")
    linked_tray_id = flask_request.args.get("linked_tray_id")
    items = sorted(db.escalations.values(), key=lambda e: e["_seq"])
    if request_id:
        items = [e for e in items if e["request_id"] == request_id]
    if status:
        items = [e for e in items if e["status"] == status]
    if esc_type:
        items = [e for e in items if e["type"] == esc_type]
    if linked_tray_id:
        items = [e for e in items if e.get("linked_tray_id") == linked_tray_id]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(e) for e in page], limit, offset, total)


@bp.get("/escalations/<id>")
def get_escalation(id):
    get_auth()
    esc = _get_escalation_or_404(id)
    return success_object(core.serialize(esc))


@bp.post("/escalations/<id>/acknowledge")
def acknowledge_escalation(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["VendorCoordinator"])
    esc = _get_escalation_or_404(id)

    if esc["status"] != "OPEN":
        raise_err("ERR_ESCALATION_INVALID_STATE", "Only an OPEN escalation can be acknowledged")
    esc["status"] = "ACKNOWLEDGED"
    core.touch(esc)
    return success_object(core.serialize(esc))


@bp.post("/escalations/<id>/resolve")
def resolve_escalation(id):
    _, role = get_auth()
    body = get_body(required=True)

    resolution_type = req_enum(body, "resolution_type", RESOLUTION_TYPES)

    require_role(role, ["VendorCoordinator"])
    esc = _get_escalation_or_404(id)

    if esc["status"] not in {"OPEN", "ACKNOWLEDGED"}:
        raise_err("ERR_ESCALATION_INVALID_STATE", "Only an OPEN or ACKNOWLEDGED escalation can be resolved")

    if esc["type"] == "MISSING_TRAY" and resolution_type == "BACKFILL_DELIVERY":
        tray = db.trays.get(esc.get("linked_tray_id") or "")
        if tray is None or tray["status"] not in BACKFILL_OK_STATES:
            raise_err(
                "ERR_ESCALATION_RESOLUTION_INVALID",
                "BACKFILL_DELIVERY requires the linked tray to have materialized",
            )

    esc["status"] = "RESOLVED"
    esc["resolution_type"] = resolution_type
    core.touch(esc)
    return success_object(core.serialize(esc))
