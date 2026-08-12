"""Arrhythmia alerts and notification attempts."""
import db
from bp import bp
from clock import now
from db import base_record, touch
from domain import (compute_sla_deadline, create_attempt, fatigue_index_dec,
                    fatigue_status_of)
from errors import ApiError
from helpers import (READ_ROLES, auth, body, opt_enum, pagination, req_enum,
                     req_str, require, sorted_by_creation)
from response import serialize, success, success_list

SEVERITIES = {"CRITICAL", "URGENT", "ROUTINE"}
CLOSE_OUTCOMES = {"FALSE_POSITIVE", "RESOLVED"}
LOAD_STATUSES = {"ACKNOWLEDGED", "TRIAGED", "ESCALATED", "NOTIFIED"}


def _get_alert_or_404(alert_id):
    a = db.alerts.get(alert_id)
    if a is None:
        raise ApiError("ERR_ALERT_NOT_FOUND", 404, "Alert not found")
    return a


def _check_assignee(alert, uid):
    """Ownership: when an assignee exists, only the assignee may act."""
    assigned = alert["assigned_technician_id"]
    if assigned is not None and assigned != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Caller is not the assigned technician")


def _decrement_load(technician_id):
    tech = db.technicians.get(technician_id)
    if tech is not None:
        tech["open_alert_load"] = max(0, tech["open_alert_load"] - 1)
        touch(tech)


@bp.post("/v1/episodes/<episode_id>/alerts")
def raise_alert(episode_id):
    uid, role = auth()
    require(role, {"DeviceGateway"})
    ep = db.episodes.get(episode_id)
    if ep is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND", 404, "Episode not found")
    d = body()
    severity = req_enum(d, "severity", SEVERITIES)
    arrhythmia_type = req_str(d, "arrhythmia_type")
    t = now()
    rec = base_record()
    rec.update({
        "episode_id": ep["id"],
        "severity": severity,
        "arrhythmia_type": arrhythmia_type,
        "detected_at": t,
        "sla_deadline": compute_sla_deadline(severity, t),
        "status": "NEW",
        "assigned_technician_id": None,
        "acknowledged_at": None,
        "closed_outcome": None,
        "notification_attempt_count": 0,
    })
    db.alerts[rec["id"]] = rec
    if severity == "CRITICAL":
        ep["unacknowledged_critical_count"] += 1
        touch(ep)
    return success(serialize(rec), 201)


@bp.get("/v1/alerts")
def list_alerts():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    ep_f = request.args.get("episode_id")
    tech_f = request.args.get("assigned_technician_id")
    status_f = request.args.get("status")
    sev_f = request.args.get("severity")
    items = list(db.alerts.values())
    if ep_f is not None:
        items = [x for x in items if x["episode_id"] == ep_f]
    if tech_f is not None:
        items = [x for x in items if x["assigned_technician_id"] == tech_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    if sev_f is not None:
        items = [x for x in items if x["severity"] == sev_f]
    return success_list(sorted_by_creation(items), limit, offset)


@bp.get("/v1/alerts/<alert_id>")
def get_alert(alert_id):
    uid, role = auth()
    require(role, READ_ROLES)
    return success(serialize(_get_alert_or_404(alert_id)))


@bp.post("/v1/alerts/<alert_id>/acknowledge")
def acknowledge_alert(alert_id):
    uid, role = auth()
    require(role, {"MonitoringTechnician"})
    alert = _get_alert_or_404(alert_id)
    tech = db.technicians.get(uid)
    if tech is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Technician not found")
    if alert["status"] != "NEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Only NEW alerts can be acknowledged")
    fatigue_status = fatigue_status_of(
        fatigue_index_dec(tech["open_alert_load"], tech["shift_capacity"]))
    if (not tech["on_shift"]
            or tech["open_alert_load"] >= tech["shift_capacity"]
            or fatigue_status == "FATIGUED"):
        raise ApiError("ERR_TECHNICIAN_UNAVAILABLE", 422,
                       "Technician is off-shift, at capacity, or fatigued")
    alert["status"] = "ACKNOWLEDGED"
    alert["assigned_technician_id"] = uid
    alert["acknowledged_at"] = now()
    touch(alert)
    tech["open_alert_load"] += 1
    tech["alerts_acknowledged_total"] += 1
    touch(tech)
    return success(serialize(alert))


@bp.post("/v1/alerts/<alert_id>/release")
def release_alert(alert_id):
    uid, role = auth()
    require(role, {"MonitoringTechnician"})
    alert = _get_alert_or_404(alert_id)
    _check_assignee(alert, uid)
    if alert["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only ACKNOWLEDGED alerts can be released")
    old_assignee = alert["assigned_technician_id"]
    alert["status"] = "NEW"
    alert["assigned_technician_id"] = None
    touch(alert)
    _decrement_load(old_assignee)
    return success(serialize(alert))


@bp.post("/v1/alerts/<alert_id>/triage")
def triage_alert(alert_id):
    uid, role = auth()
    require(role, {"MonitoringTechnician"})
    alert = _get_alert_or_404(alert_id)
    _check_assignee(alert, uid)
    d = body()
    reclass = opt_enum(d, "severity_reclass", SEVERITIES, default=None)
    if alert["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only ACKNOWLEDGED alerts can be triaged")
    if reclass is not None and reclass != alert["severity"]:
        ep = db.episodes.get(alert["episode_id"])
        if ep is not None:
            if reclass == "CRITICAL":
                ep["unacknowledged_critical_count"] += 1
                touch(ep)
            elif alert["severity"] == "CRITICAL":
                ep["unacknowledged_critical_count"] = max(
                    0, ep["unacknowledged_critical_count"] - 1)
                touch(ep)
        alert["severity"] = reclass
    if reclass is not None:
        alert["sla_deadline"] = compute_sla_deadline(alert["severity"], alert["detected_at"])
    alert["status"] = "TRIAGED"
    touch(alert)
    return success(serialize(alert))


@bp.post("/v1/alerts/<alert_id>/notify")
def notify_alert(alert_id):
    uid, role = auth()
    require(role, {"MonitoringTechnician"})
    alert = _get_alert_or_404(alert_id)
    if alert["status"] == "TRIAGED":
        _check_assignee(alert, uid)
    elif alert["status"] == "ESCALATED":
        pass  # notify from ESCALATED is not gated on assignment
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only TRIAGED or ESCALATED alerts can be notified")
    physician_id = None
    ep = db.episodes.get(alert["episode_id"])
    enr = db.enrollments.get(ep["enrollment_id"]) if ep else None
    order = db.orders.get(enr["order_id"]) if enr else None
    if order is not None:
        physician_id = order["ordering_physician_id"]
    physician = db.physicians.get(physician_id) if physician_id else None
    channel = physician["notification_preference"] if physician else "PORTAL"
    att = create_attempt(alert, channel)
    alert["status"] = "NOTIFIED"
    touch(alert)
    return success(serialize(att), 201)


@bp.post("/v1/alerts/<alert_id>/escalate")
def escalate_alert(alert_id):
    uid, role = auth()
    require(role, {"MonitoringTechnician"})
    alert = _get_alert_or_404(alert_id)
    if alert["status"] != "TRIAGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only TRIAGED alerts can be manually escalated")
    alert["status"] = "ESCALATED"
    create_attempt(alert, "ESCALATION")
    touch(alert)
    return success(serialize(alert))


@bp.post("/v1/alerts/<alert_id>/close")
def close_alert(alert_id):
    uid, role = auth()
    require(role, {"MonitoringTechnician"})
    alert = _get_alert_or_404(alert_id)
    if (alert["status"] == "ACKNOWLEDGED"
            and alert["assigned_technician_id"] is not None
            and alert["assigned_technician_id"] != uid):
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Caller is not the assigned technician")
    d = body()
    outcome = req_enum(d, "outcome", CLOSE_OUTCOMES)
    if alert["status"] == "ACKNOWLEDGED":
        if outcome != "FALSE_POSITIVE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "ACKNOWLEDGED alerts close only as FALSE_POSITIVE")
    elif alert["status"] == "NOTIFIED":
        if outcome != "RESOLVED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "NOTIFIED alerts close only as RESOLVED")
        has_ack = any(att for att in db.attempts.values()
                      if att["alert_id"] == alert["id"] and att["status"] == "ACKNOWLEDGED")
        if not has_ack:
            raise ApiError("ERR_NOTIFICATION_NOT_ACKNOWLEDGED", 422,
                           "No ACKNOWLEDGED notification attempt for this alert")
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Alert cannot be closed from its current state")
    alert["status"] = "CLOSED"
    alert["closed_outcome"] = outcome
    touch(alert)
    _decrement_load(alert["assigned_technician_id"])
    if alert["severity"] == "CRITICAL":
        ep = db.episodes.get(alert["episode_id"])
        if ep is not None:
            ep["unacknowledged_critical_count"] = max(
                0, ep["unacknowledged_critical_count"] - 1)
            touch(ep)
    return success(serialize(alert))


# -------------------------------------------------------- notification attempts
@bp.get("/v1/notification-attempts")
def list_attempts():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    alert_f = request.args.get("alert_id")
    phys_f = request.args.get("physician_id")
    status_f = request.args.get("status")
    items = list(db.attempts.values())
    if alert_f is not None:
        items = [x for x in items if x["alert_id"] == alert_f]
    if phys_f is not None:
        items = [x for x in items if x["physician_id"] == phys_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    return success_list(sorted_by_creation(items), limit, offset)


@bp.get("/v1/notification-attempts/<attempt_id>")
def get_attempt(attempt_id):
    uid, role = auth()
    require(role, READ_ROLES)
    rec = db.attempts.get(attempt_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Notification attempt not found")
    return success(serialize(rec))


@bp.post("/v1/notification-attempts/<attempt_id>/acknowledge")
def acknowledge_attempt(attempt_id):
    uid, role = auth()
    require(role, {"Physician"})
    rec = db.attempts.get(attempt_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Notification attempt not found")
    if rec["physician_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Caller is not the addressed physician")
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Attempt is already acknowledged")
    alert = db.alerts.get(rec["alert_id"])
    rec["status"] = "ACKNOWLEDGED"
    rec["within_sla"] = bool(alert is not None and now() <= alert["sla_deadline"])
    touch(rec)
    return success(serialize(rec))
