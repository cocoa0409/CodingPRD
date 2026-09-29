"""Real-time critical alerts (PRD 3.6)."""
from flask import Blueprint, g, request

import serialize
from auth import authorize
from core import touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_alert, paginate
from store import store
from validate import body, get_str

bp = Blueprint("alerts", __name__)

READ_ROLES = ("ProgramManager", "ComplianceOfficer", "PlatformAdmin", "Tester")


@bp.get("/critical-alerts/<alert_id>")
def read_alert(alert_id):
    authorize(*READ_ROLES)
    return object_response(serialize.alert(get_alert(alert_id)))


@bp.get("/critical-alerts")
def list_alerts():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.alerts.values()),
        finding_id=request.args.get("finding_id"),
        state=request.args.get("state"),
    )
    return paginate(rows, serialize.alert)


@bp.post("/critical-alerts/<alert_id>/acknowledge")
def acknowledge_alert(alert_id):
    """The outcome forks purely on the clock; the deadline instant is still on time."""
    authorize("ProgramManager", "ComplianceOfficer")
    alert = get_alert(alert_id)
    data = body()
    containment = get_str(data, "containment_action", min_len=1)
    if alert["state"] not in ("RAISED", "ESCALATED"):
        raise ApiError("ERR_ALERT_ALREADY_ACKNOWLEDGED")
    now = store.now()
    if alert["state"] == "RAISED":
        alert["acknowledged_at"] = now
        alert["acknowledged_by_user_id"] = g.user_id
        alert["containment_action"] = containment
        if now <= alert["ack_deadline_at"]:
            alert["state"] = "ACKNOWLEDGED"
            alert["escalation_level"] = 1
        else:
            alert["state"] = "ESCALATED"
            alert["escalation_level"] = 2
    else:
        alert["state"] = "ACKNOWLEDGED"
        alert["containment_action"] = containment
    touch(alert)
    return object_response(serialize.alert(alert))
