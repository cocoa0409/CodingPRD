"""Alerts and alert notifications."""
from flask import Blueprint, request

import db
import errors
from middleware import (require_roles, get_body, req_str, req_enum, opt_str,
                        query_enum, check_senior_scope, scoped_list,
                        caller_senior_scope, SEVERITIES, ALERT_STATUSES,
                        ALERT_TYPES, NOTIF_STATUSES)
from response import ok, list_ok
from services import (create_record, touch, ser, create_alert,
                      supersede_sent_notifications, start_notification_round,
                      eligible_contacts)

bp = Blueprint("alerts", __name__)

ACTIONABLE_FOR_ACK = {"RAISED", "NOTIFYING", "ESCALATED"}


def _get_alert(alert_id):
    a = db.alerts.get(alert_id)
    if a is None:
        raise errors.not_found("Alert not found")
    return a


@bp.post("/v1/alerts")
def create_manual_alert():
    require_roles(["MonitoringAgent"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    severity = req_enum(b, "severity", SEVERITIES)
    opt_str(b, "note")  # accepted, not persisted (Alert has no note field)
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    alert = create_alert(senior_id, "MANUAL", severity, manual=True)
    return ok(ser(alert), 201)


@bp.get("/v1/alerts/<alert_id>")
def get_alert(alert_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    a = _get_alert(alert_id)
    check_senior_scope(role, uid, a["senior_id"])
    return ok(ser(a))


@bp.get("/v1/alerts")
def list_alerts():
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    recs = list(db.alerts.values())
    recs = scoped_list(role, uid, recs, request.args.get("senior_id"))
    st = query_enum("status", ALERT_STATUSES)
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    at = query_enum("alert_type", ALERT_TYPES)
    if at is not None:
        recs = [r for r in recs if r["alert_type"] == at]
    did = request.args.get("device_id")
    if did is not None:
        recs = [r for r in recs if r.get("device_id") == did]
    return list_ok(recs, ser)


@bp.post("/v1/alerts/<alert_id>/acknowledge")
def acknowledge_alert(alert_id):
    role, uid = require_roles(["Caregiver", "MonitoringAgent"])
    a = _get_alert(alert_id)
    if role == "Caregiver":
        check_senior_scope(role, uid, a["senior_id"])
    if a["status"] not in ACTIONABLE_FOR_ACK:
        raise errors.alert_not_actionable()
    acked_notif_id = None
    if role == "Caregiver":
        mine = [n for n in db.notifications.values()
                if n["alert_id"] == a["id"] and n["caregiver_id"] == uid
                and n["status"] == "SENT"]
        if not mine:
            raise errors.not_notified_contact()
        acked_notif_id = mine[0]["id"]
        a["acknowledged_by_caregiver_id"] = uid
    else:
        a["acknowledged_by_caregiver_id"] = None
    supersede_sent_notifications(a["id"], acked_notif_id=acked_notif_id)
    a["status"] = "ACKNOWLEDGED"
    touch(a)
    return ok(ser(a))


@bp.post("/v1/alerts/<alert_id>/resolve")
def resolve_alert(alert_id):
    role, uid = require_roles(["Caregiver", "MonitoringAgent"])
    b = get_body(required=False)
    note = opt_str(b, "note")
    a = _get_alert(alert_id)
    if role == "Caregiver":
        check_senior_scope(role, uid, a["senior_id"])
    if a["status"] != "ACKNOWLEDGED":
        raise errors.alert_not_actionable()
    a["status"] = "RESOLVED"
    a["resolution_note"] = note
    touch(a)
    return ok(ser(a))


@bp.post("/v1/alerts/<alert_id>/mark-false-alarm")
def mark_false_alarm(alert_id):
    role, uid = require_roles(["Caregiver", "MonitoringAgent"])
    b = get_body(required=False)
    note = opt_str(b, "note")
    a = _get_alert(alert_id)
    if role == "Caregiver":
        check_senior_scope(role, uid, a["senior_id"])
    if a["status"] != "ACKNOWLEDGED":
        raise errors.alert_not_actionable()
    if a["severity"] == "CRITICAL" and role != "MonitoringAgent":
        raise errors.safety_agent_required()
    a["status"] = "FALSE_ALARM"
    a["resolution_note"] = note
    touch(a)
    return ok(ser(a))


@bp.post("/v1/alerts/<alert_id>/reopen")
def reopen_alert(alert_id):
    require_roles(["MonitoringAgent"])
    a = _get_alert(alert_id)
    if a["status"] not in ("RESOLVED", "FALSE_ALARM"):
        raise errors.alert_not_actionable()
    a["reopen_count"] += 1
    a["escalation_exhausted"] = False
    a["status"] = "RAISED"
    a["escalation_level"] = 0
    start_notification_round(a)
    touch(a)
    return ok(ser(a))


# ---------------------------------------------------------- notifications --

@bp.get("/v1/alert-notifications/<notification_id>")
def get_notification(notification_id):
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    n = db.notifications.get(notification_id)
    if n is None:
        raise errors.not_found("Alert notification not found")
    return ok(ser(n))


@bp.get("/v1/alert-notifications")
def list_notifications():
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    recs = list(db.notifications.values())
    if role == "Caregiver":
        caller_senior_scope(role, uid)  # must resolve to a real caregiver
        cid_param = request.args.get("caregiver_id")
        if cid_param is not None and cid_param != uid:
            raise errors.ownership()
        recs = [r for r in recs if r["caregiver_id"] == uid]
    else:
        cid_param = request.args.get("caregiver_id")
        if cid_param is not None:
            recs = [r for r in recs if r["caregiver_id"] == cid_param]
    aid = request.args.get("alert_id")
    if aid is not None:
        recs = [r for r in recs if r["alert_id"] == aid]
    eid = request.args.get("contact_entry_id")
    if eid is not None:
        recs = [r for r in recs if r["contact_entry_id"] == eid]
    st = query_enum("status", NOTIF_STATUSES)
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_ok(recs, ser)
