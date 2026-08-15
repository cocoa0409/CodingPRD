"""Safety alerts: timely warnings and emergency notifications."""

from datetime import timedelta

from flask import Blueprint, g, request

from core import (clock, db, enum_or_422, err, fmt_dt, fmt_dt_short, get_body,
                  get_or_404, mint, now_iso, now_iso_short, paginate, pub,
                  req_list, req_str, require_roles, success, touch, _MISSING)

bp = Blueprint("alerts", __name__)

ALERT_TYPES = {"TIMELY_WARNING", "EMERGENCY_NOTIFICATION"}
CHANNELS = {"EMAIL", "SMS", "POSTERS", "WEBSITE", "SIREN"}
WARNING_DECISION_HOURS = 48
DISSEMINATION_HOURS = 24
REOPEN_WINDOW_HOURS = 72
ALERTABLE_STATUSES = {"SUBMITTED", "UNDER_CLASSIFICATION", "CLASSIFIED",
                      "UNDER_RECLASSIFICATION"}


@bp.post("/incident-reports/<iid>/safety-alerts")
@require_roles("CleryCoordinator")
def create_alert(iid):
    data = get_body()
    alert_type = req_str(data, "alert_type")
    inc = get_or_404(db.incidents, iid)
    if inc["status"] not in ALERTABLE_STATUSES:
        err("ERR_INVALID_STATE", 409,
            "Incident status %s cannot spawn a safety alert" % inc["status"])
    for a in db.alerts.values():
        if a["incident_id"] == iid and a["status"] != "CLOSED":
            err("ERR_DUPLICATE_ACTIVE_ALERT", 409,
                "Incident already has a non-CLOSED safety alert")
    enum_or_422(alert_type, ALERT_TYPES, "alert_type")
    deadline = inc["_reported_dt"] + timedelta(hours=WARNING_DECISION_HOURS)
    alert = mint({"incident_id": iid,
                  "alert_type": alert_type,
                  "decision": None,
                  "decision_rationale": None,
                  "decided_by": None,
                  "decided_at": None,
                  "decision_deadline_at": fmt_dt_short(deadline),
                  "decision_overdue": False,
                  "authorized_by": None,
                  "authorized_at": None,
                  "dissemination_deadline_at": None,
                  "dissemination_overdue": False,
                  "distribution_channels": None,
                  "disseminated_at": None,
                  "closed_at": None,
                  "status": "PENDING_REVIEW",
                  "_decision_deadline_dt": deadline,
                  "_dissemination_deadline_dt": None,
                  "_closed_dt": None})
    db.alerts[alert["id"]] = alert
    return success(pub(alert), 201)


@bp.get("/incident-reports/<iid>/safety-alerts")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief")
def list_alerts(iid):
    get_or_404(db.incidents, iid)
    items = [a for a in db.alerts.values() if a["incident_id"] == iid]
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/safety-alerts/<aid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief")
def get_alert(aid):
    return success(pub(get_or_404(db.alerts, aid)), 200)


@bp.post("/safety-alerts/<aid>/decide")
@require_roles("CleryCoordinator")
def decide_alert(aid):
    data = get_body()
    decision = req_str(data, "decision")
    rationale = data.get("decision_rationale", _MISSING)
    if rationale is _MISSING or not isinstance(rationale, str) \
            or not rationale.strip():
        err("ERR_INVALID_REQUEST", 400,
            "Field decision_rationale is required and must be non-empty")
    alert = get_or_404(db.alerts, aid)
    if alert["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "Only a PENDING_REVIEW alert may be decided")
    enum_or_422(decision, {"ISSUE", "NO_ISSUE"}, "decision")
    alert["decision"] = decision
    alert["decision_rationale"] = rationale
    alert["decided_by"] = g.user_id
    alert["decided_at"] = now_iso_short()
    alert["decision_overdue"] = clock.current > alert["_decision_deadline_dt"]
    alert["status"] = ("DECIDED_ISSUE" if decision == "ISSUE"
                       else "DECIDED_NO_ISSUE")
    touch(alert)
    return success(pub(alert), 200)


@bp.post("/safety-alerts/<aid>/authorize")
@require_roles("PoliceChief")
def authorize_alert(aid):
    alert = get_or_404(db.alerts, aid)
    if alert["status"] != "DECIDED_ISSUE":
        err("ERR_INVALID_STATE", 409,
            "Only a DECIDED_ISSUE alert may be authorized")
    deadline = clock.current + timedelta(hours=DISSEMINATION_HOURS)
    alert["authorized_by"] = g.user_id
    alert["authorized_at"] = now_iso_short()
    alert["dissemination_deadline_at"] = fmt_dt_short(deadline)
    alert["_dissemination_deadline_dt"] = deadline
    alert["status"] = "AUTHORIZED"
    touch(alert)
    return success(pub(alert), 200)


@bp.post("/safety-alerts/<aid>/disseminate")
@require_roles("PoliceChief")
def disseminate_alert(aid):
    data = get_body()
    channels = req_list(data, "distribution_channels")
    for c in channels:
        if not isinstance(c, str):
            err("ERR_INVALID_REQUEST", 400,
                "distribution_channels elements must be strings")
    alert = get_or_404(db.alerts, aid)
    if alert["status"] != "AUTHORIZED":
        err("ERR_INVALID_STATE", 409,
            "Only an AUTHORIZED alert may be disseminated")
    if not channels:
        err("ERR_NO_DISTRIBUTION_CHANNELS", 422,
            "distribution_channels must be a non-empty subset")
    for c in channels:
        enum_or_422(c, CHANNELS, "distribution_channels")
    alert["distribution_channels"] = channels
    alert["disseminated_at"] = now_iso_short()
    alert["dissemination_overdue"] = (
        clock.current > alert["_dissemination_deadline_dt"])
    alert["status"] = "DISSEMINATED"
    touch(alert)
    return success(pub(alert), 200)


@bp.post("/safety-alerts/<aid>/close")
@require_roles("CleryCoordinator")
def close_alert(aid):
    alert = get_or_404(db.alerts, aid)
    if alert["status"] not in ("DISSEMINATED", "DECIDED_NO_ISSUE"):
        err("ERR_INVALID_STATE", 409,
            "Only a DISSEMINATED or DECIDED_NO_ISSUE alert may be closed")
    alert["closed_at"] = now_iso_short()
    alert["_closed_dt"] = clock.current
    alert["status"] = "CLOSED"
    touch(alert)
    return success(pub(alert), 200)


@bp.post("/safety-alerts/<aid>/reopen")
@require_roles("CleryCoordinator")
def reopen_alert(aid):
    data = get_body()
    reason = data.get("reason", _MISSING)
    if reason is _MISSING or not isinstance(reason, str):
        err("ERR_INVALID_REQUEST", 400, "Field reason must be a string")
    alert = get_or_404(db.alerts, aid)
    if alert["status"] != "CLOSED":
        err("ERR_INVALID_STATE", 409, "Only a CLOSED alert may be reopened")
    deadline = alert["_closed_dt"] + timedelta(hours=REOPEN_WINDOW_HOURS)
    if clock.current > deadline:
        err("ERR_ALERT_WINDOW_EXPIRED", 422,
            "Reopen window of 72 hours has expired")
    alert["reopen_reason"] = reason
    alert["decision"] = None
    alert["decided_at"] = None
    alert["authorized_at"] = None
    alert["disseminated_at"] = None
    alert["closed_at"] = None
    alert["_closed_dt"] = None
    alert["decision_overdue"] = False
    alert["dissemination_overdue"] = False
    alert["status"] = "PENDING_REVIEW"
    touch(alert)
    return success(pub(alert), 200)
