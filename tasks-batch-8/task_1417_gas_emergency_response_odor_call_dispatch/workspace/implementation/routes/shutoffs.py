"""ShutoffOrder standalone endpoints: get / authorize / decline / execute / restore."""
from flask import Blueprint

import clock
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import (check_incident_read_scope,
                           check_technician_active_assignment, load_incident,
                           load_shutoff)
from validate import get_body, opt_str

bp = Blueprint("shutoffs", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/shutoff-orders/<shutoffId>", methods=["GET"])
@require_roles(*ALL)
def get_shutoff(shutoffId, user_id, role):
    order = load_shutoff(shutoffId)
    incident = load_incident(order["incident_id"])
    check_incident_read_scope(incident, role, user_id)
    return response.success(domain.ser_shutoff(order), 200)


@bp.route("/gas-ops/shutoff-orders/<shutoffId>/authorize", methods=["POST"])
@require_roles("Supervisor")
def authorize(shutoffId, user_id, role):
    order = load_shutoff(shutoffId)
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Authorize requires a REQUESTED shutoff order", 409)
    order["status"] = "AUTHORIZED"
    order["authorized_by_user_id"] = user_id
    domain.bump(order)
    return response.success(domain.ser_shutoff(order), 200)


@bp.route("/gas-ops/shutoff-orders/<shutoffId>/decline", methods=["POST"])
@require_roles("Supervisor")
def decline(shutoffId, user_id, role):
    order = load_shutoff(shutoffId)
    opt_str(get_body(), "reason")
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Decline requires a REQUESTED shutoff order", 409)
    order["status"] = "DECLINED"
    domain.bump(order)
    return response.success(domain.ser_shutoff(order), 200)


@bp.route("/gas-ops/shutoff-orders/<shutoffId>/execute", methods=["POST"])
@require_roles("FieldTechnician")
def execute(shutoffId, user_id, role):
    order = load_shutoff(shutoffId)
    incident = load_incident(order["incident_id"])
    check_technician_active_assignment(incident["id"], user_id)
    if order["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", "Execute requires an AUTHORIZED shutoff order", 409)
    if order["entry_required"] and incident["entry_status"] not in ("AUTHORIZED", "FORCED"):
        raise ApiError("ERR_ENTRY_NOT_AUTHORIZED",
                       "Executing an entry-required shutoff requires entry_status "
                       "AUTHORIZED or FORCED", 422)
    order["status"] = "EXECUTED"
    order["executed_at"] = clock.now()
    order["executed_by_technician_id"] = user_id
    domain.bump(order)
    # Meter-scope execution under evacuation conditions is a media event (PRD §3.6).
    if (order["scope"] == "METER" and domain.evacuation_required(incident)
            and not incident["auto_notification_created"]):
        domain.auto_severity_notify(incident, "MEDIA")
        domain.bump(incident)
    return response.success(domain.ser_shutoff(order), 200)


@bp.route("/gas-ops/shutoff-orders/<shutoffId>/restore", methods=["POST"])
@require_roles("FieldTechnician")
def restore(shutoffId, user_id, role):
    order = load_shutoff(shutoffId)
    incident = load_incident(order["incident_id"])
    check_technician_active_assignment(incident["id"], user_id)
    if order["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_STATE", "Restore requires an EXECUTED shutoff order", 409)
    order["status"] = "RESTORED"
    order["restored_at"] = clock.now()
    domain.bump(order)
    return response.success(domain.ser_shutoff(order), 200)
