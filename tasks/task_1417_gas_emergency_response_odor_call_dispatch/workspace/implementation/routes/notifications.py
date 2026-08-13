"""PublicNotification standalone endpoints: get / issue / retract / discard."""
from flask import Blueprint

import clock
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import (check_incident_read_scope, load_incident,
                           load_notification)
from validate import get_body, opt_str

bp = Blueprint("notifications", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/public-notifications/<notificationId>", methods=["GET"])
@require_roles(*ALL)
def get_notification(notificationId, user_id, role):
    note = load_notification(notificationId)
    incident = load_incident(note["incident_id"])
    check_incident_read_scope(incident, role, user_id)
    return response.success(domain.ser_notification(note), 200)


@bp.route("/gas-ops/public-notifications/<notificationId>/issue", methods=["POST"])
@require_roles("Supervisor")
def issue(notificationId, user_id, role):
    note = load_notification(notificationId)
    if note["status"] != "DRAFT":
        raise ApiError("ERR_NOTIFICATION_NOT_DRAFT", "Issue requires a DRAFT notification", 409)
    note["status"] = "ISSUED"
    note["issued_at"] = clock.now()
    domain.bump(note)
    return response.success(domain.ser_notification(note), 200)


@bp.route("/gas-ops/public-notifications/<notificationId>/retract", methods=["POST"])
@require_roles("Supervisor")
def retract(notificationId, user_id, role):
    note = load_notification(notificationId)
    opt_str(get_body(), "reason")
    if note["status"] != "ISSUED":
        raise ApiError("ERR_NOTIFICATION_NOT_ISSUED",
                       "Retract requires an ISSUED notification", 409)
    note["status"] = "RETRACTED"
    note["retracted_at"] = clock.now()
    domain.bump(note)
    return response.success(domain.ser_notification(note), 200)


@bp.route("/gas-ops/public-notifications/<notificationId>/discard", methods=["POST"])
@require_roles("Supervisor")
def discard(notificationId, user_id, role):
    note = load_notification(notificationId)
    if note["status"] != "DRAFT":
        raise ApiError("ERR_NOTIFICATION_NOT_DRAFT", "Discard requires a DRAFT notification", 409)
    note["status"] = "DISCARDED"
    domain.bump(note)
    return response.success(domain.ser_notification(note), 200)
